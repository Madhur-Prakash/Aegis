"""Hash-chained, append-only audit ledger (I5) and the transition decorator.

``payload_hash = sha256(canonical_json(payload))``; ``prev_hash`` is the previous
event's ``payload_hash`` **for that deal**; genesis is 64 zeros.

Appends for one deal are serialised by a transaction-scoped Postgres advisory
lock taken inside :func:`append_ledger` itself, not by convention in the
callers.  Without it two concurrent transactions -- an API request and the
settlement worker, say -- both read the same head, both write it as their
``prev_hash``, and the chain forks: ``verify_chain`` then reports
``PREV_HASH_MISMATCH``.  That was a real defect, found by running the demo
against the live worker rather than an in-process bus.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.attest.canonical import payload_hash as hash_payload
from app.common.errors import IllegalTransition
from app.common.logging import get_logger
from app.deals.states import (
    DealEvent,
    MilestoneEvent,
    next_deal_state,
    next_milestone_state,
)
from app.models.commerce import Deal, LedgerEvent, Milestone
from app.models.enums import LedgerEventType

GENESIS_HASH = "0" * 64
# How long an append will wait for another transaction's lock on the same deal.
LEDGER_LOCK_TIMEOUT_MS = 5_000
log = get_logger("ledger")


async def _lock_deal_ledger(session: AsyncSession, deal_id: uuid.UUID) -> None:
    """Serialises appends for one deal for the rest of this transaction.

    ``pg_advisory_xact_lock`` is released on commit or rollback, so a crash
    cannot leave the lock held.  It is keyed on the deal, so appends for
    different deals never contend.
    """
    # Bounded: real contention on one deal clears in milliseconds, so a long
    # wait means something pathological -- another transaction holding the lock
    # and never ending.  A typed failure is far better than a request thread that
    # hangs forever, and `lock_timeout` is transaction-local.
    await session.execute(text(f"SET LOCAL lock_timeout = '{LEDGER_LOCK_TIMEOUT_MS}ms'"))
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"aegis:ledger:{deal_id}"},
    )


async def _prev_hash(session: AsyncSession, deal_id: uuid.UUID) -> str:
    stmt = (
        select(LedgerEvent.payload_hash)
        .where(LedgerEvent.deal_id == deal_id)
        .order_by(LedgerEvent.seq.desc())
        .limit(1)
    )
    prev = (await session.execute(stmt)).scalar_one_or_none()
    return prev or GENESIS_HASH


async def append_ledger(
    session: AsyncSession,
    *,
    deal_id: uuid.UUID,
    org_id: uuid.UUID,
    event_type: LedgerEventType | str,
    actor: str,
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> LedgerEvent:
    """Appends exactly one hash-chained event.  Never called twice per transition."""
    body = payload or {}
    await _lock_deal_ledger(session, deal_id)
    prev = await _prev_hash(session, deal_id)
    canonical = {
        "deal_id": str(deal_id),
        "event_type": str(event_type),
        "actor": actor,
        "reason": reason,
        "payload": body,
        "prev_hash": prev,
    }
    event = LedgerEvent(
        deal_id=deal_id,
        org_id=org_id,
        event_type=str(event_type),
        actor=actor,
        reason=reason,
        payload_json=body,
        payload_hash=hash_payload(canonical),
        prev_hash=prev,
    )
    session.add(event)
    await session.flush()
    log.info(
        "ledger append",
        extra={
            "deal_id": str(deal_id),
            "event_type": str(event_type),
            "seq": event.seq,
            "payload_hash": event.payload_hash,
        },
    )
    return event


@dataclass(slots=True)
class TransitionResult:
    from_state: str
    to_state: str
    ledger_event: LedgerEvent


async def transition_deal(
    session: AsyncSession,
    deal: Deal,
    event: DealEvent,
    *,
    actor: str,
    reason: str = "",
    target: Any = None,
    payload: dict[str, Any] | None = None,
) -> TransitionResult:
    """The only way a Deal's state changes.  Validates, mutates, appends one event."""
    before = deal.state
    try:
        after = next_deal_state(before, event, target)
    except IllegalTransition as exc:
        await _log_illegal(session, deal.id, deal.org_id_buyer, "Deal", before, event, actor)
        raise exc
    deal.state = after
    ledger = await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.DEAL_TRANSITION,
        actor=actor,
        reason=reason,
        payload={
            "entity": "deal",
            "from": str(before),
            "event": str(event),
            "to": str(after),
            **(payload or {}),
        },
    )
    log.info(
        "deal transition",
        extra={"deal_id": str(deal.id), "from": str(before), "to": str(after), "event": str(event)},
    )
    return TransitionResult(str(before), str(after), ledger)


async def transition_milestone(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    event: MilestoneEvent,
    *,
    actor: str,
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> TransitionResult:
    """The only way a Milestone's state changes."""
    before = milestone.state
    try:
        after = next_milestone_state(before, event)
    except IllegalTransition as exc:
        await _log_illegal(session, deal.id, deal.org_id_buyer, "Milestone", before, event, actor)
        raise exc
    milestone.state = after
    ledger = await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.MILESTONE_TRANSITION,
        actor=actor,
        reason=reason,
        payload={
            "entity": "milestone",
            "milestone_id": str(milestone.id),
            "seq": milestone.seq,
            "from": str(before),
            "event": str(event),
            "to": str(after),
            **(payload or {}),
        },
    )
    log.info(
        "milestone transition",
        extra={
            "deal_id": str(deal.id),
            "milestone_id": str(milestone.id),
            "from": str(before),
            "to": str(after),
            "event": str(event),
        },
    )
    return TransitionResult(str(before), str(after), ledger)


async def _log_illegal(
    session: AsyncSession,
    deal_id: uuid.UUID,
    org_id: uuid.UUID,
    entity: str,
    state: Any,
    event: Any,
    actor: str,
) -> None:
    """An illegal transition is logged loudly, and never silently passes."""
    log.warning(
        "illegal transition attempt",
        extra={
            "deal_id": str(deal_id),
            "entity": entity,
            "from": str(state),
            "event": str(event),
            "actor": actor,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────────────────────────────────────
async def verify_chain(session: AsyncSession, deal_id: uuid.UUID) -> dict[str, Any]:
    """Recomputes every hash in a deal's ledger and reports the exact broken index."""
    stmt = select(LedgerEvent).where(LedgerEvent.deal_id == deal_id).order_by(LedgerEvent.seq)
    events = list((await session.execute(stmt)).scalars())
    prev = GENESIS_HASH
    for index, ev in enumerate(events):
        canonical = {
            "deal_id": str(ev.deal_id),
            "event_type": ev.event_type,
            "actor": ev.actor,
            "reason": ev.reason,
            "payload": ev.payload_json,
            "prev_hash": ev.prev_hash,
        }
        expected = hash_payload(canonical)
        if ev.prev_hash != prev:
            return {
                "ok": False,
                "broken_index": index,
                "reason": "PREV_HASH_MISMATCH",
                "expected": prev,
                "found": ev.prev_hash,
                "length": len(events),
            }
        if expected != ev.payload_hash:
            return {
                "ok": False,
                "broken_index": index,
                "reason": "PAYLOAD_HASH_MISMATCH",
                "expected": expected,
                "found": ev.payload_hash,
                "length": len(events),
            }
        prev = ev.payload_hash
    return {"ok": True, "broken_index": None, "length": len(events), "head": prev}


async def replay_balances(session: AsyncSession, deal_id: uuid.UUID) -> dict[str, int]:
    """Reconstructs funded/released/refunded purely from ledger events."""
    stmt = select(LedgerEvent).where(LedgerEvent.deal_id == deal_id).order_by(LedgerEvent.seq)
    funded = released = refunded = 0
    for ev in (await session.execute(stmt)).scalars():
        payload = ev.payload_json or {}
        if ev.event_type == str(LedgerEventType.DEAL_TRANSITION) and payload.get("event") == "fund":
            funded += int(payload.get("funded_paise", 0))
        elif ev.event_type == str(LedgerEventType.PAYOUT_RECORDED):
            amount = int(payload.get("amount_paise", 0))
            if payload.get("direction") == "RELEASE":
                released += amount
            else:
                refunded += amount
    return {
        "funded_paise": funded,
        "released_paise": released,
        "refunded_paise": refunded,
        "held_paise": funded - released - refunded,
    }
