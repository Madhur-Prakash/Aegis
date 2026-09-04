"""Kafka topics and event names.  Kafka never decides whether money moves."""

from __future__ import annotations

from enum import StrEnum


class Topic(StrEnum):
    SETTLEMENT = "aegis.settlement"
    REFUNDS = "aegis.refunds"
    PAYMENT_WEBHOOKS = "aegis.payment-webhooks"
    NOTIFICATIONS = "aegis.notifications"
    AUDIT = "aegis.audit"
    CHAIN = "aegis.chain"


def dlq(topic: str) -> str:
    return f"aegis.dlq.{topic.removeprefix('aegis.')}"


ALL_TOPICS: tuple[str, ...] = tuple(t.value for t in Topic) + tuple(
    dlq(t.value) for t in Topic if t is not Topic.AUDIT
)


class EventType(StrEnum):
    SETTLEMENT_AUTHORIZED = "settlement.authorized"
    SETTLEMENT_COMPLETED = "settlement.completed"
    SETTLEMENT_FAILED = "settlement.failed"
    REFUND_REQUESTED = "refund.requested"
    REFUND_COMPLETED = "refund.completed"
    REFUND_FAILED = "refund.failed"
    PAYMENT_WEBHOOK_RECEIVED = "payment.webhook.received"
    NOTIFICATION_REQUESTED = "notification.requested"
    CHAIN_ANCHOR_REQUESTED = "chain.anchor.requested"


class ConsumerGroup(StrEnum):
    SETTLEMENT = "settlement"
    REFUNDS = "refunds"
    WEBHOOKS = "webhooks"
    NOTIFICATIONS = "notifications"
    PROJECTIONS = "projections"
    CHAIN = "chain"


MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 0.5
