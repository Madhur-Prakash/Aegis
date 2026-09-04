"""Consumer handlers.

Every handler is idempotent by construction: it guards on ``ProcessedEvent`` and
re-reads the authoritative row from Postgres.  The consumer trusts the database,
never the message payload.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attest.canonical import sha256_hex
from app.chain.adapter import get_chain
from app.common.errors import ChainUnavailable
from app.common.logging import get_logger
from app.events.outbox import (
    already_processed,
    deterministic_event_id,
    enqueue,
    mark_processed,
)
from app.events.topics import ConsumerGroup, EventType, Topic
from app.ledger.service import append_ledger
from app.models.commerce import (
    Attestation,
    ChainAnchor,
    Deal,
    LedgerEvent,
    Milestone,
    Payout,
    SettlementAuthorization,
)
from app.models.enums import LedgerEventType, NotificationKind
from app.notifications.service import fan_out
from app.settlement.engine import execute_authorization, maybe_complete_deal

log = get_logger("worker.handlers")


def _human_approved(authorization: SettlementAuthorization | None) -> bool:
    """A payout always has its authorization; a missing one is recorded as
    machine-decided rather than crashing the anchor."""
    return bool(authorization.human_approved) if authorization is not None else False


async def handle_settlement_authorized(
    session: AsyncSession, payload: dict[str, Any], group: str = ConsumerGroup.SETTLEMENT
) -> dict[str, Any]:
    """The settlement worker.  At-least-once delivery, exactly-once effect."""
    event_id = str(payload.get("event_id") or "")
    if event_id and await already_processed(session, event_id, group):
        log.info(
            "duplicate delivery ignored", extra={"event_id": event_id, "consumer_group": group}
        )
        return {"skipped": True, "reason": "ALREADY_PROCESSED"}

    authorization_id = payload.get("authorization_id")
    if not authorization_id:
        return {"skipped": True, "reason": "NO_AUTHORIZATION_ID"}

    result = await execute_authorization(session, authorization_id)

    # A worker that lost the claim race did nothing and must not ack the message:
    # marking it processed here would swallow the redelivery that is the whole
    # point of at-least-once transport.
    if result.reason == "CLAIM_HELD_BY_ANOTHER_WORKER":
        return {"skipped": True, "reason": result.reason}

    if event_id:
        await mark_processed(session, event_id, group)

    if result.payout is not None and not result.failed:
        deal = await session.get(Deal, result.payout.deal_id)
        milestone = await session.get(Milestone, result.payout.milestone_id)
        if deal is not None:
            await maybe_complete_deal(session, deal)
            anchor = ChainAnchor(
                kind="RECORD_SETTLEMENT",
                deal_id=deal.id,
                milestone_seq=int(milestone.seq) if milestone else None,
                payload_json={
                    "deal_id_b32": deal.chain_deal_id,
                    "seq": int(milestone.seq) if milestone else 0,
                    "amount_paise": int(result.payout.amount_paise),
                    # I7: the *hash* of the rail reference goes on chain, never the reference.
                    "rail_ref": "0x" + sha256_hex(result.payout.rail_ref or ""),
                    "human_approved": _human_approved(
                        await session.get(SettlementAuthorization, result.payout.authorization_id)
                    ),
                },
            )
            session.add(anchor)
            await session.flush()
            await enqueue(
                session,
                topic=Topic.CHAIN,
                event_type=EventType.CHAIN_ANCHOR_REQUESTED,
                aggregate_type="ChainAnchor",
                aggregate_id=str(anchor.id),
                payload={
                    "anchor_id": str(anchor.id),
                    "deal_id": str(deal.id),
                    "kind": "RECORD_SETTLEMENT",
                },
                event_id=deterministic_event_id(EventType.CHAIN_ANCHOR_REQUESTED, str(anchor.id)),
            )
            await enqueue(
                session,
                topic=Topic.NOTIFICATIONS,
                event_type=EventType.NOTIFICATION_REQUESTED,
                aggregate_type="Payout",
                aggregate_id=str(result.payout.id),
                payload={
                    "kind": str(NotificationKind.PAYOUT_COMPLETED),
                    "deal_id": str(deal.id),
                    "deal_reference": deal.reference,
                    "org_id_buyer": str(deal.org_id_buyer),
                    "org_id_seller": str(deal.org_id_seller),
                    "milestone_seq": int(milestone.seq) if milestone else None,
                    "direction": str(result.payout.direction),
                    "amount_paise": int(result.payout.amount_paise),
                },
                event_id=deterministic_event_id(
                    EventType.NOTIFICATION_REQUESTED, str(result.payout.id), "payout"
                ),
            )
    elif result.failed and result.payout is not None:
        deal = await session.get(Deal, result.payout.deal_id)
        if deal is not None:
            await enqueue(
                session,
                topic=Topic.NOTIFICATIONS,
                event_type=EventType.NOTIFICATION_REQUESTED,
                aggregate_type="Payout",
                aggregate_id=str(result.payout.id),
                payload={
                    "kind": str(NotificationKind.PAYOUT_FAILED),
                    "deal_id": str(deal.id),
                    "deal_reference": deal.reference,
                    "org_id_buyer": str(deal.org_id_buyer),
                    "org_id_seller": str(deal.org_id_seller),
                    "reason": result.reason,
                },
                event_id=deterministic_event_id(
                    EventType.NOTIFICATION_REQUESTED, str(result.payout.id), "payout_failed"
                ),
            )

    return {
        "payout_id": str(result.payout.id) if result.payout else None,
        "already_done": result.already_done,
        "failed": result.failed,
        "reason": result.reason,
    }


async def handle_notification(
    session: AsyncSession, payload: dict[str, Any], group: str = ConsumerGroup.NOTIFICATIONS
) -> dict[str, Any]:
    event_id = str(payload.get("event_id") or "")
    if event_id and await already_processed(session, event_id, group):
        return {"skipped": True}
    created = await fan_out(session, payload)
    if event_id:
        await mark_processed(session, event_id, group)
    return {"notifications_created": created}


async def handle_webhook_event(
    session: AsyncSession, payload: dict[str, Any], group: str = ConsumerGroup.WEBHOOKS
) -> dict[str, Any]:
    from app.payments.webhooks import reconcile_receipt

    event_id = str(payload.get("event_id") or "")
    if event_id and await already_processed(session, event_id, group):
        return {"skipped": True}
    result = await reconcile_receipt(session, str(payload.get("external_id")))
    if event_id:
        await mark_processed(session, event_id, group)
    return result


async def handle_chain_anchor(
    session: AsyncSession, payload: dict[str, Any], group: str = ConsumerGroup.CHAIN
) -> dict[str, Any]:
    """Chain writes go through the outbox/worker path too.

    An RPC failure never rolls back a settled payout: the anchor stays QUEUED,
    the attempt count rises, and the UI shows the degraded banner.
    """
    event_id = str(payload.get("event_id") or "")
    if event_id and await already_processed(session, event_id, group):
        return {"skipped": True}

    anchor = await session.get(ChainAnchor, uuid.UUID(str(payload["anchor_id"])))
    if anchor is None:
        return {"skipped": True, "reason": "ANCHOR_MISSING"}
    if anchor.status == "CONFIRMED":
        if event_id:
            await mark_processed(session, event_id, group)
        return {"skipped": True, "reason": "ALREADY_CONFIRMED"}

    chain = get_chain()
    if not chain.available:
        anchor.attempts = int(anchor.attempts) + 1
        anchor.last_error = f"chain unavailable: {chain.state().reason}"
        await session.flush()
        log.warning(
            "chain anchor deferred",
            extra={"anchor_id": str(anchor.id), "reason": chain.state().reason},
        )
        return {"deferred": True, "reason": chain.state().reason}

    body = anchor.payload_json or {}
    try:
        if anchor.kind == "OPEN_DEAL":
            deal = await session.get(Deal, anchor.deal_id)
            tx = chain.open_deal(
                body["deal_id_b32"],
                body["terms_hash"],
                chain._account.address,
                chain._account.address,
                int(body["milestone_count"]),
                int(body["dispute_window_ends"]),
            )
            if deal is not None:
                deal.chain_tx = tx.tx_hash
        elif anchor.kind == "ATTESTATION":
            tx = chain.anchor_attestation(
                body["deal_id_b32"],
                int(body["seq"]),
                body["evidence_root"],
                "0x" + str(body["attestation_hash"]).removeprefix("0x"),
                str(body["decision"]),
                int(body["confidence_bps"]),
                str(body["verifier_sig"]),
            )
            if anchor.attestation_id:
                attestation = await session.get(Attestation, anchor.attestation_id)
                if attestation is not None:
                    attestation.chain_tx = tx.tx_hash
                    attestation.chain_block = tx.block_number
        elif anchor.kind == "RECORD_SETTLEMENT":
            tx = chain.record_settlement(
                body["deal_id_b32"],
                int(body["seq"]),
                int(body["amount_paise"]),
                body["rail_ref"],
                bool(body["human_approved"]),
            )
        elif anchor.kind == "RAISE_DISPUTE":
            tx = chain.raise_dispute(body["deal_id_b32"], int(body["seq"]))
        elif anchor.kind == "RESOLVE_DISPUTE":
            tx = chain.resolve_dispute(
                body["deal_id_b32"],
                int(body["seq"]),
                int(body["release_paise"]),
                int(body["refund_paise"]),
                body["decision_hash"],
            )
        else:
            return {"skipped": True, "reason": f"UNKNOWN_ANCHOR_KIND:{anchor.kind}"}
    except ChainUnavailable as exc:
        anchor.attempts = int(anchor.attempts) + 1
        anchor.last_error = exc.message
        await session.flush()
        return {"deferred": True, "reason": exc.code}

    anchor.status = "CONFIRMED"
    anchor.tx_hash = tx.tx_hash
    anchor.block_number = tx.block_number
    import datetime as _dt

    anchor.confirmed_at = _dt.datetime.now(_dt.UTC)

    deal = await session.get(Deal, anchor.deal_id)
    if deal is not None:
        await append_ledger(
            session,
            deal_id=deal.id,
            org_id=deal.org_id_buyer,
            event_type=LedgerEventType.CHAIN_ANCHORED,
            actor="CHAIN_WORKER",
            reason=anchor.kind,
            payload={
                "anchor_id": str(anchor.id),
                "kind": anchor.kind,
                "tx_hash": tx.tx_hash,
                "block_number": tx.block_number,
                "explorer_url": tx.explorer_url,
            },
        )
        # Stamp the anchoring tx onto the ledger event this anchor corresponds to.
        if anchor.attestation_id:
            stmt = (
                select(LedgerEvent)
                .where(
                    LedgerEvent.deal_id == deal.id,
                    LedgerEvent.event_type == str(LedgerEventType.ATTESTATION_WRITTEN),
                )
                .order_by(LedgerEvent.seq.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is not None and row.chain_anchor_tx is None:
                row.chain_anchor_tx = tx.tx_hash

    if event_id:
        await mark_processed(session, event_id, group)
    await session.flush()
    log.info(
        "chain anchored",
        extra={"anchor_id": str(anchor.id), "kind": anchor.kind, "tx": tx.tx_hash},
    )
    return {"anchored": True, "tx_hash": tx.tx_hash, "block_number": tx.block_number}


async def handle_projection(
    session: AsyncSession, payload: dict[str, Any], group: str = ConsumerGroup.PROJECTIONS
) -> dict[str, Any]:
    """Reputation projection: a settled deal updates the counterparty profile."""
    from app.models.identity import CounterpartyProfile

    event_id = str(payload.get("event_id") or "")
    if event_id and await already_processed(session, event_id, group):
        return {"skipped": True}
    deal_id = payload.get("deal_id")
    if not deal_id:
        return {"skipped": True}
    deal = await session.get(Deal, uuid.UUID(str(deal_id)))
    if deal is None:
        return {"skipped": True}
    profile = await session.get(CounterpartyProfile, deal.seller_entity_id)
    if profile is None:
        profile = CounterpartyProfile(entity_id=deal.seller_entity_id)
        session.add(profile)
    total_released = int(
        sum(
            int(p.amount_paise)
            for p in (
                await session.execute(select(Payout).where(Payout.deal_id == deal.id))
            ).scalars()
            if p.status == "SUCCEEDED" and str(p.direction) == "RELEASE"
        )
    )
    profile.gmv_paise = int(profile.gmv_paise or 0) + 0  # GMV is recomputed on completion
    if str(deal.state) == "COMPLETED":
        profile.deals_completed = int(profile.deals_completed or 0) + 1
        profile.gmv_paise = int(profile.gmv_paise or 0) + total_released
        profile.largest_deal_paise = max(
            int(profile.largest_deal_paise or 0), int(deal.total_paise)
        )
    if event_id:
        await mark_processed(session, event_id, group)
    await session.flush()
    return {"projected": True}


HANDLERS: dict[str, Any] = {
    str(EventType.SETTLEMENT_AUTHORIZED): handle_settlement_authorized,
    str(EventType.REFUND_REQUESTED): handle_settlement_authorized,
    str(EventType.NOTIFICATION_REQUESTED): handle_notification,
    str(EventType.PAYMENT_WEBHOOK_RECEIVED): handle_webhook_event,
    str(EventType.CHAIN_ANCHOR_REQUESTED): handle_chain_anchor,
    str(EventType.SETTLEMENT_COMPLETED): handle_projection,
    str(EventType.REFUND_COMPLETED): handle_projection,
}

TOPIC_GROUPS: dict[str, str] = {
    str(Topic.SETTLEMENT): str(ConsumerGroup.SETTLEMENT),
    str(Topic.REFUNDS): str(ConsumerGroup.REFUNDS),
    str(Topic.PAYMENT_WEBHOOKS): str(ConsumerGroup.WEBHOOKS),
    str(Topic.NOTIFICATIONS): str(ConsumerGroup.NOTIFICATIONS),
    str(Topic.CHAIN): str(ConsumerGroup.CHAIN),
}


async def dispatch(session: AsyncSession, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload.get("event_type") or "")
    handler = HANDLERS.get(event_type)
    if handler is None:
        log.warning("no handler", extra={"topic": topic, "event_type": event_type})
        return {"skipped": True, "reason": "NO_HANDLER"}
    group = TOPIC_GROUPS.get(topic, str(ConsumerGroup.SETTLEMENT))
    if event_type in {
        str(EventType.SETTLEMENT_COMPLETED),
        str(EventType.REFUND_COMPLETED),
    }:
        group = str(ConsumerGroup.PROJECTIONS)
    return await handler(session, payload, group)
