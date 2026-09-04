"""Outbox relay entrypoint (I13).

The relay is the *only* thing that publishes to Kafka.  It selects unpublished
outbox rows ``FOR UPDATE SKIP LOCKED``, publishes each, and marks it published in
the same transaction as the publish acknowledgement.

If the relay is killed between the publish and the mark, the row is still
unpublished and will be re-published on restart.  That is why every consumer is
idempotent on ``event_id``: at-least-once publish, exactly-once effect.
``tests/integration/test_outbox_crash.py`` kills it mid-flight and asserts one
payout.
"""

from __future__ import annotations

import asyncio
import signal

from app.common.logging import configure_logging, flush, get_logger, shutdown
from app.config.settings import settings
from app.db.session import dispose_engine, session_scope
from app.events.bus import ensure_topics, get_producer
from app.events.outbox import fetch_unpublished, mark_failed, mark_published

configure_logging(settings)
log = get_logger("relay")

POLL_INTERVAL_S = 0.5
BATCH = 100

_stop = asyncio.Event()


async def relay_once(batch: int = BATCH) -> int:
    """Publishes one batch.  Returns the number of events published."""
    published = 0
    async with session_scope() as session:
        rows = await fetch_unpublished(session, limit=batch)
        if not rows:
            return 0
        done: list[int] = []
        producer = get_producer()
        for row in rows:
            try:
                await producer.publish(row.topic, row.event_id, row.payload_json)
                done.append(row.id)
                published += 1
            except Exception as exc:
                await mark_failed(session, row.id, f"{type(exc).__name__}: {exc}")
                log.warning(
                    "relay publish failed",
                    extra={
                        "outbox_id": row.id,
                        "topic": row.topic,
                        "event_id": row.event_id,
                        "error": type(exc).__name__,
                    },
                )
        await mark_published(session, done)
    if published:
        log.info("relay published", extra={"count": published})
    return published


async def main() -> None:
    if settings.KAFKA_ENABLED:
        await ensure_topics()
        await get_producer().start()
    log.info("relay started", extra={"kafka_enabled": settings.KAFKA_ENABLED})
    try:
        while not _stop.is_set():
            count = await relay_once()
            if count == 0:
                await asyncio.sleep(POLL_INTERVAL_S)
    finally:
        await get_producer().stop()


def _install_signals(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: _stop.set())


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signals(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.run_until_complete(dispose_engine())
        flush(5.0)
        shutdown()
        loop.close()
