<div align="center">

# Limitations

**Read this before drawing conclusions from anything else in the repository.**

Every simulated integration below implements the **real provider interface** and is labelled
`SIMULATED` in the UI, in `RESULTS.md` and in the Overview.
**Nothing simulated is ever described as real.**

<p>
<img alt="Rail" src="https://img.shields.io/badge/payment_rail-SIMULATED-FFC24B?style=for-the-badge&labelColor=0D0D10">
<img alt="Model" src="https://img.shields.io/badge/AI_provider-OFFLINE_ADAPTER-FFC24B?style=for-the-badge&labelColor=0D0D10">
<img alt="Contract" src="https://img.shields.io/badge/contract-NOT_DEPLOYED-FFC24B?style=for-the-badge&labelColor=0D0D10">
<img alt="Corpus" src="https://img.shields.io/badge/corpus-SYNTHETIC-FFC24B?style=for-the-badge&labelColor=0D0D10">
</p>

<p>
<img alt="Labelling" src="https://img.shields.io/badge/labelled-PER_OPERATION,_NOT_PER_RAIL-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="Live key" src="https://img.shields.io/badge/live_razorpay_key-REFUSED_AT_STARTUP-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="Fake hashes" src="https://img.shields.io/badge/invented_tx_hashes-ZERO-4FD1A5?style=flat-square&labelColor=0D0D10">
</p>

<p>
  <a href="../README.md">Overview</a>
  &nbsp;·&nbsp; <a href="README.md">Docs</a>
  &nbsp;·&nbsp; <a href="ARCHITECTURE.md">Architecture</a>
  &nbsp;·&nbsp; <a href="API.md">API</a>
  &nbsp;·&nbsp; <a href="DATA.md">Data</a>
  &nbsp;·&nbsp; <a href="SECURITY.md">Security</a>
  &nbsp;·&nbsp; <a href="OPERATIONS.md">Operations</a>
  &nbsp;·&nbsp; <a href="DEMO.md">Demo</a>
  &nbsp;·&nbsp; <a href="UI_MOTION.md">UI &amp; Motion</a>
  &nbsp;·&nbsp; <a href="DECISIONS.md">Decisions</a>
  &nbsp;·&nbsp; <b>Limitations</b>
</p>

</div>

<samp>

[1. The payment rail](#1-the-payment-rail-is-simulated-in-this-configuration) &nbsp;·&nbsp;
[2. The AI provider](#2-the-ai-provider-is-the-deterministic-offline-adapter-in-this-configuration) &nbsp;·&nbsp;
[3. No contract is deployed](#3-no-contract-is-deployed) &nbsp;·&nbsp;
[4. The corpus is synthetic](#4-the-corpus-is-synthetic) &nbsp;·&nbsp;
[5. Adaptations from the spec](#5-adaptations-from-the-build-spec-recorded-rather-than-hidden) &nbsp;·&nbsp;
[6. Smaller gaps](#6-smaller-gaps-named) &nbsp;·&nbsp;
[**7. Defects found by running**](#7-three-defects-this-build-found-by-running-itself) &nbsp;·&nbsp;
[8. Before real money](#8-what-would-need-to-be-true-before-this-touched-real-money)

</samp>

---

## 1. The payment rail is simulated in this configuration

<img alt="" src="https://img.shields.io/badge/funding-SIMULATED-FFC24B?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/release-SIMULATED-FFC24B?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/refund-SIMULATED-FFC24B?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/webhook_verification-SIMULATED-FFC24B?style=flat-square&labelColor=0D0D10">

**What is real.** `RazorpayRail` is a complete implementation of the `PaymentRail` protocol against
the Razorpay REST API: order creation, capture, Route transfers for the seller release, refunds, and
HMAC webhook signature verification. It is selected the moment `PAYMENT_RAIL=razorpay` and a
`rzp_test_` key are present, with **no other code change**.

**What is simulated.** With no Razorpay key, `SimulatedRail` runs. It implements the same protocol,
returns deterministic references (`sim_rel_…`, `sim_ref_…`), and honours the same idempotency keys.

**How you can tell.** `GET /api/v1/payments/rail` labels **each operation** independently, and the UI
renders that label next to every payout on the ledger and provenance screens. The nav chrome shows
`RAIL SIMULATED` at all times.

**Why per-operation.** Webhook verification can be genuinely real while a payout is simulated —
`RAZORPAY_WEBHOOK_SECRET` is set independently of the API key. Collapsing that into one label would
be a lie in one direction or the other.

> [!CAUTION]
> **It refuses to escalate.** `RazorpayRail` raises `RAZORPAY_NOT_TEST_MODE` on a key id that is not
> `rzp_test_`. This system has never moved real money and **cannot start doing so because someone
> pasted the wrong key**.

**Further reading** &nbsp;
[Switching it on — Operations §3](OPERATIONS.md#razorpay--test-mode-only) &nbsp;·&nbsp;
[The disclosure endpoint — API §4](API.md#endpoints-worth-knowing-about)

---

## 2. The AI provider is the deterministic offline adapter in this configuration

<img alt="" src="https://img.shields.io/badge/AI_PROVIDER-fixture-FFC24B?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/network_calls-0-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/access_to_labels-NONE-4FD1A5?style=flat-square&labelColor=0D0D10">

**What is real.** `AnthropicProvider` (`claude-opus-5` / `claude-sonnet-5`,
`thinking={"type": "adaptive"}`, byte-stable cached system prompt) and `GroqProvider`
(OpenAI-compatible chat-completions with JSON-schema response formatting) are complete. Set
`AI_PROVIDER` and a key and re-run `make eval`.

**What is simulated.** `FixtureProvider` applies the **published clause rubric** to real parsed
artifact content — real PDF text extracted by `pypdf`, real pixels analysed by Pillow. It performs no
network call and **has no access to the labels**.

**What this means for the numbers.** Suite A's accuracy of 1.0 is a measurement of *the pipeline* —
pre-checks, extraction, clause rules, the confidence computation and the guard — with a deterministic
rubric standing in for the model's judgement. It is **not** a measurement of a live LLM's judgement,
and the Overview's results table says so on its own line.

Every generated report carries this banner:

> Numbers below were produced by the deterministic offline adapter (FixtureProvider): no API key was
> configured. It applies the published clause rubric to real parsed artifact content and has no
> access to the labels.

**What is not measured at all.**

* How a live model behaves on these bundles.
* Whether it is more or less conservative on `photos_cannot_establish_quantity`.
* Whether prompt injection embedded in a PDF changes a clause verdict.

**Cost and cache.** Measured spend is **0.0 USD** because nothing was called. The INR 2.5138 figure
is a **projection** from measured token counts at pinned list prices, labelled as one everywhere it
appears. The prompt-cache hit rate is **0.0** because there is no cache to hit; the cache-control
*shape* is asserted by `tests/unit/test_prompt_cache_contract.py`, which is the most that can be
verified without a provider.

**Further reading** &nbsp;
[Why all three providers share one protocol — ADR-009](DECISIONS.md#adr-009--groq-is-a-first-class-provider-not-a-fallback) &nbsp;·&nbsp;
[Pointing it at a live model — Operations §3](OPERATIONS.md#a-live-model)

---

## 3. No contract is deployed

<img alt="" src="https://img.shields.io/badge/foundry_tests-28_PASSING-4FD1A5?style=flat-square&labelColor=0D0D10&logo=solidity&logoColor=4FD1A5">
<img alt="" src="https://img.shields.io/badge/anchors-10_QUEUED_%C2%B7_0_CONFIRMED-FFC24B?style=flat-square&labelColor=0D0D10">

`AegisEscrow.sol` compiles, and 28 Foundry tests pass — including signature recovery, the
settlement-without-human revert, the split-must-balance revert, and an assertion that the EIP-712
type-hash strings are **byte-identical** to the Python ones.

But no `CONTRACT_ADDRESS` is configured for the recorded run, so:

* anchors sit in `QUEUED` and the API reports `chain_available: false` with a reason naming what is
  missing — `CONTRACT_ADDRESS_NOT_SET` under `docker compose`, `CHAIN_DISABLED` in the eval
  environment where `CHAIN_ENABLED=false`;
* the provenance screen shows `not anchored` where a transaction hash would be, and renders an
  explorer link **only** when the backend returns one;
* `make demo` prints `10 anchors queued, 0 confirmed` and the reason.

**What is still verified.** Suite C check 5 confirms every queued anchor payload carries exactly the
local attestation's canonical hash, so the moment a contract exists the anchors published are the
right ones. Run [`make deploy-contract`](OPERATIONS.md#the-contract), set `CONTRACT_ADDRESS`, re-run
Suite C, and the on-chain read-back half is verified too.

> [!IMPORTANT]
> **No transaction hash appears anywhere in this repository that does not exist.** The reasoning is
> [ADR-007](DECISIONS.md#adr-007--the-chain-is-a-notary-and-its-absence-is-never-hidden).

---

## 4. The corpus is synthetic

2,000 deals, 150 evidence bundles, 120 calibration bundles, 30 counterparties — all generated by
`scripts/generate_dataset.py` with a declared generative model and every base rate marked
`[assumed]` in [Data §2](DATA.md#2-base-rates-every-one-declared).

**What this costs.** The risk model's AUC of 0.7435 is measured on data whose label-generating
process is published in this repository. That is honest, and it is also why LightGBM loses: the
generator is logistic in exactly the model's features, so the boosted model has nothing extra to
exploit. **On real data the ordering could easily reverse.**
[ADR-006](DECISIONS.md#adr-006--the-risk-model-is-selected-on-validation-auc-and-the-loser-is-deleted)
says this rather than presenting the baseline win as a result.

**What is genuinely exercised.** The documents are real documents. `pypdf` really parses the text
layer, Pillow really analyses the pixels, and a "low quality scan" is really blurred.

> [!NOTE]
> The image analyser's first version reported the *backdrop* colour as the garment colour — a bug
> that **only a real-pixel corpus surfaces**. A corpus of stub objects would have passed.

---

## 5. Adaptations from the build spec, recorded rather than hidden

| spec says | reality | what was done |
|:--|:--|:--|
| `setup_logify(service=…, mask_fields=[…], kafka={…})` | logifyx 1.1.3's `setup_logify()` takes **no arguments**; `mask` is a boolean; masking touches only the message string | Wrapped behind one module, added `AegisMaskFilter` for structured extras and a queue-based Kafka bridge. Full detail in [ADR-002](DECISIONS.md#adr-002--logifyx-is-wrapped-not-used-directly). |
| — | logifyx's Kafka `emit()` blocks and caches a producer against a dead event loop, hanging the process for 5+ minutes | `_KafkaAuditSink`: bounded queue, one daemon thread with a persistent loop, `atexit` drain. **5 min → 8 s.** |
| — | logifyx installs itself as the **global** logger class, flooding output with SQLAlchemy INFO | `logging.Logger` restored immediately after each Aegis logger is built. |
| `design/tokens.css` verbatim | It defines **no durations**, while `motion.ts` defines them for Framer only — so `var(--d-fast)` in CSS resolved to nothing | The scale is declared once in `app/globals.css` and `check-tokens.mjs` asserts it equals `D` in `motion.ts` numerically. The pack files are still byte-verbatim. |
| Money never in floats | Unchanged | Integer paise, `BIGINT`, everywhere. |

---

## 6. Smaller gaps, named

| gap | why it is acceptable here | what it would cost to close |
|:--|:--|:--|
| **No pagination on list endpoints** | Every list is scoped to one organization and one deal; none can grow unboundedly in this product's shape | Cursor pagination on `/deals`, `/notifications`, `/ledger/deals/{id}` |
| **SSE, not WebSockets** | Traffic is one-directional; SSE reconnects for free and needs no protocol upgrade | A WebSocket transport, for collaborative editing this product does not have |
| **In-process SSE hub** | A second API replica wakes its own subscribers through a Redis hint, and every client refetches rather than trusting the payload — so a dropped hint costs a refresh, never a wrong number | A shared pub/sub fan-out |
| **No rate limit on deal chat** | Authenticated, tenant-scoped, and never used as evidence — but an unbounded write. Named in [Security §8](SECURITY.md#8-not-built-and-named-as-such) rather than left to be discovered | One `rate_limit()` call and a setting, matching the other buckets |
| **No MFA, no CSRF token** | Mitigated by `SameSite` cookies and a same-origin API; not eliminated | See [Security §8](SECURITY.md#8-not-built-and-named-as-such) |
| **No signing-key rotation** | `signer_key_id` is already stored per attestation, so rotation is additive rather than a migration | A key registry and a resolver |
| **Python dependency scanning is not gated in CI** | `npm audit --audit-level=moderate` **is** gated and passes at 0 vulnerabilities | `pip-audit` as a CI step with a triage policy |
| **The arbiter's arithmetic is trusted only after a human reads it** | By design (I8) — it is advisory, and settlement is blocked until `human_decided_by` is non-NULL | Nothing; this is the intended behaviour |
| **Latency is measured on one machine** | Reported as such: verifier pipeline only, no database, no rail, no chain | A load test against the deployed stack |

### The postcss advisory, and how it was actually resolved

Next 15.5.25 pins `postcss@8.4.31` internally, which carries four published advisories
(sourceMappingURL path traversal and arbitrary `.map` disclosure, plus XSS via an unescaped
`</style>` in stringify output). Every other consumer in the dependency tree already wants 8.5.28.

Resolution: an `overrides` entry hoists the whole tree to `postcss@8.5.28`, which removes Next's
nested copy entirely. Verified after the change:

```
$ npm audit
found 0 vulnerabilities
$ npm ls postcss
next@15.5.25            (no nested postcss)
```

The production build, the type-check, `check-tokens` and `check-i18n` all still pass, and
`npm audit --audit-level=moderate` is a **gating** CI step rather than an advisory one — so a
regression here **fails the build instead of being documented away**.

---

## 7. Three defects this build found by running itself

<img alt="" src="https://img.shields.io/badge/none_of_these-WERE_VISIBLE_BY_READING_THE_CODE-FF4A4A?style=flat-square&labelColor=0D0D10">

Recorded because **the way they were found matters more than the fixes**.

| defect | how it surfaced | fix |
|:--|:--|:--|
| The ledger's hash chain **forked** under concurrent appends | Running `make demo` against the live worker instead of an in-process bus. `verify_chain` reported `ok: false`. | A transaction-scoped Postgres advisory lock inside `append_ledger`, plus a 12-way concurrent test that fails without it |
| Every SSE subscriber sat **`idle in transaction`**, holding a pooled connection and a lock on `ledger_events` | It blocked the test suite's `TRUNCATE` and hung pytest. | The handler closes its session before returning the stream; a test asserts the transaction is gone |
| The I12 tenant-isolation suite was **passing vacuously** | Counting the routes it enumerated: **zero**. FastAPI 0.141 wraps included routers in objects with no `path`. | Enumerate from the OpenAPI document, and assert the enumeration is non-empty. It then immediately found two routes answering 200/`null` instead of 404 |

A fourth, milder one: revoking a session left its access token working until the TTL expired. Found
by resetting a password and then calling `/auth/me` with the old token. See
[ADR-008b](DECISIONS.md#adr-008b--session-revocation-is-checked-not-assumed).

> [!IMPORTANT]
> None of these were visible by reading the code. **All four came from running the assembled system
> and counting what actually happened.**

### And nine found by attacking it

<img alt="" src="https://img.shields.io/badge/critical-2-FF4A4A?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/high-4-FF4A4A?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/medium-3-FFC24B?style=flat-square&labelColor=0D0D10">

A later adversarial pass — backend, contract and container configuration — found nine more. They are
recorded here for the same reason: **the shape of the mistake is more instructive than the patch.**

> [!CAUTION]
> **The two critical findings share a lesson worth more than either fix.** Both let a *seller pay
> themselves*, and in both cases **every invariant on this page held throughout**: there was a
> qualifying attestation (I1), the money conserved to the paise (I4), the ledger chained (I5), and a
> named human had signed (I8).
>
> I8 requires **a** human. It never required a **disinterested** one. Verification and authorization
> are different axes, and a system that reasons only about evidence quality will keep passing its own
> tests while paying the wrong party.

| defect | why the existing tests missed it | fix |
|:--|:--|:--|
| **A seller could pay themselves after a verifier `REJECT`.** `REJECTED` is a disputable state, so the seller raises a dispute on their own milestone and their own admin resolves it 100% in their favour. Reproduced on pristine `HEAD`: `200 OK`, a full-value RELEASE authorization. | Every settlement test asked *"is this evidence good enough?"*. None asked *"who is standing to gain from the answer?"* | A resolution with `release_paise > 0` must be taken by the **buyer** org (`ONLY_BUYER_APPROVES_RELEASE`). A pure refund — the seller conceding — stays open to either side. |
| **A seller could self-approve their own escalated milestone.** `AdminDep` and the tenant repo are both satisfied for the seller's own milestone, and `authorize_release` accepts any human approval of an `ESCALATE` by design. Submit deliberately ambiguous evidence, get `ESCALATE`, approve it yourself. | The review queue was modelled as an operator function. Nobody modelled the reviewer as an interested party. | `APPROVE` restricted to the buyer org; `REJECT`, which moves no money, stays open to both. |
| **Merkle second-preimage forgery, reachable unauthenticated** through `POST /evidence/verify`. Leaves and internal nodes were both a plain `sha256` over 64 bytes, so an internal node submitted as a `leaf` with a one-step-shorter proof recomputed the published root. Verified `True` on `HEAD`. | Suite C proved tampered *bytes* and tampered *fields* are rejected. It never submitted a **well-formed proof of the wrong shape**. | RFC 6962 tagging: `leaf = H(0x00‖content)`, `node = H(0x01‖l‖r)` — with the leaf tag applied **inside** `verify_proof`, which is the half that actually closes it. |
| **Prompt injection reached the money path** (I2/I3). `clause_confidence` was an unbounded float from the model, and `calibrate` clipped *after* the unverifiable penalty — so `1e9` washed the penalty out and pinned confidence at 1.0, turning an `ESCALATE` into an auto-`RELEASE`. | I2 proves the agent packages cannot *import* the settlement engine. It says nothing about the **values** they hand it. A boundary that blocks calls but not data is half a boundary. | Clamp every model-supplied score to `[0,1]`; NaN and infinity become 0.0. Suite A is still 150/150 with 0 false releases. |
| **The I2 import-lint was bypassable three ways**: relative imports were skipped outright (`from ...settlement.engine import authorize_release` inside `app/agents/verifier/` resolves straight to the money path), and `importlib.import_module` and `__import__` were invisible to it. All three confirmed **not caught** on `HEAD`. | CI plants a violation and requires the lint to fail — but it planted an *absolute* one, the only kind the lint could see. | Resolve relative imports to absolute names, treat dynamic-import calls as imports, and refuse a module name built at runtime. The boundary suite went from **16 to 33 tests**. |
| **A buyer could poison the seller's evidence bundle.** `get_or_create_open_bundle` returned the milestone's open bundle to whoever asked, so a buyer could plant a self-inconsistent invoice; the integrity pre-check then turns that into a required `UNVERIFIABLE` clause which by I3 can **never** auto-release. That is a buyer veto of a RELEASE — the exact thing [Security §1](SECURITY.md#1-threat-model) says does not exist. | The bundle was treated as a property of the milestone rather than of the party who owes the evidence. | `ONLY_SELLER_SUBMITS_EVIDENCE` on upload and submit. Outsiders still get 404, not 403. |
| **`resolveDispute` routed around the I8 human-decision guard.** `recordSettlement` refuses a non-`RELEASE` without `humanApproved`, but `resolveDispute` wrote the settled amount and stamped `humanApproved = true` itself, gated only on `deal.state == DISPUTED` — which is per **deal**, while a dispute is raised per **milestone**. Disputing milestone 1 therefore unlocked `resolveDispute` for milestone 2. | `test_settlementOnEscalateWithoutHuman_reverts` passed the whole time. It proved one door was locked; nobody had checked the other door into the same room. | Require an actual dispute on **that milestone**, and clear the flag on resolution so a sibling dispute cannot re-open it. Pinned by `test_resolveDisputeOnAnUndisputedMilestone_reverts` and `test_resolveDisputeTwice_reverts`. |
| **Two sentinel-value bypasses.** `attestationHash == 0` means "not anchored" and `settledAmountPaise == 0` means "not settled" — and both zero values were *accepted as data*, so a milestone could be anchored twice with different decisions, or settled twice with the rail reference rewritten. | The `AlreadyAnchored` / `AlreadySettled` guards were tested with realistic values, never with the sentinel itself. | Reject zero for both. Pinned by `test_anchorWithZeroAttestationHash_reverts` and `test_settlementOfZeroAmount_reverts`. |
| **Every datastore, the message bus, the mail sink and the raw API were published on `0.0.0.0`.** Mailpit needs no authentication and holds the verification and password-reset links for every seeded account. | No test covers `docker-compose.yml`, and the port list read as ordinary developer convenience. | Bind everything but the app to `127.0.0.1`; add `no-new-privileges` and `cap_drop: ALL`. See [Operations §1](OPERATIONS.md#1-one-command-start). |

Three medium findings are not tabled above because they are ordinary hardening rather than a lesson:
a Pillow decompression bomb (a 47 KB PNG declaring 49 megapixels, now rejected from the header before
decode), an unauthenticated login **timing** oracle (no hash was computed on the account-miss path,
leaving the two responses ~78 ms apart despite identical bodies — now equalised, measured ratio
**1.01**), and three unauthenticated paths that returned a bare 500 instead of a typed error, which
is an I9 violation in its own right.

> [!IMPORTANT]
> **Every fix above was first reproduced as a failing proof-of-concept against pristine `HEAD`**, and
> each new test was confirmed to fail before the fix — so they pin real changes rather than
> describing behaviour that already existed. The backend suite went from **259 to 347 tests** and the
> contract suite from **24 to 28**.



---

## 8. What would need to be true before this touched real money

1. A Razorpay production integration, with settlement reconciliation against their reports, and a
   ledger that survives a provider-side correction.
2. A deployed, audited contract, with signing keys in a KMS or HSM and a rotation path exercised.
3. MFA, a CSRF token on cookie-authenticated writes, and a penetration test.
4. Calibration re-fitted on **real** outcomes rather than a synthetic corpus, and re-fitted on a
   schedule as the population drifts.
5. A measured live-model evaluation, including an adversarial pass for prompt injection embedded in
   evidence documents.
6. A regulatory review of escrow custody in the operating jurisdiction. **Aegis is escrow software;
   it is not an escrow licence.**

> [!NOTE]
> None of the six is a code-shaped problem, which is why none of them is claimed here.

---

<div align="center">

<sub><b>Aegis</b> · programmable escrow for agentic commerce</sub>

<p>
  <a href="DECISIONS.md">&larr; Decisions</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="README.md">Docs index</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="../README.md">Overview &rarr;</a>
</p>

<sub>
<a href="../README.md">Overview</a> ·
<a href="ARCHITECTURE.md">Architecture</a> ·
<a href="API.md">API</a> ·
<a href="DATA.md">Data</a> ·
<a href="SECURITY.md">Security</a> ·
<a href="OPERATIONS.md">Operations</a> ·
<a href="DEMO.md">Demo</a> ·
<a href="UI_MOTION.md">UI &amp; Motion</a> ·
<a href="DECISIONS.md">Decisions</a>
</sub>

</div>
