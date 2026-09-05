<div align="center">

# Operations

**Running it, moving it off the local adapters, and what to look at when something is wrong.**

Nothing in section 3 requires a code change. Every switch is an environment variable,
and every one of them changes what the UI reports about itself.

<p>
<img alt="Start" src="https://img.shields.io/badge/start-ONE_COMMAND-4FD1A5?style=for-the-badge&labelColor=0D0D10&logo=docker&logoColor=4FD1A5">
<img alt="Healthchecks" src="https://img.shields.io/badge/compose_----wait-REAL_HEALTHCHECKS-4FD1A5?style=for-the-badge&labelColor=0D0D10">
<img alt="Runbook" src="https://img.shields.io/badge/runbook-8_faults-C6C0B4?style=for-the-badge&labelColor=0D0D10">
</p>

<p>
<img alt="Seed" src="https://img.shields.io/badge/seed-IDEMPOTENT_+_RESUMABLE-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="Migrations" src="https://img.shields.io/badge/migrations-ONE_PLACE,_ADVISORY_LOCK-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="Live key" src="https://img.shields.io/badge/razorpay_live_key-REFUSED-FF4A4A?style=flat-square&labelColor=0D0D10">
</p>

<p>
  <a href="../README.md">Overview</a>
  &nbsp;·&nbsp; <a href="README.md">Docs</a>
  &nbsp;·&nbsp; <a href="ARCHITECTURE.md">Architecture</a>
  &nbsp;·&nbsp; <a href="API.md">API</a>
  &nbsp;·&nbsp; <a href="DATA.md">Data</a>
  &nbsp;·&nbsp; <a href="SECURITY.md">Security</a>
  &nbsp;·&nbsp; <b>Operations</b>
  &nbsp;·&nbsp; <a href="DEMO.md">Demo</a>
  &nbsp;·&nbsp; <a href="UI_MOTION.md">UI &amp; Motion</a>
  &nbsp;·&nbsp; <a href="DECISIONS.md">Decisions</a>
  &nbsp;·&nbsp; <a href="LIMITATIONS.md">Limitations</a>
</p>

</div>

<samp>

[1. One-command start](#1-one-command-start) &nbsp;·&nbsp;
[2. Seeding](#2-seeding) &nbsp;·&nbsp;
[3. Going live on real test credentials](#3-going-live-on-real-test-credentials) &nbsp;·&nbsp;
[4. Observability](#4-observability) &nbsp;·&nbsp;
[5. Runbook](#5-runbook) &nbsp;·&nbsp;
[6. Backup and restore](#6-backup-and-restore) &nbsp;·&nbsp;
[7. Configuration reference](#7-configuration-reference) &nbsp;·&nbsp;
[8. Before a shared deployment](#8-before-a-shared-deployment)

</samp>

---

## 1. One-command start

```bash
make bootstrap    # .env from .env.example, uv sync, npm ci, forge install
make up           # docker compose up -d --wait
make seed         # idempotent AND resumable
make demo         # drives the seeded deal through every branch
```

> [!IMPORTANT]
> `docker compose up -d --wait` returns **non-zero unless every healthcheck passes**, so
> one-command startup is a real assertion rather than a hope. Kafka's probe is
> `kafka-broker-api-versions.sh`, not a sleep.

Order is enforced by compose, not by documentation: `migrate` runs to completion before `backend`,
`worker` or `relay` start, and Alembic itself takes a **Postgres advisory lock**, so even a stray
manual `alembic upgrade head` cannot race a running one.

| service | published on | purpose |
|:--|:--|:--|
| frontend | `0.0.0.0:3000` | the app — **the only port reachable from another machine** |
| backend | `127.0.0.1:8000` | API and `/docs` |
| postgres | `127.0.0.1:5432` | source of truth |
| redis | `127.0.0.1:6379` | rate limits, lock fast path |
| kafka | `127.0.0.1:29092` | external listener |
| kafka-ui | `127.0.0.1:8080` | topics, consumer groups, lag |
| mailpit | `127.0.0.1:1025` / `:8025` | every outbound email |
| minio | `127.0.0.1:9000` / `:9001` | optional: `docker compose --profile minio up -d` |

> [!CAUTION]
> **Everything except the app is loopback-only, deliberately.** Mailpit needs no authentication and
> receives the email-verification and password-reset links for every seeded account, so a Mailpit
> port reachable from another machine is account takeover for every demo user. Redis answers `INFO`
> unauthenticated and kafka-ui ships with `DYNAMIC_CONFIG_ENABLED`. Every `localhost:` URL in these
> docs still works on the machine running the stack; from anywhere else, use an SSH tunnel.
>
> Container-to-container traffic uses compose service hostnames and is unaffected by this.

Services also run with `no-new-privileges` and `cap_drop: ALL`, as **uid 10001**. Details in
[Security §7](SECURITY.md#7-transport-and-headers).

`make help` lists every target. `make destroy` removes the volumes.

**Further reading** &nbsp;
[What each service does — Architecture §6](ARCHITECTURE.md#6-services)

---

## 2. Seeding

`make seed` is **idempotent and resumable**. It uses UUID v5 deterministic ids derived from a stable
namespace, so re-running applies nothing new:

```
second run: 0 applied, 8 skipped
```

> [!NOTE]
> Resumable matters more than idempotent. If the seed dies halfway — because Kafka was not up, or the
> process was interrupted — re-running completes the remaining steps instead of failing on the ones
> already done. Each step checks for its own output before doing work.

Demo passwords come from the environment (`DEMO_BUYER_PASSWORD`, `DEMO_SELLER_PASSWORD`) and are
never hardcoded. The seeded users are created **verified**, because an unverified account cannot fund
a deal and the demo would stop at minute one.

---

## 3. Going live on real test credentials

Nothing below requires a code change. Every one of these is an environment variable, and every one
changes what the UI and `/payments/rail` report about themselves.

### Razorpay — test mode only

<img alt="" src="https://img.shields.io/badge/Razorpay-TEST_MODE_ONLY-FFC24B?style=flat-square&labelColor=0D0D10&logo=razorpay&logoColor=FFC24B">

```bash
PAYMENT_RAIL=razorpay
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
RAZORPAY_ROUTE_SELLER_ACCOUNT=acc_...     # required for a real seller release via Route
```

> [!CAUTION]
> `RazorpayRail` **refuses to start on a live key** — a key id that is not `rzp_test_` raises
> `RAZORPAY_NOT_TEST_MODE`. That is deliberate: this system has never moved real money and must not
> start doing so because someone pasted the wrong key.

Restart and check:

```bash
curl -s localhost:8000/api/v1/payments/rail | jq
```

Each operation flips to `REAL TEST MODE` **independently**. Webhook verification only flips when
`RAZORPAY_WEBHOOK_SECRET` is set and is not a placeholder, so a half-configured rail reports itself
as half-configured instead of claiming to be real.

Point the Razorpay dashboard's webhook at `POST /api/v1/payments/webhooks/razorpay`. Signatures are
verified **before the body is parsed**, and every webhook is recorded and processed **once** through
the same idempotency machinery as a payout.

### A live model

<img alt="" src="https://img.shields.io/badge/default-DETERMINISTIC_OFFLINE_ADAPTER-FFC24B?style=flat-square&labelColor=0D0D10">

```bash
AI_PROVIDER=anthropic          # or groq
AI_API_KEY=...                 # or GROQ_API_KEY
```

Then re-run `make eval`. Every generated report states the provider that produced it, so a live run
and a fixture run can never be confused — the banner at the top of `RESULTS.md`, the `provider` block
in `summary.json`, the landing-page footnote and the nav chrome all read the same field.

With Anthropic: `claude-opus-5` for verification and arbitration, `claude-sonnet-5` for extraction,
`thinking={"type": "adaptive"}`, and **never** `budget_tokens` — it 400s on both models, and
`tests/unit/test_prompt_cache_contract.py` asserts it is not passed.

### The contract

```bash
export OPERATOR_PRIVATE_KEY=0x...      # a funded Base Sepolia key
make deploy-contract
```

Then set `CONTRACT_ADDRESS` and `VERIFIER_PRIVATE_KEY`, restart, and re-run
`cd backend && uv run python -m evals.suite_c.run`. Suite C check 5 stops reporting
`CHAIN_UNAVAILABLE` and starts reading each anchor back from the contract, comparing it with the
local attestation hash.

> [!IMPORTANT]
> Anchoring is **never** on the money path. A failed anchor leaves a `ChainAnchor` row in `FAILED`
> with `last_error` and retries; it does not block or reverse a payout, and the provenance screen
> shows the queue state rather than a hash that does not exist. See
> [ADR-007](DECISIONS.md#adr-007--the-chain-is-a-notary-and-its-absence-is-never-hidden).

**Further reading** &nbsp;
[What is simulated and how you can tell — Limitations](LIMITATIONS.md) &nbsp;·&nbsp;
[The per-operation rail disclosure — API](API.md#endpoints-worth-knowing-about)

---

## 4. Observability

### The three numbers that matter

```bash
curl -s localhost:8000/api/v1/health/metrics | jq '{outbox_backlog, dlq_depth, authorizations}'
```

| metric | non-zero means |
|:--|:--|
| **`outbox_backlog`** | Unpublished outbox rows. The relay is behind — **not** that an event was lost. Sustained growth means Kafka or the relay needs attention. |
| **`dlq_depth`** | Undrained dead letters. Something needs a human. |
| **`authorizations`** | Settlement authorizations written. Compare with payouts: they should track 1:1 once consumed. |

All three are on the `/ledger` screen, so an operator does not need a terminal.

### Readiness

```bash
curl -s localhost:8000/api/v1/health/ready | jq
```

`required` distinguishes a dependency that must be up (Postgres, the object store, the rail) from one
whose absence degrades a feature (Redis, Kafka, the chain RPC). Only Postgres halts the boot screen;
Kafka down shows *"EVENTS QUEUED IN THE OUTBOX"* and the chain RPC down shows
*"ANCHORING DISABLED"* — both accurate. The full response shape is in
[API §4](API.md#endpoints-worth-knowing-about).

### Logs

Structured JSON, one file per logger, with the masking described in
[Security §4](SECURITY.md#4-secrets-and-logging-i11). Every line carries `request_id`, matching the
`x-request-id` header, so a user-reported problem resolves to exact lines.

```bash
docker compose logs -f backend worker relay
make kafka-topics                    # the topic list
docker compose exec kafka kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups     # consumer lag
```

Set `LOG_TO_KAFKA=false` to disable the audit sink; it is a bounded queue with a single daemon
thread, so a Kafka outage cannot block a request path.

---

## 5. Runbook

Eight faults, each with the actual commands.

### The outbox backlog is growing

1. Is Kafka healthy? `docker compose ps kafka`
2. Is the relay alive? `docker compose logs --tail=50 relay`
3. Restart the relay: `docker compose restart relay`. It is safe to restart at any point — it selects
   `FOR UPDATE SKIP LOCKED` and only ever sets `published_at`.
4. **Nothing is lost while the backlog grows.** Money already authorised stays authorised; the event
   is the *notification*, not the decision. See
   [Architecture §3](ARCHITECTURE.md#3-money-path-and-the-transactional-outbox-i13).

### A payout is stuck

1. `GET /api/v1/settlements/deals/{id}` — is there an authorization, and is `consumed_at` null?
2. `GET /api/v1/payments/deals/{id}/payouts` — is there a `FAILED` row, and what is
   `failure_reason`?
3. If the authorization is unconsumed and the payout failed, **the retry path is legal**: the
   milestone stays `RELEASE_APPROVED` and `_release_transition()` returns `None` on that path rather
   than forcing an illegal transition. The event will be retried.
4. If `claimed_at` is set but old, `CLAIM_TTL_S = 180` lets another worker supersede it. The rail's
   idempotency key makes that safe at the provider.

### The DLQ has entries

Inspect them in Kafka UI on `aegis.dlq.*`. Each carries the original payload and the failure. Fix the
cause, then replay. A message reaches the DLQ after `MAX_ATTEMPTS = 5` with backoff, so **a DLQ entry
means a persistent fault, not a blip**.

### The ledger does not verify

```bash
curl -s localhost:8000/api/v1/ledger/deals/{id}/verify | jq
```

`broken_index` is the exact row, with `expected` and `found`.

> [!CAUTION]
> This should be impossible: the `aegis_append_only()` trigger refuses `UPDATE` and `DELETE` **in the
> database**. If it ever happens, someone has bypassed the application with elevated privileges — and
> the response tells you exactly where the chain broke.

### `make demo` says the deal was not found

`make eval` truncates every table so the suites run against a known-empty database — the seeded demo
deal goes with it. Re-seed and re-run:

```bash
make seed && make demo        # or: make eval-demo, which does eval -> up -> seed -> demo
```

### A deal advanced on its own after `make eval`

`make eval` truncates every table, including `processed_events` — but the Kafka topics still hold the
events published before the truncate. When the worker restarts it consumes them again, the dedupe
records are gone, and a deterministically-seeded deal can pick up a settlement from the previous life
of the database.

**Nothing is corrupted**: every affected deal still conserves to the paise and its ledger still
verifies. It is an artifact of emptying the database underneath a retained log, which nothing does in
normal operation. For a pristine demo after an eval run:

```bash
make destroy && make up && make seed && make demo    # or just: make demo-reset
```

### The test suite fails while the stack is running

The suite drives the relay and the consumers **in-process** against the compose Postgres. If the
`worker` and `relay` containers are running, they consume the same Kafka topics and the same
database, and they will win claim races against the test's own attempts — producing failures like
*"0 rail calls"* that are **the idempotency guarantee working, not a defect**.

`make test` stops those two services first for exactly this reason; `make up` brings them back.

> [!NOTE]
> CI does not run `pytest` at all — it runs the static gates and `make eval` only, so the 347-test
> suite is a **local** gate. `make ci` is the full local equivalent.

### A verification looks wrong

1. `GET /api/v1/verification/milestones/{id}` — the full attestation, including
   `confidence_components` and `deterministic_prechecks`.
2. `resolved_without_llm: true` means no model was involved at all; the pre-checks decided.
3. `prompt_hash` identifies the exact rendered prompt. `model_id` and `model_version` identify what
   answered.
4. The decision is **not re-derivable** by re-running the model — models are not deterministic — but
   it **is re-checkable**: the signature verifies against the canonical payload, and the Merkle root
   proves which evidence was seen. That distinction is the whole point of
   [Architecture §4](ARCHITECTURE.md#4-evidence-and-provenance).

---

## 6. Backup and restore

```bash
docker compose exec postgres pg_dump -U aegis aegis | gzip > aegis-$(date +%F).sql.gz
docker run --rm -v aegis_evidence:/data -v "$PWD":/backup alpine \
  tar czf /backup/evidence-$(date +%F).tar.gz -C /data .
```

> [!IMPORTANT]
> **Both are needed.** The database holds every hash; the evidence volume holds the bytes those
> hashes commit to. A database without the artifacts still verifies the ledger and every signature,
> but the Merkle proofs can no longer be re-walked against real bytes — which is precisely the
> property the [provenance screen](DEMO.md#the-provenance-screen--provenanceattestationid)
> demonstrates.

Restore: `gunzip -c … | docker compose exec -T postgres psql -U aegis aegis`, then untar the volume,
then `make migrate` (a no-op if the dump is current).

---

## 7. Configuration reference

Full template in [`.env.example`](../.env.example). The values that change **behaviour** rather than
addresses:

| variable | default | effect |
|:--|:--|:--|
| `DEMO_MODE` | `true` | Registers `/dev/*`. **Set `false` in any shared deployment** — the router then does not exist. |
| `PAYMENT_RAIL` | `simulated` | `razorpay` switches to real test mode; a live key is refused. |
| `AI_PROVIDER` | `fixture` | `anthropic`, `groq`, or the deterministic offline adapter. |
| `CHAIN_ENABLED` | `true` | With no `CONTRACT_ADDRESS`, anchors queue and report why. |
| `KAFKA_ENABLED` | `true` | `false` uses an in-memory bus. Correct for tests, wrong for anything multi-process. |
| `LOG_TO_KAFKA` | `true` | The audit log sink. |
| `COOKIE_SECURE` | `false` | **Set `true` behind TLS.** |
| `TRUST_PROXY_HEADERS` | `false` | Frontend. When `false` the proxy **drops** `x-forwarded-*` and `forwarded` from the client, so the backend's rate-limit identity is the socket address and cannot be spoofed by a header — but in a plain Compose deployment that address is the frontend container for every browser client, so IP buckets are effectively shared. Set `true` **only** behind a reverse proxy that overwrites those headers rather than appending to them. |
| `JWT_SECRET` | placeholder | Generate with `openssl rand -hex 32`. Rotating it invalidates every session. It also keys the presigned-artifact HMAC, so the Compose fallback must not survive into a shared deployment — see [Security §8](SECURITY.md#8-not-built-and-named-as-such). |
| `OBJECT_STORE` | `local` | `s3` for S3 or MinIO. |
| `RATE_LIMIT_AUTH` / `_VERIFY` / `_UPLOAD` | `10/60`, `12/60`, `40/60` | Token buckets, `count/seconds`. See [API §6](API.md#6-rate-limits). |

---

## 8. Before a shared deployment

<img alt="" src="https://img.shields.io/badge/checklist-9_items-FFC24B?style=flat-square&labelColor=0D0D10">

- [ ] `DEMO_MODE=false` — the demo login route stops existing
- [ ] `JWT_SECRET` regenerated — the Compose fallback is a published constant that signs sessions
      **and** keys the presigned-artifact HMAC
- [ ] `COOKIE_SECURE=true` and TLS terminating in front
- [ ] `TRUST_PROXY_HEADERS=true` **only if** a reverse proxy in front overwrites `x-forwarded-for`;
      leaving it off is the safe default
- [ ] Port bindings reviewed — only `3000` is public by default, and nothing else should become so
- [ ] `DEMO_BUYER_PASSWORD` / `DEMO_SELLER_PASSWORD` changed, or the seed skipped
- [ ] `CORS_ORIGINS` narrowed to the real origin
- [ ] Postgres and the evidence volume backed up, and a restore **actually tried**
- [ ] The gaps in [Security §8](SECURITY.md#8-not-built-and-named-as-such) read and accepted —
      there is no MFA and no CSRF token

---

<div align="center">

<sub><b>Aegis</b> · programmable escrow for agentic commerce</sub>

<p>
  <a href="SECURITY.md">&larr; Security</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="README.md">Docs index</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="DEMO.md">Demo &rarr;</a>
</p>

<sub>
<a href="../README.md">Overview</a> ·
<a href="ARCHITECTURE.md">Architecture</a> ·
<a href="API.md">API</a> ·
<a href="DATA.md">Data</a> ·
<a href="SECURITY.md">Security</a> ·
<a href="DEMO.md">Demo</a> ·
<a href="UI_MOTION.md">UI &amp; Motion</a> ·
<a href="DECISIONS.md">Decisions</a> ·
<a href="LIMITATIONS.md">Limitations</a>
</sub>

</div>
