"""The verifier.  It writes attestations.  It never moves money (I2).

Pipeline, in this order and with no shortcuts:

1. deterministic pre-checks     (zero LLM calls; a missing required artifact is a
                                 REJECT at zero token cost)
2. extraction                   (one structured call per artifact)
3. clause evaluation            (one structured call, each clause independent)
4. confidence                   (pure Python, not the model's self-report)
5. decide                       (I3, in ``app/settlement/guards.decide``)
6. sign                         (canonical JSON -> sha256 -> EIP-712)

This package must not import ``app.settlement`` *except* for the pure guard
module ``app.settlement.guards``, which contains no I/O and no rail access.  The
CI import-lint enforces the boundary against ``settlement.engine``, ``rails`` and
``payments`` explicitly.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents._llm import LLMResult, cost_micro_usd, get_provider
from app.agents.prompts import CLAUSE_SYSTEM_PROMPT, EXTRACTION_SYSTEM_PROMPT
from app.agents.verifier.clause_rules import DETERMINISTIC_KINDS
from app.agents.verifier.confidence import ConfidenceBreakdown, compute_confidence
from app.agents.verifier.prechecks import PrecheckOutcome, integrity_clause, run_prechecks
from app.agents.verifier.render import render_clause_case, render_extraction_case
from app.agents.verifier.schemas import ClauseEvaluation, ExtractedDocument
from app.attest.canonical import payload_hash
from app.common.logging import get_logger
from app.config.settings import CALIBRATION_VERSION, REJECT_THRESHOLD, RELEASE_THRESHOLD, settings
from app.evidence.analyse import Observation, extraction_quality
from app.settlement.guards import ClauseOutcome, DecisionInput, decide

log = get_logger("agents.verifier")

EXPECTED_FIELDS: dict[str, list[str]] = {
    "INVOICE": ["vendor", "invoice_no", "date", "total", "item_code", "quantity"],
    "GRN": ["ref_no", "date", "item_code", "quantity", "uom"],
    "DELIVERY_CHALLAN": ["ref_no", "date", "quantity", "signed_by"],
    "CONDITION_REPORT": ["date", "condition", "signed_by"],
    "SPEC_REFERENCE": ["item_code", "colour_summary"],
    "PHOTO_SET": ["colour_summary", "legible"],
}


@dataclass(slots=True)
class ArtifactInput:
    artifact_id: str
    artifact_type: str
    filename: str
    mime: str
    declared_mime: str
    sha256: str
    size_bytes: int
    observation: Observation


@dataclass(slots=True)
class SpendRecord:
    purpose: str
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_micro_usd: int
    latency_ms: int


@dataclass(slots=True)
class VerificationOutput:
    decision: str
    confidence: float
    breakdown: ConfidenceBreakdown
    clause_verdicts: list[dict[str, Any]]
    prechecks: PrecheckOutcome
    reasoning: str
    provider: str
    model_id: str
    model_version: str
    prompt_hash: str
    rationale: dict[str, Any]
    spends: list[SpendRecord] = field(default_factory=list)
    extracted: dict[str, dict[str, Any]] = field(default_factory=dict)
    extraction_qualities: dict[str, float] = field(default_factory=dict)
    stage_latency_ms: dict[str, int] = field(default_factory=dict)
    llm_calls: int = 0

    @property
    def thresholds(self) -> dict[str, float]:
        return {"release": RELEASE_THRESHOLD, "reject": REJECT_THRESHOLD}


def _artifact_payload(
    artifact: ArtifactInput, fields: dict[str, Any] | None = None
) -> dict[str, Any]:
    obs = artifact.observation
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "filename": artifact.filename,
        "declared_mime": artifact.declared_mime,
        "sniffed_mime": artifact.mime,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "parseable": obs.parseable,
        "fields": fields if fields is not None else dict(obs.fields),
        "observation": obs.summary(),
    }


def _model_for(purpose: str) -> str:
    if purpose == "extraction":
        return settings.AI_MODEL_EXTRACTION
    if purpose == "arbitration":
        return settings.AI_MODEL_ARBITER
    return settings.AI_MODEL_VERIFIER


def _spend(result: LLMResult, purpose: str) -> SpendRecord:
    return SpendRecord(
        purpose=purpose,
        provider=result.provider,
        model_id=result.model_id,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cache_read_input_tokens,
        cache_write_tokens=result.usage.cache_creation_input_tokens,
        cost_micro_usd=cost_micro_usd(result.model_id, result.usage, result.provider),
        latency_ms=result.latency_ms,
    )


def verify(
    *,
    condition: dict[str, Any],
    artifacts: list[ArtifactInput],
) -> VerificationOutput:
    """Runs the whole pipeline.  Pure computation: no database, no money, no rail."""
    provider = get_provider()
    stage_latency: dict[str, int] = {}

    # ── 1. deterministic pre-checks ────────────────────────────────────
    started = time.perf_counter()
    precheck_artifacts = [_artifact_payload(a) for a in artifacts]
    prechecks = run_prechecks(condition, precheck_artifacts)
    stage_latency["prechecks"] = int((time.perf_counter() - started) * 1000)

    clauses = condition.get("clauses", [])
    required_map = {str(c["id"]): bool(c.get("required", True)) for c in clauses}

    if prechecks.resolved:
        verdicts: list[dict[str, Any]] = []
        for clause in clauses:
            existing = prechecks.clause_results.get(clause["id"])
            verdicts.append(
                {
                    "clause_id": clause["id"],
                    "verdict": existing["verdict"] if existing else "UNVERIFIABLE",
                    "evidence_refs": existing["evidence_refs"] if existing else [],
                    "clause_confidence": existing["confidence"] if existing else 0.0,
                    "note": existing["note"]
                    if existing
                    else "Not evaluated: the pre-checks rejected the bundle first.",
                    "required": required_map.get(str(clause["id"]), True),
                    "resolved_by": "precheck",
                }
            )
        integrity = integrity_clause(prechecks)
        if integrity is not None:
            verdicts.append(integrity)
        breakdown = compute_confidence(
            clause_verdicts=verdicts,
            deterministic_clause_results=prechecks.clause_results,
            extraction_qualities=[],
        )
        rationale = {
            "rule": "DETERMINISTIC_PRECHECK_REJECT",
            "confidence": breakdown.calibrated,
            "release_threshold": RELEASE_THRESHOLD,
            "reject_threshold": REJECT_THRESHOLD,
            "failed_required_clauses": [
                v["clause_id"] for v in verdicts if v["verdict"] == "FAIL" and v["required"]
            ],
            "unverifiable_required_clauses": [
                v["clause_id"] for v in verdicts if v["verdict"] == "UNVERIFIABLE" and v["required"]
            ],
            "precheck_reason": prechecks.reason,
        }
        log.info(
            "verification resolved by prechecks",
            extra={"decision": "REJECT", "reason": prechecks.reason, "llm_calls": 0},
        )
        return VerificationOutput(
            decision="REJECT",
            confidence=breakdown.calibrated,
            breakdown=breakdown,
            clause_verdicts=verdicts,
            prechecks=prechecks,
            reasoning=prechecks.reason,
            provider=provider.name,
            model_id="none",
            model_version="deterministic-prechecks",
            prompt_hash=payload_hash({"stage": "prechecks", "condition": condition}),
            rationale=rationale,
            stage_latency_ms=stage_latency,
            llm_calls=0,
        )

    # ── 2. extraction: one structured call per artifact ────────────────
    spends: list[SpendRecord] = []
    extracted: dict[str, dict[str, Any]] = {}
    qualities: dict[str, float] = {}
    enriched: list[dict[str, Any]] = []
    started = time.perf_counter()
    for artifact in artifacts:
        user_content = render_extraction_case(
            artifact_id=artifact.artifact_id,
            artifact_type=artifact.artifact_type,
            filename=artifact.filename,
            observation=artifact.observation.summary(),
        )
        result = provider.parse(
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            user_content=user_content,
            output_format=ExtractedDocument,
            model=_model_for("extraction"),
            purpose="extraction",
        )
        spends.append(_spend(result, "extraction"))
        document: ExtractedDocument = result.parsed  # type: ignore[assignment]
        fields = dict(document.fields or {})
        extracted[artifact.artifact_id] = {
            "fields": fields,
            "unreadable_fields": document.unreadable_fields,
            "legible": document.legible,
            "note": document.note,
        }
        quality = extraction_quality(
            artifact.observation,
            EXPECTED_FIELDS.get(artifact.artifact_type.upper(), list(fields)[:4] or ["date"]),
        )
        qualities[artifact.artifact_id] = quality
        payload = _artifact_payload(artifact, fields)
        payload["extraction_quality"] = quality
        payload["unreadable_fields"] = document.unreadable_fields
        enriched.append(payload)
    stage_latency["extraction"] = int((time.perf_counter() - started) * 1000)

    # Re-run the deterministic rubric over the *extracted* fields, so
    # ``verifiable_fraction`` reflects what was actually machine-checkable.
    deterministic_results: dict[str, dict[str, Any]] = {}
    for clause in clauses:
        if str(clause.get("kind", "")).upper() not in DETERMINISTIC_KINDS:
            continue
        from app.agents.verifier.clause_rules import evaluate_clause

        rule = evaluate_clause(clause, enriched)
        deterministic_results[clause["id"]] = {
            "clause_id": clause["id"],
            "kind": str(clause.get("kind")).upper(),
            "verdict": rule.verdict,
            "confidence": round(rule.confidence, 4),
            "note": rule.note,
            "evidence_refs": rule.evidence_refs,
            "required": bool(clause.get("required", True)),
            "deterministic": True,
        }
    prechecks.clause_results.update(deterministic_results)

    # ── 3. clause evaluation: one structured call ──────────────────────
    started = time.perf_counter()
    clause_content = render_clause_case(
        condition=condition,
        artifacts=enriched,
        precheck_results=list(prechecks.clause_results.values()),
    )
    clause_result = provider.parse(
        system_prompt=CLAUSE_SYSTEM_PROMPT,
        user_content=clause_content,
        output_format=ClauseEvaluation,
        model=_model_for("clause_evaluation"),
        purpose="clause_evaluation",
    )
    spends.append(_spend(clause_result, "clause_evaluation"))
    stage_latency["clause_evaluation"] = int((time.perf_counter() - started) * 1000)
    evaluation: ClauseEvaluation = clause_result.parsed  # type: ignore[assignment]

    by_id = {v.clause_id: v for v in evaluation.verdicts}
    verdicts = []
    for clause in clauses:
        cid = str(clause["id"])
        judged = by_id.get(cid)
        deterministic = deterministic_results.get(cid)
        if judged is None:
            # The model failed to answer a clause.  A missing verdict is never
            # treated as a pass: it is UNVERIFIABLE, which cannot auto-release.
            verdicts.append(
                {
                    "clause_id": cid,
                    "verdict": deterministic["verdict"] if deterministic else "UNVERIFIABLE",
                    "evidence_refs": deterministic["evidence_refs"] if deterministic else [],
                    "clause_confidence": deterministic["confidence"] if deterministic else 0.0,
                    "note": deterministic["note"]
                    if deterministic
                    else "The evaluator returned no verdict for this clause.",
                    "required": bool(clause.get("required", True)),
                    "resolved_by": "precheck" if deterministic else "missing",
                    "description": clause.get("description", ""),
                    "kind": str(clause.get("kind", "")),
                }
            )
            continue

        verdict = judged.verdict
        resolved_by = "llm"
        note = judged.note
        confidence = float(judged.clause_confidence)
        refs = list(judged.evidence_refs)
        if deterministic is not None and deterministic["verdict"] in {"PASS", "FAIL"}:
            # A deterministic contradiction is authoritative: a model may not
            # talk a machine-checkable FAIL up into a PASS.
            if deterministic["verdict"] != verdict:
                note = (
                    f"{deterministic['note']} (the deterministic check is authoritative; "
                    f"the evaluator said {verdict})"
                )
                verdict = deterministic["verdict"]
                confidence = float(deterministic["confidence"])
                refs = list(deterministic["evidence_refs"])
                resolved_by = "precheck_override"
            else:
                resolved_by = "precheck_and_llm"
        verdicts.append(
            {
                "clause_id": cid,
                "verdict": verdict,
                "evidence_refs": refs,
                "clause_confidence": round(confidence, 4),
                "note": note,
                "required": bool(clause.get("required", True)),
                "resolved_by": resolved_by,
                "description": clause.get("description", ""),
                "kind": str(clause.get("kind", "")),
            }
        )

    # An artifact that contradicts itself becomes a required UNVERIFIABLE clause,
    # so I3 and ADR-004 handle it with no special case in the decision path.
    integrity = integrity_clause(prechecks)
    if integrity is not None:
        verdicts.append(integrity)

    # ── 4. confidence (pure Python) ────────────────────────────────────
    breakdown = compute_confidence(
        clause_verdicts=verdicts,
        deterministic_clause_results=prechecks.clause_results,
        extraction_qualities=list(qualities.values()),
    )

    # ── 5. decide (I3) ─────────────────────────────────────────────────
    decision, rationale = decide(
        DecisionInput(
            confidence=breakdown.calibrated,
            clauses=tuple(
                ClauseOutcome(str(v["clause_id"]), str(v["verdict"]), bool(v["required"]))
                for v in verdicts
            ),
        )
    )
    rationale["calibration_version"] = breakdown.calibration_version

    reasoning = _compose_reasoning(decision, verdicts, evaluation.overall_note, breakdown)

    log.info(
        "verification completed",
        extra={
            "decision": decision,
            "confidence": breakdown.calibrated,
            "provider": provider.name,
            "model_id": clause_result.model_id,
            "llm_calls": len(spends),
            "unverifiable_required": breakdown.unverifiable_required,
            "prompt_hash": clause_result.prompt_hash,
            "latency_ms": sum(stage_latency.values()),
        },
    )

    return VerificationOutput(
        decision=decision,
        confidence=breakdown.calibrated,
        breakdown=breakdown,
        clause_verdicts=verdicts,
        prechecks=prechecks,
        reasoning=reasoning,
        provider=provider.name,
        model_id=clause_result.model_id,
        model_version=clause_result.model_version,
        prompt_hash=clause_result.prompt_hash,
        rationale=rationale,
        spends=spends,
        extracted=extracted,
        extraction_qualities=qualities,
        stage_latency_ms=stage_latency,
        llm_calls=len(spends),
    )


def _compose_reasoning(
    decision: str,
    verdicts: list[dict[str, Any]],
    overall_note: str,
    breakdown: ConfidenceBreakdown,
) -> str:
    unverifiable = [v for v in verdicts if v["verdict"] == "UNVERIFIABLE"]
    failed = [v for v in verdicts if v["verdict"] == "FAIL"]
    lines = [overall_note.strip()] if overall_note.strip() else []
    for v in failed:
        lines.append(f"FAIL {v['clause_id']}: {v['note']}")
    for v in unverifiable:
        lines.append(f"UNVERIFIABLE {v['clause_id']}: {v['note']}")
    lines.append(
        f"Confidence {breakdown.calibrated:.2f} = 0.45x{breakdown.verifiable_fraction:.2f} "
        f"verifiable + 0.45x{breakdown.llm_component:.2f} judged + "
        f"0.10x{breakdown.extraction_quality:.2f} extraction "
        f"- {breakdown.unverifiable_penalty:.2f} unverifiable penalty "
        f"(calibration {breakdown.calibration_version})."
    )
    if decision == "ESCALATE":
        lines.append(
            "It did not guess and it did not block: what could not be verified is named above, "
            "and a human decision is required."
        )
    return "\n".join(lines)


def attestation_canonical_payload(
    *,
    milestone_id: uuid.UUID | str,
    bundle_id: uuid.UUID | str,
    evidence_merkle_root: str,
    output: VerificationOutput,
) -> dict[str, Any]:
    """The exact object that is hashed and signed.  Ordering is irrelevant --
    ``canonical_json`` sorts -- but the *content* is the contract."""
    return {
        "milestone_id": str(milestone_id),
        "bundle_id": str(bundle_id),
        "evidence_merkle_root": evidence_merkle_root,
        "decision": output.decision,
        "confidence": float(output.confidence),
        "confidence_components": output.breakdown.as_json(),
        "clause_verdicts": [
            {
                "clause_id": v["clause_id"],
                "verdict": v["verdict"],
                "required": v["required"],
                "clause_confidence": v["clause_confidence"],
                "evidence_refs": sorted(v["evidence_refs"]),
            }
            for v in output.clause_verdicts
        ],
        "deterministic_prechecks": output.prechecks.as_json(),
        "thresholds": output.thresholds,
        "calibration_version": output.breakdown.calibration_version or CALIBRATION_VERSION,
        "provider": output.provider,
        "model_id": output.model_id,
        "model_version": output.model_version,
        "prompt_hash": output.prompt_hash,
    }
