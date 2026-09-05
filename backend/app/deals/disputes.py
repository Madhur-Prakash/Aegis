"""Disputes, the advisory arbiter, and human review.

Human review is a first-class workflow.  Every human action requires a mandatory
free-text reason, and the AI recommendation, the human decision, the delta, the
reason, the user and the timestamp are all persisted with a ledger event each.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.arbiter.pipeline import arbitrate
from app.attest.canonical import payload_hash
from app.common.errors import (
    Conflict,
    Forbidden,
    HumanDecisionRequired,
    NotFound,
    ValidationFailed,
)
from app.common.logging import get_logger
from app.deals.states import DealEvent, MilestoneEvent, deal_can, milestone_can
from app.events.outbox import deterministic_event_id, enqueue
from app.events.topics import EventType, Topic
from app.ledger.service import append_ledger, transition_deal, transition_milestone
from app.models.commerce import (
    Artifact,
    Attestation,
    ChainAnchor,
    Deal,
    Dispute,
    EvidenceBundle,
    Milestone,
)
from app.models.enums import (
    DealState,
    Decision,
    HumanAction,
    LedgerEventType,
    MilestoneState,
    NotificationKind,
)
from app.models.identity import TokenSpend
from app.settlement.engine import authorize_dispute_split, authorize_release
from app.settlement.guards import split_balances

log = get_logger("disputes")

MIN_REASON_LENGTH = 12


def _require_reason(reason: str) -> str:
    text = (reason or "").strip()
    if len(text) < MIN_REASON_LENGTH:
        raise ValidationFailed(
            code="REASON_REQUIRED",
            message=f"A written reason of at least {MIN_REASON_LENGTH} characters is required.",
            details={"field": "reason", "min_length": MIN_REASON_LENGTH},
        )
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Human review of an escalated milestone
# ─────────────────────────────────────────────────────────────────────────────
async def human_review(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    *,
    action: HumanAction | str,
    reason: str,
    user_id: uuid.UUID,
    actor: str,
    acting_org_id: uuid.UUID,
) -> dict[str, Any]:
    reason = _require_reason(reason)
    if milestone.state != MilestoneState.UNDER_HUMAN_REVIEW:
        raise Conflict(
            code="MILESTONE_NOT_UNDER_REVIEW",
            message=f"Milestone {milestone.seq} is not awaiting human review.",
            details={"state": str(milestone.state)},
        )
    attestation = await _latest_attestation(session, milestone.id)
    action = HumanAction(str(action))

    # An APPROVE releases escrowed money to the seller, so the seller cannot be
    # the one who signs it off.  The milestone is visible to both parties -- an
    # admin of the *selling* organization could otherwise submit deliberately
    # ambiguous evidence, wait for the verifier to ESCALATE, and then approve
    # their own release with no involvement from the buyer at all.  That is the
    # dishonest-seller path this product exists to close, and I3's guard does
    # not close it: `authorize_release` accepts any ESCALATE from a human.
    # A REJECT moves no money and sends the milestone back for resubmission, so
    # either party may take it.
    if action == HumanAction.APPROVE and acting_org_id != deal.org_id_buyer:
        raise Forbidden(
            code="ONLY_BUYER_APPROVES_RELEASE",
            message="Only the buyer organization can approve a release of escrowed funds.",
            details={"milestone_id": str(milestone.id)},
        )

    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.HUMAN_DECISION,
        actor=actor,
        reason=reason,
        payload={
            "milestone_id": str(milestone.id),
            "action": str(action),
            "decided_by": str(user_id),
            "attestation_id": str(attestation.id),
            "ai_decision": str(attestation.decision),
            "ai_confidence": float(attestation.confidence),
            "unverifiable_clauses": [
                v["clause_id"]
                for v in (attestation.clause_verdicts_json or [])
                if v.get("verdict") == "UNVERIFIABLE"
            ],
        },
    )

    if action == HumanAction.REJECT:
        await transition_milestone(
            session,
            deal,
            milestone,
            MilestoneEvent.HUMAN_REJECT,
            actor=actor,
            reason=reason,
            payload={"decided_by": str(user_id)},
        )
        return {"action": "REJECT", "milestone_state": str(milestone.state), "authorized": False}

    result = await authorize_release(
        session,
        deal,
        milestone,
        attestation,
        actor=actor,
        human_user_id=user_id,
    )
    log.info(
        "human review decided",
        extra={
            "deal_id": str(deal.id),
            "milestone_id": str(milestone.id),
            "action": str(action),
            "settlement_event_id": str(result.authorization.id),
            "user_id": str(user_id),
        },
    )
    return {
        "action": str(action),
        "milestone_state": str(milestone.state),
        "authorized": True,
        "authorization_id": str(result.authorization.id),
        "amount_paise": int(result.authorization.amount_paise),
    }


async def _latest_attestation(session: AsyncSession, milestone_id: uuid.UUID) -> Attestation:
    stmt = (
        select(Attestation)
        .where(Attestation.milestone_id == milestone_id)
        .order_by(Attestation.created_at.desc())
        .limit(1)
    )
    attestation = (await session.execute(stmt)).scalar_one_or_none()
    if attestation is None:
        raise NotFound(
            details={"type": "Attestation", "milestone_id": str(milestone_id)},
        )
    return attestation


# ─────────────────────────────────────────────────────────────────────────────
# Disputes
# ─────────────────────────────────────────────────────────────────────────────
async def raise_dispute(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    *,
    claim: str,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    actor: str,
) -> Dispute:
    claim = _require_reason(claim)
    if not milestone_can(milestone.state, MilestoneEvent.RAISE_DISPUTE):
        raise Conflict(
            code="MILESTONE_NOT_DISPUTABLE",
            message=f"A milestone in {milestone.state} cannot be disputed.",
            details={"state": str(milestone.state)},
        )
    if milestone.state == MilestoneState.SETTLED and milestone.released_at is not None:
        window_ends = milestone.released_at + dt.timedelta(days=int(deal.dispute_window_days))
        if dt.datetime.now(dt.UTC) > window_ends:
            raise Conflict(
                code="DISPUTE_WINDOW_CLOSED",
                message="The dispute window for this milestone has closed.",
                details={"window_ended_at": window_ends.isoformat()},
            )

    dispute = Dispute(
        deal_id=deal.id,
        milestone_id=milestone.id,
        org_id=deal.org_id_buyer,
        raised_by_user_id=user_id,
        claim=claim,
    )
    session.add(dispute)
    await session.flush()

    await transition_milestone(
        session,
        deal,
        milestone,
        MilestoneEvent.RAISE_DISPUTE,
        actor=actor,
        reason="dispute raised",
        payload={"dispute_id": str(dispute.id)},
    )
    if deal_can(deal.state, DealEvent.RAISE_DISPUTE):
        await transition_deal(
            session, deal, DealEvent.RAISE_DISPUTE, actor=actor, reason="dispute raised"
        )
    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.DISPUTE_RAISED,
        actor=actor,
        reason=claim[:400],
        payload={
            "dispute_id": str(dispute.id),
            "milestone_id": str(milestone.id),
            "raised_by": str(user_id),
            "raised_by_org": str(org_id),
        },
    )
    anchor = ChainAnchor(
        kind="RAISE_DISPUTE",
        deal_id=deal.id,
        milestone_seq=int(milestone.seq),
        payload_json={"deal_id_b32": deal.chain_deal_id, "seq": int(milestone.seq)},
    )
    session.add(anchor)
    await session.flush()
    await enqueue(
        session,
        topic=Topic.CHAIN,
        event_type=EventType.CHAIN_ANCHOR_REQUESTED,
        aggregate_type="ChainAnchor",
        aggregate_id=str(anchor.id),
        payload={"anchor_id": str(anchor.id), "deal_id": str(deal.id), "kind": "RAISE_DISPUTE"},
        event_id=deterministic_event_id(EventType.CHAIN_ANCHOR_REQUESTED, str(anchor.id)),
    )
    from app.deals.verification import queue_notification

    await queue_notification(
        session,
        deal=deal,
        milestone=milestone,
        kind=NotificationKind.DISPUTE_RAISED,
        payload={"dispute_id": str(dispute.id), "claim": claim[:200]},
    )
    log.info(
        "dispute raised",
        extra={
            "deal_id": str(deal.id),
            "milestone_id": str(milestone.id),
            "dispute_id": str(dispute.id),
        },
    )
    return dispute


async def add_counter_claim(
    session: AsyncSession, dispute: Dispute, *, counter_claim: str
) -> Dispute:
    dispute.counter_claim = _require_reason(counter_claim)
    await session.flush()
    return dispute


async def run_arbiter(
    session: AsyncSession, deal: Deal, milestone: Milestone, dispute: Dispute
) -> dict[str, Any]:
    """Advisory only.  Nothing here can move money (I8)."""
    bundle_stmt = (
        select(EvidenceBundle)
        .where(EvidenceBundle.milestone_id == milestone.id)
        .order_by(EvidenceBundle.created_at.desc())
        .limit(1)
    )
    bundle = (await session.execute(bundle_stmt)).scalar_one_or_none()
    artifacts: list[dict[str, Any]] = []
    if bundle is not None:
        rows = list(
            (
                await session.execute(select(Artifact).where(Artifact.bundle_id == bundle.id))
            ).scalars()
        )
        for a in rows:
            extracted = (a.extracted_json or {}).get("extracted") or {}
            artifacts.append(
                {
                    "artifact_id": str(a.id),
                    "artifact_type": a.artifact_type,
                    "filename": a.filename,
                    "sha256": a.sha256,
                    "fields": extracted.get("fields")
                    or ((a.extracted_json or {}).get("observation") or {}).get(
                        "machine_readable_fields", {}
                    ),
                    "extraction_quality": a.extraction_quality,
                }
            )

    attestations = [
        {
            "attestation_id": str(row.id),
            "decision": str(row.decision),
            "confidence": float(row.confidence),
            "clause_verdicts": row.clause_verdicts_json,
            "reasoning": row.reasoning,
        }
        for row in (
            await session.execute(
                select(Attestation)
                .where(Attestation.milestone_id == milestone.id)
                .order_by(Attestation.created_at)
            )
        ).scalars()
    ]

    terms = dict(deal.terms_json or {})
    tolerance = dict(terms.get("tolerance") or {})
    output = arbitrate(
        deal_terms={**terms, "tolerance": tolerance},
        milestone={
            "seq": int(milestone.seq),
            "title": milestone.title,
            "amount_paise": int(milestone.amount_paise),
            "verification_condition": milestone.verification_condition_json,
            "unit_count": tolerance.get("total_units"),
        },
        buyer_claim=dispute.claim,
        seller_claim=dispute.counter_claim or "",
        artifacts=artifacts,
        attestations=attestations,
    )
    dispute.arbiter_recommendation_json = output.as_json()
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
                outcome=output.recommendation.outcome if output.recommendation else "REJECTED",
                deal_id=deal.id,
                milestone_id=milestone.id,
            )
        )
    await session.flush()
    return dispute.arbiter_recommendation_json


async def resolve_dispute(
    session: AsyncSession,
    deal: Deal,
    milestone: Milestone,
    dispute: Dispute,
    *,
    release_paise: int,
    refund_paise: int,
    reason: str,
    user_id: uuid.UUID,
    actor: str,
    membership_can_approve: bool,
    acting_org_id: uuid.UUID,
) -> dict[str, Any]:
    """The human decision.  I8: this is the only path that can settle a dispute."""
    if not membership_can_approve:
        raise Forbidden(details={"required_role": "ADMIN"})

    # A resolution that releases anything pays the seller, so the seller cannot
    # be the one taking it.  `REJECTED` is a disputable state, which made this
    # the shortest route around the whole verifier: submit evidence, have it
    # rejected, raise a dispute on your own milestone, and resolve it in your own
    # favour with your own admin.  I8 is satisfied throughout -- `human_decided_by`
    # is set -- because I8 only requires *a* human, not a disinterested one.
    #
    # A resolution that releases nothing is a seller conceding, which pays them
    # nothing and so is not the self-dealing being refused.
    if int(release_paise) > 0 and acting_org_id != deal.org_id_buyer:
        raise Forbidden(
            code="ONLY_BUYER_APPROVES_RELEASE",
            message="Only the buyer organization can resolve a dispute in the seller's favour.",
            details={"dispute_id": str(dispute.id)},
        )

    reason = _require_reason(reason)
    amount = int(milestone.amount_paise)
    if not split_balances(amount, int(release_paise), int(refund_paise)):
        raise ValidationFailed(
            code="SPLIT_DOES_NOT_BALANCE",
            message="The release and refund must sum to the milestone amount exactly.",
            details={
                "release_paise": int(release_paise),
                "refund_paise": int(refund_paise),
                "milestone_amount_paise": amount,
            },
        )
    if dispute.resolved_at is not None:
        raise Conflict(code="DISPUTE_ALREADY_RESOLVED", message="This dispute is resolved.")

    recommendation = dispute.arbiter_recommendation_json or {}
    recommended_release = int(recommendation.get("release_paise") or 0)
    delta = int(release_paise) - recommended_release

    decision = {
        "release_paise": int(release_paise),
        "refund_paise": int(refund_paise),
        "reason": reason,
        "decided_by": str(user_id),
        "decided_at": dt.datetime.now(dt.UTC).isoformat(),
        "ai_recommended_release_paise": recommended_release if recommendation else None,
        "override_delta_paise": delta if recommendation else None,
    }
    dispute.human_decision_json = decision
    dispute.human_decided_by = user_id
    dispute.human_decided_at = dt.datetime.now(dt.UTC)
    dispute.override_delta_paise = delta if recommendation else 0
    dispute.resolved_at = dt.datetime.now(dt.UTC)
    await session.flush()

    await append_ledger(
        session,
        deal_id=deal.id,
        org_id=deal.org_id_buyer,
        event_type=LedgerEventType.DISPUTE_RESOLVED,
        actor=actor,
        reason=reason,
        payload={
            "dispute_id": str(dispute.id),
            "milestone_id": str(milestone.id),
            "human_decision": decision,
            "ai_recommendation": recommendation,
            "override_delta_paise": dispute.override_delta_paise,
        },
    )

    # Back to IN_PROGRESS so the ordinary completion path can finish the deal
    # once every milestone has settled.
    if deal.state == DealState.DISPUTED:
        await transition_deal(
            session,
            deal,
            DealEvent.RESOLVE,
            actor=actor,
            reason=reason,
            target=DealState.IN_PROGRESS,
            payload={"dispute_id": str(dispute.id)},
        )

    attestation = await _latest_attestation(session, milestone.id)
    results = await authorize_dispute_split(
        session,
        deal,
        milestone,
        dispute,
        attestation,
        release_paise=int(release_paise),
        refund_paise=int(refund_paise),
        human_user_id=user_id,
        actor=actor,
    )

    decision_hash = payload_hash(decision)
    anchor = ChainAnchor(
        kind="RESOLVE_DISPUTE",
        deal_id=deal.id,
        milestone_seq=int(milestone.seq),
        payload_json={
            "deal_id_b32": deal.chain_deal_id,
            "seq": int(milestone.seq),
            "release_paise": int(release_paise),
            "refund_paise": int(refund_paise),
            "decision_hash": "0x" + decision_hash,
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
        payload={"anchor_id": str(anchor.id), "deal_id": str(deal.id), "kind": "RESOLVE_DISPUTE"},
        event_id=deterministic_event_id(EventType.CHAIN_ANCHOR_REQUESTED, str(anchor.id)),
    )

    from app.deals.verification import queue_notification

    await queue_notification(
        session,
        deal=deal,
        milestone=milestone,
        kind=NotificationKind.DISPUTE_RESOLVED,
        payload={
            "dispute_id": str(dispute.id),
            "release_paise": int(release_paise),
            "refund_paise": int(refund_paise),
        },
    )
    log.info(
        "dispute resolved",
        extra={
            "deal_id": str(deal.id),
            "dispute_id": str(dispute.id),
            "release_paise": int(release_paise),
            "refund_paise": int(refund_paise),
            "override_delta_paise": dispute.override_delta_paise,
            "user_id": str(user_id),
        },
    )
    return {
        "dispute_id": str(dispute.id),
        "authorizations": [str(r.authorization.id) for r in results],
        "release_paise": int(release_paise),
        "refund_paise": int(refund_paise),
        "override_delta_paise": dispute.override_delta_paise,
        "decision_hash": decision_hash,
    }


async def review_queue(session: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """Escalated milestones plus disputes awaiting a human decision, tenant-scoped."""
    from sqlalchemy import or_

    stmt = (
        select(Milestone, Deal, Attestation)
        .join(Deal, Deal.id == Milestone.deal_id)
        .outerjoin(Attestation, Attestation.milestone_id == Milestone.id)
        .where(
            or_(Deal.org_id_buyer == org_id, Deal.org_id_seller == org_id),
            Milestone.state.in_([MilestoneState.UNDER_HUMAN_REVIEW, MilestoneState.DISPUTED]),
        )
        .order_by(Milestone.created_at)
    )
    rows = list((await session.execute(stmt)).all())
    seen: set[uuid.UUID] = set()
    out: list[dict[str, Any]] = []
    for milestone, deal, attestation in rows:
        if milestone.id in seen:
            continue
        seen.add(milestone.id)
        verdicts = (attestation.clause_verdicts_json if attestation else []) or []
        unverifiable = [v for v in verdicts if v.get("verdict") == "UNVERIFIABLE"]
        dispute = (
            await session.execute(
                select(Dispute)
                .where(Dispute.milestone_id == milestone.id, Dispute.resolved_at.is_(None))
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            {
                "deal_id": str(deal.id),
                "deal_reference": deal.reference,
                "milestone_id": str(milestone.id),
                "milestone_seq": int(milestone.seq),
                "milestone_title": milestone.title,
                "amount_paise": int(milestone.amount_paise),
                "state": str(milestone.state),
                "confidence": float(attestation.confidence) if attestation else None,
                "decision": str(attestation.decision) if attestation else None,
                "attestation_id": str(attestation.id) if attestation else None,
                "could_not_verify": [
                    {"clause_id": v.get("clause_id"), "note": v.get("note")} for v in unverifiable
                ],
                "dispute_id": str(dispute.id) if dispute else None,
                "arbiter_recommendation": dispute.arbiter_recommendation_json if dispute else None,
                "created_at": milestone.created_at,
            }
        )
    return out


async def require_dispute_or_404(
    session: AsyncSession, dispute_id: uuid.UUID, org_id: uuid.UUID
) -> Dispute:
    from sqlalchemy import or_

    stmt = (
        select(Dispute)
        .join(Deal, Deal.id == Dispute.deal_id)
        .where(
            Dispute.id == dispute_id,
            or_(Deal.org_id_buyer == org_id, Deal.org_id_seller == org_id),
        )
    )
    dispute = (await session.execute(stmt)).scalar_one_or_none()
    if dispute is None:
        raise NotFound(details={"type": "Dispute", "id": str(dispute_id)})
    return dispute


async def block_settlement_without_human(dispute: Dispute) -> None:
    if dispute.human_decided_by is None:
        raise HumanDecisionRequired(details={"dispute_id": str(dispute.id)})


def summarise_decision(attestation: Attestation) -> dict[str, Any]:
    return {
        "decision": str(attestation.decision),
        "is_release": attestation.decision == Decision.RELEASE,
        "confidence": float(attestation.confidence),
    }
