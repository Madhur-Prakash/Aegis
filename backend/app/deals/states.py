"""Explicit state machines as transition tables (I10).

There is no state-mutating ``if`` anywhere else in the codebase.  An unknown
``(state, event)`` pair raises :class:`IllegalTransition`; every applied transition
writes exactly one hash-chained ledger event (I5), which the decorator in
``app/ledger/service.py`` guarantees.
"""

from __future__ import annotations

from enum import StrEnum

from app.common.errors import IllegalTransition
from app.models.enums import DealState, MilestoneState


class DealEvent(StrEnum):
    SIGN_TERMS = "sign_terms"
    FUND = "fund"
    FIRST_EVIDENCE = "first_evidence"
    ALL_MILESTONES_SETTLED = "all_milestones_settled"
    RAISE_DISPUTE = "raise_dispute"
    RESOLVE = "resolve"
    CANCEL = "cancel"
    FULL_REFUND = "full_refund"
    FUNDING_WINDOW_ELAPSED = "funding_window_elapsed"


class MilestoneEvent(StrEnum):
    SUBMIT_EVIDENCE = "submit_evidence"
    START_VERIFY = "start_verify"
    ATTEST_RELEASE = "attest_release"
    ATTEST_REJECT = "attest_reject"
    ATTEST_ESCALATE = "attest_escalate"
    HUMAN_APPROVE = "human_approve"
    HUMAN_REJECT = "human_reject"
    SETTLE = "settle"
    RESUBMIT = "resubmit"
    RAISE_DISPUTE = "raise_dispute"
    RESOLVE = "resolve"


# ─────────────────────────────────────────────────────────────────────────────
# Deal.  ``resolve`` is the one event with two legal destinations; the caller
# supplies the target and the table validates it, so the branch is still in the
# table rather than in an ``if``.
# ─────────────────────────────────────────────────────────────────────────────
DEAL_TRANSITIONS: dict[tuple[DealState, DealEvent], tuple[DealState, ...]] = {
    (DealState.DRAFT, DealEvent.SIGN_TERMS): (DealState.TERMS_SIGNED,),
    (DealState.DRAFT, DealEvent.CANCEL): (DealState.CANCELLED,),
    (DealState.TERMS_SIGNED, DealEvent.FUND): (DealState.FUNDED,),
    (DealState.TERMS_SIGNED, DealEvent.CANCEL): (DealState.CANCELLED,),
    (DealState.TERMS_SIGNED, DealEvent.FUNDING_WINDOW_ELAPSED): (DealState.EXPIRED,),
    (DealState.FUNDED, DealEvent.FIRST_EVIDENCE): (DealState.IN_PROGRESS,),
    (DealState.FUNDED, DealEvent.FULL_REFUND): (DealState.REFUNDED,),
    (DealState.IN_PROGRESS, DealEvent.ALL_MILESTONES_SETTLED): (DealState.COMPLETED,),
    (DealState.IN_PROGRESS, DealEvent.RAISE_DISPUTE): (DealState.DISPUTED,),
    (DealState.IN_PROGRESS, DealEvent.FULL_REFUND): (DealState.REFUNDED,),
    (DealState.DISPUTED, DealEvent.RESOLVE): (DealState.IN_PROGRESS, DealState.COMPLETED),
}

# ─────────────────────────────────────────────────────────────────────────────
# Milestone
# ─────────────────────────────────────────────────────────────────────────────
MILESTONE_TRANSITIONS: dict[tuple[MilestoneState, MilestoneEvent], tuple[MilestoneState, ...]] = {
    (MilestoneState.PENDING, MilestoneEvent.SUBMIT_EVIDENCE): (MilestoneState.EVIDENCE_SUBMITTED,),
    (MilestoneState.EVIDENCE_SUBMITTED, MilestoneEvent.START_VERIFY): (MilestoneState.VERIFYING,),
    (MilestoneState.VERIFYING, MilestoneEvent.ATTEST_RELEASE): (MilestoneState.RELEASE_APPROVED,),
    (MilestoneState.VERIFYING, MilestoneEvent.ATTEST_REJECT): (MilestoneState.REJECTED,),
    (MilestoneState.VERIFYING, MilestoneEvent.ATTEST_ESCALATE): (
        MilestoneState.UNDER_HUMAN_REVIEW,
    ),
    (MilestoneState.UNDER_HUMAN_REVIEW, MilestoneEvent.HUMAN_APPROVE): (
        MilestoneState.RELEASE_APPROVED,
    ),
    (MilestoneState.UNDER_HUMAN_REVIEW, MilestoneEvent.HUMAN_REJECT): (MilestoneState.REJECTED,),
    (MilestoneState.RELEASE_APPROVED, MilestoneEvent.SETTLE): (MilestoneState.SETTLED,),
    (MilestoneState.REJECTED, MilestoneEvent.RESUBMIT): (MilestoneState.EVIDENCE_SUBMITTED,),
    (MilestoneState.RELEASE_APPROVED, MilestoneEvent.RAISE_DISPUTE): (MilestoneState.DISPUTED,),
    (MilestoneState.REJECTED, MilestoneEvent.RAISE_DISPUTE): (MilestoneState.DISPUTED,),
    (MilestoneState.SETTLED, MilestoneEvent.RAISE_DISPUTE): (MilestoneState.DISPUTED,),
    (MilestoneState.DISPUTED, MilestoneEvent.RESOLVE): (MilestoneState.SETTLED,),
}

# States from which a milestone may still be disputed only inside the window.
DISPUTE_WINDOW_STATES = frozenset({MilestoneState.SETTLED})

TERMINAL_DEAL_STATES = frozenset(
    {DealState.COMPLETED, DealState.CANCELLED, DealState.REFUNDED, DealState.EXPIRED}
)
TERMINAL_MILESTONE_STATES = frozenset({MilestoneState.SETTLED})


def next_deal_state(
    current: DealState, event: DealEvent, target: DealState | None = None
) -> DealState:
    allowed = DEAL_TRANSITIONS.get((DealState(current), DealEvent(event)))
    if not allowed:
        raise IllegalTransition(
            message=f"Deal cannot {event} from {current}.",
            details={"from": str(current), "event": str(event)},
        )
    if len(allowed) == 1:
        if target is not None and DealState(target) != allowed[0]:
            raise IllegalTransition(
                message=f"Deal {event} from {current} must land in {allowed[0]}.",
                details={"from": str(current), "event": str(event), "target": str(target)},
            )
        return allowed[0]
    if target is None:
        raise IllegalTransition(
            message=f"Deal {event} from {current} requires an explicit target state.",
            details={
                "from": str(current),
                "event": str(event),
                "allowed": [str(a) for a in allowed],
            },
        )
    if DealState(target) not in allowed:
        raise IllegalTransition(
            message=f"Deal cannot {event} from {current} to {target}.",
            details={"from": str(current), "event": str(event), "target": str(target)},
        )
    return DealState(target)


def next_milestone_state(current: MilestoneState, event: MilestoneEvent) -> MilestoneState:
    allowed = MILESTONE_TRANSITIONS.get((MilestoneState(current), MilestoneEvent(event)))
    if not allowed:
        raise IllegalTransition(
            message=f"Milestone cannot {event} from {current}.",
            details={"from": str(current), "event": str(event)},
        )
    return allowed[0]


def deal_can(current: DealState, event: DealEvent) -> bool:
    return (DealState(current), DealEvent(event)) in DEAL_TRANSITIONS


def milestone_can(current: MilestoneState, event: MilestoneEvent) -> bool:
    return (MilestoneState(current), MilestoneEvent(event)) in MILESTONE_TRANSITIONS
