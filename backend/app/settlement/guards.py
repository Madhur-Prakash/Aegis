"""Pure-Python invariant guards.  No I/O, no ORM, no LLM anywhere near them.

This module is the mechanical statement of I3 and I4.  It is imported by the
settlement engine and by Suite A, and it is deliberately trivial to read: the
whole safety argument of the product is these forty lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.settings import REJECT_THRESHOLD, RELEASE_THRESHOLD


@dataclass(frozen=True, slots=True)
class ClauseOutcome:
    clause_id: str
    verdict: str  # PASS | FAIL | UNVERIFIABLE
    required: bool


@dataclass(frozen=True, slots=True)
class DecisionInput:
    confidence: float
    clauses: tuple[ClauseOutcome, ...]


def required_unverifiable(clauses: tuple[ClauseOutcome, ...]) -> list[str]:
    return [c.clause_id for c in clauses if c.required and c.verdict == "UNVERIFIABLE"]


def required_failed(clauses: tuple[ClauseOutcome, ...]) -> list[str]:
    return [c.clause_id for c in clauses if c.required and c.verdict == "FAIL"]


def decide(inp: DecisionInput) -> tuple[str, dict[str, Any]]:
    """I3, in one function, with no bypass and no admin override.

    * any required clause FAIL          -> REJECT   (the evidence contradicts the clause)
    * any required clause UNVERIFIABLE  -> ESCALATE (never RELEASE, and never REJECT
                                           either: refusing a seller because the
                                           machine could not check something is
                                           blocking, and blocking is the other half
                                           of the failure this design exists to
                                           avoid. A human decides. See
                                           docs/DECISIONS.md ADR-004.)
    * conf >= 0.85 and all required satisfied -> RELEASE
    * 0.35 < conf < 0.85                -> ESCALATE
    * conf <= 0.35                      -> REJECT
    """
    failed = required_failed(inp.clauses)
    unverifiable = required_unverifiable(inp.clauses)
    reasons: dict[str, Any] = {
        "confidence": inp.confidence,
        "release_threshold": RELEASE_THRESHOLD,
        "reject_threshold": REJECT_THRESHOLD,
        "failed_required_clauses": failed,
        "unverifiable_required_clauses": unverifiable,
    }

    if failed:
        return "REJECT", {**reasons, "rule": "REQUIRED_CLAUSE_FAILED"}

    if unverifiable:
        # RELEASE is impossible, ever.  REJECT is also wrong here: nothing
        # contradicts the clause, so rejecting would punish the seller for the
        # machine's blindness.  It did not guess and it did not block.
        return "ESCALATE", {**reasons, "rule": "REQUIRED_CLAUSE_UNVERIFIABLE"}

    if inp.confidence >= RELEASE_THRESHOLD:
        return "RELEASE", {**reasons, "rule": "AT_OR_ABOVE_RELEASE_THRESHOLD"}
    if inp.confidence <= REJECT_THRESHOLD:
        return "REJECT", {**reasons, "rule": "AT_OR_BELOW_REJECT_THRESHOLD"}
    return "ESCALATE", {**reasons, "rule": "BETWEEN_THRESHOLDS"}


def may_auto_release(inp: DecisionInput) -> bool:
    decision, _ = decide(inp)
    return decision == "RELEASE"


def money_conserved(funded: int, released: int, refunded: int) -> bool:
    """I4.  Integer paise only -- a float here would be a bug, not a rounding issue."""
    for value in (funded, released, refunded):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("money must be integer paise")
    held = funded - released - refunded
    return held >= 0 and released >= 0 and refunded >= 0 and held + released + refunded == funded


def release_would_conserve(funded: int, released: int, refunded: int, amount: int) -> bool:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return False
    return money_conserved(funded, released + amount, refunded)


def refund_would_conserve(funded: int, released: int, refunded: int, amount: int) -> bool:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return False
    return money_conserved(funded, released, refunded + amount)


def split_balances(milestone_amount: int, release_paise: int, refund_paise: int) -> bool:
    """A dispute split must balance exactly (spec 19).  Never silently 'fixed up'."""
    return (
        isinstance(release_paise, int)
        and isinstance(refund_paise, int)
        and release_paise >= 0
        and refund_paise >= 0
        and release_paise + refund_paise == milestone_amount
    )
