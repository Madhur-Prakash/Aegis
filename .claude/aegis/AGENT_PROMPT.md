# BUILD AEGIS — EXECUTION PROMPT

Put the docs in `.claude/aegis/` so this prompt's paths resolve. Then paste everything below the
line into the coding agent.

---

You are the principal engineer building **Aegis** — programmable escrow for agentic commerce. INR
settles on Razorpay test-mode rails; the deal's state machine and every AI decision's provenance
are anchored on-chain so two parties who don't trust each other, and an AI that moves their money,
can all be audited later. It is a hackathon submission whose prize is judged on a public repo, a
5-minute video, and an architecture doc.

## 0. Read these before writing any code

All ten files live in `.claude/aegis/`. If they are not there, glob for `AEGIS_BUILD_SPEC.md` and
`0*-*.md` and use whatever directory contains them. Read **all ten, in full, in this order.** Do
not start until you have.

| # | File | What it gives you |
|---|---|---|
| 1 | `AEGIS_BUILD_SPEC.md` | The product, the whole backend, 13 safety invariants, domain model, state machines, verifier/arbiter design, Kafka + outbox flow, chain contract, eval harness, phase order, demo fixture, final validation |
| 2 | `ui/README.md` | Design thesis, non-negotiables, what the visual references contributed |
| 3 | `ui/00-DESIGN-SYSTEM.md` | Palette + semantics, typography, grid, micro-labels — **contains `tokens.css` complete** |
| 4 | `ui/01-MOTION-SYSTEM.md` | Durations, easings, 14 named variants, reduced-motion, perf rules — **contains `motion.ts` complete** |
| 5 | `ui/02-PRELOADER-AND-HERO.md` | Boot sequence and hero, with a millisecond timeline |
| 6 | `ui/03-DROP-IN-REVEALS.md` | Entrance system and which variant applies where |
| 7 | `ui/04-CURSOR-AND-HOVER.md` | Custom cursor, hover panel wipe, list magic-bar — working components |
| 8 | `ui/05-SCRAMBLE-CTA.md` | The scramble CTA and the `UNVERIFIABLE` reuse |
| 9 | `ui/06-SCREEN-BLUEPRINTS.md` | All six primary screens as layouts, plus supporting flows |
| 10 | `ui/07-REFERENCE-FRAMES.md` | The 16 stills in `ui/reference/` and what each drove; the "deliberately not adopted" table |

The 16 PNGs in `ui/reference/` are the visual ground truth. **Look at them** — they are cheaper
than guessing, and each doc names which frame explains which effect.

## 1. Precedence

- `AEGIS_BUILD_SPEC.md` wins on **behaviour, data, money and safety**.
- The `ui/` pack wins on **visual and motion detail**.
- Anything absent from both: choose the option that makes money movement safer, write the choice
  into `docs/DECISIONS.md`, and continue.
- If the two conflict, the spec wins and you note the conflict. (They were reconciled; §25 of the
  spec already points at the pack.)

## 2. Execution contract

1. **Build the entire system in one pass.** The spec's §35 order is an internal dependency
   sequence, not a set of approval gates. Do not stop after a phase to ask permission. Do not
   deliver a skeleton. Do not hand back a plan or pseudocode.
2. **Never report a number you did not measure.** Every metric in the README comes from
   `make eval`. Fabricating a metric, a transaction hash, a payout, or a test result is the worst
   possible outcome of this build — worse than an unfinished feature.
3. **If a test fails, fix the cause.** Never weaken a test to make CI green.
4. **If an external integration is unavailable**, implement the real provider interface, add a
   deterministic local adapter, label it clearly in the UI *and* the README, and record it in
   `docs/LIMITATIONS.md`. Never label a simulated call real.
5. **Add nothing from the spec's §39 exclusion list** (no Kubernetes, Terraform, microservices,
   token/coin/staking, vector DB, RAG, second animation library, invented design system).
6. Commit in coherent increments with real messages. Never commit a secret.

## 3. Copy these verbatim

- `frontend/design/tokens.css` ← the CSS block in `ui/00-DESIGN-SYSTEM.md` §5
- `frontend/design/motion.ts` ← the TS block in `ui/01-MOTION-SYSTEM.md` §5

Do not improvise a palette, a duration scale, or an easing curve. Every component references
tokens and named variants; **no component contains a hex colour, a raw duration, or an inline
easing curve.** Add a CI check for that if it is cheap.

## 4. These docs are NOT part of the submission — copy what is

`.claude/` is your working context, not the deliverable. The submitted repo must contain, in its
own `docs/`:

- `docs/UI_MOTION.md` ← the contents of the `ui/` pack (concatenate or copy the folder in)
- `docs/DECISIONS.md` ← starts with the "What was deliberately not adopted" table from
  `ui/07-REFERENCE-FRAMES.md` §"What was deliberately not adopted", plus its provenance note, then
  grows as you resolve ambiguities
- `docs/ARCHITECTURE.md`, `DATA.md`, `DEMO.md`, `SECURITY.md`, `API.md`, `OPERATIONS.md`,
  `LIMITATIONS.md` ← per spec §33

Also copy `ui/reference/` into the repo only if you want it there; it is optional and the PNGs are
screen recordings of third-party sites, so if you include them, keep the provenance note that says
they are motion references and nothing was reproduced from them.

## 5. The invariants — enforced in code and proven by tests

Full table with enforcement mechanisms in spec §3. The five that get broken most often:

- **I2** — the LLM never moves money. `agents/` may not import `settlement/`, `rails/` or
  `payments/`. **Ship the CI import-lint that fails on violation**, and verify it actually fails by
  deliberately breaking it once.
- **I3** — `conf >= 0.85` and no required clause `UNVERIFIABLE` → RELEASE. `0.35–0.85` → ESCALATE.
  `<= 0.35` → REJECT. A required `UNVERIFIABLE` clause can **never** auto-release. No bypass, no
  admin override of this rule.
- **I4** — `held + released + refunded == funded`, always. DB CHECK constraint plus a Hypothesis
  property test. Money is integer paise, never floats.
- **I6** — every money call idempotent on `(milestone_id, direction, attempt_no)`. 20 concurrent
  releases must produce exactly 1 payout and exactly 1 rail call. Test it.
- **I13** — no dual-write. State change and Kafka event commit in one DB transaction via the
  transactional outbox; a relay publishes. Prove it with a crash-injection test.

## 6. Ten things you will get wrong if you skim

1. **Hue is data.** Exactly three hues exist: mint = PASS/released, amber = UNVERIFIABLE/escalated/
   held, red = FAIL/adverse. The brand is monochrome. Do not add a coloured brand accent — it would
   collide with the state system and make the interface lie.
2. **`UNVERIFIABLE` never fully settles.** Its label resolves, then perpetually disturbs one random
   glyph at low amplitude, forever (`ui/05` §4). It is the only element in the product that never
   reaches rest. Under `prefers-reduced-motion` it stops and gains a static `?` and a dashed
   border.
3. **Confidence is computed in Python, not asked of the model** (`spec` §17.4). Weighted from how
   much of the condition was deterministically checkable, then calibrated against the labelled set.
   Show the breakdown in the UI.
4. **Deterministic pre-checks run before any LLM call.** A missing required artifact is a REJECT at
   zero token cost, and Report E must state what fraction of decisions resolved that way.
5. **Anthropic API, pinned:** model `claude-opus-5`, `thinking={"type": "adaptive"}`. **Never pass
   `budget_tokens`** — it 400s on Opus 5 and Sonnet 5. Structured output via
   `client.messages.parse(..., output_format=PydanticModel)`. Cache the byte-stable system prompt
   and assert `usage.cache_read_input_tokens > 0`.
6. **`make seed` must be idempotent AND resumable** (`spec` §8): UUIDv5 deterministic ids,
   `ON CONFLICT` upsert, a `SeedCheckpoint` table, and a `pg_advisory_lock`. Seeding three times
   changes nothing; an interrupted seed resumes. Never require dropping the DB.
7. **logifyx goes behind one wrapper** (`spec` §6) — `app/common/logging.py`, nothing else imports
   it. Verify the kwargs against the installed 1.1.3 and adapt the wrapper, never the call sites.
   Wire its mask list to I11 and test that masked fields never appear in output. Call `flush()`
   before worker exit and `shutdown()` in the FastAPI lifespan.
8. **Compose needs healthchecks** on postgres/redis/kafka with `condition: service_healthy`, and
   migrations run from one place behind an advisory lock. Without both, `docker compose up --build`
   from a clean clone is a coin flip — and it is a stated requirement.
9. **The `?as=buyer|seller` switch must not bypass authorization** (`spec` §14). It is a
   `DEMO_MODE`-gated dev endpoint that issues a *real* session for a seeded user through the normal
   login path. The router is not even registered when `DEMO_MODE=false`.
10. **Tenant isolation is a repository-layer concern, not per-endpoint discipline** (I12), and its
    test suite enumerates routers programmatically so a new unscoped route fails automatically.
    Cross-tenant reads return 404, not 403.

## 7. Stack — locked, do not substitute

Backend: Python 3.12 · uv (`pyproject.toml` + committed `uv.lock`) · FastAPI · SQLAlchemy 2.0 ·
Alembic · pydantic v2 · Postgres 16 · Redis 7 · Kafka (KRaft, single broker) · arq · logifyx ·
LightGBM. Frontend: Next.js 15 App Router · TypeScript · Tailwind · shadcn/ui · Framer Motion
(`motion`) · viem. Chain: Foundry · Solidity 0.8.24 · Base Sepolia. Tests: pytest · hypothesis ·
forge. Three process entrypoints (`main.py`, `worker.py`, `relay.py`) sharing one codebase —
modular monolith, not microservices.

## 8. Definition of done

Run every command in spec §37 and fix what fails:

```
docker compose config && docker compose build && docker compose up -d
make db-upgrade && make seed && make seed      # second seed must be a no-op
make lint && make test && make contract-test
make eval && make demo
make verify-ledger && make verify-chain
```

Then walk the manual checklist in §37 — including the responsive pass at **375 / 768 / 1440**, both
themes, English and Hindi, and with animations both on and off.

The build is not done until these three sentences are demonstrably true:

1. *"The LLM never moves money. It writes a signed attestation; a deterministic settlement engine
   reads it — and here is the CI check that fails if those two modules ever import each other."*
2. *"It did not guess and it did not block. It said what it could not verify, and asked for a
   human."*
3. *"Zero false releases across 150 labelled evidence bundles, and you can reproduce that with
   `make eval`."*

Finally, report the BUILD STATUS block from spec §37 with **measured values only**.

## 9. Start now

Read the ten files. Then build. Report BUILD STATUS when the system runs and the evals are green.
