# Aegis - programmable escrow for agentic commerce

**Every rupee has a provable reason.**

Milestone escrow for deals between strangers. An AI verifies the evidence, a deterministic engine
moves the money, and every decision is signed, hash-chained and anchored.

> Every number in this document was produced by `make eval` on **2026-09-04T15:00:46+00:00** and is
> reproduced in [`backend/evals/out/RESULTS.md`](backend/evals/out/RESULTS.md). Nothing here is
> typed by hand. The run used the **deterministic offline adapter** (`AI_PROVIDER=fixture`) because
> no model key was configured - see [Which numbers are real](#which-numbers-are-real) and
> [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

---

## The thesis

Agents are starting to transact. The blocker is not payments - payments work. The blocker is that
**an agent's judgement is not an auditable basis for moving money.** When a buyer's agent and a
seller's agent agree that a milestone is complete, there is nothing a bank, a regulator or a
disappointed counterparty can inspect afterwards. "The AI decided" is not an audit answer.

Aegis is escrow where the release condition is a machine-checkable document, the verifier's decision
is a signed attestation over a Merkle root of the evidence it saw, and the code that authorises a
transfer is a pure function of that attestation which **cannot import the AI at all**.

### The why-chain

1. **Two strangers cannot transact on trust.** So money goes into escrow.
2. **Escrow needs a release condition.** A human reading an invoice does not scale to agent volume.
   So the condition is a structured document of typed clauses.
3. **Typed clauses need something to evaluate them.** Some are arithmetic; some need judgement about
   a photograph. So a deterministic pre-check layer runs first, and an LLM handles only the rest.
4. **An LLM's judgement cannot be trusted with money.** So the LLM never authorises anything: it
   emits a verdict per clause, the confidence is computed in Python from how much was checkable
   deterministically, and a pure guard function decides. **CI proves the agent packages cannot even
   import the settlement engine** ([I2](#the-invariants)).
5. **A machine that must always answer will guess.** So `UNVERIFIABLE` is a first-class verdict, a
   required `UNVERIFIABLE` clause can never auto-release, and the resulting escalation lands in a
   human queue that leads with *what the agent could not verify*.
6. **A decision nobody can re-check is not evidence.** So every decision is canonicalised, hashed,
   EIP-712-signed, hash-chained into an append-only ledger, and fingerprinted on chain.
7. **A ledger that only the operator can read is not an audit trail.** So the provenance screen
   re-verifies the signature, re-walks the Merkle path, re-links the chain and lets you flip one byte
   and watch it fail.

**Money never touches the chain.** Rupees move on Razorpay the entire time. The chain holds exactly
two things: the rulebook of the deal, so neither party can quietly edit it after the evidence
arrives, and a fingerprint of every AI decision. There is no token, no coin and nothing to stake.

---

## The invariants

Enforced in code **and** proven by a test. This is the strongest page in the repository.

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
| **I9** | Expected business failures return typed, machine-readable errors - never a bare 500. | Typed error envelope + API tests |
| **I10** | State machines are explicit transition tables. No scattered state-mutating `if`s. Unknown `(state, event)` raises `IllegalTransition`. | Table-driven transitions + exhaustiveness test |
| **I11** | No secrets committed. `.env.example` only, test-mode credentials only. Logs never contain passwords, tokens, API keys, private keys, raw PII or raw evidence. | Secret scan in CI + logifyx masking + log-assertion test |
| **I12** | **Tenant isolation.** No user may read or write another organization's deals, evidence, attestations, payouts, ledger records, messages or notifications. Every query is tenant-scoped. | Repository-layer org scoping + a dedicated cross-tenant test suite |
| **I13** | **No dual-write.** A financial state change and its Kafka event are never two independent writes. Use a transactional outbox: state + outbox row commit in one DB transaction; a relay publishes. | Outbox table + relay + crash-injection test |

### Where each one is proven

| # | Code | Proof |
|---|---|---|
| I1 | [`backend/app/settlement/engine.py`](backend/app/settlement/engine.py) | `tests/unit/test_guards_and_states.py`, `evals/suite_b` check 3 |
| I2 | [`backend/scripts/import_lint.py`](backend/scripts/import_lint.py) | `tests/security/test_import_boundary.py` (16 tests) + a CI step that **plants a violation and requires the lint to fail** |
| I3 | [`backend/app/settlement/guards.py`](backend/app/settlement/guards.py) | `tests/unit/test_guards_and_states.py`, Suite A (150 bundles) |
| I4 | `ck_deals_money_conservation` CHECK + [`guards.py`](backend/app/settlement/guards.py) | `tests/property/test_money_invariant.py` (Hypothesis), Suite B checks 2 and 4 (**4,000 random legal event sequences, 0 violations**) |
| I5 | [`backend/app/ledger/service.py`](backend/app/ledger/service.py) + `aegis_append_only()` trigger | Suite B check 5 (`UPDATE` and `DELETE` both raise **in the database**) |
| I6 | Atomic `claimed_at` claim in [`engine.py`](backend/app/settlement/engine.py) | `tests/concurrency/test_idempotency.py`, Suite B check 7: **20 attempts ⇒ 1 payout, 1 rail call** |
| I7 | [`backend/app/chain/adapter.py`](backend/app/chain/adapter.py) | `tests/security/test_import_boundary.py`, `contracts/test/AegisEscrow.t.sol` |
| I8 | `Dispute.human_decided_by` + dispute settlement guard | `tests/integration/test_end_to_end.py`, `AegisEscrow.t.sol::test_settlementOnEscalateWithoutHuman_reverts` |
| I9 | [`backend/app/common/errors.py`](backend/app/common/errors.py) | `tests/api/test_routes.py` (29 tests) |
| I10 | [`backend/app/deals/states.py`](backend/app/deals/states.py) | Suite B check 1: **81 deal pairs and 88 milestone pairs enumerated; 11 and 13 legal** |
| I11 | [`backend/app/common/logging.py`](backend/app/common/logging.py) + [`scripts/secret_scan.py`](backend/scripts/secret_scan.py) | `tests/security/test_log_masking.py` (11 tests) + a CI step that **plants a fake Razorpay live key and requires the scan to fail** |
| I12 | [`backend/app/db/repo.py`](backend/app/db/repo.py) | `tests/security/test_tenant_isolation.py` (10 tests, cross-tenant reads return **404, not 403**), enumerated from the OpenAPI document so a new unscoped route fails automatically - plus a test asserting the enumeration is **not empty**, because it once was ([ADR-008c](docs/DECISIONS.md)) |
| I13 | `outbox_events` + [`backend/app/relay.py`](backend/app/relay.py) | `tests/integration/test_outbox_and_seed.py`, Suite B check 9 (**crash injection: row survives, exactly-once effect**) |

---

## Measured results

All from `make eval`. Regenerate with `cd backend && uv run python -m evals.run_all`.

### Headline

| metric | value |
|---|---|
| **False releases** (hard gate: must be 0) | **0** |
| Labelled evidence bundles | 150 (50 adversarial) |
| Decision accuracy | **1.0** |
| Escalation rate | **0.24** (target band 0.12–0.25, in band) |
| Brier score (confidence vs release-correctness) | **0.0288** |
| Decisions resolved by deterministic pre-checks | **10.67%** (16/150, at zero AI cost) |
| Suite B - settlement integrity | **PASS** (9/9) |
| Suite C - provenance integrity | **PASS** (5/5) |
| Risk model selected | **logistic**, test AUC **0.7435** |
| Cost per verification (measured) | **0.0 USD** - no provider was called |
| Cost per verification (projected at pinned prices) | **INR 2.5138** |
| Prompt-cache hit rate | **0.0** - there was no provider to cache against |
| Backend tests | **259 passed** |
| Contract tests | **24 passed** |

### Confusion matrix - 150 held-out bundles

| expected \ decided | RELEASE | REJECT | ESCALATE |
|---|---|---|---|
| **RELEASE** | 96 | 0 | 0 |
| **REJECT** | 0 | 18 | 0 |
| **ESCALATE** | 0 | 0 | 36 |

### Per-adversarial-category accuracy

| category | n | accuracy | false releases |
|---|---|---|---|
| clean | 100 | 100.0% | 0 |
| wrong_date | 8 | 100.0% | 0 |
| altered_amount | 7 | 100.0% | 0 |
| right_type_wrong_milestone | 7 | 100.0% | 0 |
| fabricated_totals | 7 | 100.0% | 0 |
| low_quality_scan | 7 | 100.0% | 0 |
| photos_cannot_establish_quantity | 7 | 100.0% | 0 |
| valid_but_unusual | 7 | 100.0% | 0 |

### Confidence calibration

The confidence is **not** the model's self-report. It is computed in Python from the verifiable
fraction of the condition, the clause verdicts, the extraction quality and an unverifiable penalty,
then mapped through an isotonic fit on a **separate 120-bundle corpus generated with a different
seed** (`data/generated/calibration`). The 150 evaluation bundles are never used for fitting.

| confidence bucket | n | mean confidence | empirical release rate |
|---|---|---|---|
| 0.00–0.20 | 37 | 0.158 | 0.000 |
| 0.20–0.35 | 15 | 0.323 | 0.000 |
| 0.35–0.50 | 2 | 0.357 | 0.000 |
| 0.50–0.65 | 0 | - | - |
| 0.65–0.85 | 0 | - | - |
| 0.85–1.00 | 96 | 0.881 | **1.000** |

The map is anchored so that `confidence >= 0.85` ⟺ `p(release is correct) == 1` on the calibration
corpus. Measured anchors for this fit: `r0 = 0.816167`, `r1 = 0.979`, class-separable.

### Risk model - reported, not tuned away

| model | test AUC | test PR-AUC | test Brier |
|---|---|---|---|
| LightGBM | 0.7261 | 0.4652 | 0.1319 |
| **logistic baseline (selected)** | **0.7435** | **0.5318** | **0.1219** |

Selection happens on the **validation** split (logistic 0.8201, LightGBM 0.8076); the test split is
scored exactly once. On this corpus the generator behind `deal_went_bad` is itself logistic in these
features, so the gradient-boosted model has nothing extra to exploit and loses on variance. **The
service loads whichever model won on validation**, and this README says `logistic` because that is
what is actually scoring deals.

### Cost and latency

490 model calls across 150 bundles (3.267 per bundle). Measured spend **0.0 USD**, because the
deterministic offline adapter performs no network call. Applying the pinned list prices for
`claude-opus-5` / `claude-sonnet-5` to the token counts this run *did* measure projects
**0.028566 USD (INR 2.5138) per verification** - a projection, clearly labelled as one.

| stage | n | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| prechecks | 150 | 0.0 | 0.0 | 2.0 |
| extraction | 134 | 0.0 | 2.0 | 22.0 |
| clause_evaluation | 134 | 0.0 | 2.0 | 3.0 |
| **end to end** | 150 | **2.0** | **6.0** | **26.0** |

Verifier pipeline only - no database, no rail, no chain.

---

## Which numbers are real

This is the part most submissions leave out.

| claim | status |
|---|---|
| Verifier accuracy, escalation rate, Brier, confusion matrix | **Measured** on 150 bundles containing real PDFs with a real text layer and real PNGs with real pixels. The extraction path is genuinely exercised. |
| Suite B and Suite C integrity checks | **Measured** against real Postgres - triggers, CHECK constraints, row locking and crash injection. |
| Risk AUC, PR-AUC, Brier, pricing tier distribution | **Measured** on a 2,000-deal synthetic corpus with a declared generative model ([`docs/DATA.md`](docs/DATA.md)). |
| Latency | **Measured** wall-clock on the build machine. |
| Cost per verification | **0.0 USD measured** (no provider called). The INR 2.5138 figure is a **projection** from measured token counts at pinned list prices. |
| Prompt-cache hit rate | **0.0, and honestly so** - there is no cache to hit without a provider. The cache-control shape is asserted by `tests/unit/test_prompt_cache_contract.py`. |
| Model quality of a *live* LLM | **Not measured.** Set `AI_PROVIDER=anthropic` or `groq` with a key and re-run `make eval`. |
| Rupee movement | **Simulated** in this configuration. See the rail table below. |
| On-chain anchoring | **Queued, not confirmed** - no contract address is configured. Suite C verifies every queued anchor payload carries exactly the local attestation hash, so the moment a contract exists the right things get anchored. |

### Payment rail - labelled per operation

The mode comes from `GET /api/v1/payments/rail` and is rendered in the UI as well as here, so the
interface cannot claim a real payout while the backend simulates one.

| operation | this configuration | with Razorpay test keys |
|---|---|---|
| funding order + capture | `SIMULATED` | `REAL TEST MODE` |
| seller release | `SIMULATED` | `REAL TEST MODE` (Route) |
| refund | `SIMULATED` | `REAL TEST MODE` |
| webhook signature verification | `SIMULATED` | `REAL TEST MODE` |

`SimulatedRail` implements the same `PaymentRail` protocol as `RazorpayRail`, returns
deterministic `sim_*` references, and is selected only when no Razorpay key is present. Nothing in
the codebase branches on "is this a demo" inside a handler.

---

## Architecture

```
                    ┌──────────────────────────────────────────────┐
   Buyer / Seller ──▶│  Next.js 15 App Router (SSR + SSE)          │
                    └───────────────┬──────────────────────────────┘
                                    │  first-party /api/* rewrite, httpOnly cookie
                    ┌───────────────▼──────────────────────────────┐
                    │  FastAPI  ·  typed error envelope (I9)       │
                    │  TenantRepo: every query org-scoped (I12)    │
                    └──┬──────────────┬──────────────┬─────────────┘
                       │              │              │
        ┌──────────────▼───┐   ┌──────▼───────┐   ┌──▼──────────────────┐
        │ agents/          │   │ evidence/    │   │ settlement/         │
        │ verifier         │   │ Merkle tree  │   │ guards.py  (pure)   │
        │ extraction       │   │ sha256 leaves│   │ engine.py           │
        │ arbiter (advice) │   └──────┬───────┘   │   ▲                 │
        │                  │          │           │   │ MAY NOT be      │
        │  ✗ cannot import ├──────────┼───────────┼───┘ imported from   │
        │    settlement    │          │           │     agents/  (I2)   │
        └──────────────────┘          │           └──┬──────────────────┘
                                      │              │
                    ┌─────────────────▼──────────────▼─────────────┐
                    │  ONE DB TRANSACTION  (I13)                   │
                    │   • state change                             │
                    │   • hash-chained ledger_event  (I5)          │
                    │   • outbox_event row                         │
                    └───────────────┬──────────────────────────────┘
                                    │  relay (at-least-once)
                    ┌───────────────▼──────────────────────────────┐
                    │  Kafka (KRaft)  ─▶  arq worker               │
                    │                      • rail call (idempotent)│
                    │                      • chain anchor          │
                    │                      • notifications         │
                    └───────────────┬──────────────────────────────┘
                    ┌───────────────▼──────────────┐  ┌────────────────────┐
                    │ Razorpay  (rupees, always)   │  │ Base Sepolia       │
                    │                              │  │ hashes only  (I7)  │
                    └──────────────────────────────┘  └────────────────────┘
```

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Stack

Python 3.12 · uv · FastAPI · SQLAlchemy 2.0 (async) · Alembic · pydantic v2 · Postgres 16 ·
Redis 7 · Kafka (KRaft) · arq · logifyx · LightGBM + scikit-learn ·
Next.js 15 App Router · TypeScript · Tailwind · Framer Motion (`motion`) · viem ·
Foundry · Solidity 0.8.24 · Base Sepolia · pytest · Hypothesis · forge.

---

## Quickstart

Prerequisites: Docker Desktop, [`uv`](https://docs.astral.sh/uv/), Node 22, and
[Foundry](https://book.getfoundry.sh/) if you want to touch the contracts.

```bash
git clone --recurse-submodules <this repo> && cd Aegis-Razorpay

make bootstrap        # .env from .env.example, uv sync, npm ci, forge install
make up               # every service, waits for real healthchecks
make seed             # idempotent AND resumable demo data
make demo             # drives the seeded deal through the whole narrative
```

Then:

| what | where |
|---|---|
| app | <http://localhost:3000> |
| API docs | <http://localhost:8000/docs> |
| mail (Mailpit) | <http://localhost:8025> |
| Kafka UI | <http://localhost:8080> |

`make help` lists every target. Nothing requires a paid key: with no `AI_API_KEY` the deterministic
offline adapter runs, and with no Razorpay key the simulated rail runs - both labelled everywhere
they appear.

### Signing in

The login screen offers **Continue as the demo buyer / seller**. That posts to `/dev/assume`, which
runs the seeded user's real email and password through the ordinary login path and sets the same
httpOnly cookies. It does **not** bypass authorization, there is no `?as=` parameter anywhere, and
with `DEMO_MODE=false` the route is never registered.

---

## The demo

`make demo` drives the seeded deal - Meridian Apparel (Bengaluru) buying 2,500 cotton twill shirts
from Tirupur Knitworks - through three milestones and every branch that matters. Measured output of
the recorded run:

| step | outcome |
|---|---|
| Terms signed | `terms_hash 02cce074a972f7ac…` |
| Risk scored | **0.0083** → `TIER_1`, 0.8% fee, 30% prefund; top factor `-1.183` "on-time rate 91% across their deals" |
| Escrow funded | **INR 420,000.00** |
| Milestone 01 - fabric procured | pre-checks **8/8**, 3 model calls, **RELEASE @ 0.879** → **INR 126,000.00** released, `sim_rel_a21033dd…` |
| Milestone 02 - production complete | **ESCALATE @ 0.197**. Clause `c2` came back **UNVERIFIABLE**: *"4 photograph(s) cannot establish a count of 500; nothing in the pixels evidences a total, and nothing contradicts it either."* **No money moved.** |
| Human review | reviewer **APPROVED** with a written reason → **INR 168,000.00** released |
| Milestone 03 - delivered & accepted | **RELEASE @ 0.865**, then the buyer **raised a dispute** over 60 units |
| Settlement worker | **refused** the pending authorization, reason `MILESTONE_DISPUTED` |
| Arbiter (advisory) | `PARTIAL` @ 0.74 - release INR 115,920.00, refund INR 10,080.00, with its arithmetic shown and **two open questions it could not answer** |
| Human resolution | approved the split, `override_delta 0` |
| Final money | funded **420,000.00** = released **409,920.00** + refunded **10,080.00** + held **0.00** · `balanced: true` |
| Ledger | **37 events**, `verify ok`, head `f4d78c5004c9e768…` |
| Chain | **10 anchors queued, 0 confirmed** - `CONTRACT_ADDRESS / OPERATOR_PRIVATE_KEY not configured` |

Step-by-step walkthrough with URLs: [`docs/DEMO.md`](docs/DEMO.md).

---

## What to look at first

1. [`backend/app/settlement/guards.py`](backend/app/settlement/guards.py) - the only place a release
   is decided. `decide()` takes exactly one argument, so there is no parameter through which an
   override could be threaded.
2. [`backend/scripts/import_lint.py`](backend/scripts/import_lint.py) - and the CI step that plants a
   violation to prove the lint fails.
3. **The verification screen** - the clause table in source order, `UNVERIFIABLE` rendered with a
   label that never stops moving, and the confidence arithmetic printed underneath.
4. **The provenance screen** - press **Tamper one byte** and watch the digest mismatch, the row
   shake once and the Merkle proof refuse.
5. [`backend/evals/suite_b/run.py`](backend/evals/suite_b/run.py) check 7 - 20 concurrent releases,
   one payout, one rail call.

---

## Deployment

`docker compose up -d --wait` is the deployment. Both images are multi-stage and run as
**uid 10001**, non-root, with no build toolchain in the runtime layer. Migrations run from exactly
one place (the `migrate` service) behind a Postgres advisory lock, so `api`, `worker` and `relay`
cannot race them.

For real Razorpay test mode, a deployed contract, or a live model, see
[`docs/OPERATIONS.md`](docs/OPERATIONS.md). Every credential is read from the environment;
`.env.example` carries placeholders only and CI fails the build if a credential-shaped literal is
committed.

---

## Limitations

Read [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) before drawing conclusions. The short version:
the payment rail and the AI provider are simulated in this configuration, no contract is deployed,
and the corpus is synthetic with every base rate declared. Each simulated integration implements the
real provider interface and is labelled per operation in the UI as well as here.

---

## Documentation

| file | what it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Every component, the request paths, the outbox, the failure modes |
| [`docs/DATA.md`](docs/DATA.md) | The synthetic corpus, every base rate marked `[sourced]` or `[assumed]` |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | ADRs, and the table of things deliberately **not** adopted |
| [`docs/DEMO.md`](docs/DEMO.md) | The walkthrough, with URLs and what to point at |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, auth, tenant isolation, masking, the parts not built |
| [`docs/API.md`](docs/API.md) | The envelope, the error codes, the auth model |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Running it, going live on test keys, deploying the contract |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Everything simulated, missing, or not measured |
| [`docs/UI_MOTION.md`](docs/UI_MOTION.md) | The design and motion system as implemented |
| [`backend/evals/out/RESULTS.md`](backend/evals/out/RESULTS.md) | The full generated results |
