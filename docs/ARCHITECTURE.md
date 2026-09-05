<div align="center">

# Architecture

**The whole system exists to make one sentence true:**<br>
no rupee moves without a signed, re-checkable reason.

Every structural decision below follows from that.

<p>
<img alt="Boundary" src="https://img.shields.io/badge/agents_%E2%86%92_settlement-BOUNDARY_ENFORCED_IN_CI-4FD1A5?style=for-the-badge&labelColor=0D0D10">
<img alt="Invariants" src="https://img.shields.io/badge/invariants-I2_%C2%B7_I5_%C2%B7_I12_%C2%B7_I13-C6C0B4?style=for-the-badge&labelColor=0D0D10">
</p>

<p>
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-async-C6C0B4?style=flat-square&labelColor=0D0D10&logo=fastapi&logoColor=4FD1A5">
<img alt="PostgreSQL" src="https://img.shields.io/badge/Postgres_16-source_of_truth-C6C0B4?style=flat-square&labelColor=0D0D10&logo=postgresql&logoColor=4FD1A5">
<img alt="Apache Kafka" src="https://img.shields.io/badge/Kafka-KRaft-C6C0B4?style=flat-square&labelColor=0D0D10&logo=apachekafka&logoColor=4FD1A5">
<img alt="Redis" src="https://img.shields.io/badge/Redis_7-fast_path_only-C6C0B4?style=flat-square&labelColor=0D0D10&logo=redis&logoColor=4FD1A5">
<img alt="Next.js" src="https://img.shields.io/badge/Next.js_15-App_Router-C6C0B4?style=flat-square&labelColor=0D0D10&logo=nextdotjs&logoColor=4FD1A5">
<img alt="Docker" src="https://img.shields.io/badge/Docker-10_containers-C6C0B4?style=flat-square&labelColor=0D0D10&logo=docker&logoColor=4FD1A5">
</p>

<p>
  <a href="../README.md">Overview</a>
  &nbsp;·&nbsp; <a href="README.md">Docs</a>
  &nbsp;·&nbsp; <b>Architecture</b>
  &nbsp;·&nbsp; <a href="API.md">API</a>
  &nbsp;·&nbsp; <a href="DATA.md">Data</a>
  &nbsp;·&nbsp; <a href="SECURITY.md">Security</a>
  &nbsp;·&nbsp; <a href="OPERATIONS.md">Operations</a>
  &nbsp;·&nbsp; <a href="DEMO.md">Demo</a>
  &nbsp;·&nbsp; <a href="UI_MOTION.md">UI &amp; Motion</a>
  &nbsp;·&nbsp; <a href="DECISIONS.md">Decisions</a>
  &nbsp;·&nbsp; <a href="LIMITATIONS.md">Limitations</a>
</p>

</div>

<samp>

[1. The one boundary that matters](#1-the-one-boundary-that-matters) &nbsp;·&nbsp;
[2. Request path, end to end](#2-request-path-end-to-end) &nbsp;·&nbsp;
[3. Money path and the transactional outbox](#3-money-path-and-the-transactional-outbox-i13) &nbsp;·&nbsp;
[4. Evidence and provenance](#4-evidence-and-provenance) &nbsp;·&nbsp;
[5. Tenant isolation](#5-tenant-isolation-i12) &nbsp;·&nbsp;
[6. Services](#6-services) &nbsp;·&nbsp;
[7. Logging](#7-logging) &nbsp;·&nbsp;
[8. Frontend](#8-frontend) &nbsp;·&nbsp;
[9. What is deliberately absent](#9-what-is-deliberately-absent)

</samp>

---

## 1. The one boundary that matters

<img alt="" src="https://img.shields.io/badge/I2-LLM_output_never_triggers_a_transfer-4FD1A5?style=flat-square&labelColor=0D0D10">

```
app/agents/                           app/settlement/
├── _llm.py                           ├── guards.py    pure. no I/O. no app.agents import
├── prompts.py                        └── engine.py    the only module that authorises money
├── verifier/
│   ├── prechecks.py         DENY   agents/ may not import settlement.engine
│   ├── clause_rules.py      DENY   agents/ may not import rails, payments, deals
│   ├── confidence.py        ALLOW  agents/ may import settlement.guards -- it is pure
│   └── pipeline.py
└── arbiter/pipeline.py
```

[`backend/scripts/import_lint.py`](../backend/scripts/import_lint.py) walks the AST of every module
under `app/agents/` and fails on any `import` or `from … import` that reaches a forbidden package.

> [!IMPORTANT]
> It is a build step, not a convention. CI plants a real violation, requires the lint to **fail**,
> restores the file, and requires it to pass. A boundary nobody tries to break is a boundary nobody
> has tested.

`app.settlement.guards` is deliberately on the *allowed* list. It is a pure function of a frozen
input with no I/O, so the verifier can call it to **predict** a decision — but predicting is all it
can do, because only `engine.py` can write a `SettlementAuthorization`, and `engine.py` is
unreachable from `agents/`.

### The guard

```python
def decide(inp: GuardInput) -> tuple[str, dict]:   # exactly one parameter
```

One parameter, frozen, no keyword flags. There is nowhere to thread an `urgent=True`, an
`override=`, or a `skip_thresholds=`, because there is no parameter for it — and adding one would
show up in every call site and in the diff.

Order of evaluation:

| order | condition | outcome | reason code |
|:--|:--|:--|:--|
| 1 | any **required** clause `FAIL` | `REJECT` | `REQUIRED_CLAUSE_FAILED` |
| 2 | any **required** clause `UNVERIFIABLE` | `ESCALATE` | `REQUIRED_CLAUSE_UNVERIFIABLE` |
| 3 | `confidence >= 0.85` | `RELEASE` | — |
| 4 | `confidence <= 0.35` | `REJECT` | — |
| 5 | otherwise | `ESCALATE` | `BETWEEN_THRESHOLDS` |

Rule 2 is the design's centre of gravity, and it is *not* a rejection. Nothing contradicted the
clause; the machine simply could not see. Rejecting would punish the seller for the machine's
blindness, and releasing would be a guess. So it escalates, forever, with no threshold that can
overrule it.

**Further reading** &nbsp;
[ADR-004](DECISIONS.md#adr-004--a-required-unverifiable-clause-escalates-it-never-rejects) &nbsp;·&nbsp;
[ADR-001](DECISIONS.md#adr-001--the-settlement-decision-is-a-pure-function-with-one-parameter) &nbsp;·&nbsp;
[Security — the prompt injector](SECURITY.md#1-threat-model)

---

## 2. Request path, end to end

<img alt="" src="https://img.shields.io/badge/I1-no_transfer_without_an_attestation-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/I10-explicit_transition_tables-4FD1A5?style=flat-square&labelColor=0D0D10">

```
POST /api/v1/milestones/{id}/start-verify
  │
  ├─ rate_limit("verify", org_id)                        Redis token bucket
  ├─ repo.get_milestone(id)                              TenantRepo: org-scoped (I12)
  ├─ repo.get_deal_for_update(deal_id)                   SELECT … FOR UPDATE
  ├─ latest_bundle_or_404(milestone)
  ├─ hub.publish("verification", …, stage=PRECHECKS|EXTRACTING|EVALUATING)   SSE hint
  │
  ├─ run_verification(session, deal, milestone, bundle)
  │    │
  │    ├─ 1. deterministic pre-checks            app/agents/verifier/prechecks.py
  │    │      • required artifact types present
  │    │      • evidence integrity: internal arithmetic consistency
  │    │      • dates inside the window, amounts against the milestone
  │    │      → may resolve the whole case with ZERO model calls (10.67% did)
  │    │
  │    ├─ 2. extraction                          one model call per artifact
  │    ├─ 3. clause rules                        pure Python where a clause is arithmetic
  │    ├─ 4. clause evaluation                   one model call for the judgement clauses
  │    ├─ 5. confidence                          computed in Python, then calibrated
  │    └─ 6. guards.decide(GuardInput(...))      the decision
  │
  ├─ sign the canonical attestation              EIP-712, app/attest/eip712.py
  ├─ IF decision == RELEASE:  engine.authorize_release(...)   ← writes the authorization
  │
  └─ ONE COMMIT: attestation + milestone state + ledger_event + outbox_event
```

> [!NOTE]
> Nothing after the commit can change the decision. The worker that later performs the payout reads
> the authorization; it never re-runs the verifier, and it **cannot reach it**.

**Further reading** &nbsp;
[Confidence is computed, not self-reported — ADR-003](DECISIONS.md#adr-003--confidence-is-computed-in-python-then-calibrated-on-a-separate-corpus) &nbsp;·&nbsp;
[What the pre-checks caught — Data §3](DATA.md#3-the-150-evaluation-bundles) &nbsp;·&nbsp;
[Watching it happen — Demo minute 2](DEMO.md#minute-2--milestone-01-releases-automatically)

---

## 3. Money path and the transactional outbox (I13)

<img alt="" src="https://img.shields.io/badge/I13-state_and_event_commit_together-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/I6-20_attempts_%E2%86%92_1_payout_1_rail_call-4FD1A5?style=flat-square&labelColor=0D0D10">

A financial state change and its Kafka event are never two independent writes.

```
                     ┌──────────────── ONE DB TRANSACTION ────────────────┐
authorize_release →  │  settlement_authorizations  INSERT                 │
                     │  milestones.state           UPDATE → RELEASE_APPROVED
                     │  ledger_events              INSERT (hash-chained)  │
                     │  outbox_events              INSERT (unpublished)   │
                     └──────────────────────┬─────────────────────────────┘
                                            │ COMMIT
                        ┌───────────────────▼──────────────────┐
                        │ relay.py                             │
                        │  SELECT … WHERE published_at IS NULL │
                        │  FOR UPDATE SKIP LOCKED              │
                        │  → Kafka → set published_at          │
                        └───────────────────┬──────────────────┘
                                            │ at-least-once
                        ┌───────────────────▼──────────────────┐
                        │ worker.py  (arq + Kafka consumer)    │
                        │  1. atomic DB claim on claimed_at    │
                        │  2. Redis lock (fast path only)      │
                        │  3. rail.release(idempotency_key)    │
                        │  4. mark_processed ON CONFLICT NOTHING
                        │  5. payout row + ledger + outbox     │
                        └──────────────────────────────────────┘
```

**At-least-once delivery, exactly-once effect.** The relay may publish an event twice; the worker's
first act is an atomic conditional `UPDATE … SET claimed_at = now() WHERE consumed_at IS NULL AND
(claimed_at IS NULL OR claimed_at < stale_before) RETURNING id`. A worker that gets no row back
returns `CLAIM_HELD_BY_ANOTHER_WORKER` **without acking**, so the message is retried rather than
silently dropped, and it makes **no rail call**.

That claim — not the Redis lock — is the serialisation point. The Redis lock is a fast path that
saves a database round trip in the common case; if Redis is down, correctness is unaffected.

> [!WARNING]
> This was a real bug. With the lock as the only guard and `required=False`, 20 concurrent releases
> produced 1 payout and **18 rail calls** — the payout table was right and the payment provider had
> been called eighteen times. Suite B check 7 now measures 20 attempts → **1 payout, 1 rail call**.
> The full post-mortem is
> [ADR-005](DECISIONS.md#adr-005--the-atomic-db-claim-not-the-redis-lock-is-the-idempotency-guarantee).

`CLAIM_TTL_S = 180` lets a worker that died mid-flight be superseded, and the rail's own idempotency
key makes the retry safe at the provider.

### Failure modes, and what each one costs

| failure | effect |
|:--|:--|
| **Relay dies before publishing** | Row stays `published_at IS NULL`; the next relay picks it up. Nothing is lost. |
| **Relay publishes twice** | The worker's claim admits one; the loser makes no rail call. |
| **Worker dies after the rail call, before the payout row** | The rail's idempotency key makes the retry a no-op at the provider; the payout row is written on retry. |
| **Kafka is down** | Outbox backlog grows, visible on `/ledger`. Money already authorised stays authorised. Nothing is dual-written. |
| **Redis is down** | Rate limiting and the lock fast path degrade; the DB claim still serialises. |
| **Postgres is down** | The API refuses readiness and the app halts at boot rather than pretending. |
| **An SSE client stays connected** | Nothing is pinned. The handler closes its database session **before** returning the stream, because a dependency-provided session is otherwise released only when the response finishes — which for SSE is hours. Left unfixed, every open tab sat `idle in transaction`, holding a pooled connection and an `ACCESS SHARE` lock on `ledger_events`. |
| **Rail call fails** | Payout row `FAILED` with the reason; the authorization stays unconsumed and can be retried. `_release_transition()` returns `None` when the milestone is already `RELEASE_APPROVED`, so the retry is legal. |
| **Milestone is disputed mid-flight** | The worker refuses with `MILESTONE_DISPUTED` and no money moves. Seen in the [demo transcript](DEMO.md#minute-4--milestone-03-a-dispute-and-an-advisory-arbiter). |

**Further reading** &nbsp;
[Runbook: the outbox backlog is growing](OPERATIONS.md#the-outbox-backlog-is-growing) &nbsp;·&nbsp;
[Runbook: a payout is stuck](OPERATIONS.md#a-payout-is-stuck) &nbsp;·&nbsp;
[Idempotency in the API](API.md#7-idempotency)

---

## 4. Evidence and provenance

<img alt="" src="https://img.shields.io/badge/I5-append--only,_hash--chained-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/enforced_by-POSTGRES_TRIGGER-4FD1A5?style=flat-square&labelColor=0D0D10">

### The Merkle tree

```
leaf content  = sha256( sha256(bytes) || sha256(canonical_json(fields)) )
leaf node     = sha256( 0x00 || leaf_content )
internal node = sha256( 0x01 || left || right )
leaves are sorted
an odd node is promoted by hashing it with itself
root          = evidence_merkle_root, stored on the attestation and signed
```

Both halves of the leaf content matter: `sha256(bytes)` binds the file, and
`sha256(canonical_json(fields))` binds the *extraction* — so changing what the system believes a
document says invalidates the proof even if the bytes are untouched. Suite C check 2 proves both:
`tampered_bytes_rejected=True`, `tampered_fields_rejected=True`.

> [!CAUTION]
> **The `0x00` / `0x01` tags are not decoration, and they were added after a forgery.** Without them a
> leaf and an internal node are both a plain `sha256` over 64 bytes, so an *internal* node submitted
> as a `leaf` with a one-step-shorter proof recomputes the published root — a second-preimage attack,
> reachable **unauthenticated** through `POST /evidence/verify`, which is precisely the endpoint whose
> job is to be trustworthy without trusting the server.
>
> The half that actually closes it is that `verify_proof` applies the leaf tag **itself**, rather than
> accepting a pre-tagged value from the caller. A verifier that trusts the shape of its input is not
> a verifier. See [Limitations §7](LIMITATIONS.md#7-three-defects-this-build-found-by-running-itself).

### Canonical JSON

Sorted keys, integers preserved as integers, UTC ISO-8601 with `Z`, no insignificant whitespace.
Suite C check 1 proves that reordering keys yields an identical hash and changing a value does not
(`key_order_independent=True`, `value_sensitive=True`).

### The signature

EIP-712 typed data over `(dealId, seq, evidenceRoot, attestationHash, decision, confidenceBps)`.

> [!TIP]
> The type-hash string is asserted **identically in Python and in Solidity**
> (`AegisEscrow.t.sol::test_typeHashes_matchPython`), so if the two ever drift, both test suites fail
> — rather than attestations quietly failing to recover on chain.

`GET /api/v1/provenance/attestations/{id}` returns `signature_verified` by **recovering the signer
address from the canonical hash**, not by comparing a stored string. Suite C check 3 measures
`recovered_signer == signer`, and that a confidence bump or a decision flip both fail to verify.

### The ledger

Append-only and hash-chained: `payload_hash = sha256(canonical_json(payload))`, and each row carries
the previous row's hash. Append-only is enforced by the `aegis_append_only()` Postgres trigger, not
by application discipline — Suite B check 5 issues an `UPDATE` and a `DELETE` and both raise **in the
database**.

`seq` uses `Identity(always=False, start=1)`; `autoincrement=True` on a non-primary-key column is a
no-op in SQLAlchemy, which was a real `NULL` violation before it was fixed.

`GET /api/v1/ledger/deals/{id}/verify` re-links the chain, reports the exact broken index on mismatch
(Suite C check 4: detected at index 3, reason `PAYLOAD_HASH_MISMATCH`), and **replays the balances
from the events alone**. A chain that links but replays to a different total is still a broken
ledger, so both are checked.

**Further reading** &nbsp;
[Signing and on-chain data — Security §6](SECURITY.md#6-signing-and-on-chain-data-i7) &nbsp;·&nbsp;
[Break it yourself — Demo minute 5](DEMO.md#minute-5--it-reconciles-and-you-can-break-it) &nbsp;·&nbsp;
[Public Merkle verification — API](API.md#endpoints-worth-knowing-about)

---

## 5. Tenant isolation (I12)

<img alt="" src="https://img.shields.io/badge/cross--tenant_read-404_NOT_403-FF4A4A?style=flat-square&labelColor=0D0D10">

Isolation is a repository concern, not per-endpoint discipline. `TenantRepo` takes the acting
organization at construction, and every accessor is scoped through one of two ownership kinds:

| kind | meaning | models |
|:--|:--|:--|
| `_OWN_ORG` | the row carries an `org_id` directly | `Entity`, `Notification` |
| `_VIA_DEAL` | the row is reachable only through a deal the org is party to, via an explicit join chain | `Milestone`, `EvidenceBundle`, `Artifact`, `Attestation`, `Dispute`, `LedgerEvent`, `DealMessage`, `Payout`, `SettlementAuthorization`, `ChainAnchor` |

`_VIA_DEAL` exists because of a real bug: artifacts were originally scoped by the *uploader's* org,
which meant a buyer could not read the seller's evidence on their own deal. **Ownership is being
party to the deal, not authorship of the row.**

A cross-tenant read returns **404, not 403**. A 403 confirms the resource exists.

There is no `?as=` parameter anywhere. The demo affordance (`POST /dev/assume`) performs a real login
for a seeded user through `auth_service.login` — password verification included — and is not
registered at all when `DEMO_MODE=false`.

**Further reading** &nbsp;
[Security §3](SECURITY.md#3-authorization-and-tenant-isolation-i12) &nbsp;·&nbsp;
[ADR-008](DECISIONS.md#adr-008--tenant-isolation-lives-in-the-repository-and-returns-404) &nbsp;·&nbsp;
[ADR-008c — when the test suite was passing vacuously](DECISIONS.md#adr-008c--an-enumerating-test-must-assert-that-it-enumerated-something)

---

## 6. Services

<img alt="" src="https://img.shields.io/badge/docker_compose_up_----wait-REAL_HEALTHCHECKS-4FD1A5?style=flat-square&labelColor=0D0D10&logo=docker&logoColor=4FD1A5">

| service | role |
|:--|:--|
| `postgres` | Source of truth. 30 tables, two append-only triggers, one money CHECK constraint. |
| `redis` | Rate limits, the lock fast path, ephemeral coordination. **Never** the source of truth. |
| `kafka` (KRaft) | 6 topics + 5 DLQs. A real readiness probe, not a sleep. |
| `migrate` | Runs Alembic once, behind a Postgres advisory lock, before anything else starts. |
| `backend` | FastAPI. `/health/ready` reports every dependency with `required` and `mode`. |
| `worker` | arq + Kafka consumer: rail calls, chain anchors, notifications. |
| `relay` | Publishes unpublished outbox rows. The only writer of `published_at`. |
| `frontend` | Next.js standalone, non-root. See the note below. |
| `mailpit` | Captures every outbound email in development. |
| `minio` | Optional (`--profile minio`) S3-compatible store; the default is the local store. |

> [!NOTE]
> **Why the frontend proxies `/api/*` through a route handler**, `app/api/[...path]/route.ts`, and
> not a `next.config.ts` rewrite: Next resolves rewrite destinations at build time and bakes them in,
> so a standalone image built without `API_INTERNAL_BASE` proxies to itself and every call fails with
> `ECONNREFUSED`. The handler reads the address per request and streams the upstream body, which SSE
> needs.

`docker compose up -d --wait` returns non-zero unless every healthcheck passes, so one-command
startup is a real assertion. Migrations run from exactly one place, so `api`, `worker` and `relay`
cannot race them.

**Further reading** &nbsp;
[Ports and one-command start — Operations §1](OPERATIONS.md#1-one-command-start) &nbsp;·&nbsp;
[The readiness contract — API](API.md#endpoints-worth-knowing-about)

---

## 7. Logging

<img alt="" src="https://img.shields.io/badge/I11-logs_never_carry_a_secret-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/masked_fields-24-C6C0B4?style=flat-square&labelColor=0D0D10">

[`app/common/logging.py`](../backend/app/common/logging.py) is the only module in the repository that
imports `logifyx`. Everything else calls `get_logger(name)`.

The wrapper exists because the shipped API differs from the documented one: `setup_logify()` takes no
arguments, `mask` is a boolean rather than a field list, and masking only touches the message string.
So the wrapper adds `AegisMaskFilter`, which masks structured `extra` fields as well, with
scheme-prefixed patterns ordered **before** key/value patterns — otherwise
`authorization: Bearer <token>` leaked the token.

The Kafka audit sink is a bridge, not a direct call: logifyx's `emit()` blocks synchronously and
caches a producer against a dead event loop, which hung the process for five minutes.
`_KafkaAuditSink` uses a bounded queue and one daemon thread with a persistent loop, plus an `atexit`
drain. **Five minutes became eight seconds.**

Because logifyx installs itself as the global logger class, the wrapper restores `logging.Logger`
immediately after each Aegis logger is constructed — otherwise SQLAlchemy's INFO stream floods the
output.

**Further reading** &nbsp;
[The full adaptation — ADR-002](DECISIONS.md#adr-002--logifyx-is-wrapped-not-used-directly) &nbsp;·&nbsp;
[The masked field list — Security §4](SECURITY.md#4-secrets-and-logging-i11)

---

## 8. Frontend

<img alt="" src="https://img.shields.io/badge/token_gate-FAILS_THE_DOCKER_BUILD-4FD1A5?style=flat-square&labelColor=0D0D10">

App Router, one client-side API module, and no ORM shape ever reaching a component.

```
design/tokens.css          verbatim from the design pack -- the only file that defines a colour
design/motion.ts           verbatim -- the only file that defines a duration or an easing
design/brand.ts            two literals for <meta name="theme-color">, read before any CSS
app/globals.css            component styles; every value is a token reference
scripts/check-tokens.mjs   fails the build on a hex colour, a raw duration or an inline easing,
                           and asserts the CSS duration scale equals D in motion.ts
scripts/check-i18n.mjs     fails the build on a key a component asks for that no dictionary has
```

Both checks run **inside the Docker build**, so an image cannot be produced from source that violates
them. CI additionally plants a hex colour and requires `check-tokens` to fail.

Three semantic hues and no more: mint = `PASS`/released, amber = `UNVERIFIABLE`/escalated/held,
red = `FAIL`/adverse. State becomes a hue in exactly one place, `lib/format.ts`.

**Further reading** &nbsp;
[The whole design and motion system](UI_MOTION.md) &nbsp;·&nbsp;
[ADR-010 — tokens copied verbatim](DECISIONS.md#adr-010--the-design-tokens-are-copied-verbatim-and-enforced-by-a-build-step)

---

## 9. What is deliberately absent

<img alt="" src="https://img.shields.io/badge/not_adopted-12_items,_each_with_a_reason-FFC24B?style=flat-square&labelColor=0D0D10">

No Kubernetes, no Terraform, no microservice split, no token or coin, no vector database, no RAG, no
second animation library, no invented design system.

Each of those was considered and rejected for a stated reason. The full table is the first thing on
[Decisions](DECISIONS.md#deliberately-not-adopted) — a system defined only by what it contains looks
arbitrary; a system that says what it refused looks designed.

---

<div align="center">

<sub><b>Aegis</b> · programmable escrow for agentic commerce</sub>

<p>
  <a href="README.md">&larr; Docs index</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="API.md">API &rarr;</a>
</p>

<sub>
<a href="../README.md">Overview</a> ·
<a href="API.md">API</a> ·
<a href="DATA.md">Data</a> ·
<a href="SECURITY.md">Security</a> ·
<a href="OPERATIONS.md">Operations</a> ·
<a href="DEMO.md">Demo</a> ·
<a href="UI_MOTION.md">UI &amp; Motion</a> ·
<a href="DECISIONS.md">Decisions</a> ·
<a href="LIMITATIONS.md">Limitations</a>
</sub>

</div>
