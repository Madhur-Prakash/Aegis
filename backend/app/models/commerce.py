"""Deals, milestones, evidence, attestations, settlement, ledger, events.

All money is BIGINT paise (I4).  Never a float, never a Decimal at the rail
boundary.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    AuthorizedBy,
    DealState,
    Decision,
    Direction,
    MilestoneState,
    PayoutStatus,
)


class Deal(Base):
    __tablename__ = "deals"
    __table_args__ = (
        # I4, enforced by the database, not by application code.
        CheckConstraint(
            "released_paise >= 0 AND refunded_paise >= 0 AND funded_paise >= 0 "
            "AND total_paise > 0 AND released_paise + refunded_paise <= funded_paise",
            name="money_conservation",
        ),
        Index("ix_deals_parties", "org_id_buyer", "org_id_seller"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    org_id_buyer: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    org_id_seller: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    buyer_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False)
    seller_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"), nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[DealState] = mapped_column(
        Enum(DealState, native_enum=False, length=20), nullable=False, default=DealState.DRAFT
    )
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    terms_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dispute_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="apparel")
    chain_deal_id: Mapped[str | None] = mapped_column(String(66))
    chain_tx: Mapped[str | None] = mapped_column(String(66))
    funded_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    released_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunded_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    risk_score: Mapped[float | None] = mapped_column()
    risk_factors_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    pricing_tier: Mapped[str | None] = mapped_column(String(20))
    funding_deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    milestones: Mapped[list[Milestone]] = relationship(
        back_populates="deal", order_by="Milestone.seq", lazy="selectin"
    )

    @property
    def held_paise(self) -> int:
        return self.funded_paise - self.released_paise - self.refunded_paise

    @property
    def balanced(self) -> bool:
        return self.held_paise + self.released_paise + self.refunded_paise == self.funded_paise


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("deal_id", "seq", name="deal_seq"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[MilestoneState] = mapped_column(
        Enum(MilestoneState, native_enum=False, length=24),
        nullable=False,
        default=MilestoneState.PENDING,
    )
    verification_condition_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    deal: Mapped[Deal] = relationship(back_populates="milestones")


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("milestones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    merkle_root: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(40))
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifacts: Mapped[list[Artifact]] = relationship(back_populates="bundle", lazy="selectin")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_bundles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    extracted_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    extraction_quality: Mapped[float | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    bundle: Mapped[EvidenceBundle] = relationship(back_populates="artifacts")


class Attestation(Base):
    """IMMUTABLE.  Enforced by a BEFORE UPDATE OR DELETE trigger, not a convention."""

    __tablename__ = "attestations"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(20), nullable=False)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("milestones.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_bundles.id", ondelete="RESTRICT"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    decision: Mapped[Decision] = mapped_column(
        Enum(Decision, native_enum=False, length=12), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    confidence_components_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    clause_verdicts_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="fixture")
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_merkle_root: Mapped[str] = mapped_column(String(64), nullable=False)
    deterministic_prechecks_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    calibration_version: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(200), nullable=False)
    signer_key_id: Mapped[str] = mapped_column(String(60), nullable=False)
    signer_address: Mapped[str] = mapped_column(String(50), nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    chain_tx: Mapped[str | None] = mapped_column(String(66))
    chain_block: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("milestones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    raised_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    counter_claim: Mapped[str | None] = mapped_column(Text)
    arbiter_recommendation_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    human_decision_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # I8: settlement of a dispute is blocked until this is non-NULL.
    human_decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    human_decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    override_delta_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SettlementAuthorization(Base):
    __tablename__ = "settlement_authorizations"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="amount_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("milestones.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id"), nullable=False, index=True)
    # I1: no rupee moves without a qualifying attestation referencing the milestone.
    attestation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attestations.id", ondelete="RESTRICT"), nullable=False
    )
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("disputes.id"))
    direction: Mapped[Direction] = mapped_column(
        Enum(Direction, native_enum=False, length=10), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authorized_by: Mapped[AuthorizedBy] = mapped_column(
        Enum(AuthorizedBy, native_enum=False, length=10), nullable=False
    )
    authorized_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    human_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authorized_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # I6's serialisation point.  ``claimed_at`` is set by an atomic conditional
    # UPDATE before the rail is called, so exactly one worker can reach the rail
    # even with twenty concurrent deliveries and Redis down.  ``consumed_at`` is
    # set only once the payout is durable.
    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (
        # I6: exactly one payout per (milestone, direction, attempt_no).
        UniqueConstraint("idempotency_key", name="idempotency_key"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("milestones.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id"), nullable=False, index=True)
    authorization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("settlement_authorizations.id"), nullable=False
    )
    direction: Mapped[Direction] = mapped_column(
        Enum(Direction, native_enum=False, length=10), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rail: Mapped[str] = mapped_column(String(20), nullable=False)
    rail_ref: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PayoutStatus] = mapped_column(
        Enum(PayoutStatus, native_enum=False, length=12), nullable=False
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    chain_tx: Mapped[str | None] = mapped_column(String(66))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxEvent(Base):
    """I13: state change and event commit in one transaction; a relay publishes."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="event_id"),
        Index("ix_outbox_unpublished", "published_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    topic: Mapped[str] = mapped_column(String(60), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """Makes reprocessing a Kafka delivery a no-op (exactly-once effect)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    consumer_group: Mapped[str] = mapped_column(String(40), primary_key=True)
    processed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(60), nullable=False)
    consumer_group: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drained_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LedgerEvent(Base):
    """APPEND ONLY, hash-chained per deal (I5).  Trigger-enforced immutability."""

    __tablename__ = "ledger_events"
    __table_args__ = (Index("ix_ledger_deal_seq", "deal_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # A real Postgres identity column: the global append order of the whole
    # ledger.  `autoincrement=True` on a non-primary-key column does nothing, so
    # this has to be an explicit Identity or the insert sends NULL.
    seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), unique=True, nullable=False
    )
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_anchor_tx: Mapped[str | None] = mapped_column(String(66))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ChainAnchor(Base):
    """Queued and completed chain writes; an RPC failure never rolls back a payout."""

    __tablename__ = "chain_anchors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id"), nullable=False, index=True)
    milestone_seq: Mapped[int | None] = mapped_column(Integer)
    attestation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    tx_hash: Mapped[str | None] = mapped_column(String(66))
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="provider_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RiskModelArtifact(Base):
    __tablename__ = "risk_model_artifacts"

    version: Mapped[str] = mapped_column(String(30), primary_key=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    feature_names_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    model_path: Mapped[str] = mapped_column(String(400), nullable=False)
    trained_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
