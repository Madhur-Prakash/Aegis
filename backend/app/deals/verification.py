"""Orchestration: run the verifier, persist a signed attestation, then let the
deterministic settlement engine decide what happens next.

This module is the seam between the two halves of the product, and the direction
of the arrow is the whole safety argument: it reads the verifier's *output* and
passes a persisted row to the engine.  ``app.agents`` is never given a handle to
anything that can move money.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verifier.pipeline import (
    ArtifactInput,
    VerificationOutput,
    attestation_canonical_payload,
    verify,
)
from app.attest.canonical import payload_hash
from app.attest.eip712 import deal_id_bytes32, sign_attestation
from app.common.errors import Conflict, NotFound
from app.common.logging import get_logger
from app.config.settings import CALIBRATION_VERSION, settings
from app.deals.states import DealEvent, MilestoneEvent, deal_can, milestone_can
from app.events.outbox import deterministic_event_id, enqueue
from app.events.topics import EventType, Topic
from app.evidence.analyse import Observation
from app.ledger.service import append_ledger, transition_deal, transition_milestone
from app.models.commerce import (
    Artifact,
    Attestation,
    ChainAnchor,
    Deal,
    EvidenceBundle,
    Milestone,
)
from app.models.enums import Decision, LedgerEventType, MilestoneState, NotificationKind
from app.models.identity import TokenSpend
from app.settlement.engine import authorize_release
from app.storage.store import get_store

log = get_logger("verification")

VERIFIER_KEY_ID = "verifier-key-01"
# A deterministic development key.  Testnet only, and it is not a secret: it
# exists so a clean clone can sign and verify attestations with no setup.  A real
# deployment sets VERIFIER_PRIVATE_KEY and this constant is never used.
_DEV_VERIFIER_KEY = "0x" + "2c".ljust(64, "7")


def verifier_key() -> str:
    return settings.VERIFIER_PRIVATE_KEY or _DEV_VERIFIER_KEY


def verifier_key_is_dev() -> bool:
    return not settings.VERIFIER_PRIVATE_KEY


async def _artifact_inputs(session: AsyncSession, bundle_id: uuid.UUID) -> list[ArtifactInput]:
    artifacts = list(
        (await session.execute(select(Artifact).where(Artifact.bundle_id == bundle_id))).scalars()
    )
    store = get_store()
    inputs: list[ArtifactInput] = []
    for artifact in artifacts:
        stored = (artifact.extracted_json or {}).get("observation")
        if stored:
            observation = Observation(
                parseable=bool(stored.get("parseable")),
                kind=str(stored.get("kind", "unknown")),
                text=str(stored.get("text_excerpt", "")),
                page_count=int(stored.get("page_count") or 0),
                fields=dict(stored.get("machine_readable_fields") or {}),
                image=dict(stored.get("image_analysis") or {}),
                notes=list(stored.get("notes") or []),
            )
        else:  # a seeded artifact whose analysis was not cached
            from app.evidence.analyse import analyse

            observation = analyse(store.get(artifact.storage_key), artifact.mime)
        inputs.append(
            ArtifactInput(
                artifact_id=str(artifact.id),
                artifact_type=artifact.artifact_type,
                filename=artifact.filename,
                mime=artifact.mime,
                declared_mime=str(
                    (artifact.extracted_json or {}).get("declared_mime") or artifact.mime
                ),
                sha256=artifact.sha256,
                size_bytes=int(artifact.size_bytes),
                observation=observation,
            )
        )
    return inputs


async def _next_attestation_reference(session: AsyncSession) -> str:
    count = int(
        (await session.execute(select(func.count()).select_from(Attestation))).scalar() or 0
    )
    return f"A-{9900 + count + 1}"


async def run_verification(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    bundle: EvidenceBundle,
    *,
    actor: str = "VERIFIER",
) -> tuple[Attestation, VerificationOutput]:
    """Verify -> attest -> (deterministically) authorise.  One transaction."""
    if milestone.state == MilestoneState.VERIFYING:
        raise Conflict(code="VERIFICATION_IN_PROGRESS", message="Verification is already running.")
    if milestone_can(milestone.state, MilestoneEvent.START_VERIFY):
        await transition_milestone(
            session,
            deal,
            milestone,
            MilestoneEvent.START_VERIFY,
            actor=actor,
            reason="verification started",
            payload={"bundle_id": str(bundle.id)},
        )
    elif milestone.state != MilestoneState.VERIFYING:
        from app.common.errors import IllegalTransition

        raise IllegalTransition(
            message=f"Milestone cannot start verification from {milestone.state}.",
            details={"from": str(milestone.state)},
        )

    artifacts = await _artifact_inputs(session, bundle.id)
    condition = milestone.verification_condition_json or {}
    output = verify(condition=condition, artifacts=artifacts)

    # Persist the per-artifact extraction and quality on the artifact rows.
    for artifact_id, extraction in output.extracted.items():
        artifact = await session.get(Artifact, uuid.UUID(artifact_id))
        if artifact is None:
            continue
        artifact.extracted_json = {
            **(artifact.extracted_json or {}),
            "extracted": extraction,
        }
        artifact.extraction_quality = output.extraction_qualities.get(artifact_id)

    for spend in output.spends:
        session.add(
            TokenSpend(
                purpose=spend.purpose,
                provider=spend.provider,
                model_id=spend.model_id,
                input_tokens=spend.input_tokens,
                output_tokens=spend.output_tokens,
                cache_read_tokens=spend.cache_read_tokens,
                cache_write_tokens=spend.cache_write_tokens,
                cost_micro_usd=spend.cost_micro_usd,
                latency_ms=spend.latency_ms,
                outcome=output.decision,
                deal_id=deal.id,
                milestone_id=milestone.id,
            )
        )

    attestation = await persist_attestation(session, deal, milestone, bundle, output, actor=actor)

    # ── the state transition follows the decision, through the table ────
    event = {
        "RELEASE": MilestoneEvent.ATTEST_RELEASE,
        "REJECT": MilestoneEvent.ATTEST_REJECT,
        "ESCALATE": MilestoneEvent.ATTEST_ESCALATE,
    }[output.decision]

    if output.decision == "RELEASE":
        # authorize_release performs the ATTEST_RELEASE transition itself, after
        # re-checking every invariant from the database row.
        await authorize_release(session, deal, milestone, attestation, actor="ENGINE")
    else:
        await transition_milestone(
            session,
            deal,
            milestone,
            event,
            actor=actor,
            reason=output.rationale.get("rule", output.decision),
            payload={
                "attestation_id": str(attestation.id),
                "confidence": float(attestation.confidence),
                "decision": output.decision,
            },
        )

    if deal_can(deal.state, DealEvent.FIRST_EVIDENCE):
        await transition_deal(
            session,
            deal,
            DealEvent.FIRST_EVIDENCE,
            actor=actor,
            reason="first evidence verified",
        )

    await queue_notification(
        session,
        deal=deal,
        milestone=milestone,
        kind=(
            NotificationKind.HUMAN_REVIEW_REQUIRED
            if output.decision == "ESCALATE"
            else NotificationKind.VERIFICATION_COMPLETED
        ),
        payload={
            "decision": output.decision,
            "confidence": float(attestation.confidence),
            "attestation_id": str(attestation.id),
            "unverifiable": [
                v["clause_id"] for v in output.clause_verdicts if v["verdict"] == "UNVERIFIABLE"
            ],
        },
    )
    return attestation, output


async def persist_attestation(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    bundle: EvidenceBundle,
    output: VerificationOutput,
    *,
    actor: str,
) -> Attestation:
    """Canonical JSON -> sha256 -> EIP-712 signature -> row -> queued anchor."""
    canonical = attestation_canonical_payload(
        milestone_id=milestone.id,
        bundle_id=bundle.id,
        evidence_merkle_root=bundle.merkle_root,
        output=output,
    )
    canonical_hash = payload_hash(canonical)
    confidence_bps = round(float(output.confidence) * 10_000)
    signature, signer_address = sign_attestation(
        verifier_key(),
        chain_id=settings.CHAIN_ID,
        verifying_contract=settings.CONTRACT_ADDRESS or None,
        deal_id=str(deal.id),
        seq=int(milestone.seq),
        evidence_root=bundle.merkle_root,
        attestation_hash=canonical_hash,
        decision=output.decision,
        confidence_bps=confidence_bps,
    )

    attestation = Attestation(
        reference=await _next_attestation_reference(session),
        milestone_id=milestone.id,
        bundle_id=bundle.id,
        org_id=deal.org_id_buyer,
        decision=Decision(output.decision),
        confidence=round(float(output.confidence), 3),
        confidence_components_json=output.breakdown.as_json(),
        clause_verdicts_json=output.clause_verdicts,
        reasoning=output.reasoning,
        provider=output.provider,
        model_id=output.model_id,
        model_version=output.model_version,
        prompt_hash=output.prompt_hash,
        evidence_merkle_root=bundle.merkle_root,
        deterministic_prechecks_json=output.prechecks.as_json(),
        thresholds_json={**output.thresholds, "rationale": output.rationale},
        calibration_version=output.breakdown.calibration_version or CALIBRATION_VERSION,
        canonical_hash=canonical_hash,
        signature=signature,
        signer_key_id=VERIFIER_KEY_ID,
        signer_address=signer_address,
    )
    session.add(attestation)
    await session.flush()

    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.ATTESTATION_WRITTEN,
        actor=actor,
        reason=output.decision,
        payload={
            "attestation_id": str(attestation.id),
            "milestone_id": str(milestone.id),
            "decision": output.decision,
            "confidence": float(attestation.confidence),
            "canonical_hash": canonical_hash,
            "evidence_merkle_root": bundle.merkle_root,
            "model_id": output.model_id,
            "provider": output.provider,
            "prompt_hash": output.prompt_hash,
            "signer_address": signer_address,
            "llm_calls": output.llm_calls,
            "resolved_by_prechecks": output.prechecks.resolved,
        },
    )

    anchor = ChainAnchor(
        kind="ATTESTATION",
        deal_id=deal.id,
        milestone_seq=int(milestone.seq),
        attestation_id=attestation.id,
        payload_json={
            "deal_id_b32": deal_id_bytes32(str(deal.id)),
            "seq": int(milestone.seq),
            "evidence_root": bundle.merkle_root,
            "attestation_hash": canonical_hash,
            "decision": output.decision,
            "confidence_bps": confidence_bps,
            "verifier_sig": signature,
        },
    )
    session.add(anchor)
    await session.flush()
    await enqueue(
        session,
        topic=Topic.CHAIN,
        event_type=EventType.CHAIN_ANCHOR_REQUESTED,
        aggregate_type="ChainAnchor",
        aggregate_id=str(anchor.id),
        payload={"anchor_id": str(anchor.id), "deal_id": str(deal.id), "kind": "ATTESTATION"},
        event_id=deterministic_event_id(EventType.CHAIN_ANCHOR_REQUESTED, str(anchor.id)),
    )
    return attestation


async def queue_notification(
    session: AsyncSession,
    *,
    deal: Deal,
    milestone: Milestone | None,
    kind: NotificationKind | str,
    payload: dict[str, Any],
) -> None:
    await enqueue(
        session,
        topic=Topic.NOTIFICATIONS,
        event_type=EventType.NOTIFICATION_REQUESTED,
        aggregate_type="Deal",
        aggregate_id=str(deal.id),
        payload={
            "kind": str(kind),
            "deal_id": str(deal.id),
            "deal_reference": deal.reference,
            "milestone_id": str(milestone.id) if milestone else None,
            "milestone_seq": int(milestone.seq) if milestone else None,
            "org_id_buyer": str(deal.org_id_buyer),
            "org_id_seller": str(deal.org_id_seller),
            **payload,
        },
        event_id=deterministic_event_id(
            EventType.NOTIFICATION_REQUESTED,
            str(deal.id),
            f"{kind}:{milestone.id if milestone else ''}:{dt.datetime.now(dt.UTC).timestamp()}",
        ),
    )


async def latest_bundle_or_404(session: AsyncSession, milestone_id: uuid.UUID) -> EvidenceBundle:
    stmt = (
        select(EvidenceBundle)
        .where(EvidenceBundle.milestone_id == milestone_id)
        .order_by(EvidenceBundle.created_at.desc())
        .limit(1)
    )
    bundle = (await session.execute(stmt)).scalar_one_or_none()
    if bundle is None:
        raise NotFound(details={"type": "EvidenceBundle", "milestone_id": str(milestone_id)})
    return bundle
