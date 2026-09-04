"""/api/v1 -- payments, settlements, notifications, chat, realtime, reputation, health, dev."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    MarkReadIn,
    MessageIn,
    MessageOut,
    NotificationOut,
    NotificationPreferenceIn,
    Ok,
)
from app.chain.adapter import get_chain
from app.common.deps import MemberDep, MembershipDep, RepoDep, SessionDep, ViewerDep
from app.common.logging import get_logger
from app.config.settings import settings
from app.events.bus import kafka_ready
from app.events.outbox import deterministic_event_id, enqueue
from app.events.topics import EventType, Topic
from app.models.commerce import (
    Attestation,
    DeadLetter,
    Deal,
    OutboxEvent,
    Payout,
    SettlementAuthorization,
)
from app.models.enums import NotificationKind
from app.models.identity import DealMessage, TokenSpend, User
from app.notifications import service as notification_service
from app.payments.webhooks import handle_webhook
from app.rails.base import rail_disclosure
from app.realtime.hub import get_hub
from app.risk.service import counterparty_passport

log = get_logger("api.misc")
router = APIRouter(tags=["platform"])


# ── Payments ────────────────────────────────────────────────────────────────
@router.get("/payments/rail", response_model=dict)
async def rail_mode() -> dict[str, Any]:
    """The per-operation real-vs-simulated disclosure the README also carries."""
    return rail_disclosure()


@router.post("/payments/webhooks/razorpay")
async def razorpay_webhook(request: Request, session: SessionDep) -> dict[str, Any]:
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    result = await handle_webhook(session, body, signature)
    await session.commit()
    return result


@router.get("/payments/deals/{deal_id}/payouts", response_model=list[dict])
async def payouts(deal_id: uuid.UUID, repo: RepoDep) -> list[dict[str, Any]]:
    rows = await repo.list_payouts(deal_id)
    return [
        {
            "id": str(p.id),
            "milestone_id": str(p.milestone_id),
            "direction": str(p.direction),
            "amount_paise": int(p.amount_paise),
            "rail": p.rail,
            "rail_ref": p.rail_ref,
            "status": str(p.status),
            "failure_reason": p.failure_reason,
            "created_at": p.created_at,
        }
        for p in rows
    ]


@router.get("/settlements/deals/{deal_id}", response_model=list[dict])
async def settlements(deal_id: uuid.UUID, repo: RepoDep) -> list[dict[str, Any]]:
    rows = await repo.list_authorizations(deal_id)
    return [
        {
            "id": str(a.id),
            "milestone_id": str(a.milestone_id),
            "attestation_id": str(a.attestation_id),
            "direction": str(a.direction),
            "amount_paise": int(a.amount_paise),
            "attempt_no": int(a.attempt_no),
            "authorized_by": str(a.authorized_by),
            "human_approved": bool(a.human_approved),
            "authorized_at": a.authorized_at,
            "consumed_at": a.consumed_at,
            "idempotency_key": a.idempotency_key,
        }
        for a in rows
    ]


# ── Reputation ──────────────────────────────────────────────────────────────
@router.get("/reputation/entities/{entity_id}", response_model=dict)
async def reputation(
    entity_id: uuid.UUID, membership: ViewerDep, session: SessionDep
) -> dict[str, Any]:
    """A counterparty passport is intentionally readable across tenants: it is the
    public trading record the other side needs before agreeing to a deal.  It
    contains no deal contents, no evidence and no member identities."""
    return await counterparty_passport(session, entity_id)


# ── Notifications ───────────────────────────────────────────────────────────
@router.get("/notifications", response_model=dict)
async def notifications(membership: ViewerDep, session: SessionDep) -> dict[str, Any]:
    rows = await notification_service.list_notifications(
        session, membership.user.id, membership.org_id
    )
    return {
        "unread": await notification_service.unread_count(
            session, membership.user.id, membership.org_id
        ),
        "items": [
            NotificationOut(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                deal_id=n.deal_id,
                read_at=n.read_at,
                created_at=n.created_at,
            ).model_dump()
            for n in rows
        ],
    }


@router.post("/notifications/mark-read", response_model=dict)
async def mark_read(
    payload: MarkReadIn, membership: ViewerDep, session: SessionDep
) -> dict[str, Any]:
    count = await notification_service.mark_read(
        session, membership.user.id, membership.org_id, payload.ids
    )
    await session.commit()
    return {"marked": count}


@router.get("/notifications/preferences", response_model=list[dict])
async def preferences(membership: ViewerDep, session: SessionDep) -> list[dict[str, Any]]:
    return await notification_service.default_preferences(session, membership.user.id)


@router.put("/notifications/preferences", response_model=Ok)
async def set_preference(
    payload: NotificationPreferenceIn, membership: ViewerDep, session: SessionDep
) -> Ok:
    await notification_service.set_preference(
        session, membership.user.id, payload.kind, in_app=payload.in_app, email=payload.email
    )
    await session.commit()
    return Ok()


# ── Deal chat ───────────────────────────────────────────────────────────────
@router.get("/chat/deals/{deal_id}", response_model=list[MessageOut])
async def messages(
    deal_id: uuid.UUID, membership: ViewerDep, repo: RepoDep, session: SessionDep
) -> list[MessageOut]:
    await repo.get_deal(deal_id)
    rows = list(
        (
            await session.execute(
                select(DealMessage, User)
                .join(User, User.id == DealMessage.sender_user_id)
                .where(DealMessage.deal_id == deal_id)
                .order_by(DealMessage.created_at)
            )
        ).all()
    )
    return [
        MessageOut(
            id=m.id,
            deal_id=m.deal_id,
            sender_user_id=m.sender_user_id,
            sender_name=u.name,
            sender_org_id=m.org_id,
            body=m.body,
            created_at=m.created_at,
            mine=m.sender_user_id == membership.user.id,
        )
        for m, u in rows
    ]


@router.post("/chat/deals/{deal_id}", response_model=MessageOut, status_code=201)
async def send_message(
    deal_id: uuid.UUID,
    payload: MessageIn,
    membership: MemberDep,
    repo: RepoDep,
    session: SessionDep,
) -> MessageOut:
    """Deal-scoped chat.  Never fed to the verifier as evidence."""
    deal = await repo.get_deal(deal_id)
    message = DealMessage(
        deal_id=deal.id,
        org_id=membership.org_id,
        sender_user_id=membership.user.id,
        body=payload.body,
    )
    session.add(message)
    await enqueue(
        session,
        topic=Topic.NOTIFICATIONS,
        event_type=EventType.NOTIFICATION_REQUESTED,
        aggregate_type="Deal",
        aggregate_id=str(deal.id),
        payload={
            "kind": str(NotificationKind.MESSAGE_RECEIVED),
            "deal_id": str(deal.id),
            "deal_reference": deal.reference,
            "org_id_buyer": str(deal.org_id_buyer),
            "org_id_seller": str(deal.org_id_seller),
            "sender_name": membership.user.name,
        },
        event_id=deterministic_event_id(
            EventType.NOTIFICATION_REQUESTED,
            str(deal.id),
            f"msg:{dt.datetime.now(dt.UTC).timestamp()}",
        ),
    )
    await session.commit()
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await get_hub().publish(
            "chat",
            org,
            "chat.message",
            {"deal_id": str(deal.id), "message_id": str(message.id)},
            scope=str(deal.id),
        )
    return MessageOut(
        id=message.id,
        deal_id=message.deal_id,
        sender_user_id=message.sender_user_id,
        sender_name=membership.user.name,
        sender_org_id=message.org_id,
        body=message.body,
        created_at=message.created_at,
        mine=True,
    )


# ── Realtime (SSE) ──────────────────────────────────────────────────────────
async def _sse(
    session: AsyncSession,
    concern: str,
    org_id: uuid.UUID,
    scope: str | None = None,
) -> StreamingResponse:
    """Subscribes to the hub, having first handed the database session back.

    A dependency-provided session is normally closed when the response finishes.
    For a StreamingResponse that is when the *stream* finishes -- which for SSE
    is minutes or hours -- so every subscriber was pinning a pooled connection
    inside an open transaction.  That blocks DDL (it was blocking the test
    suite's TRUNCATE) and exhausts the pool at a handful of open tabs.

    The stream itself touches no database: the hub is in-process, and clients
    re-fetch through ordinary requests. So the session is closed here, before the
    response is returned.
    """
    await session.close()
    return StreamingResponse(
        get_hub().subscribe(concern, org_id, scope),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/realtime/deals")
async def sse_deals(membership: MembershipDep, session: SessionDep) -> StreamingResponse:
    return await _sse(session, "deals", membership.org_id)


@router.get("/realtime/verification/{milestone_id}")
async def sse_verification(
    milestone_id: uuid.UUID, membership: MembershipDep, session: SessionDep
) -> StreamingResponse:
    return await _sse(session, "verification", membership.org_id, str(milestone_id))


@router.get("/realtime/review")
async def sse_review(membership: MembershipDep, session: SessionDep) -> StreamingResponse:
    return await _sse(session, "review", membership.org_id)


@router.get("/realtime/chat/{deal_id}")
async def sse_chat(
    deal_id: uuid.UUID, membership: MembershipDep, session: SessionDep
) -> StreamingResponse:
    return await _sse(session, "chat", membership.org_id, str(deal_id))


@router.get("/realtime/notifications")
async def sse_notifications(membership: MembershipDep, session: SessionDep) -> StreamingResponse:
    return await _sse(session, "notifications", membership.org_id)


# ── Health and metrics ──────────────────────────────────────────────────────
@router.get("/health/live", response_model=dict)
async def live() -> dict[str, Any]:
    return {"ok": True, "service": settings.SERVICE_NAME}


@router.get("/health/ready", response_model=dict)
async def ready(session: SessionDep) -> dict[str, Any]:
    from app.common.redis_client import redis_ready
    from app.storage.store import store_ready

    postgres = True
    try:
        await session.execute(select(1))
    except Exception:
        postgres = False
    redis_ok = await redis_ready()
    kafka_ok = await kafka_ready()
    chain = get_chain()
    store_ok = store_ready()

    checks: dict[str, dict[str, Any]] = {
        "postgres": {"ready": postgres, "required": True},
        "redis": {"ready": redis_ok, "required": False},
        "kafka": {"ready": kafka_ok, "required": False},
        "object_store": {"ready": store_ok, "required": True},
        "chain_rpc": {
            "ready": chain.available,
            "required": False,
            "reason": chain.state().reason,
        },
        "payment_rail": {"ready": True, "required": True, "mode": rail_disclosure()["mode"]},
    }
    degraded = [
        name for name, check in checks.items() if not check["ready"] and not check["required"]
    ]
    hard_down = [name for name, check in checks.items() if not check["ready"] and check["required"]]
    return {
        "ok": not hard_down,
        "degraded": degraded,
        "checks": checks,
        "ai_provider": settings.ai_effective_provider,
    }


@router.get("/health/metrics", response_model=dict)
async def metrics(session: SessionDep) -> dict[str, Any]:
    verifications = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(Attestation.decision, func.count()).group_by(Attestation.decision)
            )
        ).all()
    }
    settlements = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(select(Payout.status, func.count()).group_by(Payout.status))
        ).all()
    }
    dlq_depth = int(
        (
            await session.execute(
                select(func.count()).select_from(DeadLetter).where(DeadLetter.drained_at.is_(None))
            )
        ).scalar()
        or 0
    )
    outbox_backlog = int(
        (
            await session.execute(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
            )
        ).scalar()
        or 0
    )
    spend: Any = (
        await session.execute(
            select(
                func.coalesce(func.sum(TokenSpend.cost_micro_usd), 0),
                func.coalesce(func.sum(TokenSpend.input_tokens), 0),
                func.coalesce(func.sum(TokenSpend.output_tokens), 0),
                func.coalesce(func.sum(TokenSpend.cache_read_tokens), 0),
                func.count(),
            )
        )
    ).one()
    return {
        "verifications_by_decision": verifications,
        "settlements_by_status": settlements,
        "dlq_depth": dlq_depth,
        "outbox_backlog": outbox_backlog,
        "sse_subscribers": get_hub().depth(),
        "ai_spend": {
            "calls": int(spend[4]),
            "cost_micro_usd": int(spend[0]),
            "input_tokens": int(spend[1]),
            "output_tokens": int(spend[2]),
            "cache_read_tokens": int(spend[3]),
        },
        "authorizations": int(
            (
                await session.execute(select(func.count()).select_from(SettlementAuthorization))
            ).scalar()
            or 0
        ),
        "deals": int((await session.execute(select(func.count()).select_from(Deal))).scalar() or 0),
    }


# ── Measured evaluation results ─────────────────────────────────────────────
_EVAL_SUMMARY = Path(__file__).resolve().parents[3] / "evals" / "out" / "summary.json"


@router.get("/health/eval-summary", response_model=dict)
async def eval_summary() -> dict[str, Any]:
    """The headline numbers from the last ``make eval`` run, verbatim.

    The landing page renders these.  It exists so that no figure on a marketing
    surface can be typed by hand: if the file is absent the endpoint says so and
    the interface shows nothing rather than a number nobody measured.
    """
    if not _EVAL_SUMMARY.exists():
        return {
            "available": False,
            "reason": "evals/out/summary.json is absent -- run `make eval`",
        }
    try:
        payload = json.loads(_EVAL_SUMMARY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - disk-level failure
        return {"available": False, "reason": f"could not read summary: {exc}"}
    return {"available": True, **payload}
