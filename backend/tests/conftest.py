"""Test fixtures.

Integration tests run against the real Postgres from ``docker compose`` -- the
invariants they prove (DB CHECK constraints, unique indexes, row locking,
append-only triggers) do not exist without it, so faking the database would make
the tests worthless.  When no database is reachable those tests skip loudly
rather than passing vacuously.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

os.environ.setdefault("KAFKA_ENABLED", "false")
os.environ.setdefault("LOG_TO_KAFKA", "false")
os.environ.setdefault("AI_PROVIDER", "fixture")
os.environ.setdefault("PAYMENT_RAIL", "simulated")
os.environ.setdefault("CHAIN_ENABLED", "false")
os.environ.setdefault("DEMO_MODE", "true")

import contextlib

from app.agents._llm import FixtureProvider, set_provider
from app.auth.security import hash_password
from app.common.redis_client import close_redis
from app.config.settings import settings
from app.db.session import dispose_engine, get_session_factory
from app.models.enums import EntityKind, OrgRole
from app.models.identity import (
    CounterpartyProfile,
    Entity,
    Organization,
    OrganizationMember,
    User,
)
from app.notifications.email import MemoryEmailProvider, set_email_provider
from app.rails.base import SimulatedRail, set_rail


def _db_url() -> str:
    return settings.DATABASE_URL_SYNC.replace("postgresql+psycopg://", "postgresql://")


def database_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(_db_url(), connect_timeout=2):
            return True
    except Exception:
        return False


DB_AVAILABLE = database_available()
requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason="no Postgres reachable -- run `docker compose up -d postgres && make db-upgrade`",
)


@pytest_asyncio.fixture(autouse=True)
async def fresh_async_clients() -> AsyncIterator[None]:
    """Dispose every module-level async client after each test.

    pytest-asyncio gives each test its own event loop.  An asyncpg pool or an
    async Redis connection created on a loop that has since closed raises
    ``RuntimeError: Event loop is closed`` the next time it is touched -- and the
    FastAPI lifespan touches both on shutdown.  Disposing here means every test
    builds its own clients on its own loop.
    """
    yield
    with contextlib.suppress(Exception):
        await dispose_engine()
    with contextlib.suppress(Exception):
        await close_redis()


@pytest.fixture(autouse=True)
def deterministic_environment() -> Any:
    """Every test runs on the offline provider, the simulated rail and an
    in-memory email provider, so nothing reaches the network.

    The rate limiter is a real feature and stays enabled -- its own test proves
    it returns 429 -- but its Redis state is cleared between tests so one test's
    logins cannot exhaust another's budget.
    """
    set_provider(FixtureProvider())
    set_rail(SimulatedRail())
    provider = MemoryEmailProvider()
    set_email_provider(provider)
    _clear_rate_limits()
    yield provider
    set_provider(None)


def _clear_rate_limits() -> None:
    try:
        import redis

        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1)
        keys = list(client.scan_iter("aegis:rl:*", count=500)) + list(
            client.scan_iter("aegis:lock:*", count=500)
        )
        if keys:
            client.delete(*keys)
        client.close()
    except Exception:
        pass  # no Redis: the limiter degrades open, and so does this reset


@pytest_asyncio.fixture
async def session() -> AsyncIterator[Any]:
    async with get_session_factory()() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
async def truncate_all() -> AsyncIterator[None]:
    """Empties every table between tests, without dropping the schema.

    ``ledger_events`` and ``attestations`` carry append-only triggers, so the
    truncation disables them for the statement and re-enables them immediately --
    the production guard is never left off.
    """
    from sqlalchemy import text

    tables = [
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
    ]
    async with get_session_factory()() as s:
        await s.execute(text("ALTER TABLE ledger_events DISABLE TRIGGER USER"))
        await s.execute(text("ALTER TABLE attestations DISABLE TRIGGER USER"))
        await s.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        await s.execute(text("ALTER TABLE ledger_events ENABLE TRIGGER USER"))
        await s.execute(text("ALTER TABLE attestations ENABLE TRIGGER USER"))
        await s.commit()
    yield


@pytest_asyncio.fixture
async def parties(truncate_all: None) -> dict[str, Any]:
    """Two organizations, two verified owners, two entities, one seller profile."""
    async with get_session_factory()() as s:
        buyer_user = User(
            email="buyer@aegistest.dev",
            email_normalized="buyer@aegistest.dev",
            name="Buyer Owner",
            password_hash=hash_password("test-password-1234"),
            email_verified_at=dt.datetime.now(dt.UTC),
        )
        seller_user = User(
            email="seller@aegistest.dev",
            email_normalized="seller@aegistest.dev",
            name="Seller Owner",
            password_hash=hash_password("test-password-1234"),
            email_verified_at=dt.datetime.now(dt.UTC),
        )
        outsider = User(
            email="outsider@aegistest.dev",
            email_normalized="outsider@aegistest.dev",
            name="Outsider Owner",
            password_hash=hash_password("test-password-1234"),
            email_verified_at=dt.datetime.now(dt.UTC),
        )
        s.add_all([buyer_user, seller_user, outsider])
        await s.flush()

        buyer_org = Organization(
            name="Buyer Org", slug=f"buyer-{uuid.uuid4().hex[:8]}", city="Bengaluru"
        )
        seller_org = Organization(
            name="Seller Org", slug=f"seller-{uuid.uuid4().hex[:8]}", city="Tiruppur"
        )
        third_org = Organization(name="Third Org", slug=f"third-{uuid.uuid4().hex[:8]}")
        s.add_all([buyer_org, seller_org, third_org])
        await s.flush()

        s.add_all(
            [
                OrganizationMember(org_id=buyer_org.id, user_id=buyer_user.id, role=OrgRole.OWNER),
                OrganizationMember(
                    org_id=seller_org.id, user_id=seller_user.id, role=OrgRole.OWNER
                ),
                OrganizationMember(org_id=third_org.id, user_id=outsider.id, role=OrgRole.OWNER),
            ]
        )
        buyer_user.active_org_id = buyer_org.id
        seller_user.active_org_id = seller_org.id
        outsider.active_org_id = third_org.id

        buyer_entity = Entity(
            org_id=buyer_org.id, kind=EntityKind.BUYER, display_name="Buyer Procurement"
        )
        seller_entity = Entity(
            org_id=seller_org.id,
            kind=EntityKind.SELLER,
            display_name="Seller Manufacturing",
            region="Tiruppur, Tamil Nadu",
            onboarded_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=400),
        )
        s.add_all([buyer_entity, seller_entity])
        await s.flush()
        s.add(
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
        await s.commit()
        return {
            "buyer_user_id": buyer_user.id,
            "seller_user_id": seller_user.id,
            "outsider_user_id": outsider.id,
            "buyer_org_id": buyer_org.id,
            "seller_org_id": seller_org.id,
            "third_org_id": third_org.id,
            "buyer_entity_id": buyer_entity.id,
            "seller_entity_id": seller_entity.id,
            "password": "test-password-1234",
        }
