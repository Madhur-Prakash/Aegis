"""SSE fan-out hub.

One in-process publisher per concern, tenant-scoped at subscribe time.  Redis
carries a hint so a second API replica can wake its own subscribers; the payload
itself is always re-read from Postgres by the client's next fetch, so a dropped
hint costs a refresh, never correctness.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.common.logging import get_logger

log = get_logger("realtime")

MAX_QUEUE = 100


@dataclass
class Hub:
    subscribers: dict[str, set[asyncio.Queue[str]]] = field(
        default_factory=lambda: defaultdict(set)
    )
    counter: int = 0

    def _channel(self, concern: str, org_id: uuid.UUID | str, scope: str | None = None) -> str:
        return f"{concern}:{org_id}:{scope or '*'}"

    async def publish(
        self,
        concern: str,
        org_id: uuid.UUID | str,
        event: str,
        data: dict[str, Any],
        scope: str | None = None,
    ) -> None:
        self.counter += 1
        payload = json.dumps({"event": event, "data": data, "id": self.counter}, default=str)
        for channel in {self._channel(concern, org_id, scope), self._channel(concern, org_id)}:
            for queue in list(self.subscribers.get(channel, ())):
                if queue.qsize() >= MAX_QUEUE:
                    continue
                queue.put_nowait(payload)

    async def subscribe(
        self, concern: str, org_id: uuid.UUID | str, scope: str | None = None
    ) -> AsyncIterator[str]:
        channel = self._channel(concern, org_id, scope)
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE)
        self.subscribers[channel].add(queue)
        log.info("sse subscribe", extra={"channel": channel})
        try:
            yield f"event: ready\ndata: {json.dumps({'channel': concern})}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                body = json.loads(payload)
                yield (
                    f"id: {body['id']}\nevent: {body['event']}\n"
                    f"data: {json.dumps(body['data'], default=str)}\n\n"
                )
        finally:
            self.subscribers[channel].discard(queue)
            log.info("sse unsubscribe", extra={"channel": channel})

    def depth(self) -> int:
        return sum(len(v) for v in self.subscribers.values())


_hub = Hub()


def get_hub() -> Hub:
    return _hub
