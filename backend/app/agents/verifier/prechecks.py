"""Stage 1: deterministic pre-checks.  Zero LLM calls.

A missing required artifact is a REJECT at zero token cost.  Every result is
persisted in ``Attestation.deterministic_prechecks_json``, and Report E states
what fraction of decisions resolved here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.verifier.clause_rules import DETERMINISTIC_KINDS, evaluate_clause

INTEGRITY_CLAUSE_ID = "integrity"


@dataclass(slots=True)
class PrecheckOutcome:
    resolved: bool  # True when the decision is settled without any model call
    decision: str | None  # REJECT when resolved
    checks: list[dict[str, Any]] = field(default_factory=list)
    clause_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    reason: str = ""
    integrity_findings: list[dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "resolved_without_llm": self.resolved,
            "decision": self.decision,
            "reason": self.reason,
            "checks": self.checks,
            "clause_results": self.clause_results,
            "integrity_findings": self.integrity_findings,
            "passed": sum(1 for c in self.checks if c["ok"]),
            "total": len(self.checks),
        }


def run_prechecks(condition: dict[str, Any], artifacts: list[dict[str, Any]]) -> PrecheckOutcome:
    """``artifacts`` carries, per artifact: id, type, mime, sha256, size, the
    deterministic observation, and the machine-readable fields recovered from it.
    """
    outcome = PrecheckOutcome(resolved=False, decision=None)
    required_types = [t.upper() for t in (condition.get("required_artifact_types") or [])]
    present_types = {str(a.get("artifact_type", "")).upper() for a in artifacts}

    # 1. every required artifact type present?
    missing = [t for t in required_types if t not in present_types]
    outcome.checks.append(
        {
            "check": "required_artifact_types_present",
            "ok": not missing,
            "detail": {"required": required_types, "missing": missing},
        }
    )

    # 2. every artifact parseable, non-empty, hashed, MIME as claimed?
    unparseable = [str(a["artifact_id"]) for a in artifacts if not a.get("parseable")]
    outcome.checks.append(
        {
            "check": "all_artifacts_parseable",
            "ok": not unparseable,
            "detail": {"unparseable": unparseable},
        }
    )
    unhashed = [str(a["artifact_id"]) for a in artifacts if not a.get("sha256")]
    outcome.checks.append(
        {"check": "all_artifacts_hashed", "ok": not unhashed, "detail": {"unhashed": unhashed}}
    )
    empty = [str(a["artifact_id"]) for a in artifacts if not int(a.get("size_bytes") or 0)]
    outcome.checks.append(
        {"check": "no_empty_artifacts", "ok": not empty, "detail": {"empty": empty}}
    )
    mime_mismatch = [
        str(a["artifact_id"])
        for a in artifacts
        if a.get("declared_mime")
        and a.get("sniffed_mime")
        and a["declared_mime"] != a["sniffed_mime"]
    ]
    outcome.checks.append(
        {
            "check": "mime_matches_content",
            "ok": not mime_mismatch,
            "detail": {"mismatched": mime_mismatch},
        }
    )

    # 2b. does any artifact contradict itself?
    #
    # A document whose stated total does not equal the sum of its own line items
    # is not evidence of an amount, in either direction: it may be a transcription
    # slip or a fabrication, and nothing in the bundle distinguishes those.  So it
    # becomes a required UNVERIFIABLE finding, which by I3 can never auto-release
    # and by ADR-004 escalates to a human.  This is not a special case bolted on
    # for one document type: it fires for any artifact the analyser found
    # internally inconsistent.
    for artifact in artifacts:
        fields = artifact.get("fields") or {}
        observation = artifact.get("observation") or {}
        machine_fields = observation.get("machine_readable_fields") or {}
        consistent = fields.get("totals_consistent", machine_fields.get("totals_consistent"))
        if consistent is False:
            notes = [
                n
                for n in (observation.get("notes") or [])
                if "inconsistency" in n or "inconsistent" in n
            ]
            outcome.integrity_findings.append(
                {
                    "artifact_id": str(artifact["artifact_id"]),
                    "artifact_type": artifact.get("artifact_type"),
                    "finding": "INTERNALLY_INCONSISTENT_TOTALS",
                    "detail": notes[0] if notes else "stated total does not equal the line items",
                }
            )
    outcome.checks.append(
        {
            "check": "artifacts_internally_consistent",
            "ok": not outcome.integrity_findings,
            "detail": {"findings": outcome.integrity_findings},
        }
    )

    # 3 & 4. hard date windows and machine-readable numeric floors.
    hard_failures: list[str] = []
    for clause in condition.get("clauses", []):
        kind = str(clause.get("kind", "")).upper()
        if kind not in DETERMINISTIC_KINDS:
            continue
        result = evaluate_clause(clause, artifacts)
        outcome.clause_results[clause["id"]] = {
            "clause_id": clause["id"],
            "kind": kind,
            "verdict": result.verdict,
            "confidence": round(result.confidence, 4),
            "note": result.note,
            "evidence_refs": result.evidence_refs,
            "required": bool(clause.get("required", True)),
            "deterministic": True,
        }
        if kind in {"DATE_WITHIN", "AMOUNT_AT_LEAST", "QUANTITY_AT_LEAST"}:
            outcome.checks.append(
                {
                    "check": f"clause_{clause['id']}_{kind.lower()}",
                    "ok": result.verdict != "FAIL",
                    "detail": {"verdict": result.verdict, "note": result.note},
                }
            )
        if result.verdict == "FAIL" and clause.get("required", True):
            hard_failures.append(clause["id"])

    # A missing required artifact type stops the pipeline before any token is spent.
    if missing:
        outcome.resolved = True
        outcome.decision = "REJECT"
        outcome.reason = "A required artifact type was not submitted: " + ", ".join(missing)
        return outcome

    if empty or unhashed:
        outcome.resolved = True
        outcome.decision = "REJECT"
        outcome.reason = "An artifact is empty or was not hashed on upload."
        return outcome

    if mime_mismatch:
        outcome.resolved = True
        outcome.decision = "REJECT"
        outcome.reason = "An artifact's contents do not match its declared type."
        return outcome

    if hard_failures:
        outcome.resolved = True
        outcome.decision = "REJECT"
        outcome.reason = (
            "A required clause is contradicted by a deterministically checkable field: "
            + ", ".join(hard_failures)
        )
        return outcome

    return outcome


def integrity_clause(outcome: PrecheckOutcome) -> dict[str, Any] | None:
    """The synthetic required clause an evidence-integrity finding produces.

    It is a first-class ``UNVERIFIABLE`` verdict, so it flows through I3 and
    ADR-004 exactly like any other unverifiable required clause -- and it shows up
    in the clause table the reviewer reads, which is where it belongs.
    """
    if not outcome.integrity_findings:
        return None
    first = outcome.integrity_findings[0]
    detail = "; ".join(f["detail"] for f in outcome.integrity_findings)
    return {
        "clause_id": INTEGRITY_CLAUSE_ID,
        "verdict": "UNVERIFIABLE",
        "evidence_refs": [f["artifact_id"] for f in outcome.integrity_findings],
        "clause_confidence": 0.3,
        "note": (
            f"Evidence integrity: {detail}. A document that contradicts itself cannot "
            "evidence an amount in either direction, so a human must look."
        ),
        "required": True,
        "resolved_by": "precheck",
        "description": "Every artifact is internally consistent",
        "kind": "EVIDENCE_INTEGRITY",
        "artifact_type": first.get("artifact_type"),
    }
