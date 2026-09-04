"""I6 -- twenty simultaneous releases produce exactly one payout and exactly one
rail call, and duplicate Kafka delivery has a single effect."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.session import get_session_factory
from app.models.commerce import (
    Milestone,
    OutboxEvent,
    Payout,
    ProcessedEvent,
    SettlementAuthorization,
)
from app.models.enums import PayoutStatus
from app.rails.base import SimulatedRail, idempotency_key, set_rail
from tests.conftest import requires_db
from tests.factories import make_deal, submit_evidence, verify_milestone

pytestmark = requires_db


async def authorized_milestone(parties: dict[str, Any]) -> tuple[Any, Any, Any]:
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
        authorization = (
            await session.execute(
                select(SettlementAuthorization).where(
                    SettlementAuthorization.milestone_id == milestone.id
                )
            )
        ).scalar_one()
        return deal.id, milestone.id, authorization.id


def test_the_idempotency_key_is_the_specified_hash():
    import hashlib

    key = idempotency_key("m-1", "RELEASE", 1)
    assert key == hashlib.sha256(b"m-1:RELEASE:1").hexdigest()
    assert key != idempotency_key("m-1", "RELEASE", 2)
    assert key != idempotency_key("m-1", "REFUND", 1)
    assert key != idempotency_key("m-2", "RELEASE", 1)


@pytest.mark.asyncio
async def test_twenty_concurrent_releases_produce_one_payout_and_one_rail_call(parties):
    from app.settlement.engine import execute_authorization

    rail = SimulatedRail()
    set_rail(rail)
    deal_id, milestone_id, authorization_id = await authorized_milestone(parties)
    rail.calls.clear()

    async def attempt() -> str | None:
        async with get_session_factory()() as session:
            try:
                result = await execute_authorization(session, authorization_id)
                await session.commit()
                return None if result.payout is None else str(result.payout.id)
            except Exception as exc:
                await session.rollback()
                return f"error:{type(exc).__name__}"

    await asyncio.gather(*[attempt() for _ in range(20)])

    async with get_session_factory()() as session:
        payouts = list(
            (
                await session.execute(select(Payout).where(Payout.milestone_id == milestone_id))
            ).scalars()
        )
        from app.models.commerce import Deal

        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()

    succeeded = [p for p in payouts if p.status == PayoutStatus.SUCCEEDED]
    rail_calls = [c for c in rail.calls if c["op"] == "release_to_seller"]

    assert len(succeeded) == 1, f"{len(succeeded)} successful payouts"
    assert len(rail_calls) == 1, f"{len(rail_calls)} rail calls -- the rail must be called once"
    assert int(deal.released_paise) == int(succeeded[0].amount_paise)
    assert deal.balanced


@pytest.mark.asyncio
async def test_the_payout_unique_index_is_the_backstop(parties):
    """Even with the claim bypassed, the database refuses a second payout."""
    from sqlalchemy.exc import IntegrityError

    deal_id, milestone_id, authorization_id = await authorized_milestone(parties)
    async with get_session_factory()() as session:
        authorization = (
            await session.execute(
                select(SettlementAuthorization).where(
                    SettlementAuthorization.id == authorization_id
                )
            )
        ).scalar_one()
        for _ in range(2):
            session.add(
                Payout(
                    milestone_id=milestone_id,
                    deal_id=deal_id,
                    authorization_id=authorization_id,
                    direction=authorization.direction,
                    amount_paise=1,
                    rail="SIMULATED",
                    idempotency_key=authorization.idempotency_key,
                    status=PayoutStatus.SUCCEEDED,
                )
            )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_twenty_duplicate_deliveries_have_a_single_effect(parties):
    from app.events.handlers import handle_settlement_authorized

    rail = SimulatedRail()
    set_rail(rail)
    _, milestone_id, _ = await authorized_milestone(parties)

    async with get_session_factory()() as session:
        outbox = (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.topic == "aegis.settlement")
                .order_by(OutboxEvent.id)
                .limit(1)
            )
        ).scalar_one()
        payload = dict(outbox.payload_json)

    rail.calls.clear()
    for _ in range(20):
        async with get_session_factory()() as session:
            await handle_settlement_authorized(session, payload)
            await session.commit()

    async with get_session_factory()() as session:
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
    assert len(payouts) == 1
    assert len([c for c in rail.calls if c["op"] == "release_to_seller"]) == 1
    assert processed == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_deliveries_also_have_a_single_effect(parties):
    """The same message arriving on twenty consumers at once, not in sequence."""
    from app.events.handlers import handle_settlement_authorized

    rail = SimulatedRail()
    set_rail(rail)
    _, milestone_id, _ = await authorized_milestone(parties)

    async with get_session_factory()() as session:
        outbox = (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.topic == "aegis.settlement")
                .order_by(OutboxEvent.id)
                .limit(1)
            )
        ).scalar_one()
        payload = dict(outbox.payload_json)

    rail.calls.clear()

    async def deliver() -> None:
        async with get_session_factory()() as session:
            try:
                await handle_settlement_authorized(session, payload)
                await session.commit()
            except Exception:
                await session.rollback()

    await asyncio.gather(*[deliver() for _ in range(20)])

    async with get_session_factory()() as session:
        payouts = [
            p
            for p in (
                await session.execute(select(Payout).where(Payout.milestone_id == milestone_id))
            ).scalars()
            if p.status == PayoutStatus.SUCCEEDED
        ]
    assert len(payouts) == 1
    assert len([c for c in rail.calls if c["op"] == "release_to_seller"]) == 1


@pytest.mark.asyncio
async def test_a_stale_authorization_is_refused_after_the_milestone_settles(parties):
    """A replayed event long after the fact must not release a second time."""
    from app.settlement.engine import execute_authorization

    rail = SimulatedRail()
    set_rail(rail)
    _, _milestone_id, authorization_id = await authorized_milestone(parties)

    async with get_session_factory()() as session:
        first = await execute_authorization(session, authorization_id)
        await session.commit()
    assert first.payout is not None
    rail.calls.clear()

    async with get_session_factory()() as session:
        replay = await execute_authorization(session, authorization_id)
        await session.commit()
    assert replay.already_done is True
    assert rail.calls == []


@pytest.mark.asyncio
async def test_a_rail_failure_releases_the_claim_so_a_retry_can_proceed(parties):
    from app.settlement.engine import execute_authorization

    rail = SimulatedRail()
    set_rail(rail)
    _, milestone_id, authorization_id = await authorized_milestone(parties)

    rail.fail_next = True
    async with get_session_factory()() as session:
        failed = await execute_authorization(session, authorization_id)
        await session.commit()
    assert failed.failed is True
    assert failed.payout is not None
    assert failed.payout.status == PayoutStatus.FAILED

    async with get_session_factory()() as session:
        authorization = (
            await session.execute(
                select(SettlementAuthorization).where(
                    SettlementAuthorization.id == authorization_id
                )
            )
        ).scalar_one()
        assert authorization.claimed_at is None, "a failed rail call must release the claim"
        assert authorization.consumed_at is None

    # The retry uses attempt_no 2, so its idempotency key differs and the unique
    # index does not block the legitimate second attempt.
    async with get_session_factory()() as session:
        from app.models.commerce import Attestation, Deal

        deal = (
            await session.execute(
                select(Deal)
                .join(Milestone, Milestone.deal_id == Deal.id)
                .where(Milestone.id == milestone_id)
            )
        ).scalar_one()
        milestone = (
            await session.execute(select(Milestone).where(Milestone.id == milestone_id))
        ).scalar_one()
        attestation = (
            await session.execute(
                select(Attestation).where(Attestation.milestone_id == milestone_id)
            )
        ).scalar_one()
        from app.settlement.engine import authorize_release

        # The first authorization was consumed by the failure path only in the
        # sense that a FAILED payout exists; the milestone is still
        # RELEASE_APPROVED, so a second authorization is legitimate.
        retry = await authorize_release(session, deal, milestone, attestation)
        await session.commit()
        assert retry.authorization.attempt_no == 2
        assert retry.authorization.idempotency_key != authorization.idempotency_key

    async with get_session_factory()() as session:
        result = await execute_authorization(session, retry.authorization.id)
        await session.commit()
    assert result.payout is not None
    assert result.payout.status == PayoutStatus.SUCCEEDED


async def test_concurrent_ledger_appends_keep_the_chain_intact(parties):
    """I5 under concurrency.

    Twelve transactions append to the same deal's ledger at once.  Without the
    advisory lock inside ``append_ledger`` they all read the same head, write it
    as their own ``prev_hash``, and the chain forks -- which is exactly what
    happened the first time the demo ran against the live settlement worker
    instead of an in-process bus.
    """
    from app.ledger.service import append_ledger, verify_chain

    factory = get_session_factory()
    async with factory() as session:
        deal = await make_deal(session, parties)
        await session.commit()
        deal_id, org_id = deal.id, deal.org_id_buyer

    async def append(index: int) -> None:
        async with factory() as session:
            await append_ledger(
                session,
                deal_id=deal_id,
                org_id=org_id,
                event_type="DEAL_TRANSITION",
                actor=f"TEST:{index}",
                reason="concurrent append",
                payload={"index": index},
            )
            await session.commit()

    await asyncio.gather(*(append(i) for i in range(12)))

    async with factory() as session:
        verdict = await verify_chain(session, deal_id)

    assert verdict["ok"] is True, verdict
    assert verdict["broken_index"] is None
    # Every append landed: none was lost to the serialisation.
    appended = [row for row in await _actors(deal_id) if row.startswith("TEST:")]
    assert sorted(appended) == sorted(f"TEST:{i}" for i in range(12))


async def _actors(deal_id: Any) -> list[str]:
    from app.models.commerce import LedgerEvent

    async with get_session_factory()() as session:
        return [
            actor
            for (actor,) in (
                await session.execute(
                    select(LedgerEvent.actor)
                    .where(LedgerEvent.deal_id == deal_id)
                    .order_by(LedgerEvent.seq)
                )
            ).all()
        ]
