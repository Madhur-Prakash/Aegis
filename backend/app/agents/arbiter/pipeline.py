"""The arbiter.  Advisory only (I8).

It runs on a dispute and produces a recommendation.  A deterministic Python check
validates that the split balances; if it does not, the model output is
**rejected** and re-requested once, then escalated.  Nothing is ever silently
fixed up, and settlement stays blocked until ``Dispute.human_decided_by`` is set.

Like the verifier, this package may not import ``settlement``, ``rails`` or
``payments``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents._llm import cost_micro_usd, get_provider
from app.agents.prompts import ARBITER_SYSTEM_PROMPT
from app.agents.verifier.pipeline import SpendRecord, _model_for
from app.agents.verifier.render import render_arbiter_case
from app.common.errors import LLMOutputRejected
from app.common.logging import get_logger
from app.settlement.guards import split_balances

log = get_logger("agents.arbiter")


class ArbiterRecommendation(BaseModel):
    outcome: Literal["FULL_RELEASE", "PARTIAL", "FULL_REFUND"]
    release_paise: int
    refund_paise: int
    reasoning_steps: list[str] = Field(default_factory=list)
    terms_clauses_relied_on: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    open_questions: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class ArbitrationOutput:
    recommendation: ArbiterRecommendation | None
    balanced: bool
    attempts: int
    provider: str
    model_id: str
    model_version: str
    prompt_hash: str
    rejection_reason: str | None = None
    spends: list[SpendRecord] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        if self.recommendation is None:
            return {
                "available": False,
                "rejection_reason": self.rejection_reason,
                "attempts": self.attempts,
                "provider": self.provider,
                "model_id": self.model_id,
            }
        return {
            "available": True,
            "outcome": self.recommendation.outcome,
            "release_paise": self.recommendation.release_paise,
            "refund_paise": self.recommendation.refund_paise,
            "reasoning_steps": self.recommendation.reasoning_steps,
            "terms_clauses_relied_on": self.recommendation.terms_clauses_relied_on,
            "confidence": self.recommendation.confidence,
            "open_questions": self.recommendation.open_questions,
            "balanced": self.balanced,
            "attempts": self.attempts,
            "provider": self.provider,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_hash": self.prompt_hash,
            "advisory_only": True,
        }


MAX_ATTEMPTS = 2


def arbitrate(
    *,
    deal_terms: dict[str, Any],
    milestone: dict[str, Any],
    buyer_claim: str,
    seller_claim: str,
    artifacts: list[dict[str, Any]],
    attestations: list[dict[str, Any]],
) -> ArbitrationOutput:
    provider = get_provider()
    amount = int(milestone.get("amount_paise") or 0)
    user_content = render_arbiter_case(
        deal_terms=deal_terms,
        milestone=milestone,
        buyer_claim=buyer_claim,
        seller_claim=seller_claim,
        artifacts=artifacts,
        attestations=attestations,
    )

    spends: list[SpendRecord] = []
    last_reason: str | None = None
    prompt_hash = ""
    model_id = _model_for("arbitration")
    model_version = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        content = user_content
        if attempt > 1:
            content = (
                user_content
                + "\n\nThe previous recommendation was rejected by a deterministic check: "
                f"{last_reason}. release_paise + refund_paise must equal exactly {amount}."
            )
        try:
            result = provider.parse(
                system_prompt=ARBITER_SYSTEM_PROMPT,
                user_content=content,
                output_format=ArbiterRecommendation,
                model=model_id,
                purpose="arbitration",
            )
        except LLMOutputRejected as exc:
            last_reason = exc.message
            continue
        spends.append(
            SpendRecord(
                purpose="arbitration",
                provider=result.provider,
                model_id=result.model_id,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cache_read_tokens=result.usage.cache_read_input_tokens,
                cache_write_tokens=result.usage.cache_creation_input_tokens,
                cost_micro_usd=cost_micro_usd(result.model_id, result.usage, result.provider),
                latency_ms=result.latency_ms,
            )
        )
        prompt_hash = result.prompt_hash
        model_id = result.model_id
        model_version = result.model_version
        recommendation: ArbiterRecommendation = result.parsed  # type: ignore[assignment]

        if not split_balances(
            amount, int(recommendation.release_paise), int(recommendation.refund_paise)
        ):
            last_reason = (
                f"release {recommendation.release_paise} + refund {recommendation.refund_paise} "
                f"!= milestone amount {amount}"
            )
            log.warning(
                "arbiter output rejected",
                extra={"attempt": attempt, "reason": "SPLIT_DOES_NOT_BALANCE"},
            )
            continue

        expected_outcome = (
            "FULL_RELEASE"
            if recommendation.refund_paise == 0
            else "FULL_REFUND"
            if recommendation.release_paise == 0
            else "PARTIAL"
        )
        if recommendation.outcome != expected_outcome:
            # The label must match the arithmetic; correcting it silently would
            # hide a disagreement a reviewer needs to see.
            last_reason = (
                f"outcome {recommendation.outcome} contradicts the split "
                f"({recommendation.release_paise}/{recommendation.refund_paise})"
            )
            log.warning(
                "arbiter output rejected",
                extra={"attempt": attempt, "reason": "OUTCOME_CONTRADICTS_SPLIT"},
            )
            continue

        log.info(
            "arbiter recommendation",
            extra={
                "outcome": recommendation.outcome,
                "release_paise": recommendation.release_paise,
                "refund_paise": recommendation.refund_paise,
                "confidence": recommendation.confidence,
                "attempt": attempt,
                "provider": result.provider,
            },
        )
        return ArbitrationOutput(
            recommendation=recommendation,
            balanced=True,
            attempts=attempt,
            provider=result.provider,
            model_id=result.model_id,
            model_version=result.model_version,
            prompt_hash=result.prompt_hash,
            spends=spends,
        )

    log.warning("arbiter escalated without a recommendation", extra={"reason": last_reason})
    return ArbitrationOutput(
        recommendation=None,
        balanced=False,
        attempts=MAX_ATTEMPTS,
        provider=provider.name,
        model_id=model_id,
        model_version=model_version,
        prompt_hash=prompt_hash,
        rejection_reason=last_reason or "no valid recommendation produced",
        spends=spends,
    )
