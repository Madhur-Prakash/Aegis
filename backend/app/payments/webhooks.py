"""Razorpay webhook intake and reconciliation.

Signature verification happens before anything else.  The raw body is persisted,
the event is published to ``aegis.payment-webhooks``, and processing is idempotent
on the provider's event id so replays and out-of-order delivery are harmless.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ValidationFailed
from app.common.logging import get_logger
from app.config.settings import settings
from app.events.outbox import enqueue
from app.events.topics import EventType, Topic
from app.models.commerce import Payout, WebhookReceipt
from app.models.enums import PayoutStatus
from app.rails.base import verify_webhook_signature

log = get_logger("payments.webhooks")


async def handle_webhook(session: AsyncSession, body: bytes, signature: str) -> dict[str, Any]:
    valid = verify_webhook_signature(body, signature, settings.RAZORPAY_WEBHOOK_SECRET)
    if not valid:
        log.warning("webhook rejected", extra={"reason": "SIGNATURE_INVALID"})
        raise ValidationFailed(
            code="WEBHOOK_SIGNATURE_INVALID",
            message="The webhook signature does not verify.",
            http_status=400,
        )
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise ValidationFailed(
            code="WEBHOOK_MALFORMED", message="The webhook body is not valid JSON."
        ) from exc

    external_id = str(payload.get("id") or payload.get("event_id") or "")
    event_type = str(payload.get("event") or "unknown")
    if not external_id:
        raise ValidationFailed(
            code="WEBHOOK_MISSING_ID", message="The webhook carries no event id."
        )

    existing = (
        await session.execute(
            select(WebhookReceipt).where(
                WebhookReceipt.provider == "razorpay",
                WebhookReceipt.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        log.info("webhook replay ignored", extra={"external_id": external_id})
        return {"accepted": True, "duplicate": True, "event": event_type}

    receipt = WebhookReceipt(
        provider="razorpay",
        external_id=external_id,
        event_type=event_type,
        signature_valid=True,
        raw_payload=payload,
    )
    session.add(receipt)
    await enqueue(
        session,
        topic=Topic.PAYMENT_WEBHOOKS,
        event_type=EventType.PAYMENT_WEBHOOK_RECEIVED,
        aggregate_type="WebhookReceipt",
        aggregate_id=external_id,
        payload={"external_id": external_id, "event": event_type},
        event_id=f"evt_wh_{external_id}",
    )
    log.info("webhook received", extra={"external_id": external_id, "event": event_type})
    return {"accepted": True, "duplicate": False, "event": event_type}


async def reconcile_receipt(session: AsyncSession, external_id: str) -> dict[str, Any]:
    """Reconciles a stored webhook against the payout it refers to.

    A webhook never *creates* a payout: the settlement engine owns that.  It can
    only confirm or fail one that already exists, which is what keeps the rail
    from being able to move money on its own.
    """
    receipt = (
        await session.execute(
            select(WebhookReceipt).where(
                WebhookReceipt.provider == "razorpay",
                WebhookReceipt.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if receipt is None:
        return {"reconciled": False, "reason": "RECEIPT_NOT_FOUND"}
    if receipt.processed_at is not None:
        return {"reconciled": True, "duplicate": True}

    payload = receipt.raw_payload or {}
    entity = (
        payload.get("payload", {}).get("transfer", {}).get("entity")
        or payload.get("payload", {}).get("refund", {}).get("entity")
        or payload.get("payload", {}).get("payment", {}).get("entity")
        or {}
    )
    rail_ref = str(entity.get("id") or "")
    status = str(entity.get("status") or "")
    updated = 0
    if rail_ref:
        payout = (
            await session.execute(select(Payout).where(Payout.rail_ref == rail_ref))
        ).scalar_one_or_none()
        if payout is not None:
            if status in {"processed", "captured", "settled"}:
                payout.status = PayoutStatus.SUCCEEDED
                updated = 1
            elif status in {"failed", "reversed"}:
                payout.status = PayoutStatus.FAILED
                payout.failure_reason = f"rail reported {status}"
                updated = 1
    receipt.processed_at = dt.datetime.now(dt.UTC)
    await session.flush()
    log.info(
        "webhook reconciled",
        extra={"external_id": external_id, "rail_ref": rail_ref, "updated": updated},
    )
    return {"reconciled": True, "rail_ref": rail_ref, "status": status, "payouts_updated": updated}
