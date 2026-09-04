"""The deterministic settlement engine.

**This is the only module in the codebase that authorises money movement, and it
never imports ``app.agents``.**  It reads persisted attestation rows; it does not
call a model, and no model can call it.  The CI import-lint
(``scripts/import_lint.py``) fails the build if that boundary is ever crossed.

Authorisation and execution are separate:

``authorize()``  re-checks I1, I3, I4, I8, then in ONE DB transaction writes the
milestone transition, the SettlementAuthorization, the IdempotencyRecord, the
LedgerEvent and the OutboxEvent (I13).

``execute()``    runs in the worker: Redis lock, idempotency check, **re-read and
re-validate from Postgres**, rail call, Payout + LedgerEvent in one transaction,
then the completion outbox event.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import (
    ConfidenceBelowReleaseThreshold,
    Conflict,
    HumanDecisionRequired,
    MoneyInvariantViolation,
    NoQualifyingAttestation,
    RailFailure,
    UnverifiableRequiredClause,
)
from app.common.logging import get_logger
from app.common.redis_client import distributed_lock
from app.config.settings import CALIBRATION_VERSION, REJECT_THRESHOLD, RELEASE_THRESHOLD
from app.deals.states import MilestoneEvent
from app.events.outbox import deterministic_event_id, enqueue
from app.events.topics import EventType, Topic
from app.ledger.service import append_ledger, transition_milestone
from app.models.commerce import (
    Attestation,
    Deal,
    Dispute,
    IdempotencyRecord,
    Milestone,
    Payout,
    SettlementAuthorization,
)
from app.models.enums import (
    AuthorizedBy,
    Decision,
    Direction,
    LedgerEventType,
    MilestoneState,
    PayoutStatus,
)
from app.rails.base import get_rail, idempotency_key
from app.settlement.guards import (
    ClauseOutcome,
    DecisionInput,
    decide,
    refund_would_conserve,
    release_would_conserve,
)

log = get_logger("settlement")

# A claim older than this with no successful payout is reclaimable, so a worker
# that died between claiming and paying cannot strand a milestone.
CLAIM_TTL_S = 180


@dataclass(slots=True)
class AuthorizationResult:
    authorization: SettlementAuthorization
    event_id: str
    already_authorized: bool = False


def _clause_outcomes(attestation: Attestation) -> tuple[ClauseOutcome, ...]:
    return tuple(
        ClauseOutcome(
            clause_id=str(v.get("clause_id")),
            verdict=str(v.get("verdict")),
            required=bool(v.get("required", True)),
        )
        for v in (attestation.clause_verdicts_json or [])
    )


async def _next_attempt_no(
    session: AsyncSession, milestone_id: uuid.UUID, direction: Direction
) -> int:
    stmt = (
        select(func.count())
        .select_from(SettlementAuthorization)
        .where(
            SettlementAuthorization.milestone_id == milestone_id,
            SettlementAuthorization.direction == direction,
        )
    )
    return int((await session.execute(stmt)).scalar() or 0) + 1


async def authorize_release(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    attestation: Attestation,
    *,
    actor: str = "ENGINE",
    human_user_id: uuid.UUID | None = None,
) -> AuthorizationResult:
    """Authorise a milestone release.  Every invariant is re-checked here, from
    the database row -- never from whatever the caller believes."""

    # ── I1: a qualifying attestation must exist and reference this milestone ──
    if attestation is None or attestation.milestone_id != milestone.id:
        raise NoQualifyingAttestation(details={"milestone_id": str(milestone.id)})

    clauses = _clause_outcomes(attestation)
    engine_decision, rationale = decide(
        DecisionInput(confidence=float(attestation.confidence), clauses=clauses)
    )

    authorized_by = AuthorizedBy.HUMAN if human_user_id else AuthorizedBy.ENGINE

    # ── I3: no bypass, and no admin override of the release rule ──────────────
    if authorized_by == AuthorizedBy.ENGINE:
        if engine_decision != "RELEASE":
            if rationale["unverifiable_required_clauses"]:
                raise UnverifiableRequiredClause(details=rationale)
            raise ConfidenceBelowReleaseThreshold(details=rationale)
    else:
        # A human may approve an ESCALATE.  A human may NOT approve a REJECT
        # produced by a failed required clause, and may not turn an UNVERIFIABLE
        # required clause into an automatic release -- they take the decision on
        # the record, which is what human_approved=True means on-chain.
        if rationale["failed_required_clauses"]:
            raise ConfidenceBelowReleaseThreshold(
                message="A required clause failed; a human cannot approve a release.",
                details=rationale,
            )
        if attestation.decision == Decision.REJECT:
            raise ConfidenceBelowReleaseThreshold(
                message="The verifier rejected this evidence; resubmission is required.",
                details=rationale,
            )

    amount = int(milestone.amount_paise)

    # ── I4: this release must keep the sum invariant ──────────────────────────
    if not release_would_conserve(
        int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise), amount
    ):
        raise MoneyInvariantViolation(
            details={
                "funded_paise": int(deal.funded_paise),
                "released_paise": int(deal.released_paise),
                "refunded_paise": int(deal.refunded_paise),
                "requested_paise": amount,
            }
        )

    return await _write_authorization(
        session,
        deal=deal,
        milestone=milestone,
        attestation=attestation,
        direction=Direction.RELEASE,
        amount=amount,
        authorized_by=authorized_by,
        human_user_id=human_user_id,
        actor=actor,
        rationale=rationale,
        # A retry after a failed rail call re-authorises a milestone that is
        # already RELEASE_APPROVED; there is no transition left to make, and
        # forcing one would raise IllegalTransition on a perfectly legitimate
        # second attempt.
        transition_event=_release_transition(milestone, authorized_by),
    )


def _release_transition(milestone: Milestone, authorized_by: AuthorizedBy) -> MilestoneEvent | None:
    from app.deals.states import milestone_can

    if milestone.state == MilestoneState.RELEASE_APPROVED:
        return None  # already approved: this is a retry, not a new decision
    if authorized_by == AuthorizedBy.HUMAN and milestone.state == MilestoneState.UNDER_HUMAN_REVIEW:
        return MilestoneEvent.HUMAN_APPROVE
    if milestone_can(milestone.state, MilestoneEvent.ATTEST_RELEASE):
        return MilestoneEvent.ATTEST_RELEASE
    return None


async def authorize_dispute_split(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    dispute: Dispute,
    attestation: Attestation,
    *,
    release_paise: int,
    refund_paise: int,
    human_user_id: uuid.UUID,
    actor: str,
) -> list[AuthorizationResult]:
    """Authorise both legs of a resolved dispute.

    I8: ``human_decided_by`` must already be set on the dispute.  The engine
    refuses to move a rupee on an arbiter recommendation alone.
    """
    if dispute.human_decided_by is None:
        raise HumanDecisionRequired(details={"dispute_id": str(dispute.id)})
    if release_paise + refund_paise != int(milestone.amount_paise):
        raise MoneyInvariantViolation(
            message="The split must equal the milestone amount exactly.",
            details={
                "release_paise": release_paise,
                "refund_paise": refund_paise,
                "milestone_amount_paise": int(milestone.amount_paise),
            },
        )
    if release_paise and not release_would_conserve(
        int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise), release_paise
    ):
        raise MoneyInvariantViolation(details={"leg": "RELEASE"})
    if refund_paise and not refund_would_conserve(
        int(deal.funded_paise),
        int(deal.released_paise) + release_paise,
        int(deal.refunded_paise),
        refund_paise,
    ):
        raise MoneyInvariantViolation(details={"leg": "REFUND"})

    results: list[AuthorizationResult] = []
    rationale = {
        "rule": "HUMAN_DISPUTE_DECISION",
        "dispute_id": str(dispute.id),
        "release_paise": release_paise,
        "refund_paise": refund_paise,
    }
    first = True
    for direction, amount in (
        (Direction.RELEASE, release_paise),
        (Direction.REFUND, refund_paise),
    ):
        if amount <= 0:
            continue
        results.append(
            await _write_authorization(
                session,
                deal=deal,
                milestone=milestone,
                attestation=attestation,
                direction=direction,
                amount=amount,
                authorized_by=AuthorizedBy.HUMAN,
                human_user_id=human_user_id,
                actor=actor,
                rationale=rationale,
                dispute=dispute,
                transition_event=MilestoneEvent.RESOLVE if first else None,
            )
        )
        first = False
    return results


async def authorize_refund(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    attestation: Attestation,
    *,
    amount_paise: int,
    human_user_id: uuid.UUID,
    actor: str,
) -> AuthorizationResult:
    if not refund_would_conserve(
        int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise), amount_paise
    ):
        raise MoneyInvariantViolation(details={"requested_paise": amount_paise})
    return await _write_authorization(
        session,
        deal=deal,
        milestone=milestone,
        attestation=attestation,
        direction=Direction.REFUND,
        amount=amount_paise,
        authorized_by=AuthorizedBy.HUMAN,
        human_user_id=human_user_id,
        actor=actor,
        rationale={"rule": "HUMAN_REFUND"},
        transition_event=None,
    )


async def _write_authorization(
    session: AsyncSession,
    *,
    deal: Deal,
    milestone: Milestone,
    attestation: Attestation,
    direction: Direction,
    amount: int,
    authorized_by: AuthorizedBy,
    human_user_id: uuid.UUID | None,
    actor: str,
    rationale: dict[str, Any],
    transition_event: MilestoneEvent | None,
    dispute: Dispute | None = None,
) -> AuthorizationResult:
    """ONE DB TRANSACTION (I13).  The caller commits; this function never does."""
    attempt_no = await _next_attempt_no(session, milestone.id, direction)
    key = idempotency_key(str(milestone.id), str(direction), attempt_no)

    # I6: the unique index is the real guarantee.  A duplicate authorisation for
    # the same (milestone, direction, attempt) is a no-op, not a second payout.
    existing = (
        await session.execute(
            select(SettlementAuthorization).where(SettlementAuthorization.idempotency_key == key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return AuthorizationResult(
            existing,
            deterministic_event_id(EventType.SETTLEMENT_AUTHORIZED, str(existing.id)),
            already_authorized=True,
        )

    if transition_event is not None:
        await transition_milestone(
            session,
            deal,
            milestone,
            transition_event,
            actor=actor,
            reason=str(rationale.get("rule", "")),
            payload={
                "attestation_id": str(attestation.id),
                "confidence": float(attestation.confidence),
            },
        )

    authorization = SettlementAuthorization(
        milestone_id=milestone.id,
        deal_id=deal.id,
        attestation_id=attestation.id,
        dispute_id=dispute.id if dispute else None,
        direction=direction,
        amount_paise=amount,
        attempt_no=attempt_no,
        idempotency_key=key,
        authorized_by=authorized_by,
        authorized_by_user_id=human_user_id,
        human_approved=authorized_by == AuthorizedBy.HUMAN,
    )
    session.add(authorization)
    session.add(
        IdempotencyRecord(idempotency_key=key, scope=f"authorize:{direction}", result_ref=None)
    )
    await session.flush()

    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.SETTLEMENT_AUTHORIZED,
        actor=actor,
        reason=str(rationale.get("rule", "")),
        payload={
            "authorization_id": str(authorization.id),
            "milestone_id": str(milestone.id),
            "attestation_id": str(attestation.id),
            "direction": str(direction),
            "amount_paise": amount,
            "attempt_no": attempt_no,
            "authorized_by": str(authorized_by),
            "human_approved": authorization.human_approved,
            "thresholds": {"release": RELEASE_THRESHOLD, "reject": REJECT_THRESHOLD},
            "calibration_version": CALIBRATION_VERSION,
            "rationale": rationale,
        },
    )

    event_id = deterministic_event_id(EventType.SETTLEMENT_AUTHORIZED, str(authorization.id))
    await enqueue(
        session,
        topic=Topic.SETTLEMENT if direction == Direction.RELEASE else Topic.REFUNDS,
        event_type=(
            EventType.SETTLEMENT_AUTHORIZED
            if direction == Direction.RELEASE
            else EventType.REFUND_REQUESTED
        ),
        aggregate_type="SettlementAuthorization",
        aggregate_id=str(authorization.id),
        payload={
            "authorization_id": str(authorization.id),
            "deal_id": str(deal.id),
            "milestone_id": str(milestone.id),
            "direction": str(direction),
            "amount_paise": amount,
            "idempotency_key": key,
        },
        event_id=event_id,
    )

    log.info(
        "settlement authorized",
        extra={
            "deal_id": str(deal.id),
            "milestone_id": str(milestone.id),
            "attestation_id": str(attestation.id),
            "settlement_event_id": str(authorization.id),
            "direction": str(direction),
            "amount_paise": amount,
            "idempotency_key": key,
            "authorized_by": str(authorized_by),
        },
    )
    return AuthorizationResult(authorization, event_id)


# ─────────────────────────────────────────────────────────────────────────────
# Execution (settlement worker)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class ExecutionResult:
    payout: Payout | None
    already_done: bool
    failed: bool = False
    reason: str | None = None


async def execute_authorization(
    session: AsyncSession, authorization_id: uuid.UUID | str
) -> ExecutionResult:
    """Executes an authorisation exactly once.

    The consumer trusts the database, never the message payload: the
    authorisation is re-read and re-validated here, so a stale or replayed event
    can never release money.
    """
    authorization = await session.get(SettlementAuthorization, uuid.UUID(str(authorization_id)))
    if authorization is None:
        return ExecutionResult(
            None, already_done=False, failed=True, reason="AUTHORIZATION_MISSING"
        )

    # The Redis lock is the fast path: it keeps twenty concurrent deliveries from
    # all hitting the same database row.  It is NOT the guarantee -- correctness
    # must not depend on the cache being up -- so the claim below is the real
    # serialisation point.
    async with distributed_lock(f"milestone:{authorization.milestone_id}", required=False):
        # ── idempotency: already done? ack and stop ─────────────────────
        existing = (
            await session.execute(
                select(Payout).where(Payout.idempotency_key == authorization.idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status == PayoutStatus.SUCCEEDED:
            return ExecutionResult(existing, already_done=True)

        if authorization.consumed_at is not None and existing is not None:
            return ExecutionResult(existing, already_done=True)

        # ── I6: claim the authorization atomically, before the rail call ─
        #
        # One conditional UPDATE decides the winner.  Concurrent transactions
        # block on the row, then re-evaluate the predicate and match zero rows,
        # so exactly one worker proceeds to the rail.  A claim older than
        # CLAIM_TTL with no successful payout is reclaimable, so a worker that
        # died mid-flight does not strand the milestone forever.
        stale_before = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=CLAIM_TTL_S)
        claimed = await session.execute(
            update(SettlementAuthorization)
            .where(
                SettlementAuthorization.id == authorization.id,
                SettlementAuthorization.consumed_at.is_(None),
                or_(
                    SettlementAuthorization.claimed_at.is_(None),
                    SettlementAuthorization.claimed_at < stale_before,
                ),
            )
            .values(claimed_at=dt.datetime.now(dt.UTC))
            .returning(SettlementAuthorization.id)
        )
        if claimed.first() is None:
            # Another worker holds the claim and is mid-flight.  This is NOT
            # "already done": no payout exists yet, so the caller must not mark
            # the event processed.  At-least-once delivery will bring it back,
            # and by then either the payout exists (ack) or the claim has gone
            # stale (retry).
            log.info(
                "settlement claim held by another worker",
                extra={"settlement_event_id": str(authorization.id)},
            )
            return ExecutionResult(
                existing,
                already_done=existing is not None and existing.status == PayoutStatus.SUCCEEDED,
                failed=existing is None,
                reason=None if existing is not None else "CLAIM_HELD_BY_ANOTHER_WORKER",
            )
        # The claim must be visible to the other racers before the rail is called,
        # or they would block for the whole duration of the HTTP request.
        await session.commit()
        await session.refresh(authorization)

        # ── re-read and re-validate ─────────────────────────────────────
        deal = (
            await session.execute(
                select(Deal).where(Deal.id == authorization.deal_id).with_for_update()
            )
        ).scalar_one()
        milestone = await session.get(Milestone, authorization.milestone_id)
        attestation = await session.get(Attestation, authorization.attestation_id)
        if milestone is None or attestation is None:
            return ExecutionResult(None, False, failed=True, reason="STALE_AUTHORIZATION")

        amount = int(authorization.amount_paise)
        conserves = (
            release_would_conserve(
                int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise), amount
            )
            if authorization.direction == Direction.RELEASE
            else refund_would_conserve(
                int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise), amount
            )
        )
        if not conserves:
            log.warning(
                "settlement revalidation failed",
                extra={
                    "settlement_event_id": str(authorization.id),
                    "reason": "MONEY_INVARIANT",
                    "funded_paise": int(deal.funded_paise),
                    "released_paise": int(deal.released_paise),
                    "refunded_paise": int(deal.refunded_paise),
                    "amount_paise": amount,
                },
            )
            return ExecutionResult(None, False, failed=True, reason="MONEY_INVARIANT_VIOLATION")

        if authorization.direction == Direction.RELEASE and authorization.dispute_id is None:
            clauses = _clause_outcomes(attestation)
            engine_decision, rationale = decide(
                DecisionInput(confidence=float(attestation.confidence), clauses=clauses)
            )
            if engine_decision != "RELEASE" and not authorization.human_approved:
                log.warning(
                    "settlement revalidation failed",
                    extra={
                        "settlement_event_id": str(authorization.id),
                        "reason": "I3",
                        **rationale,
                    },
                )
                return ExecutionResult(None, False, failed=True, reason="I3_REVALIDATION_FAILED")

        if authorization.dispute_id is not None:
            dispute = await session.get(Dispute, authorization.dispute_id)
            if dispute is None or dispute.human_decided_by is None:
                return ExecutionResult(None, False, failed=True, reason="HUMAN_DECISION_REQUIRED")
        elif milestone.state == MilestoneState.DISPUTED:
            # A dispute raised after authorisation but before settlement voids that
            # authorisation.  Money must not move while a dispute is open, and the
            # resolution issues its own authorisations for both legs.  This is
            # re-read from the database, so a message already in flight cannot
            # slip past it.
            log.warning(
                "settlement refused: milestone is disputed",
                extra={
                    "settlement_event_id": str(authorization.id),
                    "milestone_id": str(authorization.milestone_id),
                },
            )
            authorization.consumed_at = dt.datetime.now(dt.UTC)
            await append_ledger(
                session,
                deal_id=deal.id,
                org_id=deal.org_id_buyer,
                event_type=LedgerEventType.SETTLEMENT_AUTHORIZED,
                actor="SETTLEMENT_WORKER",
                reason="VOIDED_BY_DISPUTE",
                payload={
                    "authorization_id": str(authorization.id),
                    "milestone_id": str(authorization.milestone_id),
                    "direction": str(authorization.direction),
                    "amount_paise": amount,
                    "voided": True,
                },
            )
            return ExecutionResult(None, False, failed=True, reason="MILESTONE_DISPUTED")

        # ── rail call ───────────────────────────────────────────────────
        rail = get_rail()
        try:
            if authorization.direction == Direction.RELEASE:
                ref = rail.release_to_seller(
                    str(authorization.milestone_id), amount, authorization.idempotency_key
                )
            else:
                ref = rail.refund_to_buyer(
                    str(authorization.milestone_id), amount, authorization.idempotency_key
                )
        except RailFailure as exc:
            # Release the claim: the money did not move, so a retry must be able
            # to try again rather than finding the authorization locked forever.
            authorization.claimed_at = None
            payout = Payout(
                milestone_id=authorization.milestone_id,
                deal_id=authorization.deal_id,
                authorization_id=authorization.id,
                direction=authorization.direction,
                amount_paise=amount,
                rail=str(rail.mode),
                idempotency_key=authorization.idempotency_key,
                status=PayoutStatus.FAILED,
                failure_reason=exc.message[:2000],
            )
            session.add(payout)
            await append_ledger(
                session,
                deal_id=deal.id,
                org_id=deal.org_id_buyer,
                event_type=LedgerEventType.PAYOUT_FAILED,
                actor="SETTLEMENT_WORKER",
                reason=exc.code,
                payload={
                    "authorization_id": str(authorization.id),
                    "direction": str(authorization.direction),
                    "amount_paise": amount,
                    "failure": exc.code,
                },
            )
            await enqueue(
                session,
                topic=Topic.SETTLEMENT,
                event_type=EventType.SETTLEMENT_FAILED,
                aggregate_type="SettlementAuthorization",
                aggregate_id=str(authorization.id),
                payload={
                    "deal_id": str(deal.id),
                    "milestone_id": str(authorization.milestone_id),
                    "reason": exc.code,
                },
                event_id=deterministic_event_id(EventType.SETTLEMENT_FAILED, str(authorization.id)),
            )
            log.warning(
                "payout failed",
                extra={
                    "settlement_event_id": str(authorization.id),
                    "payout_id": str(payout.id),
                    "reason": exc.code,
                },
            )
            return ExecutionResult(payout, False, failed=True, reason=exc.code)

        # ── persist Payout + balances + LedgerEvent (one transaction) ────
        payout = Payout(
            milestone_id=authorization.milestone_id,
            deal_id=authorization.deal_id,
            authorization_id=authorization.id,
            direction=authorization.direction,
            amount_paise=amount,
            rail=str(rail.mode),
            rail_ref=ref.ref,
            idempotency_key=authorization.idempotency_key,
            status=PayoutStatus.SUCCEEDED,
        )
        session.add(payout)

        if authorization.direction == Direction.RELEASE:
            deal.released_paise = int(deal.released_paise) + amount
        else:
            deal.refunded_paise = int(deal.refunded_paise) + amount

        authorization.consumed_at = dt.datetime.now(dt.UTC)
        if (
            milestone.state == MilestoneState.RELEASE_APPROVED
            and authorization.direction == Direction.RELEASE
        ):
            await transition_milestone(
                session,
                deal,
                milestone,
                MilestoneEvent.SETTLE,
                actor="SETTLEMENT_WORKER",
                reason="rail settled",
                payload={"payout_id": str(payout.id), "rail_ref": ref.ref},
            )
            milestone.released_at = dt.datetime.now(dt.UTC)

        await append_ledger(
            session,
            deal_id=deal.id,
            org_id=deal.org_id_buyer,
            event_type=LedgerEventType.PAYOUT_RECORDED,
            actor="SETTLEMENT_WORKER",
            reason="rail settled",
            payload={
                "payout_id": str(payout.id),
                "authorization_id": str(authorization.id),
                "milestone_id": str(authorization.milestone_id),
                "direction": str(authorization.direction),
                "amount_paise": amount,
                "rail": str(rail.mode),
                "rail_ref": ref.ref,
                "released_paise": int(deal.released_paise),
                "refunded_paise": int(deal.refunded_paise),
                "funded_paise": int(deal.funded_paise),
            },
        )

        await enqueue(
            session,
            topic=Topic.SETTLEMENT
            if authorization.direction == Direction.RELEASE
            else Topic.REFUNDS,
            event_type=(
                EventType.SETTLEMENT_COMPLETED
                if authorization.direction == Direction.RELEASE
                else EventType.REFUND_COMPLETED
            ),
            aggregate_type="Payout",
            aggregate_id=str(payout.id),
            payload={
                "deal_id": str(deal.id),
                "milestone_id": str(authorization.milestone_id),
                "payout_id": str(payout.id),
                "direction": str(authorization.direction),
                "amount_paise": amount,
                "rail_ref": ref.ref,
                "human_approved": authorization.human_approved,
            },
            event_id=deterministic_event_id(EventType.SETTLEMENT_COMPLETED, str(payout.id)),
        )

        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            log.warning(
                "payout uniqueness collision -- exactly-once held",
                extra={"settlement_event_id": str(authorization_id), "error": type(exc).__name__},
            )
            row = (
                await session.execute(
                    select(Payout).where(Payout.idempotency_key == authorization.idempotency_key)
                )
            ).scalar_one_or_none()
            return ExecutionResult(row, already_done=True)

        log.info(
            "payout recorded",
            extra={
                "deal_id": str(deal.id),
                "milestone_id": str(authorization.milestone_id),
                "settlement_event_id": str(authorization.id),
                "payout_id": str(payout.id),
                "rail_ref": ref.ref,
                "amount_paise": amount,
            },
        )
        return ExecutionResult(payout, already_done=False)


async def maybe_complete_deal(session: AsyncSession, deal: Deal) -> bool:
    """A deal completes when every milestone has settled.  Table-driven, as always."""
    from app.deals.states import DealEvent, deal_can
    from app.ledger.service import transition_deal

    milestones = list(
        (await session.execute(select(Milestone).where(Milestone.deal_id == deal.id))).scalars()
    )
    if not milestones or any(m.state != MilestoneState.SETTLED for m in milestones):
        return False
    if not deal_can(deal.state, DealEvent.ALL_MILESTONES_SETTLED):
        return False
    await transition_deal(
        session,
        deal,
        DealEvent.ALL_MILESTONES_SETTLED,
        actor="SETTLEMENT_WORKER",
        reason="every milestone settled",
    )
    return True


async def raise_if_unbalanced(deal: Deal) -> None:
    from app.settlement.guards import money_conserved

    if not money_conserved(
        int(deal.funded_paise), int(deal.released_paise), int(deal.refunded_paise)
    ):
        raise Conflict(
            code="MONEY_INVARIANT_VIOLATION",
            message="held + released + refunded != funded",
            details={
                "funded_paise": int(deal.funded_paise),
                "released_paise": int(deal.released_paise),
                "refunded_paise": int(deal.refunded_paise),
            },
        )
