"""/api/v1/deals and /api/v1/milestones."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.api.v1.schemas import (
    CancelIn,
    DealIn,
    DealOut,
    FundIn,
    MilestoneOut,
    MoneyOut,
    SignTermsIn,
)
from app.common.deps import MemberDep, RepoDep, SessionDep, ViewerDep
from app.common.errors import NotFound, ValidationFailed
from app.common.redis_client import rate_limit
from app.config.settings import settings
from app.deals import service as deal_service
from app.deals.disputes import review_queue
from app.models.commerce import Attestation, Deal, EvidenceBundle, Milestone
from app.models.identity import Entity, Organization
from app.realtime.hub import get_hub

router = APIRouter(tags=["deals"])


async def _milestone_views(session: SessionDep, deal: Deal) -> list[MilestoneOut]:
    """Milestones are queried, not lazily loaded off the deal: a constructed Deal
    has no loaded collection, and touching one under asyncio raises."""
    milestones = list(
        (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id).order_by(Milestone.seq)
            )
        ).scalars()
    )
    out: list[MilestoneOut] = []
    for milestone in milestones:
        bundle = (
            await session.execute(
                select(EvidenceBundle).where(EvidenceBundle.milestone_id == milestone.id).limit(1)
            )
        ).scalar_one_or_none()
        attestation = (
            await session.execute(
                select(Attestation)
                .where(Attestation.milestone_id == milestone.id)
                .order_by(Attestation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            MilestoneOut(
                id=milestone.id,
                seq=int(milestone.seq),
                title=milestone.title,
                amount_paise=int(milestone.amount_paise),
                state=str(milestone.state),
                verification_condition=milestone.verification_condition_json or {},
                released_at=milestone.released_at,
                has_evidence=bundle is not None,
                attestation_id=attestation.id if attestation else None,
                decision=str(attestation.decision) if attestation else None,
                confidence=float(attestation.confidence) if attestation else None,
            )
        )
    return out


async def _deal_view(session: SessionDep, deal: Deal, org_id: uuid.UUID) -> DealOut:
    buyer = await session.get(Organization, deal.org_id_buyer)
    seller = await session.get(Organization, deal.org_id_seller)
    buyer_entity = await session.get(Entity, deal.buyer_entity_id)
    seller_entity = await session.get(Entity, deal.seller_entity_id)
    money = deal_service.money_view(deal)
    return DealOut(
        id=deal.id,
        reference=deal.reference,
        title=deal.title,
        state=str(deal.state),
        total_paise=int(deal.total_paise),
        money=MoneyOut(**money),
        buyer_org={
            "id": str(deal.org_id_buyer),
            "name": buyer.name if buyer else "",
            "city": buyer.city if buyer else None,
            "entity_id": str(deal.buyer_entity_id),
            "entity_name": buyer_entity.display_name if buyer_entity else "",
        },
        seller_org={
            "id": str(deal.org_id_seller),
            "name": seller.name if seller else "",
            "city": seller.city if seller else None,
            "entity_id": str(deal.seller_entity_id),
            "entity_name": seller_entity.display_name if seller_entity else "",
        },
        terms_hash=deal.terms_hash,
        chain_deal_id=deal.chain_deal_id,
        chain_tx=deal.chain_tx,
        dispute_window_days=int(deal.dispute_window_days),
        risk_score=float(deal.risk_score) if deal.risk_score is not None else None,
        pricing_tier=deal.pricing_tier,
        milestones=await _milestone_views(session, deal),
        created_at=deal.created_at,
        viewer_side="buyer" if deal.org_id_buyer == org_id else "seller",
    )


@router.get("/deals", response_model=list[DealOut])
async def list_deals(
    membership: ViewerDep,
    repo: RepoDep,
    session: SessionDep,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = None,
) -> list[DealOut]:
    deals = await repo.list_deals(limit=limit, cursor=cursor)
    return [await _deal_view(session, d, membership.org_id) for d in deals]


@router.post("/deals", response_model=DealOut, status_code=201)
async def create_deal(payload: DealIn, membership: MemberDep, session: SessionDep) -> DealOut:
    seller_org_id = payload.seller_org_id
    if seller_org_id is None and payload.seller_org_slug:
        org = (
            await session.execute(
                select(Organization).where(Organization.slug == payload.seller_org_slug)
            )
        ).scalar_one_or_none()
        if org is None:
            raise NotFound(details={"type": "Organization", "slug": payload.seller_org_slug})
        seller_org_id = org.id
    if seller_org_id is None:
        raise ValidationFailed(message="Name the seller organization by id or slug.")

    buyer_entity_id = payload.buyer_entity_id
    if buyer_entity_id is None:
        entity = (
            await session.execute(select(Entity).where(Entity.org_id == membership.org_id).limit(1))
        ).scalar_one_or_none()
        if entity is None:
            raise ValidationFailed(message="Create a buyer entity for your organization first.")
        buyer_entity_id = entity.id

    seller_entity_id = payload.seller_entity_id
    if seller_entity_id is None:
        entity = (
            await session.execute(select(Entity).where(Entity.org_id == seller_org_id).limit(1))
        ).scalar_one_or_none()
        if entity is None:
            raise ValidationFailed(message="The seller organization has no trading entity.")
        seller_entity_id = entity.id

    deal = await deal_service.create_deal(
        session,
        buyer_org_id=membership.org_id,
        seller_org_id=seller_org_id,
        buyer_entity_id=buyer_entity_id,
        seller_entity_id=seller_entity_id,
        title=payload.title,
        total_paise=payload.total_paise,
        milestones=[
            {
                "seq": m.seq,
                "title": m.title,
                "amount_paise": m.amount_paise,
                "verification_condition": m.verification_condition.model_dump(),
            }
            for m in payload.milestones
        ],
        dispute_window_days=payload.dispute_window_days,
        category=payload.category,
        tolerance=payload.tolerance,
        actor=f"USER:{membership.user.id}",
    )
    await session.commit()
    await session.refresh(deal)
    return await _deal_view(session, deal, membership.org_id)


@router.get("/deals/demo", response_model=DealOut)
async def demo_deal(membership: ViewerDep, session: SessionDep) -> DealOut:
    """The seeded demo deal, resolved by reference so the URL is stable."""
    stmt = (
        select(Deal)
        .where(
            or_(
                Deal.org_id_buyer == membership.org_id,
                Deal.org_id_seller == membership.org_id,
            )
        )
        .order_by(Deal.created_at)
        .limit(1)
    )
    deal = (await session.execute(stmt)).scalar_one_or_none()
    if deal is None:
        raise NotFound(details={"type": "Deal", "hint": "run make seed"})
    return await _deal_view(session, deal, membership.org_id)


@router.get("/deals/{deal_id}", response_model=DealOut)
async def get_deal(
    deal_id: uuid.UUID, membership: ViewerDep, repo: RepoDep, session: SessionDep
) -> DealOut:
    deal = await repo.get_deal(deal_id)
    return await _deal_view(session, deal, membership.org_id)


@router.post("/deals/{deal_id}/sign-terms", response_model=DealOut)
async def sign_terms(
    deal_id: uuid.UUID,
    payload: SignTermsIn,
    membership: MemberDep,
    repo: RepoDep,
    session: SessionDep,
) -> DealOut:
    deal = await repo.get_deal_for_update(deal_id)
    await deal_service.sign_terms(session, deal, actor=f"USER:{membership.user.id}")
    await session.commit()
    await session.refresh(deal)
    await get_hub().publish("deals", deal.org_id_buyer, "deal.updated", {"deal_id": str(deal.id)})
    await get_hub().publish("deals", deal.org_id_seller, "deal.updated", {"deal_id": str(deal.id)})
    return await _deal_view(session, deal, membership.org_id)


@router.post("/deals/{deal_id}/fund", response_model=DealOut)
async def fund(
    deal_id: uuid.UUID,
    payload: FundIn,
    membership: MemberDep,
    repo: RepoDep,
    session: SessionDep,
) -> DealOut:
    deal = await repo.get_deal_for_update(deal_id)
    if deal.org_id_buyer != membership.org_id:
        raise ValidationFailed(
            code="ONLY_BUYER_FUNDS", message="Only the buyer organization funds the escrow."
        )
    await deal_service.fund_deal(
        session, deal, amount_paise=payload.amount_paise, actor=f"USER:{membership.user.id}"
    )
    await session.commit()
    await session.refresh(deal)
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await get_hub().publish("deals", org, "deal.funded", {"deal_id": str(deal.id)})
    return await _deal_view(session, deal, membership.org_id)


@router.post("/deals/{deal_id}/cancel", response_model=DealOut)
async def cancel(
    deal_id: uuid.UUID,
    payload: CancelIn,
    membership: MemberDep,
    repo: RepoDep,
    session: SessionDep,
) -> DealOut:
    deal = await repo.get_deal_for_update(deal_id)
    await deal_service.cancel_deal(
        session, deal, actor=f"USER:{membership.user.id}", reason=payload.reason
    )
    await session.commit()
    await session.refresh(deal)
    return await _deal_view(session, deal, membership.org_id)


@router.get("/deals/{deal_id}/timeline", response_model=list[dict])
async def timeline(deal_id: uuid.UUID, repo: RepoDep, session: SessionDep) -> list[dict]:
    await repo.get_deal(deal_id)
    return await deal_service.deal_timeline(session, deal_id)


@router.get("/deals/{deal_id}/risk", response_model=dict)
async def deal_risk(deal_id: uuid.UUID, repo: RepoDep, session: SessionDep) -> dict:
    deal = await repo.get_deal(deal_id)
    if deal.risk_factors_json:
        return deal.risk_factors_json
    return await deal_service.score_and_price(session, deal)


# ── Milestones ──────────────────────────────────────────────────────────────
@router.get("/milestones/review-queue", response_model=list[dict])
async def queue(membership: ViewerDep, session: SessionDep) -> list[dict]:
    """Declared before /milestones/{milestone_id} so the literal path wins."""
    return await review_queue(session, membership.org_id)


@router.get("/milestones/{milestone_id}", response_model=MilestoneOut)
async def get_milestone(
    milestone_id: uuid.UUID, repo: RepoDep, session: SessionDep
) -> MilestoneOut:
    milestone = await repo.get_milestone(milestone_id)
    bundle = (
        await session.execute(
            select(EvidenceBundle).where(EvidenceBundle.milestone_id == milestone.id).limit(1)
        )
    ).scalar_one_or_none()
    attestation = (
        await session.execute(
            select(Attestation)
            .where(Attestation.milestone_id == milestone.id)
            .order_by(Attestation.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return MilestoneOut(
        id=milestone.id,
        seq=int(milestone.seq),
        title=milestone.title,
        amount_paise=int(milestone.amount_paise),
        state=str(milestone.state),
        verification_condition=milestone.verification_condition_json or {},
        released_at=milestone.released_at,
        has_evidence=bundle is not None,
        attestation_id=attestation.id if attestation else None,
        decision=str(attestation.decision) if attestation else None,
        confidence=float(attestation.confidence) if attestation else None,
    )


@router.post("/milestones/{milestone_id}/start-verify", response_model=dict)
async def start_verify(
    milestone_id: uuid.UUID, membership: MemberDep, repo: RepoDep, session: SessionDep
) -> dict[str, Any]:
    """Runs the verifier and, if it returns RELEASE, lets the engine authorise."""
    await rate_limit("verify", str(membership.org_id), settings.RATE_LIMIT_VERIFY)
    milestone = await repo.get_milestone(milestone_id)
    deal = await repo.get_deal_for_update(milestone.deal_id)
    from app.deals.verification import latest_bundle_or_404, run_verification

    bundle = await latest_bundle_or_404(session, milestone.id)
    hub = get_hub()
    for stage in ("PRECHECKS", "EXTRACTING", "EVALUATING"):
        await hub.publish(
            "verification",
            deal.org_id_seller,
            "verification.stage",
            {"stage": stage, "milestone_id": str(milestone.id)},
            scope=str(milestone.id),
        )
    attestation, output = await run_verification(session, deal, milestone, bundle, actor="VERIFIER")
    await session.commit()
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await hub.publish(
            "verification",
            org,
            "verification.completed",
            {
                "milestone_id": str(milestone.id),
                "attestation_id": str(attestation.id),
                "decision": output.decision,
                "confidence": float(attestation.confidence),
            },
            scope=str(milestone.id),
        )
        await hub.publish("deals", org, "deal.updated", {"deal_id": str(deal.id)})
    return {
        "attestation_id": str(attestation.id),
        "decision": output.decision,
        "confidence": float(attestation.confidence),
        "milestone_state": str(milestone.state),
        "llm_calls": output.llm_calls,
        "resolved_by_prechecks": output.prechecks.resolved,
        "provider": output.provider,
    }
