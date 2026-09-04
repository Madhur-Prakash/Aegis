"""Confidence maths, the clause rubric, pre-checks, and the provider contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents._llm import (
    AnthropicProvider,
    FixtureProvider,
    Usage,
    compute_prompt_hash,
    cost_micro_usd,
)
from app.agents.prompts import (
    ARBITER_SYSTEM_PROMPT,
    CLAUSE_SYSTEM_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
)
from app.agents.verifier.clause_rules import DETERMINISTIC_KINDS, evaluate_clause
from app.agents.verifier.confidence import compute_confidence, reset_calibration_cache
from app.agents.verifier.prechecks import integrity_clause, run_prechecks
from app.agents.verifier.render import extract_case_json, render_clause_case
from app.evidence.analyse import analyse, extraction_quality


# ── confidence maths ────────────────────────────────────────────────────────
def verdicts(*specs):
    return [
        {"clause_id": cid, "verdict": v, "required": req, "clause_confidence": conf}
        for cid, v, req, conf in specs
    ]


def test_confidence_uses_the_specified_weights():
    breakdown = compute_confidence(
        clause_verdicts=verdicts(("c1", "PASS", True, 1.0), ("c2", "PASS", True, 1.0)),
        deterministic_clause_results={
            "c1": {"verdict": "PASS"},
            "c2": {"verdict": "PASS"},
        },
        extraction_qualities=[1.0],
    )
    assert breakdown.verifiable_fraction == 1.0
    assert breakdown.llm_component == 1.0
    assert breakdown.extraction_quality == 1.0
    assert breakdown.unverifiable_penalty == 0.0
    assert breakdown.raw == pytest.approx(0.45 + 0.45 + 0.10)
    assert breakdown.weights == {
        "verifiable_fraction": 0.45,
        "llm_component": 0.45,
        "extraction_quality": 0.10,
    }


def test_unverifiable_required_clause_costs_half_its_share():
    breakdown = compute_confidence(
        clause_verdicts=verdicts(("c1", "PASS", True, 1.0), ("c2", "UNVERIFIABLE", True, 0.0)),
        deterministic_clause_results={"c1": {"verdict": "PASS"}},
        extraction_qualities=[1.0],
    )
    assert breakdown.unverifiable_required == 1
    assert breakdown.total_required_clauses == 2
    assert breakdown.unverifiable_penalty == pytest.approx(0.25)


def test_unverifiable_clauses_are_excluded_from_the_llm_component():
    breakdown = compute_confidence(
        clause_verdicts=verdicts(("c1", "PASS", True, 0.9), ("c2", "UNVERIFIABLE", True, 0.99)),
        deterministic_clause_results={"c1": {"verdict": "PASS"}},
        extraction_qualities=[0.8],
    )
    # 0.99 would otherwise inflate confidence for a clause nobody could judge.
    assert breakdown.llm_component == pytest.approx(0.9)


def test_confidence_is_not_the_models_self_report():
    """A model claiming 1.0 on every clause still cannot reach the release
    threshold when nothing was deterministically checkable."""
    breakdown = compute_confidence(
        clause_verdicts=verdicts(("c1", "PASS", True, 1.0), ("c2", "PASS", True, 1.0)),
        deterministic_clause_results={},  # nothing machine-checkable
        extraction_qualities=[0.5],
    )
    assert breakdown.verifiable_fraction == 0.0
    assert breakdown.raw == pytest.approx(0.45 + 0.05)


def test_confidence_is_clamped_and_rounded():
    breakdown = compute_confidence(
        clause_verdicts=verdicts(("c1", "UNVERIFIABLE", True, 0.0)),
        deterministic_clause_results={},
        extraction_qualities=[0.0],
    )
    assert 0.0 <= breakdown.calibrated <= 1.0
    assert breakdown.as_json()["computed"] == breakdown.calibrated


def test_breakdown_json_shows_the_arithmetic():
    breakdown = compute_confidence(
        clause_verdicts=verdicts(("c1", "PASS", True, 0.9)),
        deterministic_clause_results={"c1": {"verdict": "PASS"}},
        extraction_qualities=[0.8],
    )
    payload = breakdown.as_json()
    for key in (
        "verifiable_fraction",
        "llm_component",
        "extraction_quality",
        "unverifiable_penalty",
        "raw",
        "computed",
        "formula",
        "calibration_version",
    ):
        assert key in payload
    assert payload["unverifiable_penalty"] <= 0  # displayed as a deduction


# ── clause rubric ───────────────────────────────────────────────────────────
def artifact(**kwargs):
    base = {
        "artifact_id": "a1",
        "artifact_type": "INVOICE",
        "parseable": True,
        "fields": {},
        "observation": {},
        "sha256": "ab" * 32,
        "size_bytes": 1024,
        "declared_mime": "application/pdf",
        "sniffed_mime": "application/pdf",
    }
    base.update(kwargs)
    return base


def test_artifact_present_pass_fail_unverifiable():
    clause = {
        "id": "c1",
        "kind": "ARTIFACT_PRESENT",
        "params": {"artifact_types": ["INVOICE"], "min_count": 1},
    }
    assert evaluate_clause(clause, [artifact()]).verdict == "PASS"
    assert evaluate_clause(clause, []).verdict == "FAIL"
    assert evaluate_clause(clause, [artifact(parseable=False)]).verdict == "UNVERIFIABLE"


def test_min_count_shortfall_fails():
    clause = {
        "id": "c1",
        "kind": "ARTIFACT_PRESENT",
        "params": {"artifact_types": ["PHOTO_SET"], "min_count": 4},
    }
    photos = [artifact(artifact_id=f"p{i}", artifact_type="PHOTO_SET") for i in range(2)]
    assert evaluate_clause(clause, photos).verdict == "FAIL"


def test_date_within_window():
    clause = {
        "id": "c5",
        "kind": "DATE_WITHIN",
        "params": {"field": "date", "from": "2026-08-15", "to": "2026-09-10"},
    }
    assert evaluate_clause(clause, [artifact(fields={"date": "2026-08-28"})]).verdict == "PASS"
    assert evaluate_clause(clause, [artifact(fields={"date": "2026-07-01"})]).verdict == "FAIL"
    assert evaluate_clause(clause, [artifact(fields={})]).verdict == "UNVERIFIABLE"


def test_date_formats_are_tolerated():
    clause = {
        "id": "c5",
        "kind": "DATE_WITHIN",
        "params": {"field": "date", "from": "2026-08-15", "to": "2026-09-10"},
    }
    for value in ("2026-08-28", "28-08-2026", "28/08/2026", "28 Aug 2026"):
        assert evaluate_clause(clause, [artifact(fields={"date": value})]).verdict == "PASS"


def test_quantity_floor():
    clause = {
        "id": "c4",
        "kind": "QUANTITY_AT_LEAST",
        "params": {"field": "quantity", "min": 520},
    }
    assert evaluate_clause(clause, [artifact(fields={"quantity": 540})]).verdict == "PASS"
    assert evaluate_clause(clause, [artifact(fields={"quantity": 519})]).verdict == "FAIL"


def test_photographs_cannot_establish_a_count():
    """The product's thesis, as an executable rule."""
    clause = {
        "id": "c2",
        "kind": "QUANTITY_AT_LEAST",
        "params": {"field": "unit_count", "min": 500, "artifact_types": ["PHOTO_SET"]},
    }
    photos = [
        artifact(
            artifact_id=f"p{i}",
            artifact_type="PHOTO_SET",
            fields={"visible_item_count_estimate": None, "count_establishable": False},
        )
        for i in range(4)
    ]
    result = evaluate_clause(clause, photos)
    assert result.verdict == "UNVERIFIABLE"
    assert "cannot establish" in result.note
    assert "500" in result.note


def test_field_equals_and_matches_spec():
    equals = {
        "id": "c3",
        "kind": "FIELD_EQUALS",
        "params": {"field": "item_code", "value": "CT-240-IVY"},
    }
    assert evaluate_clause(equals, [artifact(fields={"item_code": "ct-240-ivy"})]).verdict == "PASS"
    assert evaluate_clause(equals, [artifact(fields={"item_code": "CT-180-SLT"})]).verdict == "FAIL"
    assert evaluate_clause(equals, [artifact(fields={})]).verdict == "UNVERIFIABLE"

    matches = {
        "id": "c3",
        "kind": "FIELD_MATCHES_SPEC",
        "params": {"field": "signed_by", "pattern": r".{3,}"},
    }
    assert (
        evaluate_clause(matches, [artifact(fields={"signed_by": "R. Krishnan"})]).verdict == "PASS"
    )
    assert evaluate_clause(matches, [artifact(fields={"signed_by": "x"})]).verdict == "FAIL"


def test_visual_clause_is_not_deterministic():
    assert "VISUAL_CONSISTENT_WITH" not in DETERMINISTIC_KINDS
    clause = {
        "id": "c3",
        "kind": "VISUAL_CONSISTENT_WITH",
        "params": {"colour": "#efe7d3", "tolerance": 60},
    }
    photo = artifact(
        artifact_type="PHOTO_SET",
        fields={
            "legible": True,
            "colour_palette": [
                {"hex": "#212125", "share": 0.55},
                {"hex": "#eae7cf", "share": 0.30},
            ],
        },
    )
    result = evaluate_clause(clause, [photo])
    assert result.verdict == "PASS"
    assert result.deterministic is False


def test_visual_clause_sums_shares_across_buckets():
    """A continuous colour split across quantiser buckets must still count."""
    clause = {
        "id": "c3",
        "kind": "VISUAL_CONSISTENT_WITH",
        "params": {"colour": "#efe7d3", "tolerance": 60, "min_share": 0.20},
    }
    photo = artifact(
        artifact_type="PHOTO_SET",
        fields={
            "legible": True,
            "colour_palette": [
                {"hex": "#212125", "share": 0.60},
                {"hex": "#eae7cf", "share": 0.11},
                {"hex": "#f2e9d3", "share": 0.10},
            ],
        },
    )
    assert evaluate_clause(clause, [photo]).verdict == "PASS"


def test_visual_clause_fails_on_a_different_colour():
    clause = {
        "id": "c3",
        "kind": "VISUAL_CONSISTENT_WITH",
        "params": {"colour": "#efe7d3", "tolerance": 60},
    }
    photo = artifact(
        artifact_type="PHOTO_SET",
        fields={
            "legible": True,
            "colour_palette": [{"hex": "#3a5ca8", "share": 0.5}],
        },
    )
    assert evaluate_clause(clause, [photo]).verdict == "FAIL"


def test_visual_clause_is_unverifiable_when_illegible():
    clause = {
        "id": "c3",
        "kind": "VISUAL_CONSISTENT_WITH",
        "params": {"colour": "#efe7d3"},
    }
    photo = artifact(artifact_type="PHOTO_SET", fields={"legible": False})
    assert evaluate_clause(clause, [photo]).verdict == "UNVERIFIABLE"


# ── pre-checks ──────────────────────────────────────────────────────────────
def test_missing_required_artifact_type_is_a_zero_token_reject():
    condition = {
        "clauses": [
            {"id": "c1", "kind": "ARTIFACT_PRESENT", "params": {"artifact_types": ["GRN"]}}
        ],
        "required_artifact_types": ["INVOICE", "GRN"],
    }
    outcome = run_prechecks(condition, [artifact(artifact_type="GRN")])
    assert outcome.resolved
    assert outcome.decision == "REJECT"
    assert "INVOICE" in outcome.reason


def test_mime_mismatch_is_rejected():
    condition = {"clauses": [], "required_artifact_types": []}
    outcome = run_prechecks(
        condition,
        [artifact(declared_mime="application/pdf", sniffed_mime="image/png", size_bytes=10)],
    )
    assert outcome.resolved and outcome.decision == "REJECT"


def test_hard_numeric_failure_is_rejected_before_any_model_call():
    condition = {
        "clauses": [
            {
                "id": "c4",
                "kind": "QUANTITY_AT_LEAST",
                "params": {"field": "quantity", "min": 520},
                "required": True,
            }
        ],
        "required_artifact_types": [],
    }
    outcome = run_prechecks(condition, [artifact(fields={"quantity": 100}, size_bytes=10)])
    assert outcome.resolved and outcome.decision == "REJECT"
    assert "c4" in outcome.reason


def test_internally_inconsistent_document_becomes_an_unverifiable_clause():
    condition = {"clauses": [], "required_artifact_types": []}
    outcome = run_prechecks(
        condition,
        [
            artifact(
                size_bytes=10,
                fields={"totals_consistent": False},
                observation={
                    "notes": ["internal inconsistency: line items sum to 1.00 but stated 2.00"],
                    "machine_readable_fields": {"totals_consistent": False},
                },
            )
        ],
    )
    assert outcome.integrity_findings
    clause = integrity_clause(outcome)
    assert clause is not None
    assert clause["verdict"] == "UNVERIFIABLE"
    assert clause["required"] is True


def test_no_integrity_clause_when_documents_are_consistent():
    outcome = run_prechecks(
        {"clauses": [], "required_artifact_types": []},
        [artifact(size_bytes=10, fields={"totals_consistent": True})],
    )
    assert integrity_clause(outcome) is None


# ── the provider contract ───────────────────────────────────────────────────
def test_prompts_are_byte_stable_constants():
    """They sit behind the Anthropic cache breakpoint, so they must not be
    f-strings or assembled at import time."""
    import app.agents.prompts as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for name in ("EXTRACTION_SYSTEM_PROMPT", "CLAUSE_SYSTEM_PROMPT", "ARBITER_SYSTEM_PROMPT"):
        assert f'{name} = """' in source, f"{name} must be a plain triple-quoted literal"
    assert 'f"""' not in source
    assert ".format(" not in source


def test_clause_prompt_states_the_unverifiable_rule():
    text = CLAUSE_SYSTEM_PROMPT
    assert "UNVERIFIABLE" in text
    assert "500" in text  # the worked example
    assert "no urgent path" in text.lower()
    for prompt in (EXTRACTION_SYSTEM_PROMPT, ARBITER_SYSTEM_PROMPT):
        assert len(prompt) > 400


def test_anthropic_call_shape_never_passes_budget_tokens():
    """budget_tokens is rejected with a 400 on Opus 5 and Sonnet 5."""
    import inspect

    source = inspect.getsource(AnthropicProvider.parse)
    assert "budget_tokens" not in source
    assert '"type": "adaptive"' in source
    assert "cache_control" in source
    assert "output_format=output_format" in source


def test_prompt_hash_is_content_addressed():
    a = compute_prompt_hash("system", "user", "claude-opus-5")
    assert a == compute_prompt_hash("system", "user", "claude-opus-5")
    assert a != compute_prompt_hash("system", "user ", "claude-opus-5")
    assert a != compute_prompt_hash("system", "user", "claude-sonnet-5")


def test_pricing_is_the_pinned_table():
    from app.agents._llm import PRICING

    assert PRICING["claude-opus-5"] == (5.0, 25.0)
    assert PRICING["claude-sonnet-5"] == (2.0, 10.0)


def test_cached_reads_are_billed_at_a_tenth():
    plain = cost_micro_usd("claude-opus-5", Usage(input_tokens=1_000_000), "anthropic")
    cached = cost_micro_usd("claude-opus-5", Usage(cache_read_input_tokens=1_000_000), "anthropic")
    assert plain == 5_000_000
    assert cached == 500_000


def test_fixture_provider_reads_the_rendered_case_not_a_label():
    """The offline adapter is given the same prompt a live model gets, and
    answers from its content.  It never sees an expected outcome."""
    condition = {
        "clauses": [
            {
                "id": "c1",
                "kind": "ARTIFACT_PRESENT",
                "description": "invoice present",
                "params": {"artifact_types": ["INVOICE"]},
                "required": True,
            }
        ],
        "required_artifact_types": ["INVOICE"],
    }
    content = render_clause_case(
        condition=condition, artifacts=[artifact(parseable=True)], precheck_results=[]
    )
    case = extract_case_json(content)
    assert "label" not in json.dumps(case).lower()
    assert "should_release" not in json.dumps(case)

    from app.agents.verifier.schemas import ClauseEvaluation

    result = FixtureProvider().parse(
        system_prompt=CLAUSE_SYSTEM_PROMPT,
        user_content=content,
        output_format=ClauseEvaluation,
        model="fixture",
        purpose="clause_evaluation",
    )
    assert result.parsed.verdicts[0].verdict == "PASS"
    assert result.provider == "fixture"


def test_extraction_quality_penalises_illegible_evidence():
    from app.evidence.analyse import Observation

    good = Observation(
        parseable=True, kind="pdf", fields={"date": "x", "total": 1, "legible": True}
    )
    bad = Observation(parseable=True, kind="pdf", fields={"legible": False})
    unparseable = Observation(parseable=False, kind="pdf")
    fields = ["date", "total"]
    assert extraction_quality(good, fields) > extraction_quality(bad, fields)
    assert extraction_quality(unparseable, fields) == 0.0


def test_pdf_analysis_recovers_real_fields():
    from scripts.docgen import DocSpec, render_pdf

    pdf = render_pdf(
        DocSpec(
            kind="INVOICE",
            fields={
                "vendor": "Sri Textiles",
                "date": "2026-08-28",
                "item_code": "CT-240-IVY",
                "quantity": "540 m",
            },
            line_items=[
                {
                    "description": "Cotton CT-240-IVY",
                    "quantity": "540",
                    "uom": "m",
                    "amount": "76950.00",
                }
            ],
        )
    )
    obs = analyse(pdf, "application/pdf")
    assert obs.parseable
    assert obs.fields["item_code"] == "CT-240-IVY"
    assert obs.fields["date"] == "2026-08-28"
    assert obs.fields["quantity"] == 540.0
    assert obs.fields["totals_consistent"] is True


def test_pdf_analysis_detects_an_inconsistent_total():
    from scripts.docgen import DocSpec, render_pdf

    pdf = render_pdf(
        DocSpec(
            kind="INVOICE",
            fields={"vendor": "Sri Textiles", "date": "2026-08-28"},
            line_items=[
                {"description": "Cotton", "quantity": "540", "uom": "m", "amount": "76950.00"}
            ],
            stated_total_override=41_800.00,
        )
    )
    obs = analyse(pdf, "application/pdf")
    assert obs.fields["totals_consistent"] is False
    assert any("inconsisten" in note for note in obs.notes)


def test_image_analysis_reports_the_subject_colour_not_the_backdrop():
    from scripts.docgen import IVORY, render_photo

    obs = analyse(render_photo(seed=1, colour=IVORY), "image/png")
    assert obs.parseable
    subject = obs.image["subject_rgb"]
    # The backdrop is near-black; the garments are ivory.
    assert sum(subject) > 500, obs.image
    assert obs.fields["visible_item_count_estimate"] is None
    assert obs.fields["count_establishable_from_pixels"] is False


def test_calibration_falls_back_to_identity_without_an_artifact(monkeypatch, tmp_path):
    import app.agents.verifier.confidence as conf

    monkeypatch.setattr(conf, "CALIBRATION_PATH", tmp_path / "absent.json")
    reset_calibration_cache()
    value, version = conf.calibrate(0.7)
    assert value == 0.7
    assert version == "identity-fallback"
    reset_calibration_cache()
