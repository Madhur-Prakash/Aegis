"""Helpers that drive the real services, so tests exercise production paths."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.deals import service as deal_service
from app.deals.verification import run_verification
from app.evidence import service as evidence_service
from app.models.commerce import Deal, EvidenceBundle, Milestone

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"
DEMO_EVIDENCE = FIXTURES / "demo_evidence"


def demo_fixture() -> dict[str, Any]:
    import json

    return json.loads((FIXTURES / "demo_deal.json").read_text(encoding="utf-8"))


async def make_deal(
    session: AsyncSession,
    parties: dict[str, Any],
    *,
    total_paise: int = 42_000_000,
    milestones: list[dict[str, Any]] | None = None,
    fund: bool = True,
) -> Deal:
    fixture = demo_fixture()
    ms = milestones or [
        {
            "seq": m["seq"],
            "title": m["title"],
            "amount_paise": m["amount_paise"],
            "verification_condition": m["verification_condition"],
        }
        for m in fixture["milestones"]
    ]
    deal = await deal_service.create_deal(
        session,
        buyer_org_id=parties["buyer_org_id"],
        seller_org_id=parties["seller_org_id"],
        buyer_entity_id=parties["buyer_entity_id"],
        seller_entity_id=parties["seller_entity_id"],
        title=fixture["title"],
        total_paise=total_paise,
        milestones=ms,
        dispute_window_days=fixture["dispute_window_days"],
        category=fixture["category"],
        tolerance=fixture["tolerance"],
        actor="TEST",
    )
    await deal_service.sign_terms(session, deal, actor="TEST")
    if fund:
        await deal_service.fund_deal(session, deal, actor="TEST")
    await session.commit()
    await session.refresh(deal)
    return deal


async def submit_evidence(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    folder: str,
) -> EvidenceBundle:
    """Uploads the demo fixture's real PDFs and PNGs through the real service."""
    import json

    manifest = json.loads((DEMO_EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    bundle = await evidence_service.get_or_create_open_bundle(session, milestone, org_id, user_id)
    for entry in manifest[folder]:
        data = (DEMO_EVIDENCE / folder / entry["filename"]).read_bytes()
        await evidence_service.add_artifact(
            session,
            bundle,
            org_id=org_id,
            artifact_type=entry["artifact_type"],
            filename=entry["filename"],
            declared_mime=entry["mime"],
            data=data,
        )
    await evidence_service.submit_bundle(
        session, bundle, milestone.verification_condition_json or {}
    )
    from app.deals.states import MilestoneEvent, milestone_can
    from app.ledger.service import transition_milestone

    # Mirrors the evidence router: a first submission is SUBMIT_EVIDENCE, and a
    # submission after a REJECT is RESUBMIT.
    event = (
        MilestoneEvent.SUBMIT_EVIDENCE
        if milestone_can(milestone.state, MilestoneEvent.SUBMIT_EVIDENCE)
        else MilestoneEvent.RESUBMIT
    )
    if milestone_can(milestone.state, event):
        await transition_milestone(
            session,
            deal,
            milestone,
            event,
            actor="TEST",
            reason="evidence submitted",
            payload={"bundle_id": str(bundle.id)},
        )
    await session.commit()
    return bundle


async def verify_milestone(
    session: AsyncSession, deal: Deal, milestone: Milestone, bundle: EvidenceBundle
) -> tuple[Any, Any]:
    attestation, output = await run_verification(session, deal, milestone, bundle, actor="TEST")
    await session.commit()
    return attestation, output


async def drain_outbox(session: AsyncSession) -> int:
    """Publishes the outbox to the in-process bus and runs the handlers, which is
    exactly what relay.py + worker.py do in production."""
    from app.relay import relay_once
    from app.worker import drain_memory_bus

    await session.commit()
    handled = 0
    for _ in range(6):
        published = await relay_once()
        processed = await drain_memory_bus()
        handled += processed
        if published == 0 and processed == 0:
            break
    return handled
