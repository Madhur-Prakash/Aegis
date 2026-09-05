"""/api/v1/evidence."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from app.api.v1.schemas import ArtifactOut, BundleOut, VerifyProofIn
from app.common.deps import MemberDep, RepoDep, SessionDep, ViewerDep
from app.common.errors import ArtifactRejected, Conflict, Forbidden
from app.common.redis_client import rate_limit
from app.config.settings import settings
from app.db.repo import TenantRepo
from app.deals.states import MilestoneEvent, milestone_can
from app.evidence import service as evidence_service
from app.ledger.service import append_ledger, transition_milestone
from app.models.commerce import Artifact, Deal, EvidenceBundle
from app.models.enums import ArtifactType, LedgerEventType, NotificationKind
from app.realtime.hub import get_hub
from app.storage.store import get_store, verify_presigned

router = APIRouter(prefix="/evidence", tags=["evidence"])

# How much of an upload is read into memory before it is refused.  One byte over
# the cap is enough to know the file is too large, and reading only that much is
# the difference between a 422 and a process that buffers whatever the client
# felt like sending.
_UPLOAD_READ_CEILING = settings.MAX_ARTIFACT_BYTES + 1


async def _require_selling_org(repo: TenantRepo, deal_id: uuid.UUID, org_id: uuid.UUID) -> Deal:
    """Only the seller may put artifacts in a milestone's evidence bundle.

    The milestone is visible to both parties, and the open bundle is shared:
    ``get_or_create_open_bundle`` returns whichever unsubmitted bundle exists for
    the milestone regardless of who is asking.  So without this the *buyer* could
    add an artifact to the seller's bundle -- a fabricated invoice whose totals
    do not add up, say -- and the evidence-integrity pre-check would turn it into
    a required UNVERIFIABLE clause that by I3 can never auto-release.  That is a
    buyer veto of a release, which docs/SECURITY.md says does not exist.
    """
    deal = await repo.get_deal(deal_id)
    if org_id != deal.org_id_seller:
        raise Forbidden(
            code="ONLY_SELLER_SUBMITS_EVIDENCE",
            message="Only the selling organization can add evidence to this milestone.",
            details={"deal_id": str(deal.id)},
        )
    return deal


def _artifact_view(artifact: Artifact) -> ArtifactOut:
    payload = artifact.extracted_json or {}
    extracted = payload.get("extracted") or {}
    observation = payload.get("observation") or {}
    fields = extracted.get("fields") or observation.get("machine_readable_fields") or {}
    return ArtifactOut(
        id=artifact.id,
        artifact_type=artifact.artifact_type,
        filename=artifact.filename,
        mime=artifact.mime,
        size_bytes=int(artifact.size_bytes),
        sha256=artifact.sha256,
        extraction_quality=artifact.extraction_quality,
        extracted_fields=fields,
        unreadable_fields=extracted.get("unreadable_fields") or [],
        download_url=get_store().presign_get(artifact.storage_key, 600),
        created_at=artifact.created_at,
    )


async def _bundle_view(session: SessionDep, bundle: EvidenceBundle) -> BundleOut:
    artifacts = list(
        (await session.execute(select(Artifact).where(Artifact.bundle_id == bundle.id))).scalars()
    )
    return BundleOut(
        id=bundle.id,
        milestone_id=bundle.milestone_id,
        merkle_root=bundle.merkle_root,
        submitted_at=bundle.submitted_at,
        artifacts=[_artifact_view(a) for a in artifacts],
    )


@router.get("/milestones/{milestone_id}/bundle", response_model=BundleOut | None)
async def get_bundle(
    milestone_id: uuid.UUID, repo: RepoDep, session: SessionDep, membership: ViewerDep
) -> BundleOut | None:
    """`null` means "no evidence yet"; a milestone you cannot see is a 404.

    See the note on `attestation_for_milestone`: the milestone is resolved through
    the tenant repo so those two cases are not both 200.
    """
    await repo.get_milestone(milestone_id)
    bundle = await repo.latest_bundle(milestone_id)
    if bundle is None:
        return None
    return await _bundle_view(session, bundle)


@router.post("/milestones/{milestone_id}/upload", response_model=ArtifactOut, status_code=201)
async def upload(
    milestone_id: uuid.UUID,
    membership: MemberDep,
    repo: RepoDep,
    session: SessionDep,
    artifact_type: str = Form(...),
    file: UploadFile = File(...),
) -> ArtifactOut:
    await rate_limit("upload", str(membership.org_id), settings.RATE_LIMIT_UPLOAD)
    if artifact_type.upper() not in {t.value for t in ArtifactType}:
        raise ArtifactRejected(
            code="UNKNOWN_ARTIFACT_TYPE",
            message="That artifact type is not recognised.",
            details={"allowed": [t.value for t in ArtifactType]},
        )
    milestone = await repo.get_milestone(milestone_id)
    await _require_selling_org(repo, milestone.deal_id, membership.org_id)
    # Bounded read: `enforce_size` further down runs *after* the bytes are already
    # in memory, so an unbounded `file.read()` let anyone with an account decide
    # how much of the process's memory to consume with a single multipart body.
    data = await file.read(_UPLOAD_READ_CEILING)
    if len(data) > settings.MAX_ARTIFACT_BYTES:
        raise ArtifactRejected(
            code="FILE_TOO_LARGE",
            message="The file exceeds the maximum size.",
            details={"max_bytes": settings.MAX_ARTIFACT_BYTES},
        )
    bundle = await evidence_service.get_or_create_open_bundle(
        session, milestone, membership.org_id, membership.user.id
    )
    artifact = await evidence_service.add_artifact(
        session,
        bundle,
        org_id=membership.org_id,
        artifact_type=artifact_type,
        filename=file.filename or "artifact",
        declared_mime=file.content_type or "application/octet-stream",
        data=data,
    )
    await session.commit()
    return _artifact_view(artifact)


@router.post("/milestones/{milestone_id}/submit", response_model=BundleOut)
async def submit(
    milestone_id: uuid.UUID, membership: MemberDep, repo: RepoDep, session: SessionDep
) -> BundleOut:
    milestone = await repo.get_milestone(milestone_id)
    await _require_selling_org(repo, milestone.deal_id, membership.org_id)
    deal = await repo.get_deal_for_update(milestone.deal_id)
    bundle = await repo.latest_bundle(milestone_id)
    if bundle is None:
        raise Conflict(code="NO_BUNDLE", message="Upload at least one artifact first.")
    await evidence_service.submit_bundle(
        session, bundle, milestone.verification_condition_json or {}
    )
    event = (
        MilestoneEvent.SUBMIT_EVIDENCE
        if milestone_can(milestone.state, MilestoneEvent.SUBMIT_EVIDENCE)
        else MilestoneEvent.RESUBMIT
    )
    await transition_milestone(
        session,
        deal,
        milestone,
        event,
        actor=f"USER:{membership.user.id}",
        reason="evidence bundle submitted",
        payload={"bundle_id": str(bundle.id), "merkle_root": bundle.merkle_root},
    )
    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.EVIDENCE_SUBMITTED,
        actor=f"USER:{membership.user.id}",
        reason="evidence bundle submitted",
        payload={
            "bundle_id": str(bundle.id),
            "milestone_id": str(milestone.id),
            "merkle_root": bundle.merkle_root,
        },
    )
    from app.deals.verification import queue_notification

    await queue_notification(
        session,
        deal=deal,
        milestone=milestone,
        kind=NotificationKind.EVIDENCE_SUBMITTED,
        payload={"bundle_id": str(bundle.id)},
    )
    await session.commit()
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await get_hub().publish("deals", org, "evidence.submitted", {"deal_id": str(deal.id)})
    return await _bundle_view(session, bundle)


@router.get("/artifacts/{artifact_id}/proof", response_model=dict)
async def proof(
    artifact_id: uuid.UUID, repo: RepoDep, session: SessionDep, membership: ViewerDep
) -> dict:
    artifact = await repo.get_artifact(artifact_id)
    return await evidence_service.proof_for_artifact(session, artifact.bundle_id, artifact.id)


@router.get("/download/{token}")
async def download(token: str) -> Response:
    """Short-lived presigned download.  The token carries an HMAC and an expiry;
    there is no public path to an artifact."""
    key = verify_presigned(token)
    data = get_store().get(key)
    # `text/plain` is an accepted artifact type, so an artifact can hold markup.
    # The API is same-origin with the app through the Next rewrite, so a browser
    # that sniffed one of these into HTML would be running script on the app's
    # own origin.  Declare the type and refuse the sniff.
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/verify", response_model=dict)
async def verify_proof(payload: VerifyProofIn) -> dict:
    """Public Merkle verification: ``(leaf, proof, root)``.  Used by the tamper demo."""
    return evidence_service.verify_external_proof(
        payload.leaf.removeprefix("0x"),
        [{"position": s.position, "hash": s.hash.removeprefix("0x")} for s in payload.proof],
        payload.root.removeprefix("0x"),
    )
