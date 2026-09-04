"""verify -> attest -> authorize -> Kafka -> worker -> payout -> ledger, end to end.

This is the test that proves the three sentences the submission rests on.
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.common.errors import (
    HumanDecisionRequired,
    IllegalTransition,
    MoneyInvariantViolation,
    UnverifiableRequiredClause,
    ValidationFailed,
)
from app.db.session import get_session_factory
from app.ledger.service import replay_balances, verify_chain
from app.models.commerce import (
    ChainAnchor,
    Deal,
    LedgerEvent,
    Milestone,
    OutboxEvent,
    Payout,
    SettlementAuthorization,
)
from app.models.enums import (
    AuthorizedBy,
    DealState,
    Decision,
    Direction,
    MilestoneState,
    PayoutStatus,
)
from app.models.identity import Notification, TokenSpend
from tests.conftest import requires_db
from tests.factories import drain_outbox, make_deal, submit_evidence, verify_milestone

pytestmark = requires_db


async def milestone(session: Any, deal: Deal, seq: int) -> Milestone:
    return (
        await session.execute(
            select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == seq)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_milestone_one_releases_and_the_money_bar_conserves(parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        assert deal.state == DealState.FUNDED
        assert deal.funded_paise == 42_000_000
        assert deal.held_paise == 42_000_000
        assert deal.balanced

        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        assert bundle.merkle_root != "0" * 64
        assert bundle.submitted_at is not None

        attestation, output = await verify_milestone(session, deal, m1, bundle)
        assert output.decision == "RELEASE"
        assert attestation.decision == Decision.RELEASE
        assert float(attestation.confidence) >= 0.85
        assert m1.state == MilestoneState.RELEASE_APPROVED

        # I1: an authorization exists and references the attestation.
        authorization = (
            await session.execute(
                select(SettlementAuthorization).where(SettlementAuthorization.milestone_id == m1.id)
            )
        ).scalar_one()
        assert authorization.attestation_id == attestation.id
        assert authorization.authorized_by == AuthorizedBy.ENGINE
        assert authorization.human_approved is False

        # I13: the outbox row committed in the same transaction as the state change.
        outbox = list(
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.topic == "aegis.settlement")
                )
            ).scalars()
        )
        assert len(outbox) == 1
        assert outbox[0].published_at is None

        await drain_outbox(session)
        await session.refresh(deal)
        await session.refresh(m1)

        payout = (
            await session.execute(select(Payout).where(Payout.milestone_id == m1.id))
        ).scalar_one()
        assert payout.status == PayoutStatus.SUCCEEDED
        assert payout.direction == Direction.RELEASE
        assert payout.amount_paise == 12_600_000
        assert payout.rail_ref

        assert m1.state == MilestoneState.SETTLED
        assert m1.released_at is not None
        assert deal.released_paise == 12_600_000
        assert deal.held_paise == 29_400_000
        assert deal.balanced

        # I5: the ledger is intact and replays to the same balances.
        chain = await verify_chain(session, deal.id)
        assert chain["ok"], chain
        replayed = await replay_balances(session, deal.id)
        assert replayed["released_paise"] == deal.released_paise
        assert replayed["funded_paise"] == deal.funded_paise


@pytest.mark.asyncio
async def test_milestone_two_escalates_and_no_money_moves(parties):
    """The demo's most important beat: it did not guess and it did not block."""
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m2 = await milestone(session, deal, 2)
        bundle = await submit_evidence(
            session,
            deal,
            m2,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        _attestation, output = await verify_milestone(session, deal, m2, bundle)

        assert output.decision == "ESCALATE"
        assert m2.state == MilestoneState.UNDER_HUMAN_REVIEW

        unverifiable = [v for v in output.clause_verdicts if v["verdict"] == "UNVERIFIABLE"]
        assert len(unverifiable) == 1
        assert unverifiable[0]["required"] is True
        assert "cannot establish" in unverifiable[0]["note"]
        assert "500" in unverifiable[0]["note"]

        # No money moved, and no authorization was written.
        await drain_outbox(session)
        await session.refresh(deal)
        assert deal.released_paise == 0
        assert deal.held_paise == 42_000_000
        assert deal.balanced
        count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(SettlementAuthorization)
                    .where(SettlementAuthorization.milestone_id == m2.id)
                )
            ).scalar()
            or 0
        )
        assert count == 0

        # A human-review notification exists.
        kinds = {n.kind for n in (await session.execute(select(Notification))).scalars()}
        assert "HUMAN_REVIEW_REQUIRED" in kinds


@pytest.mark.asyncio
async def test_the_engine_refuses_to_release_an_escalated_milestone(parties):
    """I3 has no bypass: the engine re-checks and raises, even when asked
    directly."""
    from app.settlement.engine import authorize_release

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m2 = await milestone(session, deal, 2)
        bundle = await submit_evidence(
            session,
            deal,
            m2,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        attestation, _ = await verify_milestone(session, deal, m2, bundle)

        with pytest.raises(UnverifiableRequiredClause) as exc:
            await authorize_release(session, deal, m2, attestation)
        assert exc.value.code == "UNVERIFIABLE_REQUIRED_CLAUSE"
        assert exc.value.details["unverifiable_required_clauses"]


@pytest.mark.asyncio
async def test_a_human_can_approve_an_escalation_and_it_is_recorded(parties):
    from app.deals.disputes import human_review

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m2 = await milestone(session, deal, 2)
        bundle = await submit_evidence(
            session,
            deal,
            m2,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        _attestation, _ = await verify_milestone(session, deal, m2, bundle)

        result = await human_review(
            session,
            deal,
            m2,
            action="APPROVE",
            reason="Counted 500 units against the packing list on site.",
            user_id=parties["buyer_user_id"],
            actor=f"USER:{parties['buyer_user_id']}",
        )
        await session.commit()
        assert result["authorized"] is True
        assert result["amount_paise"] == 16_800_000

        authorization = (
            await session.execute(
                select(SettlementAuthorization).where(SettlementAuthorization.milestone_id == m2.id)
            )
        ).scalar_one()
        assert authorization.authorized_by == AuthorizedBy.HUMAN
        assert authorization.human_approved is True
        assert authorization.authorized_by_user_id == parties["buyer_user_id"]

        # The human decision is on the record with its reason and the AI's view.
        decision_event = (
            await session.execute(
                select(LedgerEvent)
                .where(
                    LedgerEvent.deal_id == deal.id,
                    LedgerEvent.event_type == "HUMAN_DECISION",
                )
                .limit(1)
            )
        ).scalar_one()
        assert "packing list" in decision_event.reason
        assert decision_event.payload_json["ai_decision"] == "ESCALATE"
        assert decision_event.payload_json["decided_by"] == str(parties["buyer_user_id"])
        assert decision_event.payload_json["unverifiable_clauses"]

        await drain_outbox(session)
        await session.refresh(deal)
        await session.refresh(m2)
        assert m2.state == MilestoneState.SETTLED
        assert deal.released_paise == 16_800_000
        assert deal.balanced


@pytest.mark.asyncio
async def test_a_human_approval_requires_a_written_reason(parties):
    from app.deals.disputes import human_review

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m2 = await milestone(session, deal, 2)
        bundle = await submit_evidence(
            session,
            deal,
            m2,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        await verify_milestone(session, deal, m2, bundle)
        with pytest.raises(ValidationFailed) as exc:
            await human_review(
                session,
                deal,
                m2,
                action="APPROVE",
                reason="ok",
                user_id=parties["buyer_user_id"],
                actor="test",
            )
        assert exc.value.code == "REASON_REQUIRED"


@pytest.mark.asyncio
async def test_the_full_three_milestone_narrative_reconciles(parties):
    """M1 releases, M2 escalates then a human approves, M3 is disputed before it
    settles and the resolved split closes the deal at exactly zero held."""
    from app.deals.disputes import human_review, raise_dispute, resolve_dispute, run_arbiter

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)

        # M1
        m1 = await milestone(session, deal, 1)
        b1 = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        await verify_milestone(session, deal, m1, b1)
        await drain_outbox(session)

        # M2 -> escalate -> human approve
        m2 = await milestone(session, deal, 2)
        b2 = await submit_evidence(
            session,
            deal,
            m2,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        await verify_milestone(session, deal, m2, b2)
        await human_review(
            session,
            deal,
            m2,
            action="APPROVE",
            reason="Counted on site against the carton manifest.",
            user_id=parties["buyer_user_id"],
            actor="test",
        )
        await session.commit()
        await drain_outbox(session)

        # M3 -> verify -> dispute before settlement
        m3 = await milestone(session, deal, 3)
        b3 = await submit_evidence(
            session,
            deal,
            m3,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="delivery",
        )
        await verify_milestone(session, deal, m3, b3)
        await session.refresh(m3)
        assert m3.state == MilestoneState.RELEASE_APPROVED

        dispute = await raise_dispute(
            session,
            deal,
            m3,
            claim="60 of 500 units show colour variance beyond the approved swatch.",
            user_id=parties["buyer_user_id"],
            org_id=parties["buyer_org_id"],
            actor="test",
        )
        await session.commit()
        await session.refresh(m3)
        assert m3.state == MilestoneState.DISPUTED

        # The pending authorization must be refused, not executed.
        await drain_outbox(session)
        await session.refresh(deal)
        assert deal.held_paise == 12_600_000, "money moved while a dispute was open"

        recommendation = await run_arbiter(session, deal, m3, dispute)
        await session.commit()
        assert recommendation["outcome"] == "PARTIAL"
        assert recommendation["release_paise"] + recommendation["refund_paise"] == 12_600_000
        assert recommendation["balanced"] is True
        assert recommendation["advisory_only"] is True
        assert recommendation["open_questions"]

        result = await resolve_dispute(
            session,
            deal,
            m3,
            dispute,
            release_paise=recommendation["release_paise"],
            refund_paise=recommendation["refund_paise"],
            reason="Accepted the arbiter split; the condition report supports it.",
            user_id=parties["buyer_user_id"],
            actor="test",
            membership_can_approve=True,
        )
        await session.commit()
        await drain_outbox(session)
        await session.refresh(deal)
        await session.refresh(m3)

        assert m3.state == MilestoneState.SETTLED
        assert deal.state == DealState.COMPLETED
        assert deal.funded_paise == 42_000_000
        assert deal.released_paise + deal.refunded_paise == 42_000_000
        assert deal.held_paise == 0
        assert deal.balanced

        # Both legs executed.
        payouts = list(
            (await session.execute(select(Payout).where(Payout.milestone_id == m3.id))).scalars()
        )
        directions = {str(p.direction) for p in payouts if p.status == PayoutStatus.SUCCEEDED}
        assert directions == {"RELEASE", "REFUND"}
        assert result["release_paise"] == recommendation["release_paise"]

        chain = await verify_chain(session, deal.id)
        assert chain["ok"], chain


@pytest.mark.asyncio
async def test_a_dispute_cannot_settle_without_a_human(parties):
    """I8, exercised against the engine directly."""
    from app.deals.disputes import raise_dispute
    from app.settlement.engine import authorize_dispute_split

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        attestation, _ = await verify_milestone(session, deal, m1, bundle)
        dispute = await raise_dispute(
            session,
            deal,
            m1,
            claim="a written claim about the goods",
            user_id=parties["buyer_user_id"],
            org_id=parties["buyer_org_id"],
            actor="test",
        )
        await session.commit()
        assert dispute.human_decided_by is None

        with pytest.raises(HumanDecisionRequired):
            await authorize_dispute_split(
                session,
                deal,
                m1,
                dispute,
                attestation,
                release_paise=12_600_000,
                refund_paise=0,
                human_user_id=parties["buyer_user_id"],
                actor="test",
            )


@pytest.mark.asyncio
async def test_a_dispute_split_that_does_not_balance_is_refused(parties):
    from app.deals.disputes import raise_dispute, resolve_dispute

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        await verify_milestone(session, deal, m1, bundle)
        dispute = await raise_dispute(
            session,
            deal,
            m1,
            claim="a written claim about the goods",
            user_id=parties["buyer_user_id"],
            org_id=parties["buyer_org_id"],
            actor="test",
        )
        await session.commit()
        with pytest.raises(ValidationFailed) as exc:
            await resolve_dispute(
                session,
                deal,
                m1,
                dispute,
                release_paise=1_000_000,
                refund_paise=1_000_000,  # != 12,600,000
                reason="a written reason for the split",
                user_id=parties["buyer_user_id"],
                actor="test",
                membership_can_approve=True,
            )
        assert exc.value.code == "SPLIT_DOES_NOT_BALANCE"


@pytest.mark.asyncio
async def test_a_rejected_milestone_can_be_resubmitted(parties):
    """The REJECT -> resubmit path, using evidence that genuinely fails."""

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        # Submitting the production photo set against the fabric milestone omits
        # both required artifact types: a zero-token REJECT.
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        attestation, output = await verify_milestone(session, deal, m1, bundle)
        assert output.decision == "REJECT"
        assert output.prechecks.resolved is True
        assert output.llm_calls == 0, "a missing required artifact must cost zero tokens"
        assert m1.state == MilestoneState.REJECTED

        spends = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TokenSpend)
                    .where(TokenSpend.milestone_id == m1.id)
                )
            ).scalar()
            or 0
        )
        assert spends == 0

        # Resubmit with the right evidence.
        correct = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        attestation2, output2 = await verify_milestone(session, deal, m1, correct)
        assert output2.decision == "RELEASE"
        assert attestation2.id != attestation.id


@pytest.mark.asyncio
async def test_an_attestation_row_is_immutable(parties):
    from sqlalchemy import text

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        attestation, _ = await verify_milestone(session, deal, m1, bundle)
        attestation_id = attestation.id

    async with get_session_factory()() as session:
        with pytest.raises(Exception) as exc:
            await session.execute(
                text("UPDATE attestations SET confidence = 0.99 WHERE id = :id"),
                {"id": attestation_id},
            )
            await session.commit()
        assert "append-only" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_the_attestation_records_full_provenance(parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        attestation, _output = await verify_milestone(session, deal, m1, bundle)

        assert attestation.model_id
        assert attestation.model_version
        assert len(attestation.prompt_hash) == 64
        assert attestation.evidence_merkle_root == bundle.merkle_root
        assert len(attestation.canonical_hash) == 64
        assert attestation.signature.startswith("0x")
        assert attestation.signer_address.startswith("0x")
        assert attestation.signer_key_id == "verifier-key-01"
        assert attestation.calibration_version
        assert attestation.thresholds_json["release"] == 0.85
        assert attestation.thresholds_json["reject"] == 0.35
        assert attestation.confidence_components_json["formula"]
        assert attestation.deterministic_prechecks_json["total"] > 0

        # The signature verifies against the recorded signer.
        from app.attest.eip712 import verify_signature
        from app.config.settings import settings

        assert verify_signature(
            attestation.signature,
            attestation.signer_address,
            chain_id=settings.CHAIN_ID,
            verifying_contract=settings.CONTRACT_ADDRESS or None,
            deal_id=str(deal.id),
            seq=int(m1.seq),
            evidence_root=attestation.evidence_merkle_root,
            attestation_hash=attestation.canonical_hash,
            decision=str(attestation.decision),
            confidence_bps=round(float(attestation.confidence) * 10_000),
        )


@pytest.mark.asyncio
async def test_a_chain_anchor_is_queued_and_carries_only_hashes(parties):
    """I7: nothing but hashes, ids, integers and a signature reaches the chain."""
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        attestation, _ = await verify_milestone(session, deal, m1, bundle)
        await drain_outbox(session)

        anchors = list(
            (
                await session.execute(select(ChainAnchor).where(ChainAnchor.deal_id == deal.id))
            ).scalars()
        )
        assert anchors
        attestation_anchor = next(a for a in anchors if a.kind == "ATTESTATION")
        payload = attestation_anchor.payload_json
        assert payload["attestation_hash"] == attestation.canonical_hash
        assert payload["evidence_root"] == bundle.merkle_root
        assert isinstance(payload["confidence_bps"], int)

        # No prose anywhere in any anchor payload.
        import json as _json

        blob = _json.dumps([a.payload_json for a in anchors])
        for forbidden in (
            "Sri Textiles",
            "Meridian",
            "Tirupur",
            "invoice-ct240",
            "@",
            "cannot establish",
        ):
            assert forbidden not in blob, f"{forbidden!r} reached a chain payload"

        settlement = next((a for a in anchors if a.kind == "RECORD_SETTLEMENT"), None)
        if settlement is not None:
            # The rail reference is hashed, never sent in the clear.
            payout = (
                await session.execute(select(Payout).where(Payout.milestone_id == m1.id))
            ).scalar_one()
            assert payout.rail_ref not in _json.dumps(settlement.payload_json)


@pytest.mark.asyncio
async def test_an_illegal_transition_raises_and_writes_nothing(parties):
    from app.deals.states import MilestoneEvent
    from app.ledger.service import transition_milestone

    async def ledger_count(session: Any, deal_id: uuid.UUID) -> int:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(LedgerEvent)
                    .where(LedgerEvent.deal_id == deal_id)
                )
            ).scalar()
            or 0
        )

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        # Plain values, captured before the rollback: a rollback expires every
        # instance, and touching an expired attribute afterwards would emit IO
        # outside the async context.
        deal_id, milestone_id = deal.id, m1.id
        before = await ledger_count(session, deal_id)

        with pytest.raises(IllegalTransition) as exc:
            await transition_milestone(
                session, deal, m1, MilestoneEvent.SETTLE, actor="test", reason="nope"
            )
        assert exc.value.code == "ILLEGAL_TRANSITION"
        await session.rollback()

    async with get_session_factory()() as session:
        assert await ledger_count(session, deal_id) == before
        reloaded = (
            await session.execute(select(Milestone).where(Milestone.id == milestone_id))
        ).scalar_one()
        assert reloaded.state == MilestoneState.PENDING


@pytest.mark.asyncio
async def test_funding_more_than_the_total_is_refused(parties):
    from app.deals import service as deal_service

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties, fund=False)
        with pytest.raises(MoneyInvariantViolation):
            await deal_service.fund_deal(session, deal, amount_paise=99_999_999, actor="test")


@pytest.mark.asyncio
async def test_milestones_must_sum_to_the_total(parties):
    from app.deals import service as deal_service

    async with get_session_factory()() as session:
        with pytest.raises(MoneyInvariantViolation):
            await deal_service.create_deal(
                session,
                buyer_org_id=parties["buyer_org_id"],
                seller_org_id=parties["seller_org_id"],
                buyer_entity_id=parties["buyer_entity_id"],
                seller_entity_id=parties["seller_entity_id"],
                title="mismatched",
                total_paise=1000,
                milestones=[
                    {
                        "seq": 1,
                        "title": "m",
                        "amount_paise": 999,
                        "verification_condition": {"clauses": []},
                    }
                ],
            )


@pytest.mark.asyncio
async def test_every_transition_writes_exactly_one_ledger_event(parties):
    """I5.  Counted per transition, not in aggregate."""
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties, fund=False)
        transitions = [
            e
            for e in (
                await session.execute(
                    select(LedgerEvent)
                    .where(LedgerEvent.deal_id == deal.id)
                    .order_by(LedgerEvent.seq)
                )
            ).scalars()
            if e.event_type == "DEAL_TRANSITION"
        ]
        # create -> sign_terms is the only transition so far.
        assert len(transitions) == 1
        assert transitions[0].payload_json["event"] == "sign_terms"
        assert transitions[0].prev_hash != "0" * 64  # DEAL_CREATED came first


@pytest.mark.asyncio
async def test_the_ledger_is_hash_chained_from_genesis(parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        events = list(
            (
                await session.execute(
                    select(LedgerEvent)
                    .where(LedgerEvent.deal_id == deal.id)
                    .order_by(LedgerEvent.seq)
                )
            ).scalars()
        )
        assert events[0].prev_hash == "0" * 64
        assert len(events) >= 2
        for previous, current in itertools.pairwise(events):
            assert current.prev_hash == previous.payload_hash


@pytest.mark.asyncio
async def test_risk_scoring_produces_a_tier_and_plain_language_factors(parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties, fund=False)
        assessment = deal.risk_factors_json
        assert 0.0 <= assessment["risk_score"] <= 1.0
        assert assessment["pricing"]["tier"]
        assert len(assessment["top_factors"]) == 3
        for factor in assessment["top_factors"]:
            assert factor["plain_language"]
            assert factor["sign"] in {"+", "-"}
            assert factor["direction"] in {"increases", "decreases"}
        assert assessment["score_version"]


@pytest.mark.asyncio
async def test_token_spend_is_recorded_for_every_ai_call(parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = await milestone(session, deal, 1)
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        _, output = await verify_milestone(session, deal, m1, bundle)
        spends = list(
            (
                await session.execute(select(TokenSpend).where(TokenSpend.milestone_id == m1.id))
            ).scalars()
        )
        assert len(spends) == output.llm_calls > 0
        for spend in spends:
            assert spend.model_id
            assert spend.provider
            assert spend.input_tokens > 0
            assert spend.latency_ms >= 0
            assert spend.outcome == output.decision
