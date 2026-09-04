"""Idempotent, resumable seed (spec 8).

Running ``make seed`` three times in a row produces the same database as running
it once.  An interrupted run resumes at the step that failed.  Dropping the
database is never a precondition.

Four mechanisms, all of them present:

1. **Deterministic ids** -- every seeded row's primary key is
   ``uuid5(AEGIS_SEED_NS, natural_key)``, so a re-run recomputes the same id and
   upsert is trivial and stable across machines.
2. **Upsert, never blind insert** -- ``INSERT ... ON CONFLICT (id) DO UPDATE`` for
   mutable columns, ``DO NOTHING`` for immutable ones.
3. **Checkpoints** -- a ``SeedCheckpoint`` row per named step, keyed by a hash of
   the step's inputs.  A completed step is skipped unless its inputs changed.
4. **Advisory lock** -- the whole run holds ``pg_advisory_lock`` so two concurrent
   seeds cannot interleave.

    python -m scripts.seed          # idempotent, resumable
    python -m scripts.seed --fail-at entities   # for the resume test
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attest.canonical import payload_hash
from app.auth.security import hash_password, normalize_email
from app.common.ids import seed_id
from app.common.logging import configure_logging, get_logger
from app.config.settings import settings
from app.db.session import dispose_engine, get_session_factory
from app.models.commerce import Deal, Milestone
from app.models.enums import DealState, EntityKind, OrgRole
from app.models.identity import (
    CounterpartyProfile,
    Entity,
    Organization,
    OrganizationMember,
    SeedCheckpoint,
    User,
)

configure_logging(settings)
log = get_logger("seed")

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"
GENERATED = ROOT / "data" / "generated"

SEED_LOCK_ID = 5_411_982_337_004


class SeedFailure(RuntimeError):
    """Raised by ``--fail-at`` so the resume path can be tested for real."""


def fixture() -> dict[str, Any]:
    path = FIXTURES / "demo_deal.json"
    if not path.exists():
        raise SystemExit("data/fixtures/demo_deal.json missing -- run `make dataset` first")
    return json.loads(path.read_text(encoding="utf-8"))


async def _checkpoint_done(session: AsyncSession, step: str, digest: str) -> bool:
    row = await session.get(SeedCheckpoint, step)
    return row is not None and row.payload_hash == digest


async def _mark_done(session: AsyncSession, step: str, digest: str) -> None:
    await session.execute(
        insert(SeedCheckpoint)
        .values(step_name=step, payload_hash=digest, completed_at=dt.datetime.now(dt.UTC))
        .on_conflict_do_update(
            index_elements=[SeedCheckpoint.step_name],
            set_={"payload_hash": digest, "completed_at": dt.datetime.now(dt.UTC)},
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Steps
# ─────────────────────────────────────────────────────────────────────────────
async def step_organizations(session: AsyncSession, data: dict[str, Any]) -> None:
    for side in ("buyer", "seller"):
        party = data[side]
        await session.execute(
            insert(Organization)
            .values(
                id=seed_id(f"org:{party['slug']}"),
                name=party["org_name"],
                slug=party["slug"],
                city=party.get("city"),
            )
            .on_conflict_do_update(
                index_elements=[Organization.id],
                set_={"name": party["org_name"], "city": party.get("city")},
            )
        )


async def step_users(session: AsyncSession, data: dict[str, Any]) -> None:
    """Both demo users are created **verified**, with passwords from the
    environment -- never a hardcoded literal in the repo."""
    passwords = {
        "buyer": settings.DEMO_BUYER_PASSWORD,
        "seller": settings.DEMO_SELLER_PASSWORD,
    }
    for side in ("buyer", "seller"):
        party = data[side]
        email = party["owner_email"]
        normalized = normalize_email(email)
        password = passwords[side]
        if not password or password.startswith("CHANGE_ME"):
            raise SystemExit(
                f"DEMO_{side.upper()}_PASSWORD is not set. Copy .env.example to .env and set it."
            )
        user_id = seed_id(f"user:{normalized}")
        existing = await session.get(User, user_id)
        # The hash is recomputed only when the password actually changed: Argon2
        # is salted, so hashing every run would rewrite the row every time and
        # make the seed non-idempotent in effect even though the id is stable.
        from app.auth.security import verify_password

        if existing is not None and verify_password(existing.password_hash, password):
            password_hash = existing.password_hash
        else:
            password_hash = hash_password(password)
        await session.execute(
            insert(User)
            .values(
                id=user_id,
                email=email,
                email_normalized=normalized,
                name=party["owner_name"],
                password_hash=password_hash,
                email_verified_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                active_org_id=seed_id(f"org:{party['slug']}"),
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_={
                    "name": party["owner_name"],
                    "password_hash": password_hash,
                    "email_verified_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    "active_org_id": seed_id(f"org:{party['slug']}"),
                },
            )
        )


async def step_memberships(session: AsyncSession, data: dict[str, Any]) -> None:
    for side in ("buyer", "seller"):
        party = data[side]
        await session.execute(
            insert(OrganizationMember)
            .values(
                id=seed_id(f"member:{party['slug']}:{party['owner_email']}"),
                org_id=seed_id(f"org:{party['slug']}"),
                user_id=seed_id(f"user:{normalize_email(party['owner_email'])}"),
                role=OrgRole.OWNER,
                joined_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            )
            .on_conflict_do_nothing(index_elements=[OrganizationMember.id])
        )


async def step_entities(session: AsyncSession, data: dict[str, Any]) -> None:
    for side, kind in (("buyer", EntityKind.BUYER), ("seller", EntityKind.SELLER)):
        party = data[side]
        since = data["seller_profile"]["counterparty_since"] if side == "seller" else "2025-06-01"
        await session.execute(
            insert(Entity)
            .values(
                id=seed_id(f"entity:{party['slug']}"),
                org_id=seed_id(f"org:{party['slug']}"),
                kind=kind,
                display_name=party["entity_name"],
                region=party.get("region"),
                onboarded_at=dt.datetime.fromisoformat(since).replace(tzinfo=dt.UTC),
            )
            .on_conflict_do_update(
                index_elements=[Entity.id],
                set_={"display_name": party["entity_name"], "region": party.get("region")},
            )
        )


async def step_counterparty_profiles(session: AsyncSession, data: dict[str, Any]) -> None:
    profile = data["seller_profile"]
    await session.execute(
        insert(CounterpartyProfile)
        .values(
            entity_id=seed_id(f"entity:{data['seller']['slug']}"),
            deals_completed=profile["deals_completed"],
            gmv_paise=profile["gmv_paise"],
            disputes_raised=profile["disputes_raised"],
            disputes_lost=profile["disputes_lost"],
            on_time_rate=profile["on_time_rate"],
            largest_deal_paise=profile["largest_deal_paise"],
            category=profile["category"],
        )
        .on_conflict_do_update(
            index_elements=[CounterpartyProfile.entity_id],
            set_={
                "deals_completed": profile["deals_completed"],
                "gmv_paise": profile["gmv_paise"],
                "disputes_raised": profile["disputes_raised"],
                "on_time_rate": profile["on_time_rate"],
                "largest_deal_paise": profile["largest_deal_paise"],
                "category": profile["category"],
            },
        )
    )
    # The 30 synthetic counterparties back the reputation view; they are optional
    # so a clone without `make dataset` still seeds the demo.
    path = GENERATED / "counterparties.json"
    if not path.exists():
        return
    for record in json.loads(path.read_text(encoding="utf-8")):
        org_id = seed_id(f"org:{record['slug']}")
        entity_id = seed_id(f"entity:{record['slug']}")
        await session.execute(
            insert(Organization)
            .values(
                id=org_id,
                name=record["display_name"],
                slug=record["slug"],
                city=record["region"].split(",")[0],
            )
            .on_conflict_do_nothing(index_elements=[Organization.id])
        )
        await session.execute(
            insert(Entity)
            .values(
                id=entity_id,
                org_id=org_id,
                kind=EntityKind.SELLER,
                display_name=record["display_name"],
                region=record["region"],
                onboarded_at=dt.datetime.now(dt.UTC)
                - dt.timedelta(days=int(record["counterparty_age_days"])),
            )
            .on_conflict_do_nothing(index_elements=[Entity.id])
        )
        await session.execute(
            insert(CounterpartyProfile)
            .values(
                entity_id=entity_id,
                deals_completed=record["deals_completed"],
                gmv_paise=record["gmv_paise"],
                disputes_raised=record["disputes_raised"],
                disputes_lost=record["disputes_lost"],
                on_time_rate=record["on_time_rate"],
                largest_deal_paise=record["largest_deal_paise"],
                category=record["category"],
            )
            .on_conflict_do_update(
                index_elements=[CounterpartyProfile.entity_id],
                set_={"deals_completed": record["deals_completed"]},
            )
        )


async def step_demo_deal(session: AsyncSession, data: dict[str, Any]) -> None:
    deal_id = seed_id(f"deal:{data['reference']}")
    terms = {
        "version": 1,
        "title": data["title"],
        "total_paise": data["total_paise"],
        "currency": "INR",
        "category": data["category"],
        "dispute_window_days": data["dispute_window_days"],
        "tolerance": data["tolerance"],
        "milestones": [
            {
                "seq": m["seq"],
                "title": m["title"],
                "amount_paise": m["amount_paise"],
                "verification_condition": m["verification_condition"],
            }
            for m in data["milestones"]
        ],
    }
    from app.attest.eip712 import deal_id_bytes32

    await session.execute(
        insert(Deal)
        .values(
            id=deal_id,
            reference=data["reference"],
            title=data["title"],
            org_id_buyer=seed_id(f"org:{data['buyer']['slug']}"),
            org_id_seller=seed_id(f"org:{data['seller']['slug']}"),
            buyer_entity_id=seed_id(f"entity:{data['buyer']['slug']}"),
            seller_entity_id=seed_id(f"entity:{data['seller']['slug']}"),
            total_paise=data["total_paise"],
            state=DealState.DRAFT,
            terms_json=terms,
            terms_hash=payload_hash(terms),
            dispute_window_days=data["dispute_window_days"],
            category=data["category"],
            chain_deal_id=deal_id_bytes32(str(deal_id)),
            funding_deadline=dt.datetime.now(dt.UTC) + dt.timedelta(days=7),
        )
        # The deal's financial state is IMMUTABLE from the seed's point of view:
        # re-seeding must never reset a demo that has already moved money.
        .on_conflict_do_nothing(index_elements=[Deal.id])
    )


async def step_milestones(session: AsyncSession, data: dict[str, Any]) -> None:
    deal_id = seed_id(f"deal:{data['reference']}")
    for m in data["milestones"]:
        await session.execute(
            insert(Milestone)
            .values(
                id=seed_id(f"milestone:{data['reference']}:{m['seq']}"),
                deal_id=deal_id,
                seq=m["seq"],
                title=m["title"],
                amount_paise=m["amount_paise"],
                verification_condition_json=m["verification_condition"],
            )
            .on_conflict_do_nothing(index_elements=[Milestone.id])
        )


async def step_risk_model_artifacts(session: AsyncSession, data: dict[str, Any]) -> None:
    from app.models.commerce import RiskModelArtifact

    meta_path = GENERATED / "risk_model.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    await session.execute(
        insert(RiskModelArtifact)
        .values(
            version=str(meta.get("version", "lgbm-1")),
            metrics_json=meta.get("metrics", {}),
            feature_names_json=meta.get("feature_names", []),
            model_path=str(GENERATED / "risk_lgbm.txt"),
        )
        .on_conflict_do_update(
            index_elements=[RiskModelArtifact.version],
            set_={"metrics_json": meta.get("metrics", {})},
        )
    )


STEPS: tuple[tuple[str, Any], ...] = (
    ("organizations", step_organizations),
    ("users", step_users),
    ("memberships", step_memberships),
    ("entities", step_entities),
    ("counterparty_profiles", step_counterparty_profiles),
    ("demo_deal", step_demo_deal),
    ("milestones", step_milestones),
    ("risk_model_artifacts", step_risk_model_artifacts),
)


async def run_seed(fail_at: str | None = None) -> dict[str, Any]:
    data = fixture()
    digest = payload_hash(data)
    summary: dict[str, Any] = {"steps": {}, "skipped": 0, "applied": 0}

    factory = get_session_factory()
    # One connection holds the advisory lock for the whole run.
    async with factory() as lock_session:
        await lock_session.execute(text("SELECT pg_advisory_lock(:id)"), {"id": SEED_LOCK_ID})
        await lock_session.commit()
        try:
            for name, fn in STEPS:
                step_digest = payload_hash({"step": name, "inputs": digest})
                async with factory() as session:
                    if await _checkpoint_done(session, name, step_digest):
                        summary["steps"][name] = "skipped"
                        summary["skipped"] += 1
                        continue
                if fail_at == name:
                    summary["steps"][name] = "failed"
                    log.warning("seed step failed deliberately", extra={"step": name})
                    raise SeedFailure(f"--fail-at {name}")
                # Each step runs in its own transaction, so an interruption leaves
                # completed steps durable and the failed one untouched.
                async with factory() as session:
                    await fn(session, data)
                    await _mark_done(session, name, step_digest)
                    await session.commit()
                summary["steps"][name] = "applied"
                summary["applied"] += 1
                log.info("seed step applied", extra={"step": name})
        finally:
            await lock_session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": SEED_LOCK_ID})
            await lock_session.commit()

    async with factory() as session:
        counts = {}
        for model, label in (
            (Organization, "organizations"),
            (User, "users"),
            (Entity, "entities"),
            (Deal, "deals"),
            (Milestone, "milestones"),
        ):
            from sqlalchemy import func

            counts[label] = int(
                (await session.execute(select(func.count()).select_from(model))).scalar() or 0
            )
        summary["counts"] = counts
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Aegis demo data (idempotent)")
    parser.add_argument("--fail-at", default=None, help="raise at this step (resume test)")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    args = parser.parse_args()
    try:
        summary = await run_seed(args.fail_at)
    finally:
        await dispose_engine()
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print("seed complete")
        for name, state in summary["steps"].items():
            print(f"  {state:8s} {name}")
        print(f"  applied {summary['applied']}, skipped {summary['skipped']}")
        print("  counts: " + ", ".join(f"{k}={v}" for k, v in summary["counts"].items()))
        print()
        print(f"  buyer  {settings.DEMO_BUYER_EMAIL}")
        print(f"  seller {settings.DEMO_SELLER_EMAIL}")
        print("  passwords come from DEMO_BUYER_PASSWORD / DEMO_SELLER_PASSWORD in .env")


if __name__ == "__main__":
    asyncio.run(main())
