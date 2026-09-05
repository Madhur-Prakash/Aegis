"""/api/v1/disputes and human review actions."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.v1.schemas import CounterClaimIn, DisputeIn, HumanReviewIn, ResolveDisputeIn
from app.common.deps import AdminDep, MemberDep, RepoDep, SessionDep, ViewerDep
from app.deals import disputes as dispute_service
from app.models.commerce import Dispute
from app.models.enums import OrgRole
from app.realtime.hub import get_hub

router = APIRouter(tags=["disputes"])


def _dispute_view(dispute: Dispute) -> dict[str, Any]:
    return {
        "id": str(dispute.id),
        "deal_id": str(dispute.deal_id),
        "milestone_id": str(dispute.milestone_id),
        "claim": dispute.claim,
        "counter_claim": dispute.counter_claim,
        "arbiter_recommendation": dispute.arbiter_recommendation_json,
        "human_decision": dispute.human_decision_json,
        "human_decided_by": str(dispute.human_decided_by) if dispute.human_decided_by else None,
        "human_decided_at": dispute.human_decided_at,
        "override_delta_paise": int(dispute.override_delta_paise),
        "resolved_at": dispute.resolved_at,
        "created_at": dispute.created_at,
        # I8, stated in the payload the UI renders.
        "settlement_blocked_until_human_decision": dispute.human_decided_by is None,
    }


@router.post("/milestones/{milestone_id}/human-review", response_model=dict)
async def human_review(
    milestone_id: uuid.UUID,
    payload: HumanReviewIn,
    membership: AdminDep,
    repo: RepoDep,
    session: SessionDep,
) -> dict[str, Any]:
    """APPROVE or REJECT an escalated milestone.  A written reason is mandatory."""
    milestone = await repo.get_milestone(milestone_id)
    deal = await repo.get_deal_for_update(milestone.deal_id)
    result = await dispute_service.human_review(
        session,
        deal,
        milestone,
        action=payload.action,
        reason=payload.reason,
        user_id=membership.user.id,
        actor=f"USER:{membership.user.id}",
        acting_org_id=membership.org_id,
    )
    await session.commit()
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await get_hub().publish(
            "review", org, "review.decided", {"milestone_id": str(milestone_id)}
        )
        await get_hub().publish("deals", org, "deal.updated", {"deal_id": str(deal.id)})
    return result


@router.post("/milestones/{milestone_id}/disputes", response_model=dict, status_code=201)
async def raise_dispute(
    milestone_id: uuid.UUID,
    payload: DisputeIn,
    membership: MemberDep,
    repo: RepoDep,
    session: SessionDep,
) -> dict[str, Any]:
    milestone = await repo.get_milestone(milestone_id)
    deal = await repo.get_deal_for_update(milestone.deal_id)
    dispute = await dispute_service.raise_dispute(
        session,
        deal,
        milestone,
        claim=payload.claim,
        user_id=membership.user.id,
        org_id=membership.org_id,
        actor=f"USER:{membership.user.id}",
    )
    await session.commit()
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await get_hub().publish("review", org, "dispute.raised", {"dispute_id": str(dispute.id)})
    return _dispute_view(dispute)


@router.get("/disputes", response_model=list[dict])
async def list_disputes(membership: ViewerDep, session: SessionDep) -> list[dict[str, Any]]:
    from sqlalchemy import or_

    from app.models.commerce import Deal

    stmt = (
        select(Dispute)
        .join(Deal, Deal.id == Dispute.deal_id)
        .where(or_(Deal.org_id_buyer == membership.org_id, Deal.org_id_seller == membership.org_id))
        .order_by(Dispute.created_at.desc())
    )
    return [_dispute_view(d) for d in (await session.execute(stmt)).scalars()]


@router.get("/disputes/{dispute_id}", response_model=dict)
async def get_dispute(
    dispute_id: uuid.UUID, membership: ViewerDep, session: SessionDep
) -> dict[str, Any]:
    dispute = await dispute_service.require_dispute_or_404(session, dispute_id, membership.org_id)
    return _dispute_view(dispute)


@router.post("/disputes/{dispute_id}/counter-claim", response_model=dict)
async def counter_claim(
    dispute_id: uuid.UUID,
    payload: CounterClaimIn,
    membership: MemberDep,
    session: SessionDep,
) -> dict[str, Any]:
    dispute = await dispute_service.require_dispute_or_404(session, dispute_id, membership.org_id)
    await dispute_service.add_counter_claim(session, dispute, counter_claim=payload.counter_claim)
    await session.commit()
    return _dispute_view(dispute)


@router.post("/disputes/{dispute_id}/arbiter", response_model=dict)
async def run_arbiter(
    dispute_id: uuid.UUID, membership: MemberDep, repo: RepoDep, session: SessionDep
) -> dict[str, Any]:
    """Runs the advisory arbiter.  It cannot move money (I8)."""
    dispute = await dispute_service.require_dispute_or_404(session, dispute_id, membership.org_id)
    milestone = await repo.get_milestone(dispute.milestone_id)
    deal = await repo.get_deal(dispute.deal_id)
    recommendation = await dispute_service.run_arbiter(session, deal, milestone, dispute)
    await session.commit()
    return {"dispute_id": str(dispute_id), "recommendation": recommendation}


@router.post("/disputes/{dispute_id}/resolve", response_model=dict)
async def resolve(
    dispute_id: uuid.UUID,
    payload: ResolveDisputeIn,
    membership: AdminDep,
    repo: RepoDep,
    session: SessionDep,
) -> dict[str, Any]:
    dispute = await dispute_service.require_dispute_or_404(session, dispute_id, membership.org_id)
    milestone = await repo.get_milestone(dispute.milestone_id)
    deal = await repo.get_deal_for_update(dispute.deal_id)
    result = await dispute_service.resolve_dispute(
        session,
        deal,
        milestone,
        dispute,
        release_paise=payload.release_paise,
        refund_paise=payload.refund_paise,
        reason=payload.reason,
        user_id=membership.user.id,
        actor=f"USER:{membership.user.id}",
        membership_can_approve=membership.at_least(OrgRole.ADMIN),
        acting_org_id=membership.org_id,
    )
    await session.commit()
    for org in (deal.org_id_buyer, deal.org_id_seller):
        await get_hub().publish("review", org, "dispute.resolved", {"dispute_id": str(dispute_id)})
        await get_hub().publish("deals", org, "deal.updated", {"deal_id": str(deal.id)})
    return result
