"""Transactional outbox (I13).

A financial state change and its Kafka event are never two independent writes.
``enqueue`` only adds a row to the session; the caller's single transaction commits
both, and ``relay.py`` publishes afterwards.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.attest.canonical import payload_hash
from app.common.logging import get_logger
from app.events.topics import EventType, Topic
from app.models.commerce import OutboxEvent, ProcessedEvent

log = get_logger("outbox")


def deterministic_event_id(
    event_type: EventType | str, aggregate_id: str, discriminator: str = ""
) -> str:
    """A stable event id, so a retried enqueue cannot produce a second event."""
    return "evt_" + payload_hash({"t": str(event_type), "a": aggregate_id, "d": discriminator})[:32]


async def enqueue(
    session: AsyncSession,
    *,
    topic: Topic | str,
    event_type: EventType | str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> OutboxEvent:
    """Adds the outbox row to the *current* transaction.  Never commits."""
    eid = event_id or deterministic_event_id(event_type, aggregate_id)
    existing = (
        await session.execute(select(OutboxEvent).where(OutboxEvent.event_id == eid))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        topic=str(topic),
        event_type=str(event_type),
        event_id=eid,
        payload_json={"event_id": eid, "event_type": str(event_type), **payload},
    )
    session.add(row)
    await session.flush()
    log.info(
        "outbox enqueued",
        extra={
            "topic": str(topic),
            "event_type": str(event_type),
            "event_id": eid,
            "aggregate_id": aggregate_id,
        },
    )
    return row


async def fetch_unpublished(session: AsyncSession, limit: int = 100) -> list[OutboxEvent]:
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list((await session.execute(stmt)).scalars())


async def mark_published(session: AsyncSession, ids: list[int]) -> None:
    if not ids:
        return
    from sqlalchemy import func

    await session.execute(
        update(OutboxEvent).where(OutboxEvent.id.in_(ids)).values(published_at=func.now())
    )


async def mark_failed(session: AsyncSession, row_id: int, error: str) -> None:
    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == row_id)
        .values(attempts=OutboxEvent.attempts + 1, last_error=error[:2000])
    )


async def already_processed(session: AsyncSession, event_id: str, group: str) -> bool:
    stmt = select(ProcessedEvent).where(
        ProcessedEvent.event_id == event_id, ProcessedEvent.consumer_group == group
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def mark_processed(session: AsyncSession, event_id: str, group: str) -> None:
    """Idempotent.  Two consumers racing on the same message must not turn a
    primary-key collision into a rolled-back transaction that discards the work
    one of them already did."""
    from sqlalchemy.dialects.postgresql import insert

    await session.execute(
        insert(ProcessedEvent)
        .values(event_id=event_id, consumer_group=group)
        .on_conflict_do_nothing(
            index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer_group]
        )
    )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None
