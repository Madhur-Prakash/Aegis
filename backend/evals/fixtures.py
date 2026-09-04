"""Database fixtures shared by the suites that need one.

Every suite that touches Postgres builds its own world here.  No suite depends
on `make seed` having run, on `make demo` having run, or on the order the
suites execute in -- so `make eval` is reproducible from an empty database.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select, text

from app.auth.security import hash_password
from app.db.session import get_session_factory
from app.models.commerce import Deal, Milestone
from app.models.enums import EntityKind, OrgRole
from app.models.identity import (
    CounterpartyProfile,
    Entity,
    Organization,
    OrganizationMember,
    User,
)

TABLES: tuple[str, ...] = (
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
)


async def reset_database() -> None:
    """Empties every table without dropping the schema.

    The append-only triggers are disabled for the truncate and re-enabled in the
    same transaction: the production guard is never left off.
    """
    async with get_session_factory()() as session:
        await session.execute(text("ALTER TABLE ledger_events DISABLE TRIGGER USER"))
        await session.execute(text("ALTER TABLE attestations DISABLE TRIGGER USER"))
        await session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await session.execute(text("ALTER TABLE ledger_events ENABLE TRIGGER USER"))
        await session.execute(text("ALTER TABLE attestations ENABLE TRIGGER USER"))
        await session.commit()


async def make_parties(prefix: str = "eval") -> dict[str, Any]:
    """Two organizations, two verified owners, two entities, one seller profile."""
    suffix = uuid.uuid4().hex[:8]
    async with get_session_factory()() as session:
        buyer = User(
            email=f"{prefix}-buyer-{suffix}@aegistest.dev",
            email_normalized=f"{prefix}-buyer-{suffix}@aegistest.dev",
            name="Eval Buyer",
            password_hash=hash_password("eval-password-1234"),
            email_verified_at=dt.datetime.now(dt.UTC),
        )
        seller = User(
            email=f"{prefix}-seller-{suffix}@aegistest.dev",
            email_normalized=f"{prefix}-seller-{suffix}@aegistest.dev",
            name="Eval Seller",
            password_hash=hash_password("eval-password-1234"),
            email_verified_at=dt.datetime.now(dt.UTC),
        )
        session.add_all([buyer, seller])
        await session.flush()

        buyer_org = Organization(name="Eval Buyer Org", slug=f"{prefix}-buyer-{suffix}")
        seller_org = Organization(name="Eval Seller Org", slug=f"{prefix}-seller-{suffix}")
        session.add_all([buyer_org, seller_org])
        await session.flush()
        session.add_all(
            [
                OrganizationMember(org_id=buyer_org.id, user_id=buyer.id, role=OrgRole.OWNER),
                OrganizationMember(org_id=seller_org.id, user_id=seller.id, role=OrgRole.OWNER),
            ]
        )

        buyer_entity = Entity(
            org_id=buyer_org.id, kind=EntityKind.BUYER, display_name="Eval Procurement"
        )
        seller_entity = Entity(
            org_id=seller_org.id,
            kind=EntityKind.SELLER,
            display_name="Eval Manufacturing",
            region="Tiruppur, Tamil Nadu",
            onboarded_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=400),
        )
        session.add_all([buyer_entity, seller_entity])
        await session.flush()
        session.add(
            CounterpartyProfile(
                entity_id=seller_entity.id,
                deals_completed=11,
                gmv_paise=314_000_000,
                disputes_raised=1,
                on_time_rate=0.91,
                largest_deal_paise=62_000_000,
                category="apparel",
            )
        )
        await session.commit()
        return {
            "buyer_org_id": buyer_org.id,
            "seller_org_id": seller_org.id,
            "buyer_entity_id": buyer_entity.id,
            "seller_entity_id": seller_entity.id,
            "buyer_user_id": buyer.id,
            "seller_user_id": seller.id,
        }


async def settled_deal(parties: dict[str, Any]) -> tuple[uuid.UUID, uuid.UUID]:
    """A funded deal whose first milestone has been verified and settled.

    Returns ``(deal_id, attestation_id)``.  Built with the real services, so the
    ledger it produces is the ledger the product produces.
    """
    from tests.factories import drain_outbox, make_deal, submit_evidence, verify_milestone

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
        attestation, _ = await verify_milestone(session, deal, milestone, bundle)
        await drain_outbox(session)
        return deal.id, attestation.id


async def deal_reference(deal_id: uuid.UUID) -> str:
    async with get_session_factory()() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        return deal.reference
