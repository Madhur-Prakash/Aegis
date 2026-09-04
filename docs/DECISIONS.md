# Decisions

## Deliberately not adopted

The most useful page in a build like this is the list of things that were considered and rejected. A
system defined only by what it contains looks arbitrary; a system that says what it refused looks
designed.

| not adopted | why |
|---|---|
| **Kubernetes** | The whole system is ten containers on one host in the default profile, one of them a one-shot migration job. Kubernetes would add a control plane, a manifest tree and an operational surface larger than the product, and would make `docker compose up -d --wait` — a real, verifiable one-command start — impossible to keep. |
| **Terraform / IaC** | There is one deployment target and it is declared in `docker-compose.yml`. A second declaration layer would be a second thing to keep in sync, with nothing gained. |
| **A microservice split** | The interesting boundary in this system is `agents/` ⇸ `settlement/`, and that boundary is enforced *harder* by an AST import-lint in one process than it would be by an HTTP hop. Splitting into services would replace a compile-time guarantee with a network call that any service could make. |
| **A token, a coin, or staking** | Money moves on Razorpay in rupees, start to finish. A token would add custody risk, regulatory exposure and a second unit of account, and would solve nothing: the chain here is a notary, not a treasury. |
| **A vector database / RAG over the terms** | The release condition is a **structured document of typed clauses**, not a corpus. Retrieval would replace an exact, auditable evaluation of clause `c2` with a similarity search that cannot be audited. |
| **A second animation library** | Framer Motion (`motion`) does everything the design pack asks for. A second library would mean two easing vocabularies and two reduced-motion behaviours in one product. |
| **An invented design system** | The design pack's tokens and motion primitives are copied **verbatim** (`design/tokens.css`, `design/motion.ts`). `scripts/check-tokens.mjs` fails the build if a component reintroduces a literal, and additionally asserts the CSS duration scale equals `D` in `motion.ts`. |
| **A generic rules engine / DSL for clauses** | The clause kinds are a closed set with typed parameters. A DSL would let an operator write a clause the verifier cannot evaluate and the guard cannot reason about — which is exactly how a release condition becomes unauditable. |
| **LLM-in-the-loop confidence** | The model's self-reported confidence is not used for anything. See ADR-003. |
| **An admin override on the thresholds** | There is no code path for it. See ADR-001. |
| **Storing artifact bytes on chain** | I7. The chain gets hashes, ids, integers, enums and signatures. Bytes stay in object storage behind tenant-scoped presigned URLs. |
| **Soft deletes on the ledger** | `ledger_events` is append-only in the *database*, by trigger. A soft-delete column would be a way to un-say something that was said. |

### Provenance of this build

The design pack in `.claude/aegis/ui/` was read in full before any component was written, and the
four visual references it describes were studied for their *structure*, not copied:

* the **flap-reveal headline** and the boot staircase wipe come from reference A;
* the **column-mask (slat) backdrop** and per-line blur rise come from reference B;
* the **flanking sonar arcs** come from reference C;
* the **hover-panel card** and its restraint — nothing lifts, nothing gains a shadow — come from
  reference D.

Two deliberate departures: reference D's cursor is red, and this product reserves red for
`FAIL`/adverse only, so the cursor is `mix-blend-mode: difference` and carries no hue at all.
Reference B's hero imagery is lifestyle photography; there is none here, so the slats reveal a
generated hairline lattice instead.

---

## ADR-001 — The settlement decision is a pure function with one parameter

**Status:** accepted.

**Context.** Every escrow system eventually gets a request for an exception: a priority customer, an
urgent release, a support agent unblocking a stuck deal. Each one arrives as a plausible feature
request, and each one is a hole in the only guarantee the product sells.

**Decision.** `app/settlement/guards.py::decide()` takes **exactly one** parameter — a frozen
`GuardInput` — and returns `(decision, reasons)`. It performs no I/O, reads no settings and consults
no feature flag.

**Consequences.** There is nowhere to put `urgent=True`. Adding one would change the signature, which
would change every call site, which would appear in the diff. A human *can* release an escalated
milestone — that is what the review queue is for — but only by writing a `SettlementAuthorization`
with their user id and a mandatory written reason, which lands in the ledger. The threshold itself is
never bypassed; the decision is simply made by a person instead, and recorded as such.

**Rejected alternative.** A `settings.RELEASE_THRESHOLD` that operations could tune at runtime. A
threshold that can be lowered under pressure is not a threshold.

---

## ADR-002 — logifyx is wrapped, not used directly

**Status:** accepted, with the adaptation documented because the shipped API differs from the spec.

**Context.** The build spec calls for
`setup_logify(service=…, mask_fields=[…], kafka={…})`. The published package (1.1.3) exposes
`setup_logify()` with **no arguments**; `mask` is a boolean, not a field list; and masking applies
only to the formatted message string, not to structured `extra` fields.

**Decision.** One module — `app/common/logging.py` — imports `logifyx`. Nothing else in the
repository may. Inside it:

* `_MASK_FIELDS` and `AegisMaskFilter` mask structured extras as well as the message;
* `_MESSAGE_PATTERNS` puts scheme-prefixed patterns **first**, because
  `authorization: Bearer <token>` was leaking the token behind a key/value pattern that matched the
  header name but not the scheme;
* `_KafkaAuditSink` is a bridge — a bounded queue plus one daemon thread running a persistent event
  loop, with an `atexit` drain — because logifyx's `emit()` blocks synchronously and caches a
  producer against a dead loop. Directly wired, this hung the process for over five minutes; through
  the bridge, eight seconds;
* `logging.Logger` is restored as the global logger class immediately after each Aegis logger is
  built, because logifyx installs itself globally and SQLAlchemy's INFO stream otherwise floods the
  output;
* child handlers are removed and `propagate = True`, because both together produced duplicate lines.

**Consequences.** The dependency is honoured and pinned as the spec requires, the divergence is
recorded here rather than hidden, and swapping the library later touches one file.

---

## ADR-003 — Confidence is computed in Python, then calibrated on a separate corpus

**Status:** accepted.

**Context.** The obvious design is to ask the model how confident it is. That number is not a
probability, is not comparable between prompts, and moves when the prompt is reworded.

**Decision.** Confidence is computed from four measured components with published weights:

```
raw = 0.45 · verifiable_fraction
    + 0.45 · llm_component
    + 0.10 · extraction_quality
    − 0.50 · (unverifiable_required / total_required)
```

`raw` is then mapped through an isotonic fit of `P(RELEASE is the correct action | raw)` on a
**separate 120-bundle corpus generated with a different seed**, and finally through a monotone
threshold-anchored transform:

```
raw <= r0      →  0.35 · raw / r0                     ∈ [0.00, 0.35]
r0 < raw < r1  →  0.35 + 0.50 · p(raw)                ∈ (0.35, 0.85)
raw >= r1      →  0.85 + 0.15 · (raw − r1)/(1 − r1)   ∈ [0.85, 1.00]
```

with `r0 = max{raw : p == 0}` and `r1 = min{raw : p == 1}`.

**Consequences.** `confidence >= 0.85` means "release was correct every time this score occurred on
the calibration corpus" — an empirical claim, not a vibe. The measured 0.85–1.00 bucket contains 96
decisions with an empirical release rate of **1.000**, and the Brier score is **0.0288**. The
`confidence_components` object is returned by the API and rendered in full on the verification
screen, so the arithmetic is inspectable rather than asserted.

**Cost.** A second corpus must be generated and the fit is only as good as it. The anchors are
published (`r0 = 0.816167`, `r1 = 0.979`, class-separable) so the fit can be criticised.

**A real bug this design caught.** An earlier fit used isotonic crossings and produced `r1 = 0.988`,
compressing almost every genuine release into the top 1.2% of the range. Switching to
class-separated extremes made the map usable. Both methods are in `evals/fit_calibration.py` and the
method actually used is recorded in `calibration.json`.

---

## ADR-004 — A required `UNVERIFIABLE` clause escalates. It never rejects.

**Status:** accepted. This is the decision the product is built around.

**Context.** Early on, `decide()` treated an unverifiable required clause as a failure whenever
confidence fell below the reject threshold. That produced **31 cases** where the correct answer was
`ESCALATE` and the system returned `REJECT`.

**Decision.** Order of evaluation in `decide()`:

1. a required clause `FAIL` → `REJECT`
2. a required clause `UNVERIFIABLE` → **`ESCALATE`**, unconditionally, before any threshold is read
3. only then the thresholds

**Reasoning.** `FAIL` and `UNVERIFIABLE` are different claims. `FAIL` says *the evidence contradicts
the clause*. `UNVERIFIABLE` says *the evidence neither supports nor contradicts it, and I could not
tell*. Rejecting on `UNVERIFIABLE` punishes the seller for the machine's blindness; releasing on it
is a guess. Escalation is the only honest outcome, so a required `UNVERIFIABLE` can never
auto-release **and** never auto-reject.

**Consequences.** The escalation rate is a real cost — measured **0.24**, inside the 0.12–0.25 band.
It is reported as a headline number rather than buried, because a system that escalates a quarter of
its cases is making a claim about its own limits that a reader is entitled to weigh.

This is also why the interface never lets `UNVERIFIABLE` look settled: the chip resolves and then
keeps disturbing one glyph, forever. It is the only element in the product that never comes to rest,
and it is the only one that should not.

---

## ADR-005 — The atomic DB claim, not the Redis lock, is the idempotency guarantee

**Status:** accepted, after the first design failed a measurement.

**Context.** The first implementation took a Redis lock before the rail call. The lock was acquired
with `required=False`, so a worker that failed to acquire it **proceeded anyway**. Suite B measured
20 concurrent releases producing 1 payout and **18 rail calls** — the payout table was correct and the
payment provider had been called eighteen times.

**Decision.** The serialisation point is a single atomic statement in Postgres:

```sql
UPDATE settlement_authorizations
   SET claimed_at = now()
 WHERE id = :id
   AND consumed_at IS NULL
   AND (claimed_at IS NULL OR claimed_at < :stale_before)
RETURNING id
```

The winner commits immediately so racers see the claim *before* the rail call. A worker that gets no
row back returns `CLAIM_HELD_BY_ANOTHER_WORKER` **without acknowledging the message**, so delivery is
retried rather than silently dropped, and makes no rail call. The Redis lock remains only as a fast
path that avoids a round trip in the common case; if Redis is down, correctness is unchanged.

**Consequences.** Measured: 20 attempts → **1 payout, 1 rail call, 1 distinct result**.

Two further bugs surfaced and were fixed here rather than papered over:

* the losing racer's `mark_processed` collided on the primary key and rolled back the transaction,
  **voiding the winner's payout**. Fixed with `ON CONFLICT DO NOTHING` plus the non-acking return.
* retry after a rail failure was impossible, because the transition forced `ATTEST_RELEASE` from
  `RELEASE_APPROVED`. `_release_transition()` now returns `None` on that path, so a retry is legal
  while the state machine stays exhaustive.

`CLAIM_TTL_S = 180` lets a worker that died mid-flight be superseded; the rail's own idempotency key
makes that retry a no-op at the provider.

---

## ADR-006 — The risk model is selected on validation AUC, and the loser is deleted

**Status:** accepted.

**Context.** LightGBM is in the locked stack. On this corpus it **loses** to a logistic baseline:
test AUC 0.7261 vs 0.7435.

**Decision.** `report_d` fits both, selects on the **validation** split (logistic 0.8201, LightGBM
0.8076), deletes the losing booster artifact, and the risk service loads whichever model won. The
test split is scored exactly once, at the end.

**Consequences.** The README says `logistic`, because that is what actually scores a deal. The reason
is published in [`DATA.md`](DATA.md): the generator behind `deal_went_bad` is itself logistic in
these features, so the boosted model has nothing extra to exploit and loses on variance.

**Rejected alternative.** Tuning LightGBM until it wins. That would be fitting the model to the
corpus's known generative form, and reporting the result as if it generalised.

---

## ADR-007 — The chain is a notary, and its absence is never hidden

**Status:** accepted.

**Context.** No contract is deployed for the recorded run. The tempting move is to show a plausible
transaction hash.

**Decision.** Anchoring is asynchronous and advisory. `ChainAnchor` rows carry `QUEUED`, `PENDING`,
`CONFIRMED` or `FAILED`, and the UI renders an explorer link **only** when the backend returns one.
A failed or missing anchor never blocks or reverses a payout. Suite C check 5 verifies that every
queued anchor payload carries exactly the local attestation's canonical hash, so the moment a
contract address exists the right things get anchored.

**Consequences.** The provenance screen says `not anchored` where a hash would be, `make demo`
prints `10 anchors queued, 0 confirmed` with the reason
`CONTRACT_ADDRESS / OPERATOR_PRIVATE_KEY not configured`, and the README's results table marks
on-chain anchoring as **queued, not confirmed**. Nothing anywhere shows a transaction that does not
exist.

---

## ADR-008 — Tenant isolation lives in the repository, and returns 404

**Status:** accepted.

**Context.** Per-endpoint `if resource.org_id != user.org_id` checks are the standard approach and
the standard source of cross-tenant leaks: one endpoint forgets, and the leak is invisible until
someone finds it.

**Decision.** `TenantRepo` takes the acting organization at construction. Every accessor is scoped
through one of two declared ownership kinds — `_OWN_ORG` for rows carrying an `org_id`, and
`_VIA_DEAL` for rows reachable only through a deal the org is party to, with an explicit join chain.
A cross-tenant read raises `NotFound`, so the API returns **404, not 403**.

**Consequences.** Adding a model means declaring its ownership kind; there is no way to add a
tenant-scoped table and forget the scoping, because the repository has no unscoped accessor. A 403
would confirm the resource exists, so 404 it is.

**A real bug this shape caught.** Artifacts were first scoped by the *uploader's* organization, which
meant the buyer could not read the seller's evidence on their own deal. `_VIA_DEAL` encodes the
correct rule: ownership is being party to the deal, not having authored the row.

---

## ADR-008b — Session revocation is checked, not assumed

**Status:** accepted, after a live verification pass found the gap.

**Context.** Access tokens are stateless JWTs with a 15-minute TTL. `logout`, a password reset and
refresh-reuse detection all called `revoke_all_sessions`, which revokes **refresh** rows. Nothing
checked the access token against them, so a bearer token already in hand kept working for up to
fifteen more minutes — while the UI and `docs/SECURITY.md` both said "every other session is signed
out".

Found by exercising the flow against the running stack rather than by reading the code: reset the
password, then call `/auth/me` with the old token, and it answered 200.

**Decision.** `current_user` resolves the token's `sid` claim — which is the refresh **family id** —
and refuses the request if that family has no unrevoked row. One indexed lookup per authenticated
request.

**Consequences.** Revocation takes effect on the next request instead of within the TTL, which is
what the copy already promised. The cost is a query the stateless design avoided; a short-TTL deny
list in Redis would remove it, and is named as not-built in
[`SECURITY.md §8`](SECURITY.md#8-not-built-and-named-as-such).

**Rejected alternative.** Shortening the access TTL to a minute. That trades a real guarantee for a
smaller window and makes every client refresh constantly.

**Two tests now pin it**, both of which failed before the fix: the reset test asserts the old access
token is refused, and the logout test does the same.

---

## ADR-008c — An enumerating test must assert that it enumerated something

**Status:** accepted, after the I12 suite was found to be passing vacuously.

**Context.** `tests/security/test_tenant_isolation.py` builds its route list by introspecting the
application, so that a new tenant-owned route added without scoping fails automatically. It walked
`app.routes`. FastAPI 0.141 wraps each `include_router` call in an `_IncludedRouter` object that
exposes **no** `path`, so the walk yielded only the five app-level routes, every `/api/v1` path was
filtered out as "public", and the central assertion was `[] == []`.

The suite was green. It was testing nothing. That is the exact failure mode it exists to prevent,
and no amount of reading the assertions would have shown it.

**Decision.** Two changes:

1. The route list now comes from `app.openapi()["paths"]` — FastAPI's own introspection, which lists
   every path and method regardless of how the routers are attached internally.
2. A new test, `test_the_route_enumeration_is_not_empty`, asserts the enumeration finds at least 60
   routes and specifically contains the two nullable routes that had drifted. **An enumerating test
   that can silently enumerate nothing is worse than no test**, because it reports safety.

**What the working suite immediately found.** `GET /verification/milestones/{id}` and
`GET /evidence/milestones/{id}/bundle` answered an outsider with **200 and a `null` body** instead of
404. No data leaked — the repository scoping was correct — but the documented contract
("cross-tenant reads return 404") was not being kept, and a legitimate caller could not tell "not
verified yet" from "not your deal". Both now resolve the milestone through the tenant repo first.

**A third defect, in the same suite.** `test_no_tenant_route_answers_without_authentication` shared
the `client` fixture with the fixture that logs two users in — and `httpx.AsyncClient` persists
cookies, so every "unauthenticated" request carried a live session. It now uses its own cookie-free
client and asserts it stays that way.

---

## ADR-009 — Groq is a first-class provider, not a fallback

**Status:** accepted.

**Context.** The verifier needs a model. Anthropic (`claude-opus-5`, with
`thinking={"type": "adaptive"}` and never `budget_tokens`) is the primary. A second provider was
requested.

**Decision.** `AI_PROVIDER` selects `anthropic`, `groq` or `fixture`. All three implement the same
`LLMProvider` protocol returning an `LLMResult` with usage, model id, latency and prompt hash. Groq
uses the OpenAI-compatible chat-completions endpoint with JSON-schema response formatting.
`FixtureProvider` is the deterministic offline adapter: it applies the published clause rubric to
real parsed artifact content, performs no network call, and **has no access to the labels**.

**Consequences.** `make eval` runs with no key at all, and every surface that reports a number says
which provider produced it — `RESULTS.md`, the README, the landing page and the nav chrome all read
the same `ai_provider` field. The fixture adapter is never described as a model.

---

## ADR-010 — The design tokens are copied verbatim and enforced by a build step

**Status:** accepted.

**Context.** Design systems decay through exceptions: one hex colour for a one-off badge, one raw
`200ms` for a transition that felt slow.

**Decision.** `design/tokens.css` and `design/motion.ts` are copied verbatim from the design pack and
are the only files permitted to contain a literal colour, duration or easing.
`scripts/check-tokens.mjs` scans `app/`, `components/`, `hooks/` and `lib/` and fails on a hex
colour, an `rgb()`/`hsl()` literal, a raw CSS duration in a `transition`/`animation` value, a raw
Framer `duration:` number, or an inline `cubic-bezier()`.

One thing the pack does not provide: `tokens.css` defines no durations, while `motion.ts` defines
them for Framer only — so CSS transitions were referencing `var(--d-fast)`, which **did not exist**.
The scale is now declared once in `app/globals.css` and the checker asserts it equals `D` in
`motion.ts` numerically, so the two layers cannot drift.

Two literals live in `design/brand.ts`: `<meta name="theme-color">` is read before any stylesheet
exists, so it cannot be a `var()`. That file is inside the exempt directory and says why.

**Consequences.** Both checks run inside the Docker build, so an image cannot be produced from
violating source. CI additionally plants a hex colour and requires the check to fail, and plants a
divergent duration to prove the scale assertion works.
