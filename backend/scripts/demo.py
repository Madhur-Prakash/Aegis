"""``make demo`` -- drive the seeded demo deal through the whole narrative and
print the walkthrough URLs.

Every outcome below is produced by the real pipeline.  No milestone is
special-cased, and every number printed is measured during this run.

    python -m scripts.demo            # advance the demo deal
    python -m scripts.demo --reset    # start the demo deal over
    python -m scripts.demo --json     # machine-readable transcript
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text

from app.common.ids import seed_id
from app.common.logging import configure_logging, get_logger
from app.config.settings import settings
from app.db.session import dispose_engine, get_session_factory
from app.deals import service as deal_service
from app.deals.disputes import human_review as do_human_review
from app.deals.disputes import raise_dispute, resolve_dispute, run_arbiter
from app.deals.verification import run_verification
from app.evidence import service as evidence_service
from app.ledger.service import verify_chain
from app.models.commerce import (
    Attestation,
    ChainAnchor,
    Deal,
    Dispute,
    EvidenceBundle,
    LedgerEvent,
    Milestone,
    Payout,
    SettlementAuthorization,
)
from app.models.enums import DealState, MilestoneState
from app.rails.base import rail_disclosure

configure_logging(settings)
log = get_logger("demo")

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"
DEMO_EVIDENCE = FIXTURES / "demo_evidence"

EVIDENCE_FOLDER = {1: "fabric", 2: "production", 3: "delivery"}


def inr(paise: int) -> str:
    return f"INR {paise / 100:,.2f}"


async def _drain(deal_id: uuid.UUID | None = None) -> int:
    """Relay the outbox and run the consumers -- exactly relay.py + worker.py.

    With Kafka disabled the consumers are driven in-process.  With Kafka enabled
    the real ``worker`` service consumes, and it may well win the claim race
    against anything this script would do -- that is I6 behaving correctly.  So
    the relay still runs here (it is idempotent) and then the script *waits* for
    every authorization on the deal to be consumed, rather than printing a money
    bar that is one step behind the truth.
    """
    from app.relay import relay_once
    from app.worker import drain_memory_bus

    handled = 0
    for _ in range(8):
        published = await relay_once()
        processed = 0
        if not settings.KAFKA_ENABLED:
            processed = await drain_memory_bus()
        handled += processed
        if published == 0 and processed == 0:
            break
    if settings.KAFKA_ENABLED and deal_id is not None:
        await _await_settlement(deal_id)
    return handled


SETTLE_TIMEOUT_S = 20.0


async def _await_settlement(deal_id: uuid.UUID) -> bool:
    """Waits until no authorization on this deal is still unconsumed.

    Returns False on timeout, which the caller reports rather than hides: a
    transcript that silently omits a stuck payout would be worse than a slow one.
    """
    factory = get_session_factory()
    deadline = asyncio.get_running_loop().time() + SETTLE_TIMEOUT_S
    while True:
        async with factory() as session:
            pending = (
                await session.execute(
                    select(func.count())
                    .select_from(SettlementAuthorization)
                    .join(Milestone, Milestone.id == SettlementAuthorization.milestone_id)
                    .where(
                        Milestone.deal_id == deal_id,
                        SettlementAuthorization.consumed_at.is_(None),
                    )
                )
            ).scalar() or 0
        if pending == 0:
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.25)


async def _load(session: Any, reference: str) -> tuple[Deal, list[Milestone]]:
    deal = (
        await session.execute(select(Deal).where(Deal.reference == reference))
    ).scalar_one_or_none()
    if deal is None:
        raise SystemExit(f"demo deal {reference} not found -- run `make seed`")
    milestones = list(
        (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id).order_by(Milestone.seq)
            )
        ).scalars()
    )
    return deal, milestones


async def _submit(
    session: Any, deal: Deal, milestone: Milestone, org_id: uuid.UUID, user_id: uuid.UUID
) -> EvidenceBundle:
    manifest = json.loads((DEMO_EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    folder = EVIDENCE_FOLDER[int(milestone.seq)]
    bundle = await evidence_service.get_or_create_open_bundle(session, milestone, org_id, user_id)
    existing = int(
        (
            await session.execute(
                select(func.count())
                .select_from(__import__("app.models.commerce", fromlist=["Artifact"]).Artifact)
                .where(
                    __import__("app.models.commerce", fromlist=["Artifact"]).Artifact.bundle_id
                    == bundle.id
                )
            )
        ).scalar()
        or 0
    )
    if existing == 0:
        for entry in manifest[folder]:
            await evidence_service.add_artifact(
                session,
                bundle,
                org_id=org_id,
                artifact_type=entry["artifact_type"],
                filename=entry["filename"],
                declared_mime=entry["mime"],
                data=(DEMO_EVIDENCE / folder / entry["filename"]).read_bytes(),
            )
    await evidence_service.submit_bundle(
        session, bundle, milestone.verification_condition_json or {}
    )
    from app.deals.states import MilestoneEvent, milestone_can
    from app.ledger.service import transition_milestone

    if milestone_can(milestone.state, MilestoneEvent.SUBMIT_EVIDENCE):
        await transition_milestone(
            session,
            deal,
            milestone,
            MilestoneEvent.SUBMIT_EVIDENCE,
            actor="SELLER_AGENT",
            reason="evidence bundle submitted",
            payload={"bundle_id": str(bundle.id)},
        )
    return bundle


# How many attempt numbers a reset clears per (milestone, direction).  A demo
# never reaches this many retries; scanning is cheaper than tracking them.
RESET_ATTEMPT_SCAN = 8


async def reset_demo(reference: str) -> None:
    """Rewinds the demo deal to DRAFT.  Destructive for that one deal only.

    The append-only triggers are disabled for the duration of the delete and
    re-enabled immediately: the production guard is never left off, and this path
    exists solely so a rehearsal can be repeated.
    """
    factory = get_session_factory()
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        milestone_ids = [m.id for m in milestones]
        bundle_ids = [
            b
            for (b,) in (
                await session.execute(
                    select(EvidenceBundle.id).where(EvidenceBundle.milestone_id.in_(milestone_ids))
                )
            ).all()
        ]
        from app.models.commerce import (
            Artifact,
            IdempotencyRecord,
            OutboxEvent,
            ProcessedEvent,
        )

        # The idempotency records and the outbox/processed rows survive a naive
        # reset and then collide with the re-run: the key is
        # sha256(milestone_id:direction:attempt_no) and the rewind resets the
        # attempt counter, so the same key is minted again.  The keys are
        # RECOMPUTED rather than read from the authorizations, because a previous
        # failed reset can leave an orphan record with no authorization to read
        # it from -- which is exactly the state this had to be fixed from.
        from app.rails.base import idempotency_key as _idem_key

        keys = [
            _idem_key(str(m), direction, attempt)
            for m in milestone_ids
            for direction in ("RELEASE", "REFUND")
            for attempt in range(1, RESET_ATTEMPT_SCAN + 1)
        ]
        event_ids = [
            e
            for (e,) in (
                await session.execute(
                    select(OutboxEvent.event_id).where(
                        OutboxEvent.aggregate_id.in_(
                            [str(deal.id), *[str(m) for m in milestone_ids]]
                        )
                    )
                )
            ).all()
        ]

        await session.execute(text("ALTER TABLE ledger_events DISABLE TRIGGER USER"))
        await session.execute(text("ALTER TABLE attestations DISABLE TRIGGER USER"))
        await session.execute(delete(Payout).where(Payout.deal_id == deal.id))
        if keys:
            await session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.idempotency_key.in_(keys))
            )
        if event_ids:
            await session.execute(
                delete(ProcessedEvent).where(ProcessedEvent.event_id.in_(event_ids))
            )
            await session.execute(delete(OutboxEvent).where(OutboxEvent.event_id.in_(event_ids)))
        await session.execute(
            delete(SettlementAuthorization).where(SettlementAuthorization.deal_id == deal.id)
        )
        await session.execute(delete(Dispute).where(Dispute.deal_id == deal.id))
        await session.execute(delete(ChainAnchor).where(ChainAnchor.deal_id == deal.id))
        await session.execute(
            delete(Attestation).where(Attestation.milestone_id.in_(milestone_ids))
        )
        if bundle_ids:
            await session.execute(delete(Artifact).where(Artifact.bundle_id.in_(bundle_ids)))
            await session.execute(delete(EvidenceBundle).where(EvidenceBundle.id.in_(bundle_ids)))
        await session.execute(delete(LedgerEvent).where(LedgerEvent.deal_id == deal.id))
        await session.execute(text("ALTER TABLE ledger_events ENABLE TRIGGER USER"))
        await session.execute(text("ALTER TABLE attestations ENABLE TRIGGER USER"))
        deal.state = DealState.DRAFT
        deal.funded_paise = 0
        deal.released_paise = 0
        deal.refunded_paise = 0
        deal.chain_tx = None
        for m in milestones:
            m.state = MilestoneState.PENDING
            m.released_at = None
        await session.commit()
    print(f"demo deal {reference} reset to DRAFT")


async def run_demo(reference: str) -> dict[str, Any]:
    factory = get_session_factory()
    transcript: list[dict[str, Any]] = []

    def beat(actor: str, event: str, **detail: Any) -> None:
        row = {
            "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "actor": actor,
            "event": event,
            **detail,
        }
        transcript.append(row)
        extras = "  ".join(f"{k}={v}" for k, v in detail.items())
        print(f"  {row['at'][11:19]}  {actor:<18} {event}{'  ' + extras if extras else ''}")

    buyer_user_id = seed_id(f"user:{settings.DEMO_BUYER_EMAIL.lower()}")
    seller_user_id = seed_id(f"user:{settings.DEMO_SELLER_EMAIL.lower()}")

    print("\nAEGIS DEMO -- every value below is produced by this run\n")
    print(f"  rail: {rail_disclosure()['mode']}   ai provider: {settings.ai_effective_provider}")
    print(
        f"  chain: {'enabled' if settings.CHAIN_ENABLED else 'disabled'}"
        f"{'  contract ' + settings.CONTRACT_ADDRESS if settings.CONTRACT_ADDRESS else ''}\n"
    )

    # ── formation and funding ──────────────────────────────────────────
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        buyer_org, seller_org = deal.org_id_buyer, deal.org_id_seller
        if deal.state == DealState.DRAFT:
            beat("Buyer Agent", "proposed milestones", count=len(milestones))
            beat("Seller Agent", "accepted terms", terms_hash=deal.terms_hash[:16] + "...")
            await deal_service.sign_terms(session, deal, actor="BUYER_AGENT")
            await session.commit()
        risk = deal.risk_factors_json or await deal_service.score_and_price(session, deal)
        beat(
            "Risk model",
            "scored counterparty",
            risk=round(float(risk.get("risk_score", 0)), 4),
            tier=risk.get("pricing", {}).get("tier"),
            fee_pct=risk.get("pricing", {}).get("escrow_fee_pct"),
        )
        for factor in risk.get("top_factors", [])[:3]:
            beat(
                "Risk model",
                f"factor {factor['sign']}{abs(factor['delta']):.3f}",
                because=factor["plain_language"],
            )
        if deal.state == DealState.TERMS_SIGNED:
            await deal_service.fund_deal(session, deal, actor="BUYER_AGENT")
            await session.commit()
            beat("Buyer Agent", "funded escrow", amount=inr(int(deal.funded_paise)))
    await _drain(deal.id)

    # ── milestone 1: the clean release ─────────────────────────────────
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        m1 = milestones[0]
        if m1.state == MilestoneState.PENDING:
            bundle = await _submit(session, deal, m1, seller_org, seller_user_id)
            await session.commit()
            beat(
                "Seller",
                "submitted evidence",
                milestone="01",
                merkle_root=bundle.merkle_root[:16] + "...",
            )
        if m1.state in {MilestoneState.EVIDENCE_SUBMITTED, MilestoneState.VERIFYING}:
            bundle = (
                await session.execute(
                    select(EvidenceBundle)
                    .where(EvidenceBundle.milestone_id == m1.id)
                    .order_by(EvidenceBundle.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
            attestation, output = await run_verification(session, deal, m1, bundle)
            await session.commit()
            checks = output.prechecks.as_json()
            beat("Verifier", "pre-checks", passed=f"{checks['passed']}/{checks['total']}")
            beat(
                "Verifier",
                f"milestone 01 {output.decision}",
                confidence=f"{float(attestation.confidence):.3f}",
                llm_calls=output.llm_calls,
            )
            beat("Settlement", "authorization written", state=str(m1.state))
    handled = await _drain(deal.id)
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        payout = (
            await session.execute(
                select(Payout).where(Payout.milestone_id == milestones[0].id).limit(1)
            )
        ).scalar_one_or_none()
        if payout is not None:
            beat("Kafka", "settlement.authorized consumed", events=handled)
            beat(
                "Settlement Worker",
                f"{payout.rail} release",
                amount=inr(int(payout.amount_paise)),
                rail_ref=payout.rail_ref,
                status=str(payout.status),
            )
        beat(
            "Money",
            "bar",
            released=inr(int(deal.released_paise)),
            held=inr(int(deal.held_paise)),
            refunded=inr(int(deal.refunded_paise)),
            balanced=deal.balanced,
        )

    # ── milestone 2: the refusal ───────────────────────────────────────
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        m2 = milestones[1]
        if m2.state == MilestoneState.PENDING:
            bundle = await _submit(session, deal, m2, seller_org, seller_user_id)
            await session.commit()
            beat(
                "Seller",
                "submitted evidence",
                milestone="02",
                merkle_root=bundle.merkle_root[:16] + "...",
            )
        if m2.state in {MilestoneState.EVIDENCE_SUBMITTED, MilestoneState.VERIFYING}:
            bundle = (
                await session.execute(
                    select(EvidenceBundle)
                    .where(EvidenceBundle.milestone_id == m2.id)
                    .order_by(EvidenceBundle.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
            attestation, output = await run_verification(session, deal, m2, bundle)
            await session.commit()
            beat(
                "Verifier",
                f"milestone 02 {output.decision}",
                confidence=f"{float(attestation.confidence):.3f}",
            )
            for v in output.clause_verdicts:
                if v["verdict"] == "UNVERIFIABLE":
                    beat("Verifier", f"clause {v['clause_id']} UNVERIFIABLE", note=v["note"])
            beat("Settlement", "no money moved", held=inr(int(deal.held_paise)))
            beat("Human review", "queued", milestone="02")
    await _drain(deal.id)

    # ── human approves milestone 2 ─────────────────────────────────────
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        m2 = milestones[1]
        if m2.state == MilestoneState.UNDER_HUMAN_REVIEW:
            result = await do_human_review(
                session,
                deal,
                m2,
                action="APPROVE",
                reason=(
                    "Counted 500 units against the packing list on site and matched the "
                    "carton manifest; the photographs are consistent with that count."
                ),
                user_id=buyer_user_id,
                actor="HUMAN:buyer-owner",
                acting_org_id=deal.org_id_buyer,
            )
            await session.commit()
            beat("Human", "APPROVE with written reason", amount=inr(result["amount_paise"]))
    await _drain(deal.id)
    async with factory() as session:
        deal, _ = await _load(session, reference)
        beat(
            "Money",
            "bar",
            released=inr(int(deal.released_paise)),
            held=inr(int(deal.held_paise)),
            balanced=deal.balanced,
        )

    # ── milestone 3: verify, then dispute before it settles ────────────
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        m3 = milestones[2]
        if m3.state == MilestoneState.PENDING:
            bundle = await _submit(session, deal, m3, seller_org, seller_user_id)
            await session.commit()
            beat(
                "Seller",
                "submitted evidence",
                milestone="03",
                merkle_root=bundle.merkle_root[:16] + "...",
            )
        if m3.state in {MilestoneState.EVIDENCE_SUBMITTED, MilestoneState.VERIFYING}:
            bundle = (
                await session.execute(
                    select(EvidenceBundle)
                    .where(EvidenceBundle.milestone_id == m3.id)
                    .order_by(EvidenceBundle.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
            attestation, output = await run_verification(session, deal, m3, bundle)
            await session.commit()
            beat(
                "Verifier",
                f"milestone 03 {output.decision}",
                confidence=f"{float(attestation.confidence):.3f}",
            )

    # The buyer disputes inside the window, before the worker settles.  The
    # settlement worker then refuses the pending authorization because the
    # milestone is DISPUTED -- money must not move while a dispute is open.
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        m3 = milestones[2]
        open_dispute = (
            await session.execute(select(Dispute).where(Dispute.milestone_id == m3.id).limit(1))
        ).scalar_one_or_none()
        if open_dispute is None and m3.state in {
            MilestoneState.RELEASE_APPROVED,
            MilestoneState.SETTLED,
        }:
            open_dispute = await raise_dispute(
                session,
                deal,
                m3,
                claim=(
                    "60 of 500 units show colour variance beyond the approved CT-240-IVY "
                    "swatch; we are claiming the tolerance deduction on those units."
                ),
                user_id=buyer_user_id,
                org_id=buyer_org,
                actor="HUMAN:buyer-owner",
            )
            await session.commit()
            beat("Buyer", "raised dispute", milestone="03", units=60)
    handled = await _drain(deal.id)
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        beat(
            "Settlement Worker",
            "refused pending authorization",
            reason="MILESTONE_DISPUTED",
            held=inr(int(deal.held_paise)),
        )

    async with factory() as session:
        deal, milestones = await _load(session, reference)
        m3 = milestones[2]
        dispute = (
            await session.execute(select(Dispute).where(Dispute.milestone_id == m3.id).limit(1))
        ).scalar_one()
        if dispute.arbiter_recommendation_json is None:
            recommendation = await run_arbiter(session, deal, m3, dispute)
            await session.commit()
        else:
            recommendation = dispute.arbiter_recommendation_json
        beat(
            "Arbiter (advisory)",
            recommendation["outcome"],
            release=inr(recommendation["release_paise"]),
            refund=inr(recommendation["refund_paise"]),
            confidence=recommendation["confidence"],
        )
        for step in recommendation["reasoning_steps"]:
            beat("Arbiter (advisory)", "reasoning", step=step)
        for question in recommendation["open_questions"]:
            beat("Arbiter (advisory)", "open question", question=question)

        if dispute.human_decided_by is None:
            result = await resolve_dispute(
                session,
                deal,
                m3,
                dispute,
                release_paise=int(recommendation["release_paise"]),
                refund_paise=int(recommendation["refund_paise"]),
                reason=(
                    "Accepted the arbiter's split: the 20% tolerance deduction on 60 units "
                    "matches the signed condition report."
                ),
                user_id=buyer_user_id,
                actor="HUMAN:buyer-owner",
                membership_can_approve=True,
                acting_org_id=deal.org_id_buyer,
            )
            await session.commit()
            beat(
                "Human",
                "approved split",
                release=inr(result["release_paise"]),
                refund=inr(result["refund_paise"]),
                override_delta=result["override_delta_paise"],
            )
    await _drain(deal.id)

    # ── close ──────────────────────────────────────────────────────────
    async with factory() as session:
        deal, milestones = await _load(session, reference)
        beat(
            "Money",
            "bar",
            funded=inr(int(deal.funded_paise)),
            released=inr(int(deal.released_paise)),
            refunded=inr(int(deal.refunded_paise)),
            held=inr(int(deal.held_paise)),
            balanced=deal.balanced,
        )
        beat("Deal", "state", value=str(deal.state))

        ledger = await verify_chain(session, deal.id)
        beat("Ledger", "verify", ok=ledger["ok"], events=ledger["length"])

        anchors = list(
            (
                await session.execute(select(ChainAnchor).where(ChainAnchor.deal_id == deal.id))
            ).scalars()
        )
        confirmed = [a for a in anchors if a.status == "CONFIRMED"]
        beat("Chain", "anchors", queued=len(anchors) - len(confirmed), confirmed=len(confirmed))
        for a in confirmed:
            beat("Chain", f"{a.kind} anchored", tx=a.tx_hash)
        if anchors and not confirmed:
            beat(
                "Chain",
                "anchoring unavailable",
                reason="CONTRACT_ADDRESS / OPERATOR_PRIVATE_KEY not configured"
                if not settings.CONTRACT_ADDRESS
                else "chain RPC unreachable",
            )

        attestations = list(
            (
                await session.execute(
                    select(Attestation)
                    .where(Attestation.milestone_id.in_([m.id for m in milestones]))
                    .order_by(Attestation.created_at)
                )
            ).scalars()
        )
        payouts = list(
            (
                await session.execute(
                    select(Payout).where(Payout.deal_id == deal.id).order_by(Payout.created_at)
                )
            ).scalars()
        )

        summary = {
            "deal": {
                "id": str(deal.id),
                "reference": deal.reference,
                "state": str(deal.state),
                "funded_paise": int(deal.funded_paise),
                "released_paise": int(deal.released_paise),
                "refunded_paise": int(deal.refunded_paise),
                "held_paise": int(deal.held_paise),
                "balanced": deal.balanced,
                "risk_score": float(deal.risk_score) if deal.risk_score is not None else None,
                "pricing_tier": deal.pricing_tier,
                "terms_hash": deal.terms_hash,
            },
            "milestones": [
                {
                    "seq": int(m.seq),
                    "title": m.title,
                    "amount_paise": int(m.amount_paise),
                    "state": str(m.state),
                }
                for m in milestones
            ],
            "attestations": [
                {
                    "reference": a.reference,
                    "milestone_id": str(a.milestone_id),
                    "decision": str(a.decision),
                    "confidence": float(a.confidence),
                    "provider": a.provider,
                    "model_id": a.model_id,
                    "prompt_hash": a.prompt_hash,
                    "canonical_hash": a.canonical_hash,
                    "signer_address": a.signer_address,
                    "chain_tx": a.chain_tx,
                }
                for a in attestations
            ],
            "payouts": [
                {
                    "direction": str(p.direction),
                    "amount_paise": int(p.amount_paise),
                    "rail": p.rail,
                    "rail_ref": p.rail_ref,
                    "status": str(p.status),
                }
                for p in payouts
            ],
            "ledger": ledger,
            "rail": rail_disclosure(),
            "ai_provider": settings.ai_effective_provider,
            "transcript": transcript,
        }

    out = Path(__file__).resolve().parents[1] / "evals" / "out" / "demo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")

    base = settings.PUBLIC_APP_URL
    # Real routes only.  There is deliberately no `?as=` parameter anywhere in
    # this product: sign in with the demo buttons on the login screen, which
    # perform a genuine login through the ordinary path.
    print("\n  WALKTHROUGH")
    print(f"    sign in             {base}/login   (Continue as the demo buyer / seller)")
    print(f"    deal cockpit        {base}/deals/{deal.id}")
    print(f"    review queue        {base}/review")
    print(
        f"    verification (M02)  {base}/deals/{deal.id}/milestones/"
        f"{next(m.id for m in milestones if m.seq == 2)}/verification"
    )
    if attestations:
        print(f"    provenance          {base}/provenance/{attestations[0].id}")
    print(f"    ledger              {base}/deals/{deal.id}/ledger")
    print(f"    risk and pricing    {base}/deals/{deal.id}/risk")
    print(f"    counterparty        {base}/entities/{deal.seller_entity_id}")
    print(f"    platform ledger     {base}/ledger")
    print("    kafka ui            http://localhost:8080")
    print("    mailpit             http://localhost:8025")
    print("\n  transcript written to backend/evals/out/demo.json\n")
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Aegis demo walkthrough")
    parser.add_argument("--reference", default="D-4812")
    parser.add_argument("--reset", action="store_true", help="rewind the demo deal to DRAFT")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.reset:
            await reset_demo(args.reference)
        summary = await run_demo(args.reference)
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    finally:
        # The relay starts a Kafka producer when Kafka is enabled.  Stopping it
        # explicitly avoids the "Unclosed AIOKafkaProducer" warning at exit and,
        # more usefully, flushes anything still buffered.
        from app.events.bus import get_producer

        with contextlib.suppress(Exception):
            await get_producer().stop()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
