# AEGIS — FULL BUILD / BUILDER-READY MASTER PROMPT

> **Programmable escrow for agentic commerce.** Two parties who do not trust each other — one or
> both represented by AI agents — transact through an AI-mediated milestone escrow. INR settles on
> Razorpay test-mode rails. The deal's rulebook and every AI decision's provenance are anchored
> on-chain so the whole thing can be independently audited later.
>
> Built for: **Razorpay AI Buildathon, Track 05 (Open Track)**.
> Submission deliverables: public repo + 5-minute video + architecture doc.

---

# 0. ROLE AND EXECUTION CONTRACT

You are the principal engineer building **Aegis**. You are not producing a prototype of
disconnected mock screens, and you are not producing a plan.

**Build the complete working system in one implementation pass.** Frontend, backend, database,
auth, organizations, agent workflows, AI verifier, AI arbiter, deterministic settlement engine,
Razorpay test-mode integration, Kafka event backbone, Redis, object storage, blockchain contract,
on-chain provenance, cryptographic attestations, audit ledger, ML risk model, synthetic dataset,
evaluation harness, tests, Docker, Makefile, idempotent seeding, docs, demo fixtures.

Rules of engagement:

1. **Do not stop after a partial phase and ask for approval.** Section 35 gives an internal
   dependency order; work through it continuously.
2. **Do not ask me to implement missing subsystems later.** Everything in this document is in
   scope for this build.
3. **Never violate section 3 (INVARIANTS).** They are load-bearing safety properties enforced in
   code, DB constraints, CI checks and tests — not style preferences.
4. **Never report a number you did not measure.** Every metric in the README comes from
   `make eval`. Fabricating a metric, a transaction hash, a payout, or a test result is the single
   worst outcome of this build — worse than an unfinished feature.
5. **When the spec is ambiguous, choose the option that makes money movement safer**, record the
   decision in `docs/DECISIONS.md`, and continue.
6. **Do not add anything in section 38 (NO FEATURE CREEP).**
7. If a test fails, fix the underlying cause. Never weaken a test to make CI green.

At the end, produce the BUILD STATUS report in section 36.

---

# 1. READ ORDER AND PRECEDENCE

This file is the single source of truth. If any other document in the repo conflicts with it,
this file wins, and you note the conflict in `docs/DECISIONS.md`.

**This document explicitly overrides two things from earlier drafts of the Aegis spec:**

| Earlier draft said | Now |
|---|---|
| Build in 7 phases, stop and report at each exit gate | **Build everything in one pass.** Phases survive only as an internal dependency order (§35) |
| Auth, registration, password reset, email verification, orgs/teams are OUT of scope | **All IN scope and fully implemented** (§14, §15) |
| Notifications, email, chat, mobile, i18n, dark mode are OUT of scope | **All IN scope** (§26, §27) |

Everything else from the product thesis, domain model, state machines, verifier architecture,
arbiter architecture, provenance model, blockchain design, evaluation methodology and demo
scenario is preserved and expanded below.

---

# 2. PRODUCT THESIS

The problem: two strangers want to trade. The buyer will not send ₹4.2L to a seller it has never
met; the seller will not cut fabric before seeing money. Normally a broker takes 8%, or the deal
never happens.

The 2026 problem on top of it: **the buyer may be an AI agent.** So a new question appears that
no existing system can answer — *who authorized this payment, on what evidence, and can you prove
it six months from now?*

Aegis must be able to answer all ten of these, for any rupee that moved:

1. Who authorized the transaction? 2. What exactly were the agreed terms? 3. What evidence was
submitted? 4. What did the AI verify? 5. What did the AI **fail** to verify? 6. Which model and
version produced the recommendation? 7. What confidence was computed, and how? 8. Why was money
released? 9. Who approved the dispute resolution? 10. Can all of the above be independently
verified later, by someone who trusts neither party?

### The core principle

**The LLM never moves money.** The LLM produces a structured, signed attestation. A separate
deterministic settlement engine validates that attestation and performs the financial action.
This separation is mandatory and mechanically enforced (I2).

### Why a blockchain is here — put this in the README and say it in the first 20 seconds of the video

> Money never touches the chain. Rupees move on Razorpay the entire time. The chain holds exactly
> two things: the rulebook of the deal, so neither party can quietly edit it after the fact; and a
> fingerprint of every AI decision, so "the AI decided" can be replaced with a verifiable record.
> If the buyer kept that in their own database, the seller would have to trust the buyer. Nobody
> trusts anybody. That is the entire reason it goes somewhere neither party controls.

Anything not covered by that paragraph does not go on the chain. No token, no coin, no staking, no
AMM, no bridge, no wallet onboarding flow.

---

# 3. NON-NEGOTIABLE INVARIANTS

Enforce each in code **and** prove each with a test. Put this table in the README verbatim; it is
the strongest single page of the submission.

| # | Invariant | Enforced by |
|---|---|---|
| **I1** | No rupee moves without a qualifying `Attestation` row referencing that milestone and evidence bundle. | FK + NOT NULL, settlement engine guard, integration test |
| **I2** | LLM output never triggers a transfer. `agents/` may not import `settlement/`, `rails/`, or `payments/`. | Import-lint in CI that fails on violation |
| **I3** | `RELEASE_THRESHOLD = 0.85`, `REJECT_THRESHOLD = 0.35`. `conf >= 0.85` **and** every required clause verifiably satisfied → RELEASE. `0.35 < conf < 0.85` → ESCALATE. `conf <= 0.35` → REJECT. A required `UNVERIFIABLE` clause can **never** auto-release. No urgent bypass, no prompt-level exception, no admin override of this rule. | Pure-Python guard in settlement engine + Suite A |
| **I4** | For every deal, at every valid state: `held + released + refunded == funded`. Money is integer paise (`BIGINT`). Never floats, never `Decimal` at the rail boundary. | DB CHECK constraint + Hypothesis property test |
| **I5** | Every valid state transition creates exactly one append-only, hash-chained `LedgerEvent`. Illegal transitions raise, are logged, and never silently pass. | Transition decorator + ledger verify endpoint + test |
| **I6** | Every money operation is idempotent on `(milestone_id, direction, attempt_no)`. 20 simultaneous release attempts ⇒ exactly 1 payout and exactly 1 rail call. | Unique index + Redis lock + `IdempotencyRecord` + concurrency test |
| **I7** | On-chain data is hashes, ids, integers, enums and signatures only. Never names, emails, addresses, documents, invoice contents, messages or raw evidence. | Chain adapter signature accepts `bytes32`/ints only + lint test |
| **I8** | The arbiter is advisory. `Dispute.human_decided_by` must be non-NULL before any dispute settlement. Overrides are logged with the delta. | DB constraint + settlement guard + test |
| **I9** | Expected business failures return typed, machine-readable errors — never a bare 500. | Typed error envelope + API tests |
| **I10** | State machines are explicit transition tables. No scattered state-mutating `if`s. Unknown `(state, event)` raises `IllegalTransition`. | Table-driven transitions + exhaustiveness test |
| **I11** | No secrets committed. `.env.example` only, test-mode credentials only. Logs never contain passwords, tokens, API keys, private keys, raw PII or raw evidence. | Secret scan in CI + logifyx masking + log-assertion test |
| **I12** | **Tenant isolation.** No user may read or write another organization's deals, evidence, attestations, payouts, ledger records, messages or notifications. Every query is tenant-scoped. | Repository-layer org scoping + a dedicated cross-tenant test suite |
| **I13** | **No dual-write.** A financial state change and its Kafka event are never two independent writes. Use a transactional outbox: state + outbox row commit in one DB transaction; a relay publishes. | Outbox table + relay + crash-injection test |

The typed error envelope (I9):

```json
{
  "error": {
    "code": "CONFIDENCE_BELOW_RELEASE_THRESHOLD",
    "message": "Evidence cannot be released automatically.",
    "details": { "confidence": 0.51, "threshold": 0.85, "unverifiable_clauses": ["c2"] },
    "request_id": "req_01J..."
  }
}
```

---

# 4. REPOSITORY STRUCTURE

```
aegis/
├── README.md                      # thesis → why-chain → invariants → demo → eval → rails → deploy → limits
├── AEGIS_BUILD_SPEC.md            # this file
├── Makefile                       # self-documenting; bare `make` prints help
├── docker-compose.yml             # full stack, healthchecked
├── docker-compose.dev.yml         # hot reload overrides
├── .env.example                   # complete, no realistic-looking fake secrets
├── .gitignore  .dockerignore
├── ui/                            # THE DESIGN PACK — read before any frontend code (§25)
│   ├── README.md  00-DESIGN-SYSTEM.md  01-MOTION-SYSTEM.md
│   ├── 02-PRELOADER-AND-HERO.md  03-DROP-IN-REVEALS.md
│   ├── 04-CURSOR-AND-HOVER.md  05-SCRAMBLE-CTA.md
│   ├── 06-SCREEN-BLUEPRINTS.md  07-REFERENCE-FRAMES.md
│   └── reference/                 # 16 curated stills from the reference recordings
├── docs/
│   ├── ARCHITECTURE.md  DATA.md  DECISIONS.md  DEMO.md
│   ├── SECURITY.md  API.md  OPERATIONS.md  LIMITATIONS.md
│   └── UI_MOTION.md               # §25 — copy of ui/ (the design pack)
├── contracts/                     # Foundry
│   ├── src/AegisEscrow.sol
│   ├── test/  script/  foundry.toml
├── backend/
│   ├── pyproject.toml  uv.lock  alembic.ini
│   ├── migrations/versions/
│   ├── app/
│   │   ├── main.py                # FastAPI app + lifespan
│   │   ├── worker.py              # Kafka consumer entrypoint
│   │   ├── relay.py               # outbox → Kafka relay entrypoint
│   │   ├── config/                # pydantic-settings, one Settings object
│   │   ├── common/                # logging, errors, canonical json, ids, deps, pagination
│   │   ├── api/v1/                # routers only — thin
│   │   ├── auth/  users/  organizations/
│   │   ├── deals/                 # state machine, transition table, guards
│   │   ├── evidence/              # upload, storage, merkle bundling
│   │   ├── agents/verifier/  agents/arbiter/     # MUST NOT import settlement|rails|payments
│   │   ├── settlement/            # deterministic money engine
│   │   ├── rails/                 # PaymentRail: RazorpayRail | SimulatedRail
│   │   ├── payments/              # webhooks, reconciliation
│   │   ├── events/                # kafka producer/consumer, outbox, topics, DLQ
│   │   ├── attest/                # canonical json, sha256, merkle, EIP-712
│   │   ├── chain/                 # contract adapter
│   │   ├── ledger/                # hash-chained append-only log
│   │   ├── risk/                  # LightGBM model + explanations
│   │   ├── notifications/  chat/  realtime/
│   │   └── storage/               # ObjectStore: LocalStore | S3Store
│   ├── evals/{suite_a,suite_b,suite_c,report_d,report_e}/
│   ├── scripts/{seed.py,generate_dataset.py,deploy_contract.py}
│   └── tests/{unit,integration,api,security,property,concurrency}/
├── frontend/
│   ├── package.json  next.config.ts  tailwind.config.ts
│   ├── app/                       # App Router
│   ├── components/                # ui/ (shadcn) + domain/
│   ├── design/                    # §25 — tokens.css + motion.ts  ← the ONLY visual-identity files
│   │                              #        copy both VERBATIM from ui/00 and ui/01
│   ├── lib/  hooks/  i18n/{en.json,hi.json}
├── data/{fixtures,generated}/
└── .github/workflows/ci.yml
```

**Modular monolith, not microservices.** Three process entrypoints (`main.py`, `worker.py`,
`relay.py`) share one codebase and one database. No Kubernetes, no Terraform, no service mesh.

---

# 5. PYTHON ENVIRONMENT — uv

Use **uv** for dependency and environment management. `pyproject.toml` + committed `uv.lock` are
the dependency definition. A hand-maintained `requirements.txt` is not acceptable as the primary
source; generate one only if some tool demands it.

- Local: `uv sync --frozen` behind `make install`; `uv run` for every command.
- Docker: multi-stage build, `uv sync --frozen --no-dev` in the builder, copy the venv into a slim
  runtime layer. Cache-mount `uv` so rebuilds are fast.
- Pin Python `3.12` in `[project.requires-python]` and in the image tag.
- `make lint` = `ruff check` + `ruff format --check` + `mypy app`. `make format` = `ruff format`.

Required backend dependencies (minimum): `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2.0`,
`alembic`, `pydantic>=2`, `pydantic-settings`, `asyncpg`/`psycopg[binary]`, `redis`,
`aiokafka` (or `confluent-kafka`), `anthropic`, `argon2-cffi`, `pyjwt`, `python-multipart`,
`boto3` (S3-compatible store), `eth-account`, `web3`, `lightgbm`, `scikit-learn`, `pandas`,
`pyarrow`, `matplotlib`, `logifyx>=1.1.3`, and dev: `pytest`, `pytest-asyncio`, `hypothesis`,
`httpx`, `ruff`, `mypy`, `testcontainers` (or compose-based test fixtures).

---

# 6. LOGGING — logifyx

Use **logifyx** (PyPI `logifyx`, ≥ 1.1.3) for all backend logging. Its native features map
directly onto this project's requirements: structured output, automatic masking of sensitive
data, and Kafka streaming.

Wrap it in exactly one module, `app/common/logging.py`, so nothing else imports logifyx directly:

```python
# app/common/logging.py
from logifyx import setup_logify, get_logify_logger, ContextLoggerAdapter, flush, shutdown

_MASK_FIELDS = (
    "password", "password_hash", "token", "access_token", "refresh_token",
    "authorization", "api_key", "secret", "private_key", "operator_private_key",
    "verifier_private_key", "razorpay_key_secret", "webhook_secret",
    "email", "phone", "address", "artifact_bytes", "raw_evidence", "otp",
)

def configure_logging(settings) -> None:
    """Call once, from the FastAPI lifespan and from every worker entrypoint."""
    setup_logify(
        service=settings.SERVICE_NAME,          # aegis-api | aegis-worker | aegis-relay
        level=settings.LOG_LEVEL,
        json=True,                              # structured everywhere, including local
        mask_fields=_MASK_FIELDS,
        kafka={"bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
               "topic": "aegis.audit"} if settings.LOG_TO_KAFKA else None,
    )

def get_logger(name: str, **context):
    """Returns a context-bound logger. Always bind the ids you have."""
    return ContextLoggerAdapter(get_logify_logger(name), context)
```

- Bind context on every request: `request_id`, `org_id`, `user_id`, and where applicable
  `deal_id`, `milestone_id`, `attestation_id`, `settlement_event_id`, `payout_id`,
  `idempotency_key`, `kafka_message_id`.
- Call `flush()` before any worker process exits and `shutdown()` in the FastAPI lifespan
  teardown, or you will silently lose the last log lines — the ones you need after a crash.
- The mask list above is the mechanical half of **I11**. Write a test that logs a payload
  containing each masked field and asserts the value does not appear in the emitted record.
- Every financial operation must be traceable end to end through logs alone:
  `request_id → deal_id → milestone_id → attestation_id → settlement_event_id → payout_id → rail_ref`.
- **Verify the exact API surface against the installed version before writing the wrapper.** If a
  keyword above does not exist in 1.1.3, adapt the wrapper — never the call sites — and record
  what you changed in `docs/DECISIONS.md`. Because everything goes through `get_logger()`, the
  entire logging stack is swappable in one file.

Log exactly one line per state transition, per AI call (with usage/latency), per settlement
decision, per rail call, per Kafka publish and consume, and per authorization failure.

---

# 7. DATABASE — POSTGRES + ALEMBIC

PostgreSQL 16 is the sole source of truth for financial state. Redis and Kafka never hold
authoritative state.

- Use real constraints: foreign keys, unique indexes, CHECK constraints, `NOT NULL`, and
  `SELECT ... FOR UPDATE` row locking on the deal row when settling. Application code alone is not
  an acceptable guarantee for I1, I4 or I6.
- The money-conservation CHECK (I4) lives on `Deal`:
  `CHECK (released_paise >= 0 AND refunded_paise >= 0 AND released_paise + refunded_paise <= funded_paise)`.
- `Attestation` and `LedgerEvent` are append-only. Enforce with a `BEFORE UPDATE OR DELETE`
  trigger that raises, not just a code convention.
- All schema changes go through **Alembic**. Migrations are committed, reviewed, reversible where
  reasonable, and never hand-edited into a running database.
  `make db-migrate m="..."` / `make db-upgrade` / `make db-downgrade`.
- **Migrations run from exactly one place.** In dev, an entrypoint runs `alembic upgrade head`
  guarded by a Postgres advisory lock so the api, worker and relay containers starting at once
  cannot race. Never leave migration to "whichever container boots first".

---

# 8. SEEDING — IDEMPOTENT AND RESUMABLE

`make seed` must be safe to run any number of times, and safe to re-run after being interrupted
halfway. Running `make seed` three times in a row produces the same database as running it once —
no duplicate users, organizations, entities, deals, milestones, evidence or fixtures.

Mechanism — implement all four parts:

1. **Deterministic ids.** Every seeded row gets a UUIDv5 derived from a stable namespace and a
   natural key: `uuid5(AEGIS_SEED_NS, "user:buyer@meridian.demo")`. Re-running recomputes the same
   id, so upsert is trivial and stable across machines.
2. **Upsert, never blind insert.** `INSERT ... ON CONFLICT (id) DO UPDATE` for mutable fields;
   `DO NOTHING` for immutable ones. Never `DELETE` the database as a precondition.
3. **Checkpoints.** A `SeedCheckpoint(step_name PK, completed_at, payload_hash)` table. Each step
   is a named function; completed steps are skipped unless their input hash changed. Steps run in
   dependency order, each in its own transaction:
   `organizations → users → memberships → entities → counterparty_profiles → demo_deal →
    milestones → evidence_bundles → artifacts → risk_model_artifacts`.
   If step 6 fails, re-running `make seed` resumes at step 6.
4. **Advisory lock.** Wrap the whole run in `pg_advisory_lock` so two concurrent seeds cannot
   interleave.

Also provide `make reset-seed` — drops and recreates the schema, re-runs migrations, re-seeds — as
the explicit, clearly-labelled destructive path. It must never be required just because a seed run
was interrupted.

Write a test that: seeds, seeds again, asserts row counts are unchanged; then seeds with a step
forced to raise, re-seeds, and asserts the final state is complete and correct.

---

# 9. REDIS

Use Redis only where it is genuinely justified:

- **Distributed locks** around rail calls (belt to the DB unique-index braces, I6). Use
  `SET NX PX` with a token and safe release; never a naked `DEL`.
- **Rate limiting** on `/auth/register`, `/auth/login`, `/auth/password-reset`,
  `/auth/verify-email`, evidence upload and verification triggers. Sliding window per IP and per
  account. Return `429` with a typed error and `Retry-After`.
- **Caching** read-heavy derived data: reputation summaries, risk scores, chain read-backs.
  Always with a TTL, always reconstructible from Postgres.
- **Short-lived state**: email-verification and password-reset token lookups, SSE fan-out hints.

Never store deals, balances, attestations or ledger state in Redis. If Redis is flushed, the
application must lose nothing but cache warmth.

---

# 10. KAFKA — THE PAYMENT AND SETTLEMENT BACKBONE

Kafka is mandatory and must genuinely participate in the payment flow, not sit decoratively in the
architecture diagram.

**The governing rule: Kafka does not decide whether money moves.** The deterministic settlement
engine decides, inside a database transaction. Kafka transports the *already-authorized* command
and the resulting facts.

### Topics

```
aegis.settlement          # settlement.authorized, settlement.completed, settlement.failed
aegis.refunds             # refund.requested, refund.completed, refund.failed
aegis.payment-webhooks    # payment.webhook.received
aegis.notifications       # notification.requested
aegis.audit               # append-only audit/log stream (logifyx sink)
aegis.dlq.<topic>         # dead letters per topic
```

Single broker in **KRaft mode** (no Zookeeper) for local development, plus `kafka-ui` for the
demo. Create topics idempotently on startup.

### The flow — implement exactly this

```
Verifier  →  Attestation (signed, persisted)
                      │
                      ▼
        Deterministic Settlement Engine
        ├─ re-check I1  (qualifying attestation exists)
        ├─ re-check I3  (decision + confidence + no UNVERIFIABLE required clause)
        ├─ re-check I4  (this release keeps the sum invariant)
        ├─ re-check I8  (dispute path: human_decided_by present)
        │
        ▼  ONE DB TRANSACTION (I13)
        ├─ milestone → RELEASE_APPROVED
        ├─ INSERT SettlementAuthorization
        ├─ INSERT IdempotencyRecord (unique)
        ├─ INSERT LedgerEvent (hash-chained)
        └─ INSERT OutboxEvent(settlement.authorized)
                      │
                      ▼  outbox relay (relay.py)
                   Kafka aegis.settlement
                      │
                      ▼  Settlement Worker (worker.py)
        ├─ Redis lock on milestone
        ├─ idempotency check → already done? ack and stop
        ├─ RE-READ authorization from Postgres and RE-VALIDATE
        │    (a stale or replayed event must never release money)
        ├─ PaymentRail call
        ├─ persist Payout + LedgerEvent (one transaction)
        └─ OutboxEvent(settlement.completed | settlement.failed)
                      │
                      ▼
        Kafka → ledger projection, notifications, SSE to UI
```

### Consumer requirements

- **Idempotent by construction.** Key every message with an `event_id`; a `ProcessedEvent` table
  makes reprocessing a no-op. A duplicate delivery must never cause a duplicate payment — prove it
  with a test that delivers the same message 20 times.
- **Re-authorize before acting.** The consumer trusts the database, never the message payload.
- Manual offset commit *after* successful processing. At-least-once delivery, exactly-once effect.
- Bounded retry with exponential backoff, then **dead-letter** with the full failure reason. A DLQ
  message is a visible operational event, not a silent drop.
- Consumer groups per concern: `settlement`, `refunds`, `webhooks`, `notifications`, `projections`.

### Crash-injection test (proves I13)

Commit the outbox row, kill the relay before publish, restart, assert the event publishes exactly
once and the payout happens exactly once. This test is worth more to your submission than three
extra screens.

---

# 11. OBJECT STORAGE FOR EVIDENCE

Evidence artifacts (PDFs, images) are files and need a home. Define one interface:

```python
class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> StoredRef: ...
    def get(self, key: str) -> bytes: ...
    def presign_get(self, key: str, ttl_s: int) -> str: ...
    def delete(self, key: str) -> None: ...
```

- `LocalStore` — a Docker volume, default for development. `S3Store` — boto3, works against MinIO
  or real S3, selected by env var. MinIO may be included in compose as an optional profile.
- On upload: stream to storage, compute `sha256` while streaming, store the hash on `Artifact`,
  and never trust a client-supplied hash.
- Enforce max size, an allowlist of MIME types, and a real content sniff — not just the extension.
- Access is tenant-scoped (I12) and served through short-lived presigned URLs; never a public path.
- Artifact bytes are never logged and never sent on-chain (I7, I11).

---

# 12. AUTHENTICATION

Fully in scope. Implement completely.

**Registration** — email + password + name. Email unique (case-insensitive, store normalized).
Password hashed with **Argon2id** (`argon2-cffi`), sensible memory/time cost, never MD5/SHA/bcrypt-
by-hand. Password policy: minimum length 10, reject a known-weak list, no composition theatre.

**Login / session** — short-lived access token (JWT, 15 min) + rotating refresh token stored
server-side and revocable. Refresh rotation with reuse detection: a replayed refresh token
invalidates the whole family and logs a security event. `httpOnly`, `Secure`, `SameSite=Lax`
cookies for the browser; `Authorization: Bearer` accepted for API clients. Logout revokes.
Generic error message on bad credentials — never reveal whether the email exists.

**Email verification**

```
REGISTER → VERIFICATION_REQUIRED → (email token) → VERIFIED
```

Unverified accounts may sign in but cannot create or fund deals, submit evidence, or approve
anything. Enforce that in a dependency, not in the UI.

**Password reset**

```
forgot-password → reset token → new password
```

Tokens: cryptographically random, **hashed at rest**, single-use, 30-minute expiry, invalidated by
a successful reset or a password change, never logged, never returned in an API response. The
forgot-password endpoint responds identically whether or not the account exists. A successful reset
revokes every existing session.

**Email delivery** — `EmailProvider` interface with `DevelopmentEmailProvider` writing to
**Mailpit** in compose. The project must run end to end locally with no external email service and
no API key.

Rate-limit every auth endpoint (§9). Log every auth decision with the reason; never log the
credential.

---

# 13. ORGANIZATIONS, TEAMS, TENANCY

```
Organization(id, name, slug, created_at)
OrganizationMember(org_id, user_id, role, joined_at)        UNIQUE(org_id, user_id)
Invitation(id, org_id, email, role, token_hash, expires_at, accepted_at, invited_by)
```

Roles: `OWNER` > `ADMIN` > `MEMBER` > `VIEWER`.

| Capability | OWNER | ADMIN | MEMBER | VIEWER |
|---|---|---|---|---|
| Create/fund deals | ✓ | ✓ | ✓ | — |
| Submit evidence | ✓ | ✓ | ✓ | — |
| Approve human review / disputes | ✓ | ✓ | — | — |
| Invite / remove members, change roles | ✓ | ✓ | — | — |
| View deals, ledger, provenance | ✓ | ✓ | ✓ | ✓ |
| Delete organization, transfer ownership | ✓ | — | — | — |

Implement: create org, list members, invite by email (token flow), accept invite, change role,
remove member, switch active organization, and last-owner protection (an org can never be left
without an OWNER).

**Tenant isolation (I12) is architectural, not per-endpoint discipline.** Put org scoping in the
repository/query layer so a developer cannot forget it: every query for a tenant-owned entity takes
an `org_id` and filters on it. Authorization is a FastAPI dependency chain
(`current_user → current_membership → require_role(...) → require_resource_in_org(...)`), and it
returns `404` — not `403` — for another tenant's resource, so ids do not leak by probing.

**A dedicated security test suite (§31) must attempt cross-tenant access on every single
tenant-owned route and assert failure.** Enumerate routes programmatically so a new route added
without scoping fails the suite automatically.

---

# 14. DEMO USERS AND THE `?as=` SWITCH

Seed two organizations, two entities, and real users:

```
Org "Meridian Label"   (Bangalore)   Entity kind BUYER
    owner@meridian.demo      OWNER
Org "Tirupur Exports"                Entity kind SELLER
    owner@tirupur.demo       OWNER
```

Both seeded users are created **verified**, with passwords from `.env` (never a hardcoded literal
in the repo).

The demo convenience switch:

```
/deals/demo?as=buyer
/deals/demo?as=seller
```

**It must not bypass authorization.** Implement it as a dev-only endpoint `POST /api/v1/dev/assume`
that is registered **only when `DEMO_MODE=true`**, accepts `buyer|seller`, and issues a genuine
session for the corresponding seeded user through the normal login path. Every downstream request
is then an ordinary authenticated, tenant-scoped request. In the code, the guard is a hard
`if not settings.DEMO_MODE: raise NotFound` at router registration time — not a runtime flag check
inside a handler. Document it in `docs/SECURITY.md` as a deliberate demo affordance.

---

# 15. DOMAIN MODEL

All money is `BIGINT` paise. Never floats.

```
User(id, email_normalized UNIQUE, email, name, password_hash, email_verified_at,
     status, created_at)
RefreshToken(id, user_id, token_hash, family_id, expires_at, revoked_at, replaced_by)
Organization / OrganizationMember / Invitation                        # §13

Entity(id, org_id, kind[BUYER|SELLER], display_name, pubkey, created_at)

Deal(id, org_id_buyer, org_id_seller, buyer_entity_id, seller_entity_id, total_paise,
     state, terms_json, terms_hash, dispute_window_days, chain_deal_id, chain_tx,
     funded_paise, released_paise, refunded_paise, risk_score, pricing_tier, created_at)
     CHECK (released_paise + refunded_paise <= funded_paise)

Milestone(id, deal_id, seq, title, amount_paise, state, verification_condition_json,
          released_at)                                        UNIQUE(deal_id, seq)

# verification_condition_json
{ clauses: [{ id, kind, description, params, required }],
  required_artifact_types: [...],
  tolerance: {...} }
# clause kinds: ARTIFACT_PRESENT | DATE_WITHIN | AMOUNT_AT_LEAST | QUANTITY_AT_LEAST
#               | FIELD_EQUALS | FIELD_MATCHES_SPEC | VISUAL_CONSISTENT_WITH

EvidenceBundle(id, milestone_id, submitted_by_user_id, merkle_root, submitted_at)
Artifact(id, bundle_id, artifact_type, filename, mime, storage_key, size_bytes,
         sha256, extracted_json, extraction_quality)

Attestation(id, milestone_id, bundle_id, decision[RELEASE|REJECT|ESCALATE],
            confidence NUMERIC(4,3), clause_verdicts_json, reasoning,
            model_id, model_version, prompt_hash, evidence_merkle_root,
            deterministic_prechecks_json, thresholds_json, calibration_version,
            signature, signer_key_id, chain_tx, created_at)      # IMMUTABLE

Dispute(id, deal_id, milestone_id, raised_by_user_id, claim, counter_claim,
        arbiter_recommendation_json, human_decision_json, human_decided_by,
        override_delta_paise, resolved_at)

SettlementAuthorization(id, milestone_id, attestation_id, direction, amount_paise,
                        authorized_at, authorized_by[ENGINE|HUMAN], consumed_at)
Payout(id, milestone_id, direction[RELEASE|REFUND], amount_paise, rail,
       rail_ref, idempotency_key UNIQUE, status, failure_reason, created_at)
IdempotencyRecord(idempotency_key PK, scope, result_ref, created_at)

OutboxEvent(id, aggregate_type, aggregate_id, topic, event_id UNIQUE, payload_json,
            created_at, published_at)                             # I13
ProcessedEvent(event_id PK, consumer_group, processed_at)

LedgerEvent(id, seq BIGSERIAL, deal_id, event_type, actor, reason, payload_json,
            payload_hash, prev_hash, chain_anchor_tx, created_at)  # APPEND ONLY

CounterpartyProfile(entity_id PK, deals_completed, gmv_paise, disputes_raised,
                    disputes_lost, on_time_rate, largest_deal_paise, risk_score,
                    score_version, updated_at)

Notification(id, org_id, user_id, kind, title, body, deal_id, read_at, created_at)
NotificationPreference(user_id, kind, in_app, email)
DealMessage(id, deal_id, org_id, sender_user_id, body, created_at, read_by_json)

TokenSpend(id, purpose, model_id, input_tokens, output_tokens, cache_read_tokens,
           cost_micro_usd, latency_ms, deal_id, milestone_id, created_at)
SeedCheckpoint(step_name PK, completed_at, payload_hash)
AuditRecord(id, org_id, actor_user_id, action, target_type, target_id, meta_json, created_at)
```

---

# 16. STATE MACHINES

Explicit transition tables. Every transition takes `(entity, event, actor, reason)`, is validated
against the table, and writes exactly one `LedgerEvent` (I5). Unknown pairs raise
`IllegalTransition` (I10).

**Deal**

```
DRAFT ──sign_terms──▶ TERMS_SIGNED ──fund──▶ FUNDED ──first_evidence──▶ IN_PROGRESS
IN_PROGRESS ──all_milestones_settled──▶ COMPLETED
IN_PROGRESS ──raise_dispute──▶ DISPUTED ──resolve──▶ IN_PROGRESS | COMPLETED
DRAFT | TERMS_SIGNED ──cancel──▶ CANCELLED
FUNDED | IN_PROGRESS ──full_refund──▶ REFUNDED
TERMS_SIGNED ──funding_window_elapsed──▶ EXPIRED
```

**Milestone**

```
PENDING ──submit_evidence──▶ EVIDENCE_SUBMITTED ──start_verify──▶ VERIFYING
VERIFYING ──attest(RELEASE,  conf>=0.85, no UNVERIFIABLE required)──▶ RELEASE_APPROVED ──settle──▶ SETTLED
VERIFYING ──attest(REJECT,   conf<=0.35)──▶ REJECTED ──resubmit──▶ EVIDENCE_SUBMITTED
VERIFYING ──attest(ESCALATE, 0.35<conf<0.85)──▶ UNDER_HUMAN_REVIEW
UNDER_HUMAN_REVIEW ──human_approve──▶ RELEASE_APPROVED
UNDER_HUMAN_REVIEW ──human_reject──▶ REJECTED
RELEASE_APPROVED | REJECTED | SETTLED(in window) ──raise_dispute──▶ DISPUTED ──resolve──▶ SETTLED
```

Write an exhaustiveness test that iterates every `(state, event)` pair and asserts each either
appears in the table or raises.

---

# 17. THE VERIFIER AGENT

`backend/app/agents/verifier/`. **It writes attestations. It never moves money (I2).**

It **does**: inspect evidence, extract structured fields, evaluate clauses independently, compute
evidence quality, compute confidence, produce and sign an attestation.
It **must not**: call Razorpay, create payouts, release or refund money, or import `settlement/`,
`rails/` or `payments/`.

### Pipeline — this order, no shortcuts

```
1. DETERMINISTIC PRE-CHECKS  (zero LLM calls)
   - every required artifact type present?
   - every artifact parseable, non-empty, sha256 recorded, MIME as claimed?
   - hard date windows satisfied?
   - machine-readable numeric floors satisfied?
   A missing required artifact → REJECT immediately, zero tokens spent.
   Persist every pre-check result in deterministic_prechecks_json.
   (Report E must state what fraction of decisions were resolved here at zero AI cost.)

2. EXTRACTION  (one structured LLM call per artifact)
   invoice  → {vendor, invoice_no, date, currency, total_paise, line_items[]}
   grn      → {ref_no, date, item_code, quantity, uom}
   photoset → {visible_item_count_estimate, colour_summary, defects_noted[], legible}
   Attach extraction_quality ∈ [0,1] from field completeness + legibility signals.

3. CLAUSE EVALUATION  (one structured LLM call, each clause judged independently)
   per clause → {clause_id, verdict: PASS|FAIL|UNVERIFIABLE,
                 evidence_refs[], clause_confidence, note}

4. CONFIDENCE  (pure Python — NOT the model's self-reported number)
   verifiable_fraction = deterministic_clauses_passed / total_required_clauses
   llm_component       = mean(clause_confidence for non-UNVERIFIABLE clauses)
   penalty             = 0.5 * (unverifiable_required_clauses / total_required_clauses)
   raw   = 0.45*verifiable_fraction + 0.45*llm_component + 0.10*mean(extraction_quality)
   confidence = calibrate(raw - penalty)     # isotonic/bucket map fitted on the labelled set

   Any required clause FAIL          → REJECT (confidence then irrelevant)
   Any required clause UNVERIFIABLE  → RELEASE is impossible, ever
   Otherwise the thresholds decide.

5. DECIDE   RELEASE (≥0.85) | ESCALATE (0.35–0.85) | REJECT (≤0.35)
6. SIGN     canonical JSON → sha256 → EIP-712 sign with the verifier key → persist → anchor
```

**`UNVERIFIABLE` is a first-class verdict** and must be used honestly. "Four photographs cannot
establish that exactly 500 finished units exist" is `UNVERIFIABLE` — not `PASS`, not `FAIL`. This
single design decision is what makes the demo's refusal beat real instead of staged.

Put this sentence in the README: *"We do not trust the model's self-reported confidence.
Confidence is computed from how much of the condition was checkable deterministically, and
calibrated against a labelled set."* Then show the calibration plot.

### AI provider integration

Configure by environment, never hardcode a key:

```
AI_PROVIDER=anthropic
AI_MODEL_VERIFIER=claude-opus-5
AI_MODEL_ARBITER=claude-opus-5
AI_MODEL_EXTRACTION=claude-sonnet-5        # optional cost lever
```

Wrap the SDK in `agents/_llm.py` behind an `LLMProvider` interface so a deterministic
`FixtureProvider` can serve tests and offline eval runs. Pinned facts for the Anthropic path:

- Use `claude-opus-5` for clause evaluation and the arbiter. `claude-sonnet-5` is an acceptable
  cost lever for per-artifact extraction. Record whichever ran in `Attestation.model_id`.
  Pricing for Report E: Opus 5 `$5 / $25` per MTok in/out; Sonnet 5 `$2 / $10`.
- `thinking={"type": "adaptive"}`. **Never** pass `budget_tokens` — it is rejected with a 400 on
  Opus 5 and Sonnet 5.
- Structured output via the SDK parse helper:

```python
import anthropic
from pydantic import BaseModel
from typing import List, Literal

class ClauseVerdict(BaseModel):
    clause_id: str
    verdict: Literal["PASS", "FAIL", "UNVERIFIABLE"]
    evidence_refs: List[str]
    clause_confidence: float
    note: str

class ClauseEvaluation(BaseModel):
    verdicts: List[ClauseVerdict]
    overall_note: str

resp = anthropic.Anthropic().messages.parse(
    model=settings.AI_MODEL_VERIFIER,
    max_tokens=16000,
    thinking={"type": "adaptive"},
    system=[{"type": "text", "text": VERIFIER_SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": render_case(condition, artifacts)}],
    output_format=ClauseEvaluation,
)
evaluation = resp.parsed_output
```

- **Prompt caching:** the system prompt and clause rubric are byte-stable — put them first behind a
  `cache_control` breakpoint, keep the volatile case payload after it. Assert
  `resp.usage.cache_read_input_tokens > 0` in a test and report the observed hit rate.
- `prompt_hash` = sha256 of the exact rendered system + user content. This is what makes a decision
  reproducible six months later.
- Record model, version, input/output/cache tokens, cost, latency and outcome in `TokenSpend` for
  **every** call.
- Thresholds and `calibration_version` are written into every attestation. Changing a threshold is
  a config change with a ledger event, never a code edit.

---

# 18. ATTESTATION, CANONICAL JSON, EIP-712

- `Attestation` is immutable. No `UPDATE`, ever. A correction is a new row that references the one
  it supersedes.
- **Canonical JSON** (`app/attest/canonical.py`, written once, used everywhere): sorted keys, no
  insignificant whitespace, integers not floats, UTC ISO-8601 with `Z`, explicit `null` handling. A
  hash that depends on dict ordering is worthless. Unit-test that reordering input keys yields an
  identical hash.
- Sign the canonical attestation with the verifier key using **EIP-712** typed data. The contract
  recovers the signer on-chain, so the record proves *who* attested — not merely that something was
  attested. That is what lifts this above "we wrote a hash to a chain".
- **Evidence Merkle tree:** each leaf = `sha256(artifact_bytes) || sha256(canonical_json(extracted_fields))`,
  leaves sorted, standard binary tree, documented duplicate-node rule. Store `merkle_root` on the
  bundle. Expose `POST /api/v1/verify/evidence` taking `(artifact, proof, root)`.
- **Tamper demo, required:** verify a proof successfully → mutate one byte → verify again → it
  fails visibly in the UI.

---

# 19. THE ARBITER AGENT AND HUMAN REVIEW

`backend/app/agents/arbiter/`. Runs only on a `Dispute`. **Advisory only (I8).**

Input: deal terms, milestone terms, the tolerance clause, buyer claim, seller claim, every artifact
on the disputed milestone, and the prior attestation chain.

```python
class ArbiterRecommendation(BaseModel):
    outcome: Literal["FULL_RELEASE", "PARTIAL", "FULL_REFUND"]
    release_paise: int
    refund_paise: int
    reasoning_steps: List[str]        # each step cites artifact ids
    terms_clauses_relied_on: List[str]
    confidence: float
    open_questions: List[str]         # what a human must check that it could not
```

- Validate `release_paise + refund_paise == disputed_milestone_amount_paise` in Python. If it does
  not balance, **reject the model output** and re-request or escalate. Never silently "fix it up".
- Settlement is blocked until `human_decided_by` is non-NULL.

**Human review is a first-class workflow, not an admin afterthought.** The reviewer sees: the
evidence, extracted fields, the verifier decision, the confidence *and its component breakdown*,
every clause verdict, the arbiter recommendation with citations, and the open questions. Actions:
`APPROVE`, `REJECT`, `OVERRIDE` — each requiring a mandatory free-text reason. For disputes, the
release/refund split is **editable**. Persist the AI recommendation, the human decision, the delta,
the reason, the user and the timestamp; emit a ledger event for each.

---

# 20. RAZORPAY PAYMENT RAIL

```python
class PaymentRail(Protocol):
    def create_hold(self, deal_id: str, amount_paise: int) -> HoldRef: ...
    def capture(self, hold_ref: HoldRef) -> CaptureRef: ...
    def release_to_seller(self, milestone_id: str, amount_paise: int,
                          idempotency_key: str) -> RailRef: ...
    def refund_to_buyer(self, milestone_id: str, amount_paise: int,
                        idempotency_key: str) -> RailRef: ...
    def get_status(self, rail_ref: RailRef) -> RailStatus: ...
```

- `RazorpayRail` — **test mode only.** Orders API for funding, Payments for capture, Route
  transfers to a linked account for seller release where the test dashboard exposes it, Refunds API
  for the refund leg.
- `SimulatedRail` — deterministic stub that writes the same `Payout` rows, ledger events and Kafka
  events, so the whole flow is identical.
- Webhooks: verify the signature before anything else, persist raw, publish to
  `aegis.payment-webhooks`, process idempotently, tolerate replays and out-of-order delivery.
- `idempotency_key = sha256(f"{milestone_id}:{direction}:{attempt_no}")`, UNIQUE in Postgres, with
  a Redis lock around the rail call.

**The README must carry this table, filled in honestly:**

| Operation | Implementation |
|---|---|
| Funding (order + capture) | REAL TEST MODE / SIMULATED |
| Seller release | REAL TEST MODE / SIMULATED |
| Refund | REAL TEST MODE / SIMULATED |
| Webhook verification | REAL TEST MODE / SIMULATED |

Judges respect the disclosure far more than they would penalise the gap. Concealing it is the only
way to actually lose points here. Never label a simulated call real.

---

# 21. BLOCKCHAIN

Foundry, Solidity 0.8.24, Base Sepolia. `contracts/src/AegisEscrow.sol`. Hashes and integers only
(I7).

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract AegisEscrow {
    enum DealState { NONE, OPEN, DISPUTED, CLOSED }
    enum Decision  { NONE, RELEASE, REJECT, ESCALATE }

    struct Deal {
        bytes32 termsHash;
        address buyer;
        address seller;
        uint64  disputeWindowEnds;
        uint8   milestoneCount;
        DealState state;
    }

    struct MilestoneRecord {
        bytes32  evidenceRoot;       // merkle root of the evidence bundle
        bytes32  attestationHash;    // sha256 of canonical attestation JSON
        Decision decision;
        uint16   confidenceBps;      // 0..10000
        uint64   settledAmountPaise;
        bytes32  railRef;            // HASH of the rail reference, never the reference
        bool     humanApproved;
        address  attestor;           // recovered from the EIP-712 signature
    }

    mapping(bytes32 => Deal) public deals;                  // dealId
    mapping(bytes32 => MilestoneRecord) public milestones;  // keccak(dealId, seq)

    event DealOpened(bytes32 indexed dealId, bytes32 termsHash, uint8 milestoneCount);
    event AttestationAnchored(bytes32 indexed dealId, uint8 seq, bytes32 evidenceRoot,
                              bytes32 attestationHash, Decision decision,
                              uint16 confidenceBps, address attestor);
    event SettlementRecorded(bytes32 indexed dealId, uint8 seq, uint64 amountPaise,
                             bytes32 railRef, bool humanApproved);
    event DisputeRaised(bytes32 indexed dealId, uint8 seq, address by);
    event DisputeResolved(bytes32 indexed dealId, uint8 seq, uint64 releasePaise,
                          uint64 refundPaise, bytes32 decisionHash);

    function openDeal(bytes32 dealId, bytes32 termsHash, address buyer, address seller,
                      uint8 milestoneCount, uint64 disputeWindowEnds) external onlyOperator;
    function anchorAttestation(bytes32 dealId, uint8 seq, bytes32 evidenceRoot,
                               bytes32 attestationHash, Decision decision,
                               uint16 confidenceBps, bytes calldata verifierSig) external onlyOperator;
    function recordSettlement(bytes32 dealId, uint8 seq, uint64 amountPaise,
                              bytes32 railRef, bool humanApproved) external onlyOperator;
    function raiseDispute(bytes32 dealId, uint8 seq) external;
    function resolveDispute(bytes32 dealId, uint8 seq, uint64 releasePaise,
                            uint64 refundPaise, bytes32 decisionHash) external onlyOperator;
}
```

`forge test` must cover: only-operator enforcement, double-anchor rejection,
decision/confidence round-trip, EIP-712 signature recovery, dispute-window enforcement, and
settlement-amount bounds.

**Operator-key limitation — document it plainly, do not pretend otherwise:**

```
Current:  backend holds the operator key (permissioned anchoring)
Next:     operator multisig
Then:     buyer/seller EIP-712 co-signed terms
Goal:     fully non-custodial
```

Naming your own trust assumption reads as competence. Hiding it reads as the opposite.

Commit the deployed address and a Basescan link. Chain writes go through the outbox/worker path too
— a chain RPC failure must never roll back a settled payout, and must be visibly retried.

### Local audit ledger

`payload_hash = sha256(canonical_json(payload))`, `prev_hash` = previous event's `payload_hash` for
that deal, genesis `0x00…00`. Expose `GET /api/v1/deals/{id}/ledger/verify`:

```json
{ "ok": false, "broken_index": 7, "expected": "0x…", "found": "0x…" }
```

---

# 22. ML RISK MODEL

LightGBM binary classifier in `backend/app/risk/`.

- **Target:** `deal_went_bad` = dispute raised OR refund required.
- **Features:** `deals_completed`, `log(gmv_paise)`, `dispute_rate`, `on_time_rate`,
  `deal_paise / largest_deal_paise` (stretch ratio), `milestone_count`, `avg_milestone_paise`,
  `category`, `counterparty_age_days`, and `condition_objectivity_score` — the fraction of clauses
  that are deterministically checkable. That last one is genuinely predictive and a pleasure to
  explain.
- **Pricing tiers:**

| risk band | escrow fee | hold after final release | buyer prefund |
|---|---|---|---|
| < 0.10 | 0.8% | 0 days | 30% |
| 0.10–0.25 | 1.5% | 3 days | 50% |
| 0.25–0.50 | 2.5% | 7 days | 100% |
| > 0.50 | decline | — | — |

- Never show a bare score. Always the top-3 contributing factors in plain language.
- Report D: AUC, PR-AUC, calibration curve, a logistic-regression baseline to beat, and the
  tier distribution over the synthetic portfolio.

---

# 23. NOTIFICATIONS, EMAIL, CHAT, REALTIME

All in scope. None becomes a separate service.

**Notifications** — `Notification` + `NotificationPreference`. Kafka `aegis.notifications` is the
async source. Events: deal created, terms signed, deal funded, evidence submitted, verification
completed, **human review required**, dispute raised, dispute resolved, payout completed, payout
failed, invitation received. In-app bell with unread count; email for the subset the user opted
into.

**Email** — `EmailProvider` interface, `DevelopmentEmailProvider` → Mailpit. Templates: email
verification, password reset, organization invitation, human review required, dispute raised,
settlement completed. No external service required to run locally.

**Chat** — deal-scoped only. `DealMessage` with sender, timestamp, unread tracking. Buyer and
seller exchange messages inside the deal cockpit. Off-chain, tenant-scoped, never fed to the
verifier as evidence. This is not a messaging platform; resist every urge to make it one.

**Realtime** — SSE (preferred; simpler than WebSockets here) for deal state changes, verification
progress, human-review queue updates, settlement status, chat and notifications. One endpoint per
concern, authenticated, tenant-scoped, with reconnect and last-event-id. Do not over-engineer.

---

# 24. FRONTEND

Next.js (App Router) + TypeScript + Tailwind + shadcn/ui + `viem` for chain reads.

Non-negotiables:

- **Mobile-first and genuinely responsive.** Every screen works at 375px, 768px and 1440px. No
  horizontal page scroll, ever; wide tables and diagrams scroll inside their own container. Touch
  targets ≥ 44px. Test all six screens at all three widths before declaring done.
- **Dark and light mode**, toggled and persisted per user (server-side preference plus an
  immediate localStorage read to avoid a flash). All colours come from tokens (§25); no literal hex
  in a component.
- **i18n: English + Hindi.** Centralized dictionaries in `frontend/i18n/{en,hi}.json`, a `t()`
  helper, no hardcoded user-facing strings in components. Currency and dates via `Intl` with the
  `en-IN` numbering system, so ₹4,20,000 renders with Indian grouping — not ₹420,000.
- **Fintech-grade, not generic-AI-dashboard.** Money state, verification state, uncertainty, human
  approval and provenance must be visually unmistakable. Uncertainty is a first-class visual state
  with its own treatment — not a yellow badge bolted onto a success component.
- Never expose ORM shapes; consume the typed API. Loading, empty, and error states for every view.
- Accessibility: real focus states, labelled inputs, keyboard-operable dialogs, AA contrast in both
  themes, `aria-live` on the verification result.

### The six primary screens

1. **Deal cockpit** — state machine visual, parties, total, milestone cards, and a **money bar**
   that always visibly satisfies `held + released + refunded = funded` (I4 on screen). Includes the
   agent console panel and the chat panel.
2. **Evidence submission** — drag-and-drop, artifact type selection, upload progress, computed
   sha256, extracted-fields preview, bundle assembly and submit.
3. **Verification result** — *the most important screen.* Clause-by-clause table with
   PASS / FAIL / **UNVERIFIABLE** treatments, the confidence value *with its component breakdown*,
   the decision, the reasoning, and evidence citations that link to the artifact.
4. **Human review queue** — escalated milestones, precisely what the agent could not verify, the
   evidence, the recommendation, approve / reject / override with a mandatory reason, and an
   editable split for disputes.
5. **Provenance explorer** — for any rupee: model, model version, prompt hash, evidence Merkle
   root, clause verdicts, confidence computation, verifier signer, human approver, on-chain tx
   link, and the **tamper-check widget**.
6. **Reputation view** — counterparty passport: attested history, completed deals, GMV, disputes,
   on-time rate, risk score, top-3 factors in plain language, resulting escrow pricing tier.

Plus the supporting flows: auth (register, verify, login, forgot/reset), organization management
and invitations, notification centre, settings (theme, language, notification preferences).

### Agent console content

```
Buyer Agent      → proposed 3 milestones
Seller Agent     → accepted terms
Buyer Agent      → funded escrow ₹4,20,000
Seller           → submitted evidence (milestone 1)
Verifier         → pre-checks passed (4/4)
Verifier         → milestone 1 RELEASE (confidence 0.94)
Settlement       → authorization written
Kafka            → settlement.authorized published
Settlement Worker→ Razorpay release ₹1,26,000 OK
Chain            → attestation anchored 0x…
```

---

# 25. UI MOTION AND THE REFERENCE VIDEO PROTOCOL

The UI must be animated, not merely responsive. **A reference video of the desired animated site
will be supplied.** Handle it like this — the whole point is that the video can arrive *after* the
build starts without forcing a rewrite.

### 25.1 Two-file visual indirection (build this from the start)

Every visual and motion decision lives in exactly two files:

```
frontend/design/tokens.css   # colour, type scale, spacing, radius, shadow, both themes
frontend/design/motion.ts    # durations, easings, distances, stagger, named variants
```

Components consume tokens and named motion variants only. **No component contains a hex colour, a
raw duration, or an inline easing curve.**

### 25.2 The design pack — ALREADY WRITTEN. READ IT.

The reference recordings have been supplied and frame-analysed. The resulting design and motion
system lives in **`aegis/ui/`** and it is binding. Read all of it before writing any frontend code:

| File | Contents |
|---|---|
| `ui/README.md` | Index, the design thesis, non-negotiables, what each reference contributed |
| `ui/00-DESIGN-SYSTEM.md` | Palette with semantics, typography, scale, grid, micro-labels — **contains `tokens.css` verbatim** |
| `ui/01-MOTION-SYSTEM.md` | Durations, easings, every named variant, reduced-motion, perf rules — **contains `motion.ts` verbatim** |
| `ui/02-PRELOADER-AND-HERO.md` | Boot sequence and hero, shot by shot with timings |
| `ui/03-DROP-IN-REVEALS.md` | The element entrance system and where each variant applies |
| `ui/04-CURSOR-AND-HOVER.md` | Custom cursor, item hover panel wipe, list magic-bar |
| `ui/05-SCRAMBLE-CTA.md` | The scramble CTA component and the `UNVERIFIABLE` reuse |
| `ui/06-SCREEN-BLUEPRINTS.md` | All six primary screens plus supporting flows |
| `ui/07-REFERENCE-FRAMES.md` | The 16 stills in `ui/reference/` and what each one drove |

Copy `tokens.css` and `motion.ts` from those two files verbatim; do not improvise a palette, a
duration scale, or an easing curve. Copy `ui/` into `docs/UI_MOTION.md` (or symlink it) to satisfy
§33. Copy the "What was deliberately not adopted" table from `ui/07-REFERENCE-FRAMES.md` into
`docs/DECISIONS.md`.

**Three rules from that pack that override anything you might otherwise assume:**

1. **Hue is data.** Exactly three hues exist in the product — mint = `PASS`/released, amber =
   `UNVERIFIABLE`/escalated/held, red = `FAIL`/adverse. The brand is monochrome. Never introduce a
   coloured brand accent; it would collide with the state system and make the interface lie.
2. **`UNVERIFIABLE` never fully settles.** Its label resolves and then perpetually disturbs one
   random glyph at low amplitude (`ui/05` §4). It is the only element in the product that never
   reaches rest, and it is the visual signature of the demo's most important beat.
3. **The money bar animates its layout, never its total width**, so `held + released + refunded ==
   funded` is visibly conserved on screen (`ui/06` §1).

### 25.3 Motion engineering rules (independent of the video)

- **Library:** Framer Motion (`motion`) for React. Tailwind transitions for trivial hovers. Do not
  add a second animation library.
- **Animate `transform` and `opacity` only.** Never animate `width`, `height`, `top`, `left` or
  `box-shadow` in a loop. No layout thrash; 60fps on a mid-range phone is the bar.
- **`prefers-reduced-motion` is mandatory.** One hook, honoured globally: reduce to opacity-only
  crossfades, disable parallax and ambient loops, keep every state change perceivable. This is an
  accessibility requirement, not a nice-to-have.
- Entrance animations run **once** per mount; never re-animate on every re-render or scroll pass.
- Scroll reveals use `IntersectionObserver` (Framer's `whileInView` with `once: true`), never
  scroll-event listeners.
- Skeletons for loading, not spinners, on the deal cockpit and verification screens.
- **Motion that carries meaning** — spend the animation budget on the moments the demo depends on:
  the money bar re-splitting when a milestone releases; the clause table resolving row by row; the
  `UNVERIFIABLE` state arriving with distinctly *different* motion from `PASS`; the attestation
  seal forming as it is signed and anchored; the tamper check failing. Those five moments are worth
  more than a decorative hero.
- Every animated element must have a correct static end state. If JS fails, the page is still fully
  readable — verify by disabling animations entirely.

---

# 26. API DESIGN

Versioned under `/api/v1`:

```
/auth          register, login, logout, refresh, verify-email, resend-verification,
               forgot-password, reset-password, me
/users         profile, preferences (theme, language, notifications)
/organizations CRUD, members, invitations, accept-invite, role changes, switch
/entities      buyer/seller entities per org
/deals         create, list, get, sign-terms, fund, cancel, timeline
/milestones    list, get, submit-evidence, start-verify, human-approve, human-reject
/evidence      upload, bundle, get, presigned download
/verification  attestation for a milestone, clause detail, confidence breakdown
/disputes      raise, get, arbiter recommendation, human decision
/settlements   authorizations, status
/payments      webhooks, payout status, rail mode disclosure
/ledger        deal ledger, verify
/provenance    attestation provenance, chain records, verify-evidence
/reputation    counterparty profile, risk score, pricing
/notifications list, mark read, preferences
/chat          deal messages, send, mark read
/realtime      SSE streams
/dev           assume (DEMO_MODE only)
/health        liveness, readiness (db, redis, kafka, chain rpc)
```

Pydantic request/response schemas everywhere; ORM models never leave the repository layer.
Cursor pagination on every list. Consistent typed errors (I9). OpenAPI served and exported to
`docs/API.md`.

---

# 27. DOCKER

```
docker compose up --build
```

must take a clean clone to a working system with **nothing installed on the host** but Docker.

Services: `frontend`, `backend` (api), `worker` (Kafka consumers), `relay` (outbox publisher),
`postgres`, `redis`, `kafka` (KRaft, single broker), `kafka-ui`, `mailpit`, and optionally `minio`
behind a compose profile.

Requirements:

- **Healthchecks on every dependency**, and `depends_on: { condition: service_healthy }` on the
  app services. Without this, one-command startup is a coin flip — Kafka and Postgres both need a
  real readiness probe, not a sleep.
- The migration entrypoint holds a Postgres advisory lock so api/worker/relay cannot race.
- `docker-compose.dev.yml` adds bind mounts and hot reload (`uvicorn --reload`, `next dev`).
- Multi-stage builds; non-root users; `.dockerignore` that excludes `.venv`, `node_modules`,
  `data/generated`, `.git`.
- Named volumes for postgres, kafka, redis and evidence storage so data survives a restart.
- Contract tooling (Foundry) may run in its own container or on the host; the app must start
  without it, degrading to "chain anchoring unavailable" with a visible banner — never a crash.

---

# 28. MAKEFILE

Self-documenting; bare `make` prints the help table (parse `##` comments after each target).

```
make help              ## show this help
make up                ## build and start the full stack
make down              ## stop the stack
make logs              ## tail all service logs
make install           ## uv sync + npm install
make dev               ## start with hot reload
make lint  format  test

make db-migrate m="…"  ## create an Alembic revision
make db-upgrade        ## apply migrations
make db-downgrade      ## roll back one revision
make seed              ## idempotent, resumable seed
make reset-seed        ## DESTRUCTIVE: drop, migrate, reseed

make demo              ## load the demo deal and print the walkthrough URLs
make dataset           ## regenerate synthetic data (seed 42)

make eval              ## run every suite and regenerate all README numbers
make eval-a  eval-b  eval-c  eval-d  eval-e

make contract-test     ## forge test
make deploy-contract   ## deploy to Base Sepolia, write address to .env

make verify-ledger     ## verify hash chains for all deals
make verify-chain      ## compare on-chain anchors against local attestations
make clean
```

---

# 29. SYNTHETIC DATA

`backend/scripts/generate_dataset.py`, seeded (`--seed 42`), fully deterministic.

- `deals.parquet` — 2,000 deals with outcomes for the risk model, with train/valid/**test** splits
  written to disk. The test split is touched exactly once, at the end.
- `evidence/` — **150 labelled bundles** across 5 milestone types, with *real* generated PDFs and
  images so the extraction path is genuinely exercised. Each labelled
  `should_release | should_reject | should_escalate`.
  At least 40 must be adversarial: correct document with the **wrong date**; correct document with
  an **altered amount**; **right type, wrong milestone**; a **fabricated** invoice with internally
  inconsistent totals; a **low-quality scan** (correct label: escalate); photos that **cannot
  establish quantity** (correct label: escalate); and a **perfectly valid but unusual** bundle to
  catch over-rejection.
- `counterparties.json` — 30 entities with histories, including 4 thin-file cases.
- `data/fixtures/demo_deal.json` — the exact demo deal, so `make demo` is reproducible.

`docs/DATA.md` declares every base rate, each marked **[sourced]** (with the source) or
**[assumed]** (with why the assumption is conservative). One honest page here protects every number
in the README.

---

# 30. EVALUATION HARNESS

`make eval` regenerates **every metric in the README** from scratch. No hardcoded numbers anywhere
in the docs. Output to `evals/out/` as JSON plus a markdown table for direct paste.

**Suite A — verifier accuracy** (150 labelled bundles)
3×3 confusion matrix over {release, reject, escalate}; **HARD GATE: false releases == 0** — a false
release is unrecoverable money, so if this is not zero the build is failing, printed loudly;
escalation rate with a stated target band (12–25%) and a sentence on why too high is useless and
too low is unsafe; confidence calibration by bucket plus Brier score; per-adversarial-category
breakdown that shows your **worst** category honestly.

**Suite B — settlement integrity** (property + concurrency)
I4 holds after any random legal event sequence; 20 concurrent releases ⇒ exactly one payout;
no release without a qualifying attestation; full ledger replay reconstructs identical balances;
every illegal transition raises; duplicate Kafka delivery ⇒ single effect; outbox crash-injection
⇒ exactly-once publish.

**Suite C — provenance integrity**
Flip one artifact byte ⇒ Merkle proof fails; mutate a ledger event ⇒ verify reports the exact
broken index; every on-chain anchor matches the local attestation hash on read-back.

**Report D — risk model** AUC, PR-AUC, calibration, logistic baseline comparison, tier distribution.

**Report E — cost and latency** tokens and ₹/$ per verification, prompt-cache hit rate, p50/p95
latency per pipeline stage, and the share of decisions resolved by deterministic pre-checks alone
at zero AI cost.

Verify reproducibility by deleting `evals/out/`, re-running, and diffing.

---

# 31. TESTING

Real tests. Minimum coverage by kind:

`unit` (canonical JSON, merkle, confidence maths, transition table, pricing tiers) ·
`integration` (verify → attest → authorize → Kafka → worker → payout → ledger, end to end) ·
`api` (every route, happy path and typed error) · `state machine` (exhaustive `(state, event)`) ·
`property` (Hypothesis, I4) · `concurrency` (I6, 20 parallel releases) ·
`kafka` (duplicate delivery, DLQ routing, offset commit ordering) ·
`outbox` (crash injection, I13) · `blockchain` (`forge test`) · `merkle/tamper` ·
`auth` (registration, verification gating, reset single-use, refresh reuse detection) ·
`tenant isolation` (see below) · `seed idempotency` (seed×3, and resume-after-failure) ·
`logging` (masked fields never appear in output).

**Security suite — required, and it must be route-exhaustive:**

Cross-tenant access on every tenant-owned route (enumerate the router programmatically so a new
unscoped route fails automatically) · broken object-level authorization via id guessing ·
expired and malformed tokens · refresh-token replay · password-reset token replay and
post-reset session revocation · duplicate payment requests · duplicate Kafka events ·
attestation with a forged signature · altered evidence · invalid state transition attempts ·
replayed and malformed webhooks · unverified-email privilege attempt · role escalation attempt
(MEMBER approving a dispute) · secret leakage in logs and error responses.

CI (`.github/workflows/ci.yml`): lint → typecheck → unit → integration (compose services) →
`forge test` → import-lint (I2) → secret scan → build both images.

---

# 32. OBSERVABILITY

Structured logs (§6) with correlation throughout. `/health` reports liveness plus per-dependency
readiness (postgres, redis, kafka, object store, chain RPC) with degraded-mode flags. Expose
lightweight counters for verifications by decision, settlements by outcome, DLQ depth, and AI spend
— a small internal `/metrics`-style JSON endpoint is sufficient; do not install Prometheus and
Grafana for a hackathon.

Every financial operation traceable end to end:
`request_id → deal_id → milestone_id → attestation_id → settlement_event_id → payout_id → rail_ref`.

---

# 33. DOCUMENTATION

`README.md` in this order: thesis → **why blockchain** → invariants table → architecture diagram →
quickstart → demo walkthrough → evaluation results → real-vs-simulated rail table → deployment →
limitations.

```
docs/ARCHITECTURE.md   diagrams, module boundaries, the money/AI separation (I2),
                       Kafka + outbox flow, trust model, operator-key limitation
docs/DATA.md           base rates, [sourced] vs [assumed]
docs/DECISIONS.md      ADR log — every ambiguity you resolved and why
docs/DEMO.md           the timestamped video beat sheet (§35)
docs/SECURITY.md       auth model, tenancy, threat notes, the DEMO_MODE affordance
docs/API.md            exported OpenAPI reference
docs/OPERATIONS.md     runbook: migrations, seeding, DLQ drain, key rotation, redeploy
docs/UI_MOTION.md      §25 — copy of ui/ (design + motion pack, already written)
docs/LIMITATIONS.md    what is simulated, what is permissioned, what would change next
```

---

# 34. ENVIRONMENT AND QUICKSTART

`.env.example` — complete, with placeholders that are obviously placeholders. Never commit a fake
secret that looks real enough to be mistaken for one.

```
SERVICE_NAME=aegis-api
LOG_LEVEL=INFO
LOG_TO_KAFKA=true
DEMO_MODE=true

DATABASE_URL=postgresql+asyncpg://aegis:aegis@postgres:5432/aegis
REDIS_URL=redis://redis:6379/0
KAFKA_BOOTSTRAP_SERVERS=kafka:9092

OBJECT_STORE=local            # local | s3
S3_ENDPOINT=  S3_BUCKET=  S3_ACCESS_KEY=  S3_SECRET_KEY=

JWT_SECRET=<generate-me>
ACCESS_TOKEN_TTL_MINUTES=15
REFRESH_TOKEN_TTL_DAYS=14

EMAIL_PROVIDER=development
SMTP_HOST=mailpit  SMTP_PORT=1025

RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
RAZORPAY_KEY_SECRET=<test-mode-secret>
RAZORPAY_WEBHOOK_SECRET=<test-mode-webhook-secret>
PAYMENT_RAIL=razorpay         # razorpay | simulated

AI_PROVIDER=anthropic
AI_API_KEY=<your-key>
AI_MODEL_VERIFIER=claude-opus-5
AI_MODEL_ARBITER=claude-opus-5
AI_MODEL_EXTRACTION=claude-sonnet-5

BLOCKCHAIN_RPC_URL=https://sepolia.base.org
CHAIN_ID=84532
CONTRACT_ADDRESS=
OPERATOR_PRIVATE_KEY=<testnet-only>
VERIFIER_PRIVATE_KEY=<testnet-only>

DEMO_BUYER_PASSWORD=<set-me>
DEMO_SELLER_PASSWORD=<set-me>
```

The README quickstart must be exactly this, with no undocumented manual steps:

```bash
git clone …  && cd aegis
cp .env.example .env          # fill AI_API_KEY and the Razorpay test keys
docker compose up --build
make db-upgrade
make seed
make demo
```

---

# 35. IMPLEMENTATION ORDER

Build continuously through this dependency order. Do not stop between steps to ask for approval.

```
 1 repo structure, .env.example, gitignore/dockerignore
 2 Docker compose + healthchecks + entrypoints
 3 uv / pyproject / FastAPI skeleton / Settings
 4 logifyx wrapper + typed errors + request ids
 5 Postgres models + Alembic initial migration
 6 auth (register, verify, login, refresh, reset)
 7 organizations, memberships, invitations, tenancy layer
 8 domain model: entities, deals, milestones
 9 explicit state machines + transition guards
10 hash-chained ledger + verify endpoint
11 object storage + evidence upload + sha256
12 merkle + canonical JSON + EIP-712 signing
13 PaymentRail interface + SimulatedRail
14 Redis locks + rate limiting
15 Kafka topics + producer/consumer + outbox + relay + DLQ
16 deterministic settlement engine (all invariant re-checks)
17 RazorpayRail + webhooks + reconciliation
18 LLM provider abstraction + FixtureProvider
19 verifier: pre-checks → extraction → clauses → confidence → attestation
20 blockchain contract + forge tests + deploy + anchoring
21 arbiter + dispute flow + human review + partial settlement
22 risk model + pricing + reputation
23 notifications + email + deal chat + SSE
24 frontend: design tokens + motion primitives (VERBATIM from ui/00, ui/01) + shell + auth
25 frontend: the six primary screens
26 i18n (en/hi), dark mode, mobile pass, animation pass (per ui/01 §3 five moments)
27 synthetic dataset generator
28 idempotent resumable seed + demo fixture
29 tests: unit → integration → property → concurrency → kafka → security
30 eval suites A/B/C + reports D/E
31 documentation + README numbers from make eval
32 final integration pass and BUILD STATUS report
```

---

# 36. THE DEMO — FIXTURE AND VIDEO BEAT SHEET

**Fixture.** Meridian Label (Bangalore, buyer, represented by a procurement agent) buys 500 custom
kurtas from Tirupur Exports. Total **₹4,20,000**. Neither has traded with the other before.

| # | Milestone | Amount | Condition |
|---|---|---|---|
| 1 | Fabric procured | ₹1,26,000 (30%) | supplier invoice + GRN, fabric code `CT-240-IVY`, quantity ≥ 520 m, dated within window |
| 2 | Production complete | ₹1,68,000 (40%) | photo set evidencing 500 finished units matching the approved spec |
| 3 | Delivered & accepted | ₹1,26,000 (30%) | signed delivery challan + condition report, 7-day dispute window |

**Required outcomes** — produced by the real pipeline, never by a special case:

- **Milestone 1** → all clauses PASS, confidence ≈ 0.94, **RELEASE**, ₹1,26,000 settles.
- **Milestone 2** → clause "500 finished units" returns **UNVERIFIABLE** (four photographs cannot
  establish a count of 500), confidence ≈ 0.51, **ESCALATE**, **no money moves**, human review
  appears.
- **Milestone 3** → buyer disputes 60 of 500 units for colour variance. Arbiter recommends
  **PARTIAL: release ₹1,15,920, refund ₹10,080** (60 × ₹840 unit price × 20% variance deduction).
  Human approves. Both legs execute. The money bar reconciles to `released + refunded == funded`.

### Video, 5:00

- **0:00–0:20** the why-chain paragraph, said before anything else.
- **0:20–0:50** the deadlock, and the new question an AI buyer creates.
- **0:50–1:30** deal formation, funding ₹4,20,000, `openDeal` on Basescan, money bar at held.
- **1:30–2:15** milestone 1 clean release: pre-checks, all PASS, 0.94, ₹1,26,000 out, anchored.
- **2:15–3:05** **milestone 2 — the refusal. The most important 50 seconds of the submission.**
  UNVERIFIABLE, 0.51, ESCALATE, no movement, human queue. Say it aloud: *"it did not guess, and it
  did not block — it said what it could not verify and asked for a human."*
- **3:05–3:50** dispute → arbiter recommendation with citations → editable split → human approves →
  ₹1,15,920 / ₹10,080 → money bar closes.
- **3:50–4:30** provenance explorer, then the tamper demo failing on camera. *"When agents move
  money, 'the AI decided' is not an acceptable audit answer. This is."*
- **4:30–5:00** `make eval`: **0 false releases across 150 labelled bundles**, escalation rate,
  calibration plot, Suites B and C green. Close on the invariants table.

Do not spend video time on onboarding, settings or auth.

---

# 37. FINAL VALIDATION

Run all of these and fix what fails:

```bash
docker compose config
docker compose build
docker compose up -d
make db-upgrade
make seed
make seed                 # must be a no-op
make lint
make test
make contract-test
make eval
make demo
make verify-ledger
make verify-chain
```

Then verify by hand:

```
registration · email verification (Mailpit) · login · refresh · logout
password reset (single use, sessions revoked)
organization create · invite · accept · role change · remove
cross-tenant access blocked on every route
?as=buyer / ?as=seller switch (and DEMO_MODE=false removes it entirely)
demo deal loads · evidence upload · sha256 shown
verifier runs · UNVERIFIABLE reached honestly · escalation queue populated
human approve with mandatory reason · dispute · arbiter · editable split · override logged
Kafka settlement path (kafka-ui shows the events) · duplicate event is a no-op · DLQ works
Redis lock prevents double release · outbox survives a relay kill
Razorpay test-mode calls (or clearly-labelled SimulatedRail)
chain anchoring · Basescan link · merkle tamper detection · ledger verify reports broken index
risk score with plain-language factors · pricing tier
notifications · deal chat · SSE live updates
mobile 375px · tablet 768px · desktop 1440px · no horizontal scroll
dark/light toggle persists · English/Hindi switch · ₹ Indian digit grouping
prefers-reduced-motion honoured · animations off ⇒ page still fully readable
```

### BUILD STATUS report

Report only what you actually measured:

```
BUILD STATUS
Backend: PASS/FAIL          Frontend: PASS/FAIL        Database: PASS/FAIL
Auth: PASS/FAIL             Organizations: PASS/FAIL   Tenant isolation: PASS/FAIL
Kafka: PASS/FAIL            Outbox/relay: PASS/FAIL    Redis: PASS/FAIL
Object storage: PASS/FAIL   Razorpay: REAL / SIMULATED (per-op table)
Blockchain: PASS/FAIL       Verifier: PASS/FAIL        Arbiter: PASS/FAIL
Settlement: PASS/FAIL       Ledger: PASS/FAIL          Merkle: PASS/FAIL
Risk model: PASS/FAIL       Notifications: PASS/FAIL   Chat: PASS/FAIL
i18n: PASS/FAIL             Dark mode: PASS/FAIL       Mobile: PASS/FAIL
Animations: PASS/FAIL       Docker: PASS/FAIL          Seed idempotency: PASS/FAIL
Tests: X passed / Y failed
Eval A false releases: N    Escalation rate: N%        Brier: N
Eval D AUC: N (baseline N)  Eval E cost/verification: ₹N
Demo end-to-end: PASS/FAIL
```

---

# 38. FAILURE POLICY

Do not hide failures. If an external integration is unavailable:

1. implement the real provider interface and keep the real integration code,
2. provide a deterministic local adapter,
3. label it clearly in the UI **and** the README,
4. document the limitation in `docs/LIMITATIONS.md`.

**Never fabricate** a blockchain transaction, a Razorpay payout, an evaluation number, an AI
confidence value, or a test result. If a test fails, fix the cause — never weaken the test.

---

# 39. NO FEATURE CREEP

Do not add: Kubernetes · Terraform · microservices · a service mesh · multiple blockchains · a
token, coin, staking, AMM or bridge · wallet-connect onboarding · vector databases · RAG ·
embeddings · fine-tuning · a generic plugin architecture · arbitrary contract types · a
general-purpose messaging platform · a native mobile app · Prometheus/Grafana · a second animation
library · a design system of your own invention.

The goal is **one deeply implemented agentic escrow system**, not a feature count.

---

# 40. THE THREE SENTENCES THAT WIN THIS

1. *"The LLM never moves money. It writes a signed attestation; a deterministic settlement engine
   reads it. Here is the CI check that fails if those two modules ever import each other."*
2. *"It did not guess and it did not block. It said what it could not verify, and asked for a
   human."*
3. *"Zero false releases across 150 labelled evidence bundles — and you can reproduce that with
   `make eval`."*

Every line of this specification exists to make those three sentences demonstrably true.

---

# 41. START BUILDING NOW

Do not produce a plan. Do not produce pseudocode. Do not stop at the skeleton. Do not ask for
per-phase approval.

Read this specification, create the complete repository, implement every required subsystem, run
the tests and evaluations, fix the failures, and leave the project in a runnable state. Then report
BUILD STATUS from section 37 with measured values only.
