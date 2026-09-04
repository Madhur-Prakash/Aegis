"""Kafka producer / consumer wrapper plus an in-process fallback bus.

Kafka is mandatory in the payment flow, but the *effect* is exactly-once because
consumers re-read and re-validate the database (never the message payload) and
guard on ``ProcessedEvent``.  When ``KAFKA_ENABLED=false`` -- unit tests, offline
eval -- the same handlers run over an in-memory queue, so no code path is unique
to Kafka being present.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from app.attest.canonical import canonical_bytes
from app.common.logging import get_logger
from app.config.settings import settings
from app.events.topics import ALL_TOPICS, Topic

log = get_logger("kafka")


@dataclass(slots=True)
class Message:
    topic: str
    key: str
    value: dict[str, Any]
    offset: int = 0


@dataclass
class InMemoryBus:
    """Deterministic stand-in used when Kafka is disabled."""

    queues: dict[str, deque[Message]] = field(default_factory=lambda: defaultdict(deque))
    published: list[Message] = field(default_factory=list)

    async def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        msg = Message(topic, key, value, offset=len(self.published))
        self.queues[topic].append(msg)
        self.published.append(msg)
        log.info("kafka publish", extra={"topic": topic, "key": key, "transport": "memory"})

    async def drain(self, topic: str) -> list[Message]:
        out: list[Message] = []
        while self.queues[topic]:
            out.append(self.queues[topic].popleft())
        return out

    def depth(self, topic: str) -> int:
        return len(self.queues[topic])


_memory_bus = InMemoryBus()


def memory_bus() -> InMemoryBus:
    return _memory_bus


class KafkaProducerWrapper:
    def __init__(self) -> None:
        self._producer: Any = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if not settings.KAFKA_ENABLED:
            return
        from aiokafka import AIOKafkaProducer

        async with self._lock:
            if self._producer is not None:
                return
            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: canonical_bytes(v),
                key_serializer=lambda k: str(k).encode(),
                enable_idempotence=True,
                acks="all",
                request_timeout_ms=10_000,
            )
            await self._producer.start()
            log.info("kafka producer started", extra={"servers": settings.KAFKA_BOOTSTRAP_SERVERS})

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, key: str, value: dict[str, Any]) -> None:
        if not settings.KAFKA_ENABLED:
            await _memory_bus.publish(topic, key, value)
            return
        if self._producer is None:
            await self.start()
        assert self._producer is not None
        await self._producer.send_and_wait(topic, value=value, key=key)
        log.info("kafka publish", extra={"topic": topic, "key": key, "transport": "kafka"})

    @property
    def live(self) -> bool:
        return self._producer is not None


_producer = KafkaProducerWrapper()


def get_producer() -> KafkaProducerWrapper:
    return _producer


async def ensure_topics() -> bool:
    """Creates every topic idempotently.  Returns readiness."""
    if not settings.KAFKA_ENABLED:
        return True
    try:
        from aiokafka.admin import AIOKafkaAdminClient, NewTopic

        admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        await admin.start()
        try:
            existing = set(await admin.list_topics())
            missing = [
                NewTopic(name=t, num_partitions=1, replication_factor=1)
                for t in ALL_TOPICS
                if t not in existing
            ]
            if missing:
                await admin.create_topics(missing)
                log.info("kafka topics created", extra={"count": len(missing)})
        finally:
            await admin.close()
        return True
    except Exception as exc:
        log.warning("kafka topic setup failed", extra={"error": type(exc).__name__})
        return False


async def kafka_ready() -> bool:
    if not settings.KAFKA_ENABLED:
        return True
    try:
        from aiokafka.admin import AIOKafkaAdminClient

        admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        await admin.start()
        try:
            await admin.list_topics()
        finally:
            await admin.close()
        return True
    except Exception:
        return False


def decode_value(raw: bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return json.loads(raw.decode("utf-8"))


__all__ = [
    "InMemoryBus",
    "KafkaProducerWrapper",
    "Message",
    "Topic",
    "decode_value",
    "ensure_topics",
    "get_producer",
    "kafka_ready",
    "memory_bus",
]
