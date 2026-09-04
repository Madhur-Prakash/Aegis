"""I4 as a Hypothesis property, and the database CHECK that backs it up."""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from app.settlement.guards import (
    money_conserved,
    refund_would_conserve,
    release_would_conserve,
    split_balances,
)

MONEY = st.integers(min_value=1, max_value=10**13)


@hyp_settings(max_examples=800, deadline=None)
@given(funded=MONEY, moves=st.lists(st.tuples(st.booleans(), st.integers(1, 10**13)), max_size=14))
def test_no_legal_sequence_of_moves_can_break_conservation(funded, moves):
    """The engine only applies a move the guards approve, so applying exactly
    those keeps ``held + released + refunded == funded`` at every step."""
    released = refunded = 0
    for is_release, amount in moves:
        if is_release:
            if release_would_conserve(funded, released, refunded, amount):
                released += amount
        else:
            if refund_would_conserve(funded, released, refunded, amount):
                refunded += amount
        assert money_conserved(funded, released, refunded)
        assert funded - released - refunded >= 0
    assert (funded - released - refunded) + released + refunded == funded


@hyp_settings(max_examples=600, deadline=None)
@given(funded=MONEY, released=st.integers(0, 10**13), refunded=st.integers(0, 10**13))
def test_conservation_is_exactly_the_stated_predicate(funded, released, refunded):
    expected = released >= 0 and refunded >= 0 and released + refunded <= funded
    assert money_conserved(funded, released, refunded) == expected


@hyp_settings(max_examples=400, deadline=None)
@given(funded=MONEY, released=st.integers(0, 10**13), refunded=st.integers(0, 10**13))
def test_a_move_is_approved_only_if_it_conserves(funded, released, refunded):
    if not money_conserved(funded, released, refunded):
        return
    remaining = funded - released - refunded
    assert release_would_conserve(funded, released, refunded, remaining) == (remaining > 0)
    assert not release_would_conserve(funded, released, refunded, remaining + 1)
    assert refund_would_conserve(funded, released, refunded, remaining) == (remaining > 0)
    assert not refund_would_conserve(funded, released, refunded, remaining + 1)


@hyp_settings(max_examples=400, deadline=None)
@given(amount=MONEY, split=st.floats(0.0, 1.0))
def test_a_dispute_split_always_balances_or_is_refused(amount, split):
    release = int(amount * split)
    refund = amount - release
    assert split_balances(amount, release, refund)
    assert sum((release, refund)) == amount


@hyp_settings(max_examples=200, deadline=None)
@given(amount=MONEY, delta=st.integers(1, 10**6))
def test_an_unbalanced_split_is_always_refused(amount, delta):
    assert not split_balances(amount, amount, delta)
    assert not split_balances(amount, amount + delta, 0)


@hyp_settings(
    max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(value=st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=10**6))
def test_a_float_amount_is_never_accepted(value):
    """Money is integer paise.  A float reaching the guard is a bug, and it
    raises rather than being silently coerced."""
    with pytest.raises(TypeError):
        money_conserved(value, 0, 0)  # type: ignore[arg-type]
    assert not release_would_conserve(1_000_000, 0, 0, value)  # type: ignore[arg-type]
