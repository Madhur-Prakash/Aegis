"""Deal creation, terms signing, funding, cancellation, timeline."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attest.canonical import payload_hash
from app.attest.eip712 import deal_id_bytes32
from app.common.errors import Conflict, MoneyInvariantViolation, ValidationFailed
from app.common.logging import get_logger
from app.deals.states import DealEvent
from app.events.outbox import deterministic_event_id, enqueue
from app.events.topics import EventType, Topic
from app.ledger.service import append_ledger, transition_deal
from app.models.commerce import ChainAnchor, Deal, Milestone
from app.models.enums import DealState, LedgerEventType, NotificationKind
from app.models.identity import Entity
from app.rails.base import get_rail
from app.risk.service import score_deal
from app.settlement.guards import money_conserved

log = get_logger("deals")


async def next_reference(session: AsyncSession) -> str:
    count = int((await session.execute(select(func.count()).select_from(Deal))).scalar() or 0)
    return f"D-{4800 + count + 1}"


def build_terms(
    *,
    title: str,
    total_paise: int,
    milestones: list[dict[str, Any]],
    dispute_window_days: int,
    category: str,
    tolerance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "title": title,
        "total_paise": int(total_paise),
        "currency": "INR",
        "category": category,
        "dispute_window_days": int(dispute_window_days),
        "tolerance": tolerance or {},
        "milestones": [
            {
                "seq": int(m["seq"]),
                "title": m["title"],
                "amount_paise": int(m["amount_paise"]),
                "verification_condition": m["verification_condition"],
            }
            for m in milestones
        ],
    }


async def create_deal(
    session: AsyncSession,
    *,
    buyer_org_id: uuid.UUID,
    seller_org_id: uuid.UUID,
    buyer_entity_id: uuid.UUID,
    seller_entity_id: uuid.UUID,
    title: str,
    total_paise: int,
    milestones: list[dict[str, Any]],
    dispute_window_days: int = 7,
    category: str = "apparel",
    tolerance: dict[str, Any] | None = None,
    actor: str = "BUYER_AGENT",
    deal_id: uuid.UUID | None = None,
    reference: str | None = None,
) -> Deal:
    if not milestones:
        raise ValidationFailed(message="A deal needs at least one milestone.")
    if buyer_org_id == seller_org_id:
        raise ValidationFailed(message="A deal needs two distinct organizations.")
    milestone_total = sum(int(m["amount_paise"]) for m in milestones)
    if milestone_total != int(total_paise):
        raise MoneyInvariantViolation(
            message="Milestone amounts must sum to the deal total exactly.",
            details={"total_paise": int(total_paise), "milestones_sum_paise": milestone_total},
        )
    for m in milestones:
        if int(m["amount_paise"]) <= 0:
            raise ValidationFailed(message="Every milestone amount must be positive.")

    terms = build_terms(
        title=title,
        total_paise=total_paise,
        milestones=milestones,
        dispute_window_days=dispute_window_days,
        category=category,
        tolerance=tolerance,
    )
    deal = Deal(
        id=deal_id or uuid.uuid4(),
        reference=reference or await next_reference(session),
        title=title,
        org_id_buyer=buyer_org_id,
        org_id_seller=seller_org_id,
        buyer_entity_id=buyer_entity_id,
        seller_entity_id=seller_entity_id,
        total_paise=int(total_paise),
        state=DealState.DRAFT,
        terms_json=terms,
        terms_hash=payload_hash(terms),
        dispute_window_days=dispute_window_days,
        category=category,
        chain_deal_id=deal_id_bytes32(str(deal_id or uuid.uuid4())),
        funding_deadline=dt.datetime.now(dt.UTC) + dt.timedelta(days=7),
    )
    deal.chain_deal_id = deal_id_bytes32(str(deal.id))
    session.add(deal)
    await session.flush()

    for m in milestones:
        session.add(
            Milestone(
                deal_id=deal.id,
                seq=int(m["seq"]),
                title=m["title"],
                amount_paise=int(m["amount_paise"]),
                verification_condition_json=m["verification_condition"],
                due_at=m.get("due_at"),
            )
        )
    await session.flush()

    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.DEAL_CREATED,
        actor=actor,
        reason="deal created",
        payload={
            "reference": deal.reference,
            "total_paise": deal.total_paise,
            "terms_hash": deal.terms_hash,
            "milestone_count": len(milestones),
        },
    )
    await score_and_price(session, deal)
    from app.deals.verification import queue_notification

    await queue_notification(
        session,
        deal=deal,
        milestone=None,
        kind=NotificationKind.DEAL_CREATED,
        payload={"total_paise": deal.total_paise},
    )
    log.info(
        "deal created",
        extra={
            "deal_id": str(deal.id),
            "reference": deal.reference,
            "total_paise": deal.total_paise,
        },
    )
    return deal


async def score_and_price(session: AsyncSession, deal: Deal) -> dict[str, Any]:
    """Risk score, top-3 factors and the resulting pricing tier."""
    seller = await session.get(Entity, deal.seller_entity_id)
    assessment = await score_deal(session, deal, seller)
    deal.risk_score = assessment["risk_score"]
    deal.risk_factors_json = assessment
    deal.pricing_tier = assessment["pricing"]["tier"]
    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.RISK_SCORED,
        actor="RISK_MODEL",
        reason=assessment["pricing"]["tier"],
        payload={
            "risk_score": assessment["risk_score"],
            "score_version": assessment["score_version"],
            "pricing": assessment["pricing"],
            "top_factors": assessment["top_factors"],
        },
    )
    return assessment


async def milestone_count(session: AsyncSession, deal_id: uuid.UUID) -> int:
    """Counted with a query, never through a lazy relationship load.

    A plain ``deal.milestones`` access on an object that was constructed rather
    than queried performs synchronous IO, which raises ``MissingGreenlet`` under
    asyncio.  Every count in a write path therefore goes through here.
    """
    stmt = select(func.count()).select_from(Milestone).where(Milestone.deal_id == deal_id)
    return int((await session.execute(stmt)).scalar() or 0)


async def sign_terms(session: AsyncSession, deal: Deal, *, actor: str) -> Deal:
    count = await milestone_count(session, deal.id)
    await transition_deal(
        session,
        deal,
        DealEvent.SIGN_TERMS,
        actor=actor,
        reason="terms signed by both parties",
        payload={"terms_hash": deal.terms_hash},
    )
    anchor = ChainAnchor(
        kind="OPEN_DEAL",
        deal_id=deal.id,
        payload_json={
            "deal_id_b32": deal.chain_deal_id,
            "terms_hash": "0x" + deal.terms_hash,
            "milestone_count": count,
            "dispute_window_ends": int(
                (dt.datetime.now(dt.UTC) + dt.timedelta(days=deal.dispute_window_days)).timestamp()
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
        payload={"anchor_id": str(anchor.id), "deal_id": str(deal.id), "kind": "OPEN_DEAL"},
        event_id=deterministic_event_id(EventType.CHAIN_ANCHOR_REQUESTED, str(anchor.id)),
    )
    from app.deals.verification import queue_notification

    await queue_notification(
        session,
        deal=deal,
        milestone=None,
        kind=NotificationKind.TERMS_SIGNED,
        payload={"terms_hash": deal.terms_hash},
    )
    return deal


async def fund_deal(
    session: AsyncSession, deal: Deal, *, amount_paise: int | None = None, actor: str
) -> Deal:
    """Funds the escrow through the rail, then records the funded balance.

    The rail call happens first because a hold that fails must not leave the deal
    believing it holds money.  The balance write and the ledger event commit
    together with the caller's transaction.
    """
    amount = int(amount_paise if amount_paise is not None else deal.total_paise)
    if amount != int(deal.total_paise):
        raise MoneyInvariantViolation(
            message="Aegis funds the full deal total in one step.",
            details={"requested_paise": amount, "total_paise": int(deal.total_paise)},
        )
    rail = get_rail()
    hold = rail.create_hold(str(deal.id), amount)
    capture = rail.capture(hold)

    deal.funded_paise = amount
    if not money_conserved(
        int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise)
    ):
        raise MoneyInvariantViolation()

    await transition_deal(
        session,
        deal,
        DealEvent.FUND,
        actor=actor,
        reason="escrow funded",
        payload={
            "funded_paise": amount,
            "rail": str(rail.mode),
            "hold_ref": hold.ref,
            "capture_ref": capture.ref,
        },
    )
    from app.deals.verification import queue_notification

    await queue_notification(
        session,
        deal=deal,
        milestone=None,
        kind=NotificationKind.DEAL_FUNDED,
        payload={"funded_paise": amount, "rail": str(rail.mode)},
    )
    log.info(
        "deal funded",
        extra={
            "deal_id": str(deal.id),
            "funded_paise": amount,
            "rail": str(rail.mode),
            "rail_ref": capture.ref,
        },
    )
    return deal


async def cancel_deal(session: AsyncSession, deal: Deal, *, actor: str, reason: str) -> Deal:
    await transition_deal(session, deal, DealEvent.CANCEL, actor=actor, reason=reason)
    return deal


async def expire_if_unfunded(session: AsyncSession, deal: Deal) -> bool:
    if deal.state != DealState.TERMS_SIGNED or deal.funding_deadline is None:
        return False
    if deal.funding_deadline > dt.datetime.now(dt.UTC):
        return False
    await transition_deal(
        session,
        deal,
        DealEvent.FUNDING_WINDOW_ELAPSED,
        actor="SCHEDULER",
        reason="funding window elapsed",
    )
    return True


def money_view(deal: Deal) -> dict[str, Any]:
    """The money bar's data.  ``balanced`` is computed, never asserted."""
    funded = int(deal.funded_paise)
    released = int(deal.released_paise)
    refunded = int(deal.refunded_paise)
    held = funded - released - refunded
    return {
        "funded_paise": funded,
        "released_paise": released,
        "refunded_paise": refunded,
        "held_paise": held,
        "balanced": held + released + refunded == funded and held >= 0,
    }


async def deal_timeline(session: AsyncSession, deal_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.commerce import LedgerEvent

    events = list(
        (
            await session.execute(
                select(LedgerEvent).where(LedgerEvent.deal_id == deal_id).order_by(LedgerEvent.seq)
            )
        ).scalars()
    )
    out: list[dict[str, Any]] = []
    for ev in events:
        out.append(
            {
                "seq": int(ev.seq),
                "at": ev.created_at,
                "event_type": ev.event_type,
                "actor": ev.actor,
                "reason": ev.reason,
                "payload": ev.payload_json,
                "payload_hash": ev.payload_hash,
                "prev_hash": ev.prev_hash,
                "chain_anchor_tx": ev.chain_anchor_tx,
            }
        )
    return out


async def raise_deal_dispute_state(
    session: AsyncSession, deal: Deal, *, actor: str, reason: str
) -> None:
    from app.deals.states import deal_can

    if deal_can(deal.state, DealEvent.RAISE_DISPUTE):
        await transition_deal(session, deal, DealEvent.RAISE_DISPUTE, actor=actor, reason=reason)
    elif deal.state != DealState.DISPUTED:
        raise Conflict(
            code="DEAL_NOT_DISPUTABLE",
            message=f"A deal in {deal.state} cannot be disputed.",
            details={"state": str(deal.state)},
        )
