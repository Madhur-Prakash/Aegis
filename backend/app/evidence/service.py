"""Evidence upload, bundling and Merkle assembly."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attest.merkle import leaf_hash, merkle_proof, merkle_root, verify_proof
from app.common.errors import ArtifactRejected, NotFound
from app.common.logging import get_logger
from app.evidence.analyse import analyse
from app.models.commerce import Artifact, EvidenceBundle, Milestone
from app.storage.store import enforce_size, get_store, sniff_content_type

log = get_logger("evidence")


async def get_or_create_open_bundle(
    session: AsyncSession, milestone: Milestone, org_id: uuid.UUID, user_id: uuid.UUID | None
) -> EvidenceBundle:
    stmt = (
        select(EvidenceBundle)
        .where(
            EvidenceBundle.milestone_id == milestone.id,
            EvidenceBundle.submitted_at.is_(None),
        )
        .order_by(EvidenceBundle.created_at.desc())
        .limit(1)
    )
    bundle = (await session.execute(stmt)).scalar_one_or_none()
    if bundle is not None:
        return bundle
    bundle = EvidenceBundle(
        milestone_id=milestone.id,
        org_id=org_id,
        submitted_by_user_id=user_id,
        merkle_root="0" * 64,
    )
    session.add(bundle)
    await session.flush()
    return bundle


async def add_artifact(
    session: AsyncSession,
    bundle: EvidenceBundle,
    *,
    org_id: uuid.UUID,
    artifact_type: str,
    filename: str,
    declared_mime: str,
    data: bytes,
) -> Artifact:
    """Streams to storage, hashes while streaming, and never trusts a client hash."""
    enforce_size(len(data))
    sniffed = sniff_content_type(data, declared_mime, filename)
    store = get_store()
    key = f"{org_id}/{bundle.milestone_id}/{uuid.uuid4()}-{filename[:80]}"
    ref = store.put(key, data, sniffed)

    observation = analyse(data, sniffed)
    if not observation.parseable and sniffed == "application/pdf":
        log.warning(
            "artifact not parseable",
            extra={"storage_key": key, "notes": observation.notes},
        )

    artifact = Artifact(
        bundle_id=bundle.id,
        org_id=org_id,
        artifact_type=artifact_type.upper(),
        filename=filename[:255],
        mime=sniffed,
        storage_key=ref.key,
        size_bytes=ref.size_bytes,
        sha256=ref.sha256,
        extracted_json={
            "declared_mime": declared_mime,
            "sniffed_mime": sniffed,
            "observation": observation.summary(),
        },
    )
    session.add(artifact)
    await session.flush()
    await recompute_root(session, bundle)
    return artifact


async def recompute_root(session: AsyncSession, bundle: EvidenceBundle) -> str:
    artifacts = list(
        (await session.execute(select(Artifact).where(Artifact.bundle_id == bundle.id))).scalars()
    )
    leaves = [
        leaf_hash(
            a.sha256,
            ((a.extracted_json or {}).get("observation") or {}).get("machine_readable_fields", {}),
        )
        for a in artifacts
    ]
    root = merkle_root(leaves) if leaves else "0" * 64
    bundle.merkle_root = root
    await session.flush()
    return root


async def bundle_leaves(session: AsyncSession, bundle_id: uuid.UUID) -> list[tuple[Artifact, str]]:
    artifacts = list(
        (await session.execute(select(Artifact).where(Artifact.bundle_id == bundle_id))).scalars()
    )
    return [
        (
            a,
            leaf_hash(
                a.sha256,
                ((a.extracted_json or {}).get("observation") or {}).get(
                    "machine_readable_fields", {}
                ),
            ),
        )
        for a in artifacts
    ]


async def proof_for_artifact(
    session: AsyncSession, bundle_id: uuid.UUID, artifact_id: uuid.UUID
) -> dict[str, Any]:
    pairs = await bundle_leaves(session, bundle_id)
    leaves = [leaf for _, leaf in pairs]
    target = next((leaf for a, leaf in pairs if a.id == artifact_id), None)
    if target is None:
        raise NotFound(details={"type": "Artifact", "id": str(artifact_id)})
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, target)
    return {
        "artifact_id": str(artifact_id),
        "leaf": target,
        "proof": proof,
        "root": root,
        "valid": verify_proof(target, proof, root),
    }


def verify_external_proof(leaf: str, proof: list[dict[str, str]], root: str) -> dict[str, Any]:
    ok = verify_proof(leaf, proof, root)
    return {"ok": ok, "leaf": leaf, "root": root, "steps": len(proof)}


async def submit_bundle(
    session: AsyncSession, bundle: EvidenceBundle, condition: dict[str, Any]
) -> EvidenceBundle:
    artifacts = list(
        (await session.execute(select(Artifact).where(Artifact.bundle_id == bundle.id))).scalars()
    )
    if not artifacts:
        raise ArtifactRejected(
            code="EMPTY_BUNDLE", message="Add at least one artifact before submitting."
        )
    await recompute_root(session, bundle)
    bundle.submitted_at = dt.datetime.now(dt.UTC)
    await session.flush()
    log.info(
        "evidence submitted",
        extra={
            "bundle_id": str(bundle.id),
            "milestone_id": str(bundle.milestone_id),
            "artifact_count": len(artifacts),
            "merkle_root": bundle.merkle_root,
        },
    )
    return bundle
