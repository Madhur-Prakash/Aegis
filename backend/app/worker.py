"""Kafka consumer entrypoint.

Manual offset commit *after* successful processing.  Bounded retry with
exponential backoff, then a dead letter carrying the full failure reason -- a DLQ
message is a visible operational event, never a silent drop.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any

from app.common.logging import configure_logging, flush, get_logger, shutdown
from app.config.settings import settings
from app.db.session import dispose_engine, session_scope
from app.events.bus import decode_value, ensure_topics, get_producer, memory_bus
from app.events.handlers import TOPIC_GROUPS, dispatch
from app.events.topics import BACKOFF_BASE_S, MAX_ATTEMPTS, Topic, dlq
from app.models.commerce import DeadLetter

configure_logging(settings)
log = get_logger("worker")

CONSUMED_TOPICS: tuple[str, ...] = (
    str(Topic.SETTLEMENT),
    str(Topic.REFUNDS),
    str(Topic.PAYMENT_WEBHOOKS),
    str(Topic.NOTIFICATIONS),
    str(Topic.CHAIN),
)

_stop = asyncio.Event()


async def process_message(topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Runs a handler with bounded retry, then dead-letters."""
    group = TOPIC_GROUPS.get(topic, "settlement")
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with session_scope() as session:
                result = await dispatch(session, topic, payload)
            log.info(
                "kafka consume",
                extra={
                    "topic": topic,
                    "consumer_group": group,
                    "event_id": payload.get("event_id"),
                    "event_type": payload.get("event_type"),
                    "attempt": attempt,
                    "result": result,
                },
            )
            return result
        except Exception as exc:
            last_error = exc
            log.warning(
                "handler failed",
                extra={
                    "topic": topic,
                    "attempt": attempt,
                    "error": type(exc).__name__,
                    "event_id": payload.get("event_id"),
                },
            )
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_BASE_S * (2 ** (attempt - 1)))

    reason = f"{type(last_error).__name__}: {last_error}"
    async with session_scope() as session:
        session.add(
            DeadLetter(
                topic=topic,
                consumer_group=group,
                event_id=str(payload.get("event_id") or ""),
                payload_json=payload,
                failure_reason=reason[:4000],
                attempts=MAX_ATTEMPTS,
            )
        )
    with contextlib.suppress(Exception):
        await get_producer().publish(dlq(topic), str(payload.get("event_id") or ""), payload)
    log.error(
        "dead lettered",
        extra={"topic": topic, "event_id": payload.get("event_id"), "reason": reason[:400]},
    )
    return {"dead_lettered": True, "reason": reason[:400]}


async def drain_memory_bus() -> int:
    """Used when Kafka is disabled (tests, offline eval, ``make demo``)."""
    handled = 0
    bus = memory_bus()
    for topic in CONSUMED_TOPICS:
        for message in await bus.drain(topic):
            await process_message(topic, message.value)
            handled += 1
    return handled


async def consume_forever() -> None:
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        *CONSUMED_TOPICS,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="aegis-worker",
        enable_auto_commit=False,  # manual commit after successful processing
        auto_offset_reset="earliest",
        max_poll_interval_ms=300_000,
    )
    await consumer.start()
    await get_producer().start()
    log.info("worker consuming", extra={"topics": list(CONSUMED_TOPICS)})
    try:
        while not _stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=20)
            for tp, messages in batch.items():
                for message in messages:
                    payload = decode_value(message.value)
                    await process_message(tp.topic, payload)
                # Offsets commit only after the batch's effects are durable.
                await consumer.commit({tp: messages[-1].offset + 1})
    finally:
        await consumer.stop()
        await get_producer().stop()


async def main() -> None:
    if settings.KAFKA_ENABLED:
        await ensure_topics()
        await consume_forever()
    else:
        log.info("kafka disabled -- draining the in-process bus")
        while not _stop.is_set():
            if await drain_memory_bus() == 0:
                await asyncio.sleep(0.5)


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
        # Without this the last log lines -- the ones needed after a crash -- are lost.
        flush(5.0)
        shutdown()
        loop.close()
