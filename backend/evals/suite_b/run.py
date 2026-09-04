"""Suite B -- settlement integrity (property + concurrency).

Every check here runs against the real Postgres, because the properties being
proven are database properties: a CHECK constraint, a unique index, row locking,
and the transactional outbox.  With no database reachable the suite reports
SKIPPED rather than passing vacuously.

    python -m evals.suite_b.run
"""

from __future__ import annotations

import asyncio
import random
import sys
from typing import Any

from sqlalchemy import func, select, text

from app.config.settings import settings
from app.db.session import dispose_engine, get_session_factory
from app.deals.states import (
    DEAL_TRANSITIONS,
    MILESTONE_TRANSITIONS,
    DealEvent,
    MilestoneEvent,
    next_deal_state,
    next_milestone_state,
)
from app.models.commerce import (
    Deal,
    LedgerEvent,
    Milestone,
    OutboxEvent,
    Payout,
    ProcessedEvent,
    SettlementAuthorization,
)
from app.models.enums import DealState, MilestoneState, PayoutStatus
from app.settlement.guards import money_conserved, release_would_conserve
from evals.fixtures import make_parties, reset_database
from evals.runner import provider_banner, table, write_json, write_markdown

TABLES = [
    "dead_letters",
    "processed_events",
    "outbox_events",
    "idempotency_records",
    "payouts",
    "settlement_authorizations",
    "chain_anchors",
    "disputes",
    "attestations",
    "ledger_events",
    "artifacts",
    "evidence_bundles",
    "milestones",
    "deals",
    "deal_messages",
    "notifications",
    "notification_preferences",
    "token_spends",
    "audit_records",
    "counterparty_profiles",
    "entities",
    "invitations",
    "organization_members",
    "organizations",
    "refresh_tokens",
    "email_tokens",
    "users",
    "webhook_receipts",
    "seed_checkpoints",
    "risk_model_artifacts",
]


# ─────────────────────────────────────────────────────────────────────────────
# B1: I4 holds after any random legal event sequence
# ─────────────────────────────────────────────────────────────────────────────
def check_money_invariant_property(trials: int = 4000, seed: int = 42) -> dict[str, Any]:
    """A pure property check over random legal money sequences.

    ``tests/property/test_money_invariant.py`` runs the same property under
    Hypothesis; this is the reproducible, seeded version whose count goes in the
    report.
    """
    rng = random.Random(seed)
    violations = 0
    for _ in range(trials):
        funded = rng.randrange(1, 10_000_000)
        released = refunded = 0
        for _ in range(rng.randrange(0, 12)):
            remaining = funded - released - refunded
            if remaining <= 0:
                break
            amount = rng.randrange(1, remaining + 1)
            if rng.random() < 0.6:
                if not release_would_conserve(funded, released, refunded, amount):
                    violations += 1
                    continue
                released += amount
            else:
                refunded += amount
            if not money_conserved(funded, released, refunded):
                violations += 1
    return {
        "check": "I4 holds after any random legal event sequence",
        "trials": trials,
        "violations": violations,
        "ok": violations == 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# B2: 20 concurrent releases => exactly one payout, exactly one rail call
# ─────────────────────────────────────────────────────────────────────────────
async def check_concurrent_release(parties: dict[str, Any], attempts: int = 20) -> dict[str, Any]:
    from app.rails.base import SimulatedRail, set_rail
    from app.settlement.engine import execute_authorization
    from tests.factories import make_deal, submit_evidence, verify_milestone

    rail = SimulatedRail()
    set_rail(rail)

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        milestone = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        bundle = await submit_evidence(
            session,
            deal,
            milestone,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        await verify_milestone(session, deal, milestone, bundle)
        authorization = (
            await session.execute(
                select(SettlementAuthorization).where(
                    SettlementAuthorization.milestone_id == milestone.id
                )
            )
        ).scalar_one()
        authorization_id = authorization.id
        deal_id = deal.id

    rail.calls.clear()

    async def one() -> str | None:
        async with factory() as s:
            try:
                result = await execute_authorization(s, authorization_id)
                await s.commit()
                return None if result.payout is None else str(result.payout.id)
            except Exception as exc:  # a losing racer must fail loudly, not pay twice
                await s.rollback()
                return f"error:{type(exc).__name__}"

    outcomes = await asyncio.gather(*[one() for _ in range(attempts)])

    async with factory() as session:
        payouts = list(
            (
                await session.execute(select(Payout).where(Payout.milestone_id == milestone.id))
            ).scalars()
        )
        succeeded = [p for p in payouts if p.status == PayoutStatus.SUCCEEDED]
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()

    rail_calls = [c for c in rail.calls if c["op"] == "release_to_seller"]
    return {
        "check": "20 concurrent releases => exactly 1 payout and exactly 1 rail call",
        "attempts": attempts,
        "payout_rows": len(payouts),
        "succeeded_payouts": len(succeeded),
        "rail_calls": len(rail_calls),
        "released_paise": int(deal.released_paise),
        "expected_released_paise": int(payouts[0].amount_paise) if payouts else 0,
        "distinct_results": len({o for o in outcomes if o}),
        "ok": len(succeeded) == 1
        and len(rail_calls) == 1
        and int(deal.released_paise) == int(payouts[0].amount_paise),
    }


# ─────────────────────────────────────────────────────────────────────────────
# B3: no release without a qualifying attestation
# ─────────────────────────────────────────────────────────────────────────────
async def check_no_release_without_attestation(parties: dict[str, Any]) -> dict[str, Any]:
    from app.common.errors import NoQualifyingAttestation
    from app.settlement.engine import authorize_release
    from tests.factories import make_deal

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        milestone = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        raised = False
        try:
            await authorize_release(session, deal, milestone, None)  # type: ignore[arg-type]
        except NoQualifyingAttestation:
            raised = True
        except Exception:
            raised = False
        await session.rollback()
    return {
        "check": "I1 -- authorize_release without an attestation raises",
        "raised_typed_error": raised,
        "ok": raised,
    }


# ─────────────────────────────────────────────────────────────────────────────
# B4: full ledger replay reconstructs identical balances
# ─────────────────────────────────────────────────────────────────────────────
async def check_ledger_replay(parties: dict[str, Any]) -> dict[str, Any]:
    from app.ledger.service import replay_balances, verify_chain
    from tests.factories import (
        drain_outbox,
        make_deal,
        submit_evidence,
        verify_milestone,
    )

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        for seq, folder in ((1, "fabric"),):
            milestone = (
                await session.execute(
                    select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == seq)
                )
            ).scalar_one()
            bundle = await submit_evidence(
                session,
                deal,
                milestone,
                org_id=parties["seller_org_id"],
                user_id=parties["seller_user_id"],
                folder=folder,
            )
            await verify_milestone(session, deal, milestone, bundle)
        await drain_outbox(session)
        deal_id = deal.id

    async with factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        replayed = await replay_balances(session, deal_id)
        chain = await verify_chain(session, deal_id)
    matches = (
        replayed["funded_paise"] == int(deal.funded_paise)
        and replayed["released_paise"] == int(deal.released_paise)
        and replayed["refunded_paise"] == int(deal.refunded_paise)
    )
    return {
        "check": "full ledger replay reconstructs identical balances",
        "stored": {
            "funded_paise": int(deal.funded_paise),
            "released_paise": int(deal.released_paise),
            "refunded_paise": int(deal.refunded_paise),
        },
        "replayed": replayed,
        "hash_chain_ok": chain["ok"],
        "ledger_events": chain["length"],
        "ok": matches and chain["ok"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# B5: every illegal transition raises
# ─────────────────────────────────────────────────────────────────────────────
def check_transition_exhaustiveness() -> dict[str, Any]:
    from app.common.errors import IllegalTransition

    deal_pairs = 0
    deal_legal = 0
    for state in DealState:
        for event in DealEvent:
            deal_pairs += 1
            legal = (state, event) in DEAL_TRANSITIONS
            try:
                targets = DEAL_TRANSITIONS.get((state, event))
                next_deal_state(state, event, targets[0] if targets and len(targets) > 1 else None)
                raised = False
            except IllegalTransition:
                raised = True
            if legal:
                deal_legal += 1
                if raised:
                    return {
                        "check": "every (state, event) pair is in the table or raises",
                        "ok": False,
                        "failure": f"legal deal pair raised: {state} + {event}",
                    }
            elif not raised:
                return {
                    "check": "every (state, event) pair is in the table or raises",
                    "ok": False,
                    "failure": f"illegal deal pair did not raise: {state} + {event}",
                }

    ms_pairs = 0
    ms_legal = 0
    for state in MilestoneState:
        for event in MilestoneEvent:
            ms_pairs += 1
            legal = (state, event) in MILESTONE_TRANSITIONS
            try:
                next_milestone_state(state, event)
                raised = False
            except IllegalTransition:
                raised = True
            if legal:
                ms_legal += 1
                if raised:
                    return {
                        "check": "every (state, event) pair is in the table or raises",
                        "ok": False,
                        "failure": f"legal milestone pair raised: {state} + {event}",
                    }
            elif not raised:
                return {
                    "check": "every (state, event) pair is in the table or raises",
                    "ok": False,
                    "failure": f"illegal milestone pair did not raise: {state} + {event}",
                }
    return {
        "check": "every (state, event) pair is in the table or raises",
        "deal_pairs": deal_pairs,
        "deal_legal": deal_legal,
        "milestone_pairs": ms_pairs,
        "milestone_legal": ms_legal,
        "ok": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# B6: duplicate Kafka delivery => single effect
# ─────────────────────────────────────────────────────────────────────────────
async def check_duplicate_delivery(parties: dict[str, Any], deliveries: int = 20) -> dict[str, Any]:
    from app.events.handlers import handle_settlement_authorized
    from app.rails.base import SimulatedRail, set_rail
    from tests.factories import make_deal, submit_evidence, verify_milestone

    rail = SimulatedRail()
    set_rail(rail)
    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        milestone = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        bundle = await submit_evidence(
            session,
            deal,
            milestone,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        await verify_milestone(session, deal, milestone, bundle)
        outbox = (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.topic == "aegis.settlement")
                .order_by(OutboxEvent.id)
                .limit(1)
            )
        ).scalar_one()
        payload = dict(outbox.payload_json)
        milestone_id = milestone.id

    rail.calls.clear()
    for _ in range(deliveries):
        async with factory() as session:
            await handle_settlement_authorized(session, payload)
            await session.commit()

    async with factory() as session:
        payouts = list(
            (
                await session.execute(select(Payout).where(Payout.milestone_id == milestone_id))
            ).scalars()
        )
        processed = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ProcessedEvent)
                    .where(ProcessedEvent.event_id == payload["event_id"])
                )
            ).scalar()
            or 0
        )
    rail_calls = [c for c in rail.calls if c["op"] == "release_to_seller"]
    return {
        "check": f"{deliveries} duplicate deliveries => single effect",
        "deliveries": deliveries,
        "payout_rows": len(payouts),
        "rail_calls": len(rail_calls),
        "processed_event_rows": processed,
        "ok": len(payouts) == 1 and len(rail_calls) == 1 and processed == 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# B7: outbox crash injection => exactly-once publish
# ─────────────────────────────────────────────────────────────────────────────
async def check_outbox_crash(parties: dict[str, Any]) -> dict[str, Any]:
    """Commit the outbox row, kill the relay before it can mark published,
    restart, and assert the event publishes once and the payout happens once."""
    from app.events.bus import memory_bus
    from app.events.outbox import fetch_unpublished
    from app.relay import relay_once
    from app.worker import drain_memory_bus
    from tests.factories import make_deal, submit_evidence, verify_milestone

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        milestone = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        bundle = await submit_evidence(
            session,
            deal,
            milestone,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="fabric",
        )
        await verify_milestone(session, deal, milestone, bundle)
        milestone_id = milestone.id

    bus = memory_bus()
    before = len(bus.published)

    # ── the crash: publish, then die before marking published ──────────
    async with factory() as session:
        rows = await fetch_unpublished(session, limit=50)
        target = next((r for r in rows if r.topic == "aegis.settlement"), None)
        if target is None:
            return {"check": "outbox crash injection", "ok": False, "failure": "no outbox row"}
        await bus.publish(target.topic, target.event_id, target.payload_json)
        # No mark_published, and no commit: the relay process is gone.
        await session.rollback()

    async with factory() as session:
        still_unpublished = [
            r.event_id
            for r in await fetch_unpublished(session, limit=50)
            if r.topic == "aegis.settlement"
        ]

    # ── restart: the relay republishes, the worker de-duplicates ───────
    for _ in range(6):
        published = await relay_once()
        processed = await drain_memory_bus()
        if published == 0 and processed == 0:
            break

    async with factory() as session:
        payouts = list(
            (
                await session.execute(select(Payout).where(Payout.milestone_id == milestone_id))
            ).scalars()
        )
        unpublished_after = len(await fetch_unpublished(session, limit=50))
    settlement_publishes = [m for m in bus.published[before:] if m.topic == "aegis.settlement"]
    return {
        "check": "outbox crash injection => exactly-once effect",
        "row_survived_the_crash": bool(still_unpublished),
        "publishes_after_restart": len(settlement_publishes),
        "payout_rows": len(payouts),
        "unpublished_remaining": unpublished_after,
        "note": (
            "The event was published twice at the transport layer (once before the "
            "simulated crash, once after the restart) and still produced exactly one "
            "payout: at-least-once delivery, exactly-once effect."
        ),
        "ok": bool(still_unpublished) and len(payouts) == 1 and unpublished_after == 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# B8: the database itself refuses to break I4
# ─────────────────────────────────────────────────────────────────────────────
async def check_db_constraint(parties: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.exc import IntegrityError

    from tests.factories import make_deal

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        deal_id = deal.id
    raised = False
    async with factory() as session:
        try:
            await session.execute(
                text("UPDATE deals SET released_paise = funded_paise + 1 WHERE id = :id"),
                {"id": deal_id},
            )
            await session.commit()
        except IntegrityError:
            raised = True
            await session.rollback()
    return {
        "check": "the DB CHECK constraint refuses released > funded (I4)",
        "raised": raised,
        "ok": raised,
    }


async def check_append_only(parties: dict[str, Any]) -> dict[str, Any]:
    from tests.factories import make_deal

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        event = (
            await session.execute(
                select(LedgerEvent).where(LedgerEvent.deal_id == deal.id).limit(1)
            )
        ).scalar_one()
        event_id = event.id
    update_raised = delete_raised = False
    async with factory() as session:
        try:
            await session.execute(
                text("UPDATE ledger_events SET reason = 'tampered' WHERE id = :id"),
                {"id": event_id},
            )
            await session.commit()
        except Exception:
            update_raised = True
            await session.rollback()
    async with factory() as session:
        try:
            await session.execute(
                text("DELETE FROM ledger_events WHERE id = :id"), {"id": event_id}
            )
            await session.commit()
        except Exception:
            delete_raised = True
            await session.rollback()
    return {
        "check": "ledger_events is append-only in the database, not by convention",
        "update_raised": update_raised,
        "delete_raised": delete_raised,
        "ok": update_raised and delete_raised,
    }


# ─────────────────────────────────────────────────────────────────────────────
async def main() -> int:
    from tests.conftest import database_available

    banner = provider_banner()
    if not database_available():
        payload = {
            "suite": "B -- settlement integrity",
            "status": "SKIPPED",
            "reason": "no Postgres reachable",
            "provider": banner,
            "checks": [],
            "ok": False,
        }
        write_json("suite_b.json", payload)
        write_markdown(
            "suite_b.md",
            "## Suite B -- settlement integrity\n\n**SKIPPED**: no Postgres reachable. "
            "Run `docker compose up -d postgres && make db-upgrade`.\n",
        )
        print("Suite B SKIPPED: no Postgres reachable")
        return 1

    settings.KAFKA_ENABLED = False  # the in-process bus stands in for the broker
    checks: list[dict[str, Any]] = [check_transition_exhaustiveness()]
    checks.append(check_money_invariant_property())

    for factory_fn in (
        check_no_release_without_attestation,
        check_db_constraint,
        check_append_only,
        check_ledger_replay,
        check_concurrent_release,
        check_duplicate_delivery,
        check_outbox_crash,
    ):
        await reset_database()
        parties = await make_parties("suite-b")
        checks.append(await factory_fn(parties))

    ok = all(c["ok"] for c in checks)
    payload = {
        "suite": "B -- settlement integrity",
        "status": "PASS" if ok else "FAIL",
        "provider": banner,
        "checks": checks,
        "ok": ok,
    }
    write_json("suite_b.json", payload)
    write_markdown(
        "suite_b.md",
        "## Suite B -- settlement integrity\n\n"
        + table(
            ["check", "result", "detail"],
            [
                [
                    c["check"],
                    "PASS" if c["ok"] else "FAIL",
                    ", ".join(
                        f"{k}={v}"
                        for k, v in c.items()
                        if k not in {"check", "ok", "note", "detail"}
                    )[:180],
                ]
                for c in checks
            ],
        )
        + "\n",
    )
    for c in checks:
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['check']}")
        if not c["ok"]:
            print(f"        {c}")
    print(
        f"\nSuite B: {'PASS' if ok else 'FAIL'} ({sum(1 for c in checks if c['ok'])}/{len(checks)})"
    )
    await dispose_engine()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
