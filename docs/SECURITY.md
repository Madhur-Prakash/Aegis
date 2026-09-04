# Security

What is defended, how, and — in the last section — what is deliberately not built. A threat model
that lists only strengths is marketing.

---

## 1. Threat model

| adversary | wants | primary defence |
|---|---|---|
| **A dishonest seller** | Release on evidence that does not support the clause | Deterministic pre-checks before any model call; `FAIL` on a required clause is an immediate `REJECT`; the evidence-integrity pre-check catches internally inconsistent documents (fabricated totals) that read as valid in isolation |
| **A dishonest buyer** | Withhold payment on satisfied conditions | Verification is symmetric — the buyer cannot veto a `RELEASE`; a dispute must be raised with a claim, is recorded in the ledger, and settlement of it needs a human decision with a written reason |
| **A curious tenant** | Read another organization's deals, evidence or ledger | Tenant scoping in the repository layer, not per endpoint (I12); cross-tenant reads return **404** so existence is not confirmed |
| **A prompt injector** | Get an LLM to authorise a transfer | The agent packages **cannot import** the settlement engine, the rails or the payments layer; CI proves the lint fails on a planted violation (I2). The worst a successful injection achieves is a wrong clause verdict, which then flows through the guard and the thresholds like any other verdict |
| **A tamperer** | Alter evidence or a decision after the fact | Merkle root over `sha256(bytes) ‖ sha256(canonical_json(fields))`; EIP-712 signature over the canonical hash; append-only hash-chained ledger enforced by a Postgres **trigger** |
| **An insider** | Quietly lower a threshold or release without a record | `decide()` takes one frozen parameter and reads no settings; a human release writes an authorization carrying their user id and a mandatory reason into the append-only ledger |
| **A replay attacker** | Double-spend a settlement event | Idempotent on `(milestone_id, direction, attempt_no)` with a unique index; an atomic DB claim admits exactly one worker; the rail receives an idempotency key |
| **A credential thief** | Reuse a stolen refresh token | Refresh rotation with **family revocation on reuse**; a password reset revokes every other session |

---

## 2. Authentication and sessions

* **Argon2id** password hashing (`argon2-cffi`).
* Access and refresh tokens in **httpOnly, SameSite** cookies. The frontend talks to `/api/*` on its
  own origin via a Next rewrite, so the cookie is first-party and there is no CORS-credentials
  arrangement to get wrong.
* **Refresh rotation.** Using a refresh token issues a new one and invalidates the old. Replaying a
  rotated token revokes the **entire family** — and the revocation is committed inside the service
  *before* the error is raised, because a router that raises before committing would leave the family
  alive. That was a real bug.
* **Revocation is immediate, not eventual.** The access token is a stateless JWT, so revoking the
  refresh token alone left a bearer token working for the rest of its 15-minute TTL. `current_user`
  now checks the token's `sid` (its refresh-family id) against the refresh rows and refuses a token
  whose family has been revoked — one indexed lookup per request. Verified against the running
  stack: after a logout, a reset, or refresh-reuse detection, the previously valid access token
  returns 401 on the next call.
* Password reset revokes every other session, and the UI says so — truthfully.
* Login failures are indistinguishable for "no such account" and "wrong password", and
  `POST /auth/forgot-password` returns the same confirmation either way. Neither is an enumeration
  oracle.
* Email verification gates every state-changing action. An unverified user can sign in and read;
  creating or funding a deal, submitting evidence and approving anything all return
  `EMAIL_NOT_VERIFIED`.

### Rate limits

Redis token buckets. Defaults: `auth` **10 per 60s**, `verify` **12 per 60s**, `upload` **40 per
60s**. Login is limited **per client IP and per account**, so one account cannot be brute-forced from
many addresses. Exceeding a limit returns `RATE_LIMITED` (429) — the limiter stays enabled in the
test suite and has its own test proving the 429, rather than being switched off to make CI quiet.

---

## 3. Authorization and tenant isolation (I12)

Isolation is architectural. `TenantRepo` is constructed with the acting organization and there is
**no unscoped accessor** — adding a tenant-scoped table means declaring its ownership kind:

* `_OWN_ORG` — the row carries `org_id` (`Entity`, `Notification`)
* `_VIA_DEAL` — the row is reachable only through a deal the org is party to, with an explicit join
  chain (`Milestone`, `EvidenceBundle`, `Artifact`, `Attestation`, `Dispute`, `LedgerEvent`,
  `DealMessage`, `Payout`, `SettlementAuthorization`, `ChainAnchor`)

Cross-tenant access raises `NotFound` → **404, not 403**, because a 403 confirms the resource exists.
Nine dedicated tests in `tests/security/test_tenant_isolation.py` cover deals, milestones, evidence,
artifacts, attestations, ledger entries, messages, notifications and payouts.

Roles are `OWNER`, `ADMIN`, `MEMBER`, `VIEWER`. An organization can never lose its last owner
(`LAST_OWNER_PROTECTED`).

**No impersonation.** There is no `?as=` parameter, no impersonation header and no runtime flag check
inside a handler. `POST /dev/assume` performs a real login for a seeded user through the ordinary
path — password verification included — and the router is **not registered at all** when
`DEMO_MODE=false`, so the route does not exist rather than being guarded.

---

## 4. Secrets and logging (I11)

Nothing secret is committed. `.env.example` carries placeholders only, and
`backend/scripts/secret_scan.py` fails the build on a credential-shaped literal anywhere in the
repository: Razorpay live/test key ids, PEM private keys, 32-byte hex adjacent to a key-ish name, AWS
access key ids, Anthropic/OpenAI/Groq/GitHub/Slack/Google keys, JWTs, and any
`secret`/`password`/`token`/`api_key` assignment whose value looks like real entropy. Obvious
placeholders pass; a deliberate non-secret needs an explicit `secret-scan-allow:` comment stating
why, so the exemption is visible in review. **CI plants a fake Razorpay live key and requires the
scan to fail.**

### Masked log fields

Masked in the message *and* in structured `extra` fields:

```
access_token · address · ai_api_key · api_key · artifact_bytes · authorization · email ·
email_normalized · jwt_secret · new_password · operator_private_key · otp · password ·
password_hash · phone · private_key · raw_evidence · razorpay_key_secret · refresh_token ·
secret · token · token_hash · verifier_private_key · webhook_secret
```

Scheme-prefixed patterns are ordered **before** key/value patterns, because
`authorization: Bearer <token>` leaked the token when the key/value pattern matched first. Eleven
tests in `tests/security/test_log_masking.py` log a payload containing every field above and assert
none of it reaches a sink.

Artifact bytes and extracted evidence content are never logged and never sent on chain.

---

## 5. Evidence handling

* Uploads are **content-sniffed** and a declared/sniffed mismatch is rejected
  (`ARTIFACT_REJECTED`). PDF, PNG and JPEG only; 20 MB cap.
* Stored under a random key in the object store — local by default, S3/MinIO optional. **There is no
  public path to an artifact.** Access is a short-lived HMAC-signed presigned URL minted on the
  tenant-scoped bundle view, with the expiry inside the signed payload.
* The frontend computes `sha256` in the browser before upload and displays it next to the hash the
  server computed. `crypto.subtle` requires a secure context, so when it is unavailable the UI says
  *"local hash unavailable on this origin"* rather than back-filling the server's answer — a local
  hash that is really the remote hash would prove nothing while looking like proof.

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
  cannot accept a string, so a name, an email or an invoice line cannot be passed even by mistake.

---

## 7. Transport and headers

* `poweredByHeader: false`; the app is not indexable (`robots: noindex` and `public/robots.txt`).
* CORS origins are an explicit allowlist from `CORS_ORIGINS`, and the browser does not need it at
  all because `/api/*` is same-origin.
* Both containers run as **uid 10001**, non-root, with no build toolchain in the runtime layer.
* Every response carries `x-request-id`, which also appears in every log line for that request.

---

## 8. Not built, and named as such

The honest half of this document.

| gap | consequence | what it would take |
|---|---|---|
| **No MFA / TOTP** | A stolen password is a full session | A TOTP enrolment flow and a recovery-code path |
| **No token-revocation cache** | The session-liveness check is a database read on every authenticated request. Correct, but it is a query the old stateless design did not make | A short-TTL Redis deny-list, with the database as the fallback |
| **No CSRF token on cookie-authenticated writes** | Mitigated by `SameSite` cookies and a same-origin API, but not eliminated for a browser that ignores `SameSite` | A double-submit token or an origin check on state-changing verbs |
| **No signing-key rotation or KMS/HSM** | A leaked verifier key can forge attestations from that point forward; existing ones stay verifiable under the old key id | `signer_key_id` is already stored per attestation, so rotation is additive: a key registry plus a resolver |
| **No per-field encryption at rest** | Postgres-level encryption only; a database dump exposes emails and organization names | Envelope encryption on the identity columns |
| **No audit log of reads** | Writes are fully audited in the ledger; who *read* an artifact is not recorded | A read-audit sink on the presign path |
| **No WAF, no bot defence** | Rate limits are the only abuse control | Provider-level protection |
| **No formal verification of the contract** | 24 Foundry tests, no proofs | A Certora or Halmos spec on the settlement predicate |
| **Python dependency scanning is not in CI** | `npm audit --audit-level=moderate` **is** a gating CI step and passes at 0 vulnerabilities; the Python side has no equivalent gate | `pip-audit` as a CI step, with a triage policy for advisories that have no fixed version |
| **No penetration test** | Nobody hostile has tried | An engagement |

---

## 9. Reporting

This is a hackathon submission, not a deployed service. There is no bug bounty and no on-call.
If you find something, open an issue describing the impact and the path to it.
