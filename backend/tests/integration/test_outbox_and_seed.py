"""I13 outbox crash injection, DLQ routing, and seed idempotency/resumability."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.session import get_session_factory
from app.models.commerce import DeadLetter, Milestone, OutboxEvent, Payout
from app.models.identity import Organization, SeedCheckpoint, User
from tests.conftest import requires_db
from tests.factories import make_deal, submit_evidence, verify_milestone

pytestmark = requires_db


async def _count(session: Any, model: Any) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar() or 0)


# ─────────────────────────────────────────────────────────────────────────────
# I13 -- the outbox
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_state_change_and_the_event_commit_together(parties):
    """No dual-write: if the transaction rolls back, neither the authorization
    nor its event survives."""
    from app.models.commerce import SettlementAuthorization
    from app.settlement.engine import authorize_release

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        milestone = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 2)
            )
        ).scalar_one()
        bundle = await submit_evidence(
            session,
            deal,
            milestone,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        # This one escalates, so authorize it as a human would, then roll back.
        attestation, _ = await verify_milestone(session, deal, milestone, bundle)
        before_auth = await _count(session, SettlementAuthorization)
        before_outbox = await _count(session, OutboxEvent)

        await authorize_release(
            session, deal, milestone, attestation, human_user_id=parties["buyer_user_id"]
        )
        assert await _count(session, SettlementAuthorization) == before_auth + 1
        assert await _count(session, OutboxEvent) > before_outbox
        await session.rollback()

    async with get_session_factory()() as session:
        assert await _count(session, SettlementAuthorization) == before_auth
        assert await _count(session, OutboxEvent) == before_outbox


@pytest.mark.asyncio
async def test_the_relay_can_be_killed_before_marking_published(parties):
    """Crash injection: commit the outbox row, publish, die before the mark,
    restart.  Exactly one payout."""
    from app.events.bus import memory_bus
    from app.events.outbox import fetch_unpublished
    from app.relay import relay_once
    from app.worker import drain_memory_bus

    async with get_session_factory()() as session:
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
    published_before = len(bus.published)

    # ── the crash ──────────────────────────────────────────────────────
    async with get_session_factory()() as session:
        rows = [
            r for r in await fetch_unpublished(session, limit=50) if r.topic == "aegis.settlement"
        ]
        assert rows, "the authorization produced no outbox row"
        target = rows[0]
        await bus.publish(target.topic, target.event_id, target.payload_json)
        await session.rollback()  # the relay process dies here

    async with get_session_factory()() as session:
        still = [
            r.event_id
            for r in await fetch_unpublished(session, limit=50)
            if r.topic == "aegis.settlement"
        ]
        assert still, "the row must survive an unmarked publish"

    # ── restart ────────────────────────────────────────────────────────
    for _ in range(6):
        published = await relay_once()
        processed = await drain_memory_bus()
        if published == 0 and processed == 0:
            break

    async with get_session_factory()() as session:
        payouts = list(
            (
                await session.execute(select(Payout).where(Payout.milestone_id == milestone_id))
            ).scalars()
        )
        remaining = await fetch_unpublished(session, limit=50)

    settlement_publishes = [
        m for m in bus.published[published_before:] if m.topic == "aegis.settlement"
    ]
    # Published twice at the transport layer, one payout: at-least-once
    # delivery, exactly-once effect.
    assert len(settlement_publishes) >= 2
    assert len(payouts) == 1
    assert remaining == []


@pytest.mark.asyncio
async def test_an_event_id_is_deterministic_so_a_retried_enqueue_is_a_no_op(parties):
    from app.events.outbox import deterministic_event_id, enqueue
    from app.events.topics import EventType, Topic

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        event_id = deterministic_event_id(EventType.SETTLEMENT_AUTHORIZED, str(deal.id))
        first = await enqueue(
            session,
            topic=Topic.SETTLEMENT,
            event_type=EventType.SETTLEMENT_AUTHORIZED,
            aggregate_type="Deal",
            aggregate_id=str(deal.id),
            payload={"deal_id": str(deal.id)},
            event_id=event_id,
        )
        second = await enqueue(
            session,
            topic=Topic.SETTLEMENT,
            event_type=EventType.SETTLEMENT_AUTHORIZED,
            aggregate_type="Deal",
            aggregate_id=str(deal.id),
            payload={"deal_id": str(deal.id)},
            event_id=event_id,
        )
        assert first.id == second.id


@pytest.mark.asyncio
async def test_a_permanently_failing_message_is_dead_lettered(parties):
    """A DLQ message is a visible operational event, not a silent drop."""
    from app.worker import process_message

    async with get_session_factory()() as session:
        before = await _count(session, DeadLetter)

    # An authorization id that does not exist makes the handler fail every time.
    result = await process_message(
        "aegis.settlement",
        {
            "event_id": "evt_deliberately_broken",
            "event_type": "settlement.authorized",
            "authorization_id": "not-a-uuid",
        },
    )
    assert result.get("dead_lettered") is True

    async with get_session_factory()() as session:
        assert await _count(session, DeadLetter) == before + 1
        letter = (
            await session.execute(
                select(DeadLetter).where(DeadLetter.event_id == "evt_deliberately_broken")
            )
        ).scalar_one()
        assert letter.topic == "aegis.settlement"
        assert letter.consumer_group == "settlement"
        assert letter.failure_reason  # the full reason, not a shrug
        assert letter.attempts >= 1
        assert letter.drained_at is None


@pytest.mark.asyncio
async def test_the_dlq_depth_is_reported_on_the_metrics_endpoint(parties):
    import httpx
    from asgi_lifespan import LifespanManager  # type: ignore[import-not-found]

    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/health/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "dlq_depth" in body
    assert "outbox_backlog" in body
    assert "verifications_by_decision" in body


# ─────────────────────────────────────────────────────────────────────────────
# Seeding
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_seeding_three_times_changes_nothing(truncate_all):
    from scripts.seed import run_seed

    first = await run_seed()
    assert first["applied"] == len(first["steps"])
    counts = first["counts"]

    second = await run_seed()
    assert second["applied"] == 0
    assert second["skipped"] == len(second["steps"])
    assert second["counts"] == counts

    third = await run_seed()
    assert third["applied"] == 0
    assert third["counts"] == counts


@pytest.mark.asyncio
async def test_an_interrupted_seed_resumes_at_the_failed_step(truncate_all):
    from scripts.seed import SeedFailure, run_seed

    with pytest.raises(SeedFailure):
        await run_seed(fail_at="entities")

    async with get_session_factory()() as session:
        completed = {
            row.step_name for row in (await session.execute(select(SeedCheckpoint))).scalars()
        }
        # Everything before the failure is durable; the failed step is not.
        assert {"organizations", "users", "memberships"}.issubset(completed)
        assert "entities" not in completed
        assert await _count(session, Organization) >= 2
        assert await _count(session, User) == 2

    resumed = await run_seed()
    assert resumed["steps"]["organizations"] == "skipped"
    assert resumed["steps"]["entities"] == "applied"

    async with get_session_factory()() as session:
        from app.models.commerce import Deal
        from app.models.identity import Entity

        assert await _count(session, Entity) >= 2
        assert await _count(session, Deal) >= 1

    # And it is still idempotent afterwards.
    again = await run_seed()
    assert again["applied"] == 0


@pytest.mark.asyncio
async def test_seeded_ids_are_deterministic(truncate_all):
    from app.common.ids import seed_id
    from scripts.seed import fixture, run_seed

    await run_seed()
    data = fixture()
    async with get_session_factory()() as session:
        org = await session.get(Organization, seed_id(f"org:{data['buyer']['slug']}"))
        assert org is not None
        assert org.name == data["buyer"]["org_name"]
        user = await session.get(User, seed_id(f"user:{data['buyer']['owner_email'].lower()}"))
        assert user is not None
        assert user.email_verified_at is not None, "demo users are seeded verified"


@pytest.mark.asyncio
async def test_reseeding_does_not_reset_a_demo_that_has_moved_money(truncate_all):
    """The deal's financial state is immutable from the seed's point of view."""
    from app.models.commerce import Deal
    from scripts.seed import run_seed

    await run_seed()
    async with get_session_factory()() as session:
        deal = (await session.execute(select(Deal).where(Deal.reference == "D-4812"))).scalar_one()
        deal.funded_paise = 42_000_000
        deal.released_paise = 12_600_000
        from app.models.enums import DealState

        deal.state = DealState.IN_PROGRESS
        await session.commit()

    await run_seed()

    async with get_session_factory()() as session:
        deal = (await session.execute(select(Deal).where(Deal.reference == "D-4812"))).scalar_one()
        assert deal.released_paise == 12_600_000
        assert deal.funded_paise == 42_000_000


@pytest.mark.asyncio
async def test_the_seed_refuses_to_run_without_demo_passwords(truncate_all, monkeypatch):
    from app.config.settings import settings
    from scripts.seed import run_seed

    monkeypatch.setattr(settings, "DEMO_BUYER_PASSWORD", "CHANGE_ME_demo_password")
    with pytest.raises(SystemExit) as exc:
        await run_seed()
    assert "DEMO_BUYER_PASSWORD" in str(exc.value)
