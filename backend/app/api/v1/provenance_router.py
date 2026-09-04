"""/api/v1/verification, /api/v1/provenance, /api/v1/ledger."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.v1.schemas import AttestationOut, ClauseVerdictOut
from app.attest.canonical import payload_hash, sha256_hex
from app.attest.eip712 import verify_signature
from app.chain.adapter import get_chain
from app.common.deps import RepoDep, SessionDep, ViewerDep
from app.common.errors import NotFound
from app.config.settings import settings
from app.ledger.service import replay_balances, verify_chain
from app.models.commerce import Artifact, Attestation, ChainAnchor, Payout

router = APIRouter(tags=["provenance"])


def _matches(onchain: dict[str, Any] | None, expected: Any) -> bool:
    """Whether what is on chain is byte-for-byte the local attestation hash."""
    if not onchain or expected is None:
        return False
    on = str(onchain.get("attestation_hash", "")).removeprefix("0x").lower()
    return on == str(expected).removeprefix("0x").lower()


def _attestation_view(attestation: Attestation) -> AttestationOut:
    return AttestationOut(
        id=attestation.id,
        reference=attestation.reference,
        milestone_id=attestation.milestone_id,
        bundle_id=attestation.bundle_id,
        decision=str(attestation.decision),
        confidence=float(attestation.confidence),
        confidence_components=attestation.confidence_components_json or {},
        clause_verdicts=[
            ClauseVerdictOut(
                clause_id=str(v.get("clause_id")),
                verdict=str(v.get("verdict")),
                required=bool(v.get("required", True)),
                clause_confidence=float(v.get("clause_confidence") or 0.0),
                note=str(v.get("note") or ""),
                evidence_refs=list(v.get("evidence_refs") or []),
                description=str(v.get("description") or ""),
                kind=str(v.get("kind") or ""),
                resolved_by=str(v.get("resolved_by") or ""),
            )
            for v in (attestation.clause_verdicts_json or [])
        ],
        reasoning=attestation.reasoning,
        provider=attestation.provider,
        model_id=attestation.model_id,
        model_version=attestation.model_version,
        prompt_hash=attestation.prompt_hash,
        evidence_merkle_root=attestation.evidence_merkle_root,
        deterministic_prechecks=attestation.deterministic_prechecks_json or {},
        thresholds=attestation.thresholds_json or {},
        calibration_version=attestation.calibration_version,
        canonical_hash=attestation.canonical_hash,
        signature=attestation.signature,
        signer_key_id=attestation.signer_key_id,
        signer_address=attestation.signer_address,
        chain_tx=attestation.chain_tx,
        chain_block=attestation.chain_block,
        created_at=attestation.created_at,
    )


@router.get("/verification/milestones/{milestone_id}", response_model=AttestationOut | None)
async def attestation_for_milestone(
    milestone_id: uuid.UUID, repo: RepoDep, membership: ViewerDep
) -> AttestationOut | None:
    """`null` means "not verified yet"; a milestone you cannot see is a 404.

    Resolving the milestone through the tenant repo first is what separates those
    two cases.  Without it, an org with no relationship to the deal got a 200 and
    a `null` body -- no data, but the wrong status, and indistinguishable from
    "verified nothing yet" for a legitimate caller.
    """
    await repo.get_milestone(milestone_id)
    attestation = await repo.latest_attestation(milestone_id)
    return _attestation_view(attestation) if attestation else None


@router.get("/verification/attestations/{attestation_id}", response_model=AttestationOut)
async def attestation(attestation_id: uuid.UUID, repo: RepoDep) -> AttestationOut:
    return _attestation_view(await repo.get_attestation(attestation_id))


@router.get("/verification/attestations/{attestation_id}/confidence", response_model=dict)
async def confidence_breakdown(attestation_id: uuid.UUID, repo: RepoDep) -> dict[str, Any]:
    attestation = await repo.get_attestation(attestation_id)
    return {
        "confidence": float(attestation.confidence),
        "components": attestation.confidence_components_json,
        "thresholds": attestation.thresholds_json,
        "calibration_version": attestation.calibration_version,
        "decision": str(attestation.decision),
    }


@router.get("/provenance/attestations/{attestation_id}", response_model=dict)
async def provenance(
    attestation_id: uuid.UUID, repo: RepoDep, session: SessionDep
) -> dict[str, Any]:
    """Everything behind one rupee: model, hashes, signer, human approver, chain tx."""
    attestation = await repo.get_attestation(attestation_id)
    milestone = await repo.get_milestone(attestation.milestone_id)
    deal = await repo.get_deal(milestone.deal_id)

    signature_ok = verify_signature(
        attestation.signature,
        attestation.signer_address,
        chain_id=settings.CHAIN_ID,
        verifying_contract=settings.CONTRACT_ADDRESS or None,
        deal_id=str(deal.id),
        seq=int(milestone.seq),
        evidence_root=attestation.evidence_merkle_root,
        attestation_hash=attestation.canonical_hash,
        decision=str(attestation.decision),
        confidence_bps=round(float(attestation.confidence) * 10_000),
    )

    payouts = list(
        (
            await session.execute(
                select(Payout)
                .where(Payout.milestone_id == milestone.id)
                .order_by(Payout.created_at)
            )
        ).scalars()
    )
    anchors = list(
        (
            await session.execute(
                select(ChainAnchor)
                .where(ChainAnchor.attestation_id == attestation.id)
                .order_by(ChainAnchor.created_at)
            )
        ).scalars()
    )
    artifacts = list(
        (
            await session.execute(
                select(Artifact).where(Artifact.bundle_id == attestation.bundle_id)
            )
        ).scalars()
    )
    chain = get_chain()
    return {
        "attestation": _attestation_view(attestation).model_dump(),
        "deal": {
            "id": str(deal.id),
            "reference": deal.reference,
            "terms_hash": deal.terms_hash,
            "chain_deal_id": deal.chain_deal_id,
        },
        "milestone": {
            "id": str(milestone.id),
            "seq": int(milestone.seq),
            "title": milestone.title,
            "amount_paise": int(milestone.amount_paise),
            "state": str(milestone.state),
            "released_at": milestone.released_at,
        },
        "signature_verified": signature_ok,
        "human_approver": next(
            (str(p.authorization_id) for p in payouts if p.status == "SUCCEEDED"),
            None,
        ),
        "payouts": [
            {
                "id": str(p.id),
                "direction": str(p.direction),
                "amount_paise": int(p.amount_paise),
                "rail": p.rail,
                "rail_ref": p.rail_ref,
                "rail_ref_hash": sha256_hex(p.rail_ref or ""),
                "status": str(p.status),
                "created_at": p.created_at,
            }
            for p in payouts
        ],
        "chain": {
            "available": chain.available,
            "reason": chain.state().reason,
            "chain_id": settings.CHAIN_ID,
            "contract_address": settings.CONTRACT_ADDRESS or None,
            "anchors": [
                {
                    "id": str(a.id),
                    "kind": a.kind,
                    "status": a.status,
                    "tx_hash": a.tx_hash,
                    "block_number": a.block_number,
                    "explorer_url": chain.explorer_url(a.tx_hash) if a.tx_hash else None,
                    "attempts": int(a.attempts),
                    "last_error": a.last_error,
                }
                for a in anchors
            ],
        },
        "artifacts": [
            {
                "id": str(a.id),
                "filename": a.filename,
                "artifact_type": a.artifact_type,
                "sha256": a.sha256,
            }
            for a in artifacts
        ],
    }


@router.get("/provenance/deals/{deal_id}/chain", response_model=dict)
async def chain_records(deal_id: uuid.UUID, repo: RepoDep, session: SessionDep) -> dict[str, Any]:
    """Compares each on-chain anchor against the local attestation hash."""
    deal = await repo.get_deal(deal_id)
    anchors = await repo.list_anchors(deal_id)
    chain = get_chain()
    comparisons: list[dict[str, Any]] = []
    for anchor in anchors:
        payload_json: dict[str, Any] = anchor.payload_json or {}
        expected = payload_json.get("attestation_hash")
        onchain = None
        if chain.available and anchor.milestone_seq is not None:
            onchain = chain.read_milestone(deal.chain_deal_id or "", int(anchor.milestone_seq))
        comparisons.append(
            {
                "anchor_id": str(anchor.id),
                "kind": anchor.kind,
                "status": anchor.status,
                "milestone_seq": anchor.milestone_seq,
                "tx_hash": anchor.tx_hash,
                "explorer_url": chain.explorer_url(anchor.tx_hash) if anchor.tx_hash else None,
                "local_attestation_hash": expected,
                "onchain": onchain,
                "matches": _matches(onchain, expected),
            }
        )
    return {
        "deal_id": str(deal_id),
        "chain_deal_id": deal.chain_deal_id,
        "chain_available": chain.available,
        "chain_unavailable_reason": chain.state().reason,
        "anchors": comparisons,
    }


@router.get("/ledger/deals/{deal_id}", response_model=list[dict])
async def ledger(deal_id: uuid.UUID, repo: RepoDep) -> list[dict[str, Any]]:
    events = await repo.list_ledger(deal_id)
    return [
        {
            "seq": int(e.seq),
            "event_type": e.event_type,
            "actor": e.actor,
            "reason": e.reason,
            "payload": e.payload_json,
            "payload_hash": e.payload_hash,
            "prev_hash": e.prev_hash,
            "chain_anchor_tx": e.chain_anchor_tx,
            "created_at": e.created_at,
        }
        for e in events
    ]


@router.get("/ledger/deals/{deal_id}/verify", response_model=dict)
async def ledger_verify(deal_id: uuid.UUID, repo: RepoDep, session: SessionDep) -> dict[str, Any]:
    await repo.get_deal(deal_id)
    result = await verify_chain(session, deal_id)
    result["replayed_balances"] = await replay_balances(session, deal_id)
    return result


@router.post("/provenance/tamper-check", response_model=dict)
async def tamper_check(payload: dict[str, Any]) -> dict[str, Any]:
    """Recomputes a hash over supplied bytes.  The UI's ``TAMPER ONE BYTE`` button
    flips a byte in a local copy and calls this, so the failure is real."""
    import base64

    raw = base64.b64decode(payload.get("content_b64", ""))
    expected = str(payload.get("expected_sha256", "")).removeprefix("0x")
    actual = sha256_hex(raw)
    return {
        "expected_sha256": expected,
        "actual_sha256": actual,
        "ok": bool(expected) and actual == expected,
        "byte_length": len(raw),
        "payload_hash": payload_hash({"sha256": actual}),
    }


@router.get("/provenance/attestations/{attestation_id}/canonical", response_model=dict)
async def canonical(attestation_id: uuid.UUID, repo: RepoDep) -> dict[str, Any]:
    attestation = await repo.get_attestation(attestation_id)
    if attestation is None:
        raise NotFound()
    return {
        "canonical_hash": attestation.canonical_hash,
        "signature": attestation.signature,
        "signer_address": attestation.signer_address,
        "signer_key_id": attestation.signer_key_id,
        "evidence_merkle_root": attestation.evidence_merkle_root,
        "prompt_hash": attestation.prompt_hash,
    }
