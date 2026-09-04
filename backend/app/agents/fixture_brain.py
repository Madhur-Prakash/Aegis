"""The deterministic offline brain behind :class:`FixtureProvider`.

It reads the same rendered case JSON a live model reads, applies the published
clause rubric in ``app/agents/verifier/clause_rules.py``, and returns a valid
structured object.  It has no access to eval labels, and Suite A scores it
exactly as it scores Claude or a Groq model.

Its purpose is that ``make eval``, ``make test`` and the demo all run with no
network and no API key, while still exercising the real pipeline: pre-checks,
extraction, per-clause judgement, Python-side confidence, signing, anchoring.
Every report states the provider that produced its numbers.
"""

from __future__ import annotations

from typing import Any

from app.agents.verifier.clause_rules import evaluate_clause
from app.agents.verifier.render import extract_case_json


def _extraction(case: dict[str, Any]) -> dict[str, Any]:
    analyser = case.get("analyser") or {}
    fields = dict(analyser.get("machine_readable_fields") or {})
    image = analyser.get("image_analysis") or {}
    artifact_type = str(case.get("artifact_type", "")).upper()

    unreadable: list[str] = []
    if artifact_type in {
        "INVOICE",
        "GRN",
        "DELIVERY_CHALLAN",
        "CONDITION_REPORT",
        "SPEC_REFERENCE",
    }:
        for expected in ("date", "quantity", "item_code"):
            if fields.get(expected) in (None, "", []):
                unreadable.append(expected)
    if artifact_type == "PHOTO_SET":
        fields.setdefault("visible_item_count_estimate", None)
        fields.setdefault("count_establishable", False)
        if image:
            fields.setdefault("colour_summary", image.get("dominant_hex"))
        unreadable.append("visible_item_count_estimate")

    # Rupee totals become integer paise; a float amount never leaves this stage.
    if isinstance(fields.get("total"), (int, float)):
        fields["total_paise"] = round(float(fields["total"]) * 100)

    note_bits = list(analyser.get("notes") or [])
    if fields.get("totals_consistent") is False:
        note_bits.append("stated total does not equal the sum of the line items")

    return {
        "artifact_id": case.get("artifact_id"),
        "artifact_type": case.get("artifact_type"),
        "fields": fields,
        "unreadable_fields": sorted(set(unreadable)),
        "legible": bool(fields.get("legible", analyser.get("parseable", False))),
        "note": "; ".join(note_bits)[:400],
    }


def _clause_evaluation(case: dict[str, Any]) -> dict[str, Any]:
    condition = case.get("condition") or {}
    artifacts = case.get("artifacts") or []
    verdicts = []
    for clause in condition.get("clauses", []):
        result = evaluate_clause(clause, artifacts)
        verdicts.append(
            {
                "clause_id": clause["id"],
                "verdict": result.verdict,
                "evidence_refs": result.evidence_refs,
                "clause_confidence": round(result.confidence, 4),
                "note": result.note,
            }
        )
    unverifiable = [v for v in verdicts if v["verdict"] == "UNVERIFIABLE"]
    failed = [v for v in verdicts if v["verdict"] == "FAIL"]
    if failed:
        overall = f"{len(failed)} clause(s) are contradicted by the evidence."
    elif unverifiable:
        overall = (
            f"{len(unverifiable)} clause(s) cannot be decided from this evidence in "
            "either direction."
        )
    else:
        overall = "Every clause is satisfied by the evidence submitted."
    return {"verdicts": verdicts, "overall_note": overall}


def _arbitration(case: dict[str, Any]) -> dict[str, Any]:
    """A transparent, arithmetic recommendation.

    The tolerance clause in the terms is applied to the numbers stated in the
    claims.  The split is computed to balance exactly, because a split that does
    not balance is rejected downstream and never 'fixed up'.
    """
    milestone = case.get("milestone") or {}
    terms = case.get("deal_terms") or {}
    amount = int(milestone.get("amount_paise") or 0)
    tolerance = terms.get("tolerance") or {}
    claim = str(case.get("buyer_claim") or "")

    affected = _first_int(claim, keys=("units", "pieces", "unit"))
    total_units = int(milestone.get("unit_count") or tolerance.get("total_units") or 0)
    deduction_pct = float(tolerance.get("variance_deduction_pct") or 0.0)
    unit_price_paise = int(tolerance.get("unit_price_paise") or 0)
    if not unit_price_paise and total_units:
        unit_price_paise = amount // total_units

    steps: list[str] = []
    refs = [str(a.get("artifact_id")) for a in (case.get("artifacts") or [])][:4]

    if affected and unit_price_paise and deduction_pct:
        refund = round(affected * unit_price_paise * deduction_pct / 100.0)
        refund = max(0, min(refund, amount))
        release = amount - refund
        steps.append(
            f"The claim identifies {affected} affected unit(s); artifacts {', '.join(refs)} "
            "are the evidence relied on."
        )
        steps.append(
            f"The tolerance clause allows a {deduction_pct:g}% deduction per affected unit at a "
            f"unit price of {unit_price_paise} paise: "
            f"{affected} x {unit_price_paise} x {deduction_pct:g}% = {refund} paise."
        )
        steps.append(f"Release {release} paise and refund {refund} paise, summing to {amount}.")
        outcome = (
            "PARTIAL" if 0 < refund < amount else ("FULL_REFUND" if refund else "FULL_RELEASE")
        )
        confidence = 0.74
    else:
        release, refund = amount, 0
        outcome = "FULL_RELEASE"
        steps.append(
            "The claim states no quantified defect that the tolerance clause can be applied to, "
            "and the evidence does not contradict delivery."
        )
        confidence = 0.42

    open_questions = [
        "Was an independent count or inspection sheet issued for the affected units?",
        "Do the photographs on record cover the units the buyer identifies?",
    ]
    if not affected:
        open_questions.insert(0, "How many units does the buyer say are affected?")

    return {
        "outcome": outcome,
        "release_paise": int(release),
        "refund_paise": int(refund),
        "reasoning_steps": steps,
        "terms_clauses_relied_on": [str(c) for c in (tolerance.get("clause_ids") or ["tolerance"])],
        "confidence": confidence,
        "open_questions": open_questions,
    }


def _first_int(text: str, keys: tuple[str, ...]) -> int | None:
    import re

    for key in keys:
        match = re.search(rf"(\d[\d,]*)\s*(?:of\s*\d[\d,]*\s*)?{key}\b", text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                continue
    match = re.search(r"\b(\d[\d,]{1,6})\b", text)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def answer(purpose: str, user_content: str, output_format: type) -> dict[str, Any]:
    case = extract_case_json(user_content)
    if purpose == "extraction":
        return _extraction(case)
    if purpose == "clause_evaluation":
        return _clause_evaluation(case)
    if purpose == "arbitration":
        return _arbitration(case)
    raise ValueError(f"no fixture behaviour for purpose {purpose!r}")
