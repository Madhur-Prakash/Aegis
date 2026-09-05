"""I2/I3 -- the model's numbers may not walk past the release threshold.

The import boundary stops the agents *calling* the settlement engine.  It does
not stop them influencing what the engine reads, and the honest reading of I2 is
that the worst a successful prompt injection achieves is a wrong clause verdict,
"which then flows through the guard and the thresholds like any other verdict".

That claim only holds while the numbers the model supplies stay inside the range
the thresholds were calibrated against.  ``clause_confidence`` is a bare ``float``
in the structured-output schema and it feeds ``llm_component`` directly, so an
injected model could answer ``1e9``.  ``calibrate`` clips its input, but it clips
*after* the unverifiable penalty is subtracted -- so one absurd clause washed the
penalty out entirely, pinned the calibrated confidence at 1.0, and turned a
milestone that was heading for human review into an automatic release.

These tests pin the clamp, not the calibration curve: they assert the model
cannot buy a RELEASE with a number, whatever the fitted map happens to say.
"""

from __future__ import annotations

import pytest

from app.agents.verifier.confidence import compute_confidence
from app.config.settings import RELEASE_THRESHOLD
from app.settlement.guards import ClauseOutcome, DecisionInput, decide


def _decide(verdicts: list[dict], qualities: list[float]) -> tuple[str, float]:
    breakdown = compute_confidence(
        clause_verdicts=verdicts,
        deterministic_clause_results={},
        extraction_qualities=qualities,
    )
    decision, _ = decide(
        DecisionInput(
            confidence=breakdown.calibrated,
            clauses=tuple(
                ClauseOutcome(str(v["clause_id"]), str(v["verdict"]), bool(v["required"]))
                for v in verdicts
            ),
        )
    )
    return decision, breakdown.calibrated


@pytest.mark.parametrize("injected", [1e9, 1e300, 42.0, 1.0000001])
def test_an_out_of_range_clause_confidence_cannot_reach_the_release_threshold(injected):
    """No LLM-only clause set may auto-release on the strength of its own score.

    ``verifiable_fraction`` is 0 here -- nothing was machine-checkable -- so the
    honest ceiling is 0.45*0 + 0.45*1 + 0.10*1 = 0.55, comfortably under 0.85.
    Anything above that came from the model inflating its own number.
    """
    verdicts = [
        {"clause_id": "c1", "verdict": "PASS", "required": True, "clause_confidence": injected}
    ]
    decision, confidence = _decide(verdicts, [1.0])
    assert confidence <= 0.55 + 1e-9, confidence
    assert confidence < RELEASE_THRESHOLD
    assert decision != "RELEASE"


def test_the_unverifiable_penalty_cannot_be_washed_out_by_an_inflated_score():
    """A required UNVERIFIABLE clause must keep costing what it costs."""
    honest = [
        {"clause_id": "c1", "verdict": "PASS", "required": True, "clause_confidence": 1.0},
        {"clause_id": "c2", "verdict": "UNVERIFIABLE", "required": True, "clause_confidence": 0.0},
    ]
    injected = [
        {"clause_id": "c1", "verdict": "PASS", "required": True, "clause_confidence": 1e9},
        {"clause_id": "c2", "verdict": "UNVERIFIABLE", "required": True, "clause_confidence": 0.0},
    ]
    honest_breakdown = compute_confidence(
        clause_verdicts=honest, deterministic_clause_results={}, extraction_qualities=[0.9]
    )
    injected_breakdown = compute_confidence(
        clause_verdicts=injected, deterministic_clause_results={}, extraction_qualities=[0.9]
    )
    assert injected_breakdown.calibrated == honest_breakdown.calibrated
    assert injected_breakdown.unverifiable_penalty == pytest.approx(0.25)
    # And I3 holds regardless: a required UNVERIFIABLE clause never auto-releases.
    assert _decide(injected, [0.9])[0] == "ESCALATE"


@pytest.mark.parametrize("hostile", [float("nan"), float("inf"), float("-inf"), -5.0, None, "0.99"])
def test_a_hostile_clause_confidence_never_raises_and_never_helps(hostile):
    """NaN is the nastiest of these: every comparison against it is False, so an
    unclamped NaN would slip through `decide`'s ordering tests unnoticed."""
    verdicts = [
        {"clause_id": "c1", "verdict": "PASS", "required": True, "clause_confidence": hostile}
    ]
    breakdown = compute_confidence(
        clause_verdicts=verdicts, deterministic_clause_results={}, extraction_qualities=[1.0]
    )
    assert 0.0 <= breakdown.llm_component <= 1.0
    assert breakdown.calibrated == breakdown.calibrated  # not NaN
    assert 0.0 <= breakdown.calibrated <= 1.0


def test_an_honest_high_confidence_run_is_unaffected():
    """The clamp must not cost a legitimate release."""
    verdicts = [{"clause_id": "c1", "verdict": "PASS", "required": True, "clause_confidence": 0.97}]
    deterministic = {"c1": {"clause_id": "c1", "verdict": "PASS", "required": True}}
    breakdown = compute_confidence(
        clause_verdicts=verdicts,
        deterministic_clause_results=deterministic,
        extraction_qualities=[0.95],
    )
    assert breakdown.llm_component == pytest.approx(0.97)
    assert breakdown.verifiable_fraction == 1.0
