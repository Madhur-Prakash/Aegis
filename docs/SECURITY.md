<div align="center">

# Security

**What is defended, how — and, in the last section, what is deliberately not built.**

A threat model that lists only strengths is marketing.

<p>
<img alt="Adversaries" src="https://img.shields.io/badge/threat_model-10_adversaries-C6C0B4?style=for-the-badge&labelColor=0D0D10">
<img alt="Named gaps" src="https://img.shields.io/badge/named_gaps-13-FF4A4A?style=for-the-badge&labelColor=0D0D10">
<img alt="Cross-tenant" src="https://img.shields.io/badge/cross--tenant_read-404_NOT_403-4FD1A5?style=for-the-badge&labelColor=0D0D10">
</p>

<p>
<img alt="Argon2id" src="https://img.shields.io/badge/passwords-Argon2id-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="Cookies" src="https://img.shields.io/badge/tokens-httpOnly_%C2%B7_SameSite-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="Masked fields" src="https://img.shields.io/badge/masked_log_fields-24-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="Secret scan" src="https://img.shields.io/badge/secret_scan-GATED_IN_CI-4FD1A5?style=flat-square&labelColor=0D0D10&logo=githubactions&logoColor=4FD1A5">
<img alt="Containers" src="https://img.shields.io/badge/containers-uid_10001,_cap_drop_ALL-C6C0B4?style=flat-square&labelColor=0D0D10&logo=docker&logoColor=4FD1A5">
</p>

<p>
  <a href="../README.md">Overview</a>
  &nbsp;·&nbsp; <a href="README.md">Docs</a>
  &nbsp;·&nbsp; <a href="ARCHITECTURE.md">Architecture</a>
  &nbsp;·&nbsp; <a href="API.md">API</a>
  &nbsp;·&nbsp; <a href="DATA.md">Data</a>
  &nbsp;·&nbsp; <b>Security</b>
  &nbsp;·&nbsp; <a href="OPERATIONS.md">Operations</a>
  &nbsp;·&nbsp; <a href="DEMO.md">Demo</a>
  &nbsp;·&nbsp; <a href="UI_MOTION.md">UI &amp; Motion</a>
  &nbsp;·&nbsp; <a href="DECISIONS.md">Decisions</a>
  &nbsp;·&nbsp; <a href="LIMITATIONS.md">Limitations</a>
</p>

</div>

<samp>

[1. Threat model](#1-threat-model) &nbsp;·&nbsp;
[2. Authentication and sessions](#2-authentication-and-sessions) &nbsp;·&nbsp;
[3. Tenant isolation](#3-authorization-and-tenant-isolation-i12) &nbsp;·&nbsp;
[4. Secrets and logging](#4-secrets-and-logging-i11) &nbsp;·&nbsp;
[5. Evidence handling](#5-evidence-handling) &nbsp;·&nbsp;
[6. Signing and on-chain data](#6-signing-and-on-chain-data-i7) &nbsp;·&nbsp;
[7. Transport and headers](#7-transport-and-headers) &nbsp;·&nbsp;
[**8. Not built**](#8-not-built-and-named-as-such) &nbsp;·&nbsp;
[9. Reporting](#9-reporting)

</samp>

---

## 1. Threat model

| adversary | wants | primary defence |
|:--|:--|:--|
| **A dishonest seller** | Release on evidence that does not support the clause | Deterministic pre-checks before any model call; `FAIL` on a required clause is an immediate `REJECT`; the evidence-integrity pre-check catches internally inconsistent documents (fabricated totals) that read as valid in isolation |
| **A dishonest seller** | Release on evidence the machine *could not read* — by approving it themselves | **A side check, not the guard.** Approving a human review that releases money, and resolving a dispute with `release_paise > 0`, are both restricted to the **buying** organization (`ONLY_BUYER_APPROVES_RELEASE`). A `REJECT`, which moves nothing, and a pure refund stay open to either party |
| **A dishonest buyer** | Withhold payment on satisfied conditions | Verification is symmetric — the buyer cannot veto a `RELEASE`; a dispute must be raised with a claim, is recorded in the ledger, and settling it needs a human decision with a written reason |
| **A dishonest buyer** | Manufacture a veto by poisoning the evidence | Evidence upload and submission are restricted to the **selling** organization (`ONLY_SELLER_SUBMITS_EVIDENCE`). Without this, a buyer could plant a self-inconsistent invoice into the open bundle, which the integrity pre-check turns into a required `UNVERIFIABLE` clause that by I3 can never auto-release — a veto through the front door |
| **A curious tenant** | Read another organization's deals, evidence or ledger | Tenant scoping in the repository layer, not per endpoint (I12); cross-tenant reads return **404** so existence is not confirmed |
| **A prompt injector** | Get an LLM to authorise a transfer | The agent packages **cannot import** the settlement engine, the rails or the payments layer; CI proves the lint fails on a planted violation (I2). The worst a successful injection achieves is a wrong clause verdict, which then flows through the guard and the thresholds like any other verdict |
| **A tamperer** | Alter evidence or a decision after the fact | Merkle root over `sha256(bytes) ‖ sha256(canonical_json(fields))`; EIP-712 signature over the canonical hash; append-only hash-chained ledger enforced by a Postgres **trigger** |
| **An insider** | Quietly lower a threshold, or release without a record | `decide()` takes one frozen parameter and reads no settings; a human release writes an authorization carrying their user id and a mandatory reason into the append-only ledger |
| **A replay attacker** | Double-spend a settlement event | Idempotent on `(milestone_id, direction, attempt_no)` with a unique index; an atomic DB claim admits exactly one worker; the rail receives an idempotency key |
| **A credential thief** | Reuse a stolen refresh token | Refresh rotation with **family revocation on reuse**; a password reset revokes every other session, and the access token is refused on the next request |

> [!IMPORTANT]
> The prompt-injector row is the one worth dwelling on. The defence is **not** a better prompt or an
> output filter — it is that the code which could move money is unreachable from the code that talks
> to the model. See [Architecture §1](ARCHITECTURE.md#1-the-one-boundary-that-matters).

> [!CAUTION]
> **Why two of these rows are about *who asks*, not *what the evidence shows*.** The settlement guard
> and I8 answer a different question from the one an attacker actually asks. I8 requires **a** human
> to decide a dispute — it does not require a **disinterested** one. A seller could therefore raise a
> dispute on their own milestone, have their own admin resolve it wholly in their favour, and every
> invariant on this page was satisfied the entire time: there was a qualifying attestation, the money
> conserved, the ledger chained, and a named human had signed.
>
> Authorization is a separate axis from verification, and a system that only reasons about evidence
> quality will keep passing its own tests while paying the wrong party. Both holes were found by an
> adversarial pass, are pinned by tests in `tests/security/`, and are written up in
> [Limitations §7](LIMITATIONS.md#7-three-defects-this-build-found-by-running-itself).

---

## 2. Authentication and sessions

<img alt="" src="https://img.shields.io/badge/revocation-IMMEDIATE,_NOT_EVENTUAL-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/enumeration_oracle-NONE-4FD1A5?style=flat-square&labelColor=0D0D10">

* **Argon2id** password hashing (`argon2-cffi`).
* Access and refresh tokens in **httpOnly, SameSite** cookies. The frontend talks to `/api/*` on its
  own origin, so the cookie is first-party and there is no CORS-credentials arrangement to get wrong.
* **Refresh rotation.** Using a refresh token issues a new one and invalidates the old. Replaying a
  rotated token revokes the **entire family** — and the revocation is committed inside the service
  *before* the error is raised, because a router that raises before committing would leave the family
  alive. That was a real bug.
* **Revocation is immediate, not eventual.** The access token is a stateless JWT, so revoking the
  refresh token alone left a bearer token working for the rest of its 15-minute TTL. `current_user`
  now checks the token's `sid` (its refresh-family id) against the refresh rows and refuses a token
  whose family has been revoked — one indexed lookup per request.
* Password reset revokes every other session, and the UI says so — truthfully.
* Login failures are indistinguishable for "no such account" and "wrong password" — in the body
  **and on the clock**. Until recently only the body matched: no hash was computed when the account
  did not exist, leaving the two paths about 78 ms apart, which is a perfectly good enumeration
  oracle. `login` now runs a dummy Argon2 verification on the miss path; the measured ratio between
  the two is **1.01**. `POST /auth/forgot-password` returns the same confirmation either way.
* Email verification gates every state-changing action. An unverified user can sign in and read;
  creating or funding a deal, submitting evidence and approving anything all return
  `EMAIL_NOT_VERIFIED`.

> [!NOTE]
> Verified against the running stack, not inferred from the code: after a logout, a reset, or
> refresh-reuse detection, the previously valid access token returns **401 on the next call**. The
> gap that made this necessary, and how it was found, is
> [ADR-008b](DECISIONS.md#adr-008b--session-revocation-is-checked-not-assumed).

### Rate limits

Redis token buckets. Login is limited **per client IP and per account**, so one account cannot be
brute-forced from many addresses.

| bucket | default | keyed by |
|:--|:--|:--|
| `auth:register`, `auth:login`, `auth:forgot` | `10 / 60s` | client IP |
| `auth:login:account` | `10 / 60s` | normalised email |
| `auth:resend` | `3 / 60s` | client IP |
| `verify` | `12 / 60s` | organization |
| `upload` | `40 / 60s` | organization |

Exceeding a limit returns `RATE_LIMITED` (429). The limiter stays **enabled** in the test suite and
has its own test proving the 429, rather than being switched off to make CI quiet.

The full bucket table, including the one surface that is **not** limited, is in
[API §6](API.md#6-rate-limits).

---

## 3. Authorization and tenant isolation (I12)

<img alt="" src="https://img.shields.io/badge/isolation-ARCHITECTURAL,_NOT_PER--ENDPOINT-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/dedicated_tests-10-C6C0B4?style=flat-square&labelColor=0D0D10">

Isolation is architectural. `TenantRepo` is constructed with the acting organization and there is
**no unscoped accessor** — adding a tenant-scoped table means declaring its ownership kind:

| kind | rule | models |
|:--|:--|:--|
| `_OWN_ORG` | the row carries `org_id` | `Entity`, `Notification` |
| `_VIA_DEAL` | the row is reachable only through a deal the org is party to, with an explicit join chain | `Milestone`, `EvidenceBundle`, `Artifact`, `Attestation`, `Dispute`, `LedgerEvent`, `DealMessage`, `Payout`, `SettlementAuthorization`, `ChainAnchor` |

Cross-tenant access raises `NotFound` → **404, not 403**, because a 403 confirms the resource exists.
The dedicated tests in `tests/security/test_tenant_isolation.py` cover deals, milestones, evidence,
artifacts, attestations, ledger entries, messages, notifications and payouts, and the route list they
walk is enumerated from the OpenAPI document so a new unscoped route fails automatically.

Roles are `OWNER`, `ADMIN`, `MEMBER`, `VIEWER`, and they are **ranked**: nobody may demote or
remove a member who outranks them (`ROLE_RANK_INSUFFICIENT`). Peers and yourself are still allowed,
because `transfer_ownership` depends on both. Without the rank check an `ADMIN` could demote an
`OWNER` — last-owner protection only counted owners, it never asked who was doing the counting. An
organization can also never lose its last owner (`LAST_OWNER_PROTECTED`).

> [!CAUTION]
> **No impersonation.** There is no `?as=` parameter, no impersonation header and no runtime flag
> check inside a handler. `POST /dev/assume` performs a real login for a seeded user through the
> ordinary path — password verification included — and the router is **not registered at all** when
> `DEMO_MODE=false`, so the route does not exist rather than being guarded. Set `DEMO_MODE=false`
> before any shared deployment; it is the first item on the
> [pre-deployment checklist](OPERATIONS.md#8-before-a-shared-deployment).

**Further reading** &nbsp;
[ADR-008 — why the repository layer](DECISIONS.md#adr-008--tenant-isolation-lives-in-the-repository-and-returns-404) &nbsp;·&nbsp;
[ADR-008c — when this very suite was passing vacuously](DECISIONS.md#adr-008c--an-enumerating-test-must-assert-that-it-enumerated-something)

---

## 4. Secrets and logging (I11)

Nothing secret is committed. `.env.example` carries placeholders only, and
[`backend/scripts/secret_scan.py`](../backend/scripts/secret_scan.py) fails the build on a
credential-shaped literal anywhere in the repository: Razorpay live/test key ids, PEM private keys,
32-byte hex adjacent to a key-ish name, AWS access key ids, Anthropic/OpenAI/Groq/GitHub/Slack/Google
keys, JWTs, and any `secret`/`password`/`token`/`api_key` assignment whose value looks like real
entropy.

Obvious placeholders pass; a deliberate non-secret needs an explicit `secret-scan-allow:` comment
stating why, so the exemption is visible in review.

> [!IMPORTANT]
> **CI plants a fake Razorpay live key and requires the scan to fail.** A scanner nobody has watched
> fail is a scanner nobody has tested.

### Masked log fields

All 24 are masked in the message *and* in structured `extra` fields:

```
access_token · address · ai_api_key · api_key · artifact_bytes · authorization · email ·
email_normalized · jwt_secret · new_password · operator_private_key · otp · password ·
password_hash · phone · private_key · raw_evidence · razorpay_key_secret · refresh_token ·
secret · token · token_hash · verifier_private_key · webhook_secret
```

Scheme-prefixed patterns are ordered **before** key/value patterns, because
`authorization: Bearer <token>` leaked the token when the key/value pattern matched first. Twelve
tests in `tests/security/test_log_masking.py` log a payload containing every field above and assert
none of it reaches a sink.

Artifact bytes and extracted evidence content are **never logged and never sent on chain**.

**Further reading** &nbsp;
[Why logifyx is wrapped — ADR-002](DECISIONS.md#adr-002--logifyx-is-wrapped-not-used-directly) &nbsp;·&nbsp;
[The logging module — Architecture §7](ARCHITECTURE.md#7-logging)

---

## 5. Evidence handling

<img alt="" src="https://img.shields.io/badge/uploads-CONTENT--SNIFFED-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/accepted-PDF_%C2%B7_PNG_%C2%B7_JPEG-C6C0B4?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/cap-20_MB-C6C0B4?style=flat-square&labelColor=0D0D10">

* Uploads are **content-sniffed**, and a declared/sniffed mismatch is rejected (`ARTIFACT_REJECTED`).
  PDF, PNG and JPEG only; 20 MB cap, enforced during the read rather than after it. Image dimensions
  are checked from the header before decode (40 MP ceiling) and PDFs are capped at 250 pages, so a
  47 KB file declaring 49 megapixels cannot be expanded in memory by the analyser.
* Only the **selling** organization can add evidence to a milestone
  (`ONLY_SELLER_SUBMITS_EVIDENCE`); outsiders still get 404, not 403.
* Merkle leaves and internal nodes are **domain-separated** (`0x00` / `0x01`, RFC 6962), and the leaf
  tag is applied by `verify_proof` itself rather than trusted from the caller — otherwise an internal
  node can be replayed as a leaf and forge a proof against a genuine root. Details in
  [Architecture §4](ARCHITECTURE.md#4-evidence-and-provenance).
* Stored under a random key in the object store — local by default, S3/MinIO optional. **There is no
  public path to an artifact.** Access is a short-lived HMAC-signed presigned URL minted on the
  tenant-scoped bundle view, with the expiry inside the signed payload.
* The frontend computes `sha256` in the browser before upload and displays it next to the hash the
  server computed.

> [!NOTE]
> `crypto.subtle` requires a secure context. When it is unavailable the UI says *"local hash
> unavailable on this origin"* rather than back-filling the server's answer — **a local hash that is
> really the remote hash would prove nothing while looking like proof.**

---

## 6. Signing and on-chain data (I7)

* Signing keys come from the environment (`VERIFIER_PRIVATE_KEY`, `OPERATOR_PRIVATE_KEY`) and are in
  the mask list. They are never logged, never returned by an API, and never written to the database.
* Attestations are **EIP-712** typed data over
  `(dealId, seq, evidenceRoot, attestationHash, decision, confidenceBps)`. The type-hash string is
  asserted identically in Python and Solidity, so drift breaks both test suites rather than silently
  breaking on-chain recovery.
* Verification **recovers the signer address** from the canonical hash rather than comparing a stored
  string. Suite C check 3 measures that a genuine payload verifies while a confidence bump and a
  decision flip both fail.
* On-chain data is `bytes32`, integers, enums and signatures **only**. The chain adapter's signature
  cannot accept a string, so a name, an email or an invoice line **cannot be passed even by mistake**.

**Further reading** &nbsp;
[The Merkle tree and the ledger — Architecture §4](ARCHITECTURE.md#4-evidence-and-provenance) &nbsp;·&nbsp;
[Why no contract is deployed — Limitations §3](LIMITATIONS.md#3-no-contract-is-deployed) &nbsp;·&nbsp;
[ADR-007 — the chain is a notary](DECISIONS.md#adr-007--the-chain-is-a-notary-and-its-absence-is-never-hidden)

---

## 7. Transport and headers

<img alt="" src="https://img.shields.io/badge/CSP-frame--ancestors_'none'-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/containers-uid_10001,_cap_drop_ALL-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="" src="https://img.shields.io/badge/published_ports-LOOPBACK_EXCEPT_3000-4FD1A5?style=flat-square&labelColor=0D0D10">

Every response from the frontend carries the following, set in
[`frontend/next.config.ts`](../frontend/next.config.ts):

| header | value | what it closes |
|:--|:--|:--|
| `Content-Security-Policy` | `default-src 'self'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, `object-src 'none'`, `frame-src 'none'` | Clickjacking a release button; a planted `<base>` repointing every relative URL; a posted form exfiltrating a session |
| `X-Frame-Options` | `DENY` | The same, for a browser that predates `frame-ancestors` |
| `X-Content-Type-Options` | `nosniff` | MIME confusion on a downloaded artifact |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Deal and attestation ids leaking in a `Referer` |
| `Cross-Origin-Opener-Policy` | `same-origin` | Cross-window references into an authenticated tab |
| `Permissions-Policy` | camera, microphone, geolocation, payment, USB, accelerometer, gyroscope all `()` | Features this app never uses |

> [!NOTE]
> The app has no CDN, no analytics, no embedded frame and no external font, so the policy is
> **closed** rather than merely narrowed. `'unsafe-inline'` on scripts is the one concession — Next
> inlines its own bootstrap and `layout.tsx` inlines the before-paint theme script, and replacing
> those with a nonce needs a middleware this app deliberately does not have. `'unsafe-eval'` is
> **dev-only** and is not present in a production build.

Also:

* `poweredByHeader: false`; the app is not indexable (`robots: noindex` and `public/robots.txt`).
* CORS origins are an explicit allowlist from `CORS_ORIGINS` — and the browser does not need it at
  all, because `/api/*` is same-origin.
* Both containers run as **uid 10001**, non-root, with no build toolchain in the runtime layer, and
  every service this repo builds runs with `no-new-privileges` and `cap_drop: ALL`.
* Every response carries `x-request-id`, which also appears in every log line for that request.

### Published ports

Only `frontend:3000` is published on `0.0.0.0`. Postgres, Redis, Kafka, kafka-ui, Mailpit, MinIO
**and the raw API on 8000** are bound to `127.0.0.1`.

> [!CAUTION]
> This is not cosmetic hardening. Mailpit receives the **email-verification and password-reset
> links** for every seeded account and its API needs no authentication, so a Mailpit port reachable
> from another machine is account takeover for every demo user. Redis answered `INFO` unauthenticated
> and kafka-ui shipped with `DYNAMIC_CONFIG_ENABLED`. Reaching any of them now requires an SSH
> tunnel. See [Operations §1](OPERATIONS.md#1-one-command-start).

### The forwarded-header identity

The frontend proxy **does not forward** `x-forwarded-for`, `x-forwarded-host`, `x-forwarded-proto` or
`forwarded` unless `TRUST_PROXY_HEADERS=true`. Next only fills `x-forwarded-for` from the socket when
the caller omits it, so a caller that supplies its own value had it passed straight through to the
backend, which uses the first hop as the rate-limit identity — an IP-keyed bucket could be emptied by
rotating a header. See [Rate limits](#rate-limits) for what that means for the buckets today.

---

## 8. Not built, and named as such

<img alt="" src="https://img.shields.io/badge/this_section-THE_HONEST_HALF-FF4A4A?style=flat-square&labelColor=0D0D10">

| gap | consequence | what it would take |
|:--|:--|:--|
| **`docker compose up` run directly still has a working `JWT_SECRET` default** | `docker-compose.yml` falls back to `dev-only-insecure-secret-change-me`. That one value signs access tokens **and** keys the presigned-artifact HMAC (`storage/store.py`), so anyone who reads this repository could forge a session and mint a download token for any storage key. **`make up` and `make up-build` now close this**: both depend on `ensure-env`, which writes 32 bytes of real entropy into `.env` the first time and is a no-op afterwards. The gap that remains is the person who bypasses `make` entirely | Drop the compose fallback so a missing `JWT_SECRET` is a hard boot failure. Not done, because it would break `docker compose up` as a standalone command, which some readers will reasonably try first |
| **No MFA / TOTP** | A stolen password is a full session | A TOTP enrolment flow and a recovery-code path |
| **No token-revocation cache** | The session-liveness check is a database read on every authenticated request. Correct, but it is a query the old stateless design did not make | A short-TTL Redis deny-list, with the database as the fallback |
| **No CSRF token on cookie-authenticated writes** | Mitigated by `SameSite` cookies and a same-origin API, but not eliminated for a browser that ignores `SameSite` | A double-submit token, or an origin check on state-changing verbs |
| **`X-Forwarded-For` is trusted unconditionally by the API** | `_client_ip()` takes the first hop of a client-settable header as the rate-limit identity, so a caller reaching port 8000 directly can pick its own per-IP bucket. Mitigated, not closed: the frontend proxy no longer forwards the header, the API is now loopback-only, and every email- or hash-heavy route also has a **per-account** bucket that is keyed on something the caller cannot vary | A `TRUSTED_PROXY_HOPS` setting, counting back from the right of the chain instead of trusting the left. Dropping the header outright would collapse every browser client into the proxy's single bucket, so it needs the setting rather than a deletion |
| **No rate limit on `POST /chat/deals/{id}`** | An authenticated member can flood their own deal thread. Not an unauthenticated abuse path, and chat is never used as evidence — but it is an unbounded write | One `rate_limit("chat", org_id, …)` call and a setting, matching the other buckets |
| **No signing-key rotation or KMS/HSM** | A leaked verifier key can forge attestations from that point forward; existing ones stay verifiable under the old key id | `signer_key_id` is already stored per attestation, so rotation is additive: a key registry plus a resolver |
| **No per-field encryption at rest** | Postgres-level encryption only; a database dump exposes emails and organization names | Envelope encryption on the identity columns |
| **No audit log of reads** | Writes are fully audited in the ledger; who *read* an artifact is not recorded | A read-audit sink on the presign path |
| **No WAF, no bot defence** | Rate limits are the only abuse control | Provider-level protection |
| **No formal verification of the contract, and `forge test` is not gated in CI** | 28 Foundry tests, no proofs — and CI runs the static gates plus `make eval` only, so a contract regression is caught locally or not at all | A Certora or Halmos spec on the settlement predicate, and a `contracts` job running `forge test` with `submodules: recursive` |
| **Python dependency scanning is not in CI** | `npm audit --audit-level=moderate` **is** a gating CI step and passes at 0 vulnerabilities; the Python side has no equivalent gate | `pip-audit` as a CI step, with a triage policy for advisories that have no fixed version |
| **No penetration test** | Nobody hostile has tried | An engagement |

> [!TIP]
> These thirteen are the reason [Limitations](LIMITATIONS.md) exists as its own document. The list of
> what would need to be true before this touched real money is
> [Limitations §8](LIMITATIONS.md#8-what-would-need-to-be-true-before-this-touched-real-money).

---

## 9. Reporting

This is a hackathon submission, not a deployed service. There is no bug bounty and no on-call.
If you find something, open an issue describing the impact and the path to it.

---

<div align="center">

<sub><b>Aegis</b> · programmable escrow for agentic commerce</sub>

<p>
  <a href="DATA.md">&larr; Data</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="README.md">Docs index</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="OPERATIONS.md">Operations &rarr;</a>
</p>

<sub>
<a href="../README.md">Overview</a> ·
<a href="ARCHITECTURE.md">Architecture</a> ·
<a href="API.md">API</a> ·
<a href="DATA.md">Data</a> ·
<a href="OPERATIONS.md">Operations</a> ·
<a href="DEMO.md">Demo</a> ·
<a href="UI_MOTION.md">UI &amp; Motion</a> ·
<a href="DECISIONS.md">Decisions</a> ·
<a href="LIMITATIONS.md">Limitations</a>
</sub>

</div>
