"""I3, I4, the state machines, and the pricing tiers.

These are the load-bearing pure functions: if any test in this file fails, money
can move when it should not.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from app.common.errors import IllegalTransition
from app.config.settings import REJECT_THRESHOLD, RELEASE_THRESHOLD
from app.deals.states import (
    DEAL_TRANSITIONS,
    MILESTONE_TRANSITIONS,
    DealEvent,
    MilestoneEvent,
    deal_can,
    milestone_can,
    next_deal_state,
    next_milestone_state,
)
from app.models.enums import DealState, MilestoneState
from app.risk.features import band, price
from app.settlement.guards import (
    ClauseOutcome,
    DecisionInput,
    decide,
    may_auto_release,
    money_conserved,
    refund_would_conserve,
    release_would_conserve,
    required_failed,
    required_unverifiable,
    split_balances,
)


def clauses(*specs: tuple[str, str, bool]) -> tuple[ClauseOutcome, ...]:
    return tuple(ClauseOutcome(cid, verdict, required) for cid, verdict, required in specs)


ALL_PASS = clauses(("c1", "PASS", True), ("c2", "PASS", True))


# ── I3 ──────────────────────────────────────────────────────────────────────
def test_thresholds_are_the_specified_values():
    assert RELEASE_THRESHOLD == 0.85
    assert REJECT_THRESHOLD == 0.35


@pytest.mark.parametrize("confidence", [0.85, 0.9, 0.94, 0.999, 1.0])
def test_at_or_above_release_threshold_releases(confidence):
    decision, _ = decide(DecisionInput(confidence, ALL_PASS))
    assert decision == "RELEASE"


@pytest.mark.parametrize("confidence", [0.8499, 0.7, 0.51, 0.3501])
def test_between_thresholds_escalates(confidence):
    decision, rationale = decide(DecisionInput(confidence, ALL_PASS))
    assert decision == "ESCALATE"
    assert rationale["rule"] == "BETWEEN_THRESHOLDS"


@pytest.mark.parametrize("confidence", [0.35, 0.2, 0.0])
def test_at_or_below_reject_threshold_rejects(confidence):
    decision, _ = decide(DecisionInput(confidence, ALL_PASS))
    assert decision == "REJECT"


def test_a_required_failed_clause_rejects_regardless_of_confidence():
    for confidence in (0.0, 0.5, 0.94, 1.0):
        decision, rationale = decide(
            DecisionInput(confidence, clauses(("c1", "PASS", True), ("c2", "FAIL", True)))
        )
        assert decision == "REJECT"
        assert rationale["rule"] == "REQUIRED_CLAUSE_FAILED"
        assert rationale["failed_required_clauses"] == ["c2"]


def test_a_required_unverifiable_clause_can_never_auto_release():
    """The single most important assertion in the codebase."""
    for confidence in [i / 100 for i in range(0, 101)]:
        outcome = DecisionInput(
            confidence, clauses(("c1", "PASS", True), ("c2", "UNVERIFIABLE", True))
        )
        decision, rationale = decide(outcome)
        assert decision != "RELEASE", f"released at confidence {confidence}"
        assert not may_auto_release(outcome)
        assert rationale["unverifiable_required_clauses"] == ["c2"]


def test_a_required_unverifiable_clause_escalates_and_does_not_reject():
    """It did not guess and it did not block.  Rejecting a seller because the
    machine could not check something is blocking (ADR-004)."""
    for confidence in (0.0, 0.1, 0.35, 0.5, 0.94, 1.0):
        decision, rationale = decide(
            DecisionInput(confidence, clauses(("c1", "PASS", True), ("c2", "UNVERIFIABLE", True)))
        )
        assert decision == "ESCALATE"
        assert rationale["rule"] == "REQUIRED_CLAUSE_UNVERIFIABLE"


def test_an_optional_unverifiable_clause_does_not_block_release():
    decision, _ = decide(
        DecisionInput(0.94, clauses(("c1", "PASS", True), ("c2", "UNVERIFIABLE", False)))
    )
    assert decision == "RELEASE"


def test_failed_clause_beats_unverifiable_clause():
    decision, _ = decide(
        DecisionInput(0.94, clauses(("c1", "FAIL", True), ("c2", "UNVERIFIABLE", True)))
    )
    assert decision == "REJECT"


def test_required_helpers():
    outcome = clauses(
        ("c1", "FAIL", True), ("c2", "UNVERIFIABLE", True), ("c3", "UNVERIFIABLE", False)
    )
    assert required_failed(outcome) == ["c1"]
    assert required_unverifiable(outcome) == ["c2"]


def test_no_urgency_bypass_exists_in_the_decision_code():
    """There is no code path that takes an override, a priority or a flag.

    The docstring and comments are stripped before scanning: the prose is allowed
    to *say* "no admin override", but the executable statements must not contain
    such a branch.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(decide).lstrip())
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    body = function.body[1:] if isinstance(function.body[0], ast.Expr) else function.body
    code = "\n".join(ast.unparse(node) for node in body).lower()
    for smell in ("urgent", "override", "bypass", "force", "admin", "skip", "exempt"):
        assert smell not in code, f"decide() has a {smell!r} branch"
    # And there is exactly one parameter: no flags can be passed in at all.
    assert [a.arg for a in function.args.args] == ["inp"]
    assert not function.args.kwonlyargs and not function.args.defaults


# ── I4 ──────────────────────────────────────────────────────────────────────
def test_money_conserved_basic():
    assert money_conserved(1000, 400, 600)
    assert money_conserved(1000, 0, 0)
    assert not money_conserved(1000, 700, 400)


def test_money_must_be_integer_paise():
    with pytest.raises(TypeError):
        money_conserved(1000.0, 0, 0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        money_conserved(1000, True, 0)  # type: ignore[arg-type]


def test_release_and_refund_bounds():
    assert release_would_conserve(1000, 0, 0, 1000)
    assert not release_would_conserve(1000, 0, 0, 1001)
    assert not release_would_conserve(1000, 0, 0, 0)
    assert not release_would_conserve(1000, 0, 0, -1)
    assert refund_would_conserve(1000, 400, 0, 600)
    assert not refund_would_conserve(1000, 400, 0, 601)


@hyp_settings(max_examples=500, deadline=None)
@given(
    funded=st.integers(min_value=1, max_value=10**12),
    fractions=st.lists(st.floats(0.0, 1.0), min_size=0, max_size=10),
)
def test_i4_survives_any_legal_sequence(funded: int, fractions: list[float]):
    released = refunded = 0
    for fraction in fractions:
        remaining = funded - released - refunded
        if remaining <= 0:
            break
        amount = max(1, int(remaining * fraction))
        if amount > remaining:
            continue
        if release_would_conserve(funded, released, refunded, amount):
            released += amount
        elif refund_would_conserve(funded, released, refunded, amount):
            refunded += amount
        assert money_conserved(funded, released, refunded)
    held = funded - released - refunded
    assert held >= 0
    assert held + released + refunded == funded


@hyp_settings(max_examples=300, deadline=None)
@given(
    amount=st.integers(min_value=1, max_value=10**9),
    release=st.integers(min_value=0, max_value=10**9),
)
def test_split_must_balance_exactly(amount: int, release: int):
    refund = amount - release
    if 0 <= refund <= amount:
        assert split_balances(amount, release, refund)
    assert not split_balances(amount, release, refund + 1)
    assert not split_balances(amount, release, refund - 1)


def test_split_rejects_negatives():
    assert not split_balances(1000, -1, 1001)


# ── State machines (I10) ────────────────────────────────────────────────────
def test_every_deal_pair_is_in_the_table_or_raises():
    for state in DealState:
        for event in DealEvent:
            legal = (state, event) in DEAL_TRANSITIONS
            assert deal_can(state, event) is legal
            targets = DEAL_TRANSITIONS.get((state, event))
            if legal:
                target = targets[0] if targets and len(targets) > 1 else None
                assert next_deal_state(state, event, target) in targets
            else:
                with pytest.raises(IllegalTransition):
                    next_deal_state(state, event)


def test_every_milestone_pair_is_in_the_table_or_raises():
    for state in MilestoneState:
        for event in MilestoneEvent:
            legal = (state, event) in MILESTONE_TRANSITIONS
            assert milestone_can(state, event) is legal
            if legal:
                assert (
                    next_milestone_state(state, event) == MILESTONE_TRANSITIONS[(state, event)][0]
                )
            else:
                with pytest.raises(IllegalTransition):
                    next_milestone_state(state, event)


def test_multi_target_transition_requires_an_explicit_target():
    with pytest.raises(IllegalTransition):
        next_deal_state(DealState.DISPUTED, DealEvent.RESOLVE)
    assert (
        next_deal_state(DealState.DISPUTED, DealEvent.RESOLVE, DealState.IN_PROGRESS)
        == DealState.IN_PROGRESS
    )
    assert (
        next_deal_state(DealState.DISPUTED, DealEvent.RESOLVE, DealState.COMPLETED)
        == DealState.COMPLETED
    )
    with pytest.raises(IllegalTransition):
        next_deal_state(DealState.DISPUTED, DealEvent.RESOLVE, DealState.REFUNDED)


def test_single_target_transition_rejects_a_wrong_target():
    with pytest.raises(IllegalTransition):
        next_deal_state(DealState.DRAFT, DealEvent.SIGN_TERMS, DealState.FUNDED)


def test_illegal_transition_carries_a_typed_code():
    with pytest.raises(IllegalTransition) as exc:
        next_milestone_state(MilestoneState.PENDING, MilestoneEvent.SETTLE)
    assert exc.value.code == "ILLEGAL_TRANSITION"
    assert exc.value.http_status == 409
    assert exc.value.details["from"] == "PENDING"


def test_settled_is_reachable_only_through_release_approved_or_dispute():
    sources = [
        state
        for (state, event), targets in MILESTONE_TRANSITIONS.items()
        if MilestoneState.SETTLED in targets
    ]
    assert set(sources) == {MilestoneState.RELEASE_APPROVED, MilestoneState.DISPUTED}


# ── Pricing (spec 22) ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "score,tier,fee",
    [
        (0.0, "TIER_1", 0.8),
        (0.099, "TIER_1", 0.8),
        (0.10, "TIER_2", 1.5),
        (0.249, "TIER_2", 1.5),
        (0.25, "TIER_3", 2.5),
        (0.499, "TIER_3", 2.5),
        (0.50, "DECLINE", None),
        (0.99, "DECLINE", None),
    ],
)
def test_pricing_tiers(score, tier, fee):
    result = price(score)
    assert result["tier"] == tier
    assert result["escrow_fee_pct"] == fee
    assert result["accepted"] is (tier != "DECLINE")


def test_pricing_bands_are_labelled():
    assert band(0.05) == "low"
    assert band(0.2) == "moderate"
    assert band(0.4) == "elevated"
    assert band(0.8) == "high"
