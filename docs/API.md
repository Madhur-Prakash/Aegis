# API

Base path `/api/v1`. The generated OpenAPI document is
[`openapi.json`](openapi.json) - **75 paths, 82 operations**, regenerated with `make docs` - and is
browsable at <http://localhost:8000/docs> when the stack is up.

This document covers the parts a generated schema cannot: the envelope, the auth model, the error
taxonomy and the conventions that make the API predictable.

---

## 1. Conventions

| convention | rule |
|---|---|
| **Money** | Always integer **paise**, always a field named `*_paise`, always `BIGINT`. No floats, ever, and no `Decimal` at the rail boundary. `420000000` is INR 4,200,000.00. |
| **Time** | UTC, ISO-8601 with `Z`. The frontend renders in `Asia/Kolkata`; the API never does. |
| **Ids** | UUID v4 as strings, except deterministic seed ids which are UUID v5 so `make seed` is idempotent. |
| **Hashes** | Lowercase hex, no `0x` prefix, except EVM transaction hashes and addresses, which keep theirs. |
| **Confidence** | Float in `[0, 1]`, three decimals when displayed. `0.510` and `0.51` must not look different. |
| **Enums** | Uppercase snake case, matching the Python `StrEnum` exactly. The frontend never invents a state name. |
| **Pagination** | Deliberately absent. Every list endpoint is scoped to one organization and one deal; none can grow unboundedly in this product's shape. |

## 2. Authentication

Access and refresh tokens are issued as **httpOnly, SameSite cookies** on `POST /auth/login`,
`/auth/register`, `/auth/refresh` and `/dev/assume`. The response body also carries the access token,
which is what a non-browser client uses as `Authorization: Bearer <token>`.

* Passwords are hashed with **Argon2id**.
* Refresh tokens rotate on use, and **reuse of a rotated token revokes the whole family** - the
  revocation is committed inside the service before the error is raised, so a request that raises
  still leaves the family revoked.
* `POST /auth/reset-password` revokes every other session.
* An **unverified** account can sign in and read, but cannot create or fund a deal, submit evidence,
  approve anything, **or accept an organization invitation**. Those endpoints return
  `EMAIL_NOT_VERIFIED` (403). Accepting an invitation is on that list deliberately: it grants access
  to another organization's deals, so the invitee must first have proven they hold the mailbox.

### Dependency tiers

| dependency | requires |
|---|---|
| `ViewerDep` | a session and an active organization; read-only roles included |
| `MembershipDep` | a session with an active organization membership |
| `MemberDep` | membership **and** a verified email; this is what money-touching endpoints use |
| `RepoDep` | a `TenantRepo` already bound to the acting organization |

There is no `?as=` parameter and no impersonation header. `POST /dev/assume` performs a genuine
login for a seeded user through `auth_service.login`, password verification included, and is only
registered when `DEMO_MODE=true`.

## 3. The error envelope (I9)

Every expected failure returns this shape. A bare 500 is a bug, not an outcome.

```json
{
  "error": {
    "code": "UNVERIFIABLE_REQUIRED_CLAUSE",
    "message": "A required clause could not be verified, so release is not available.",
    "details": { "clause_id": "c2" },
    "request_id": "01JD4Z8Q0000000000000000"
  }
}
```

`code` is stable and machine-readable - clients branch on it, never on the prose. `message` is
human-readable and may change. `details` is a typed object per code. `request_id` also appears on the
`x-request-id` response header and in every log line for that request, so a support conversation can
start with an id.

The frontend's `ApiError` carries `code`, `status`, `details` and `requestId`, and every error block
in the UI prints the code above the message.

### The full taxonomy

| code | HTTP | when |
|---|---|---|
| `NOT_FOUND` | 404 | The resource does not exist **or** belongs to another organization. Deliberately indistinguishable (I12). |
| `VALIDATION_FAILED` | 422 | Request body or query failed validation. |
| `CONFLICT` | 409 | The request conflicts with current state. |
| `RATE_LIMITED` | 429 | Token bucket exhausted. `details` carries the window. |
| `SERVICE_UNAVAILABLE` | 503 | A required dependency is down. |
| `UNAUTHENTICATED` | 401 | No session. |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password. Identical for both, so it is not an enumeration oracle. |
| `FORBIDDEN` | 403 | Authenticated, but the role does not permit this. |
| `EMAIL_NOT_VERIFIED` | 403 | Verified email required for this action. |
| `TOKEN_INVALID` | 401 | Malformed, expired, or wrong-key token. |
| `REFRESH_TOKEN_REUSE` | 401 | A rotated refresh token was replayed. The family is revoked. |
| `LAST_OWNER_PROTECTED` | 409 | An organization must always keep at least one owner. |
| `ILLEGAL_TRANSITION` | 409 | An unknown `(state, event)` pair (I10). Never silently ignored. |
| `MONEY_INVARIANT_VIOLATION` | 409 | The operation would break `held + released + refunded == funded` (I4). |
| `NO_QUALIFYING_ATTESTATION` | 409 | A settlement was attempted with no qualifying attestation (I1). |
| `CONFIDENCE_BELOW_RELEASE_THRESHOLD` | 409 | Auto-release requested below 0.85 (I3). |
| `UNVERIFIABLE_REQUIRED_CLAUSE` | 409 | A required clause is `UNVERIFIABLE`; auto-release is impossible (I3, ADR-004). |
| `HUMAN_DECISION_REQUIRED` | 409 | Dispute settlement attempted before a human decided (I8). |
| `RAIL_FAILURE` | 502 | The payment rail rejected or failed the call. |
| `CHAIN_UNAVAILABLE` | 503 | The chain RPC or contract is not configured or unreachable. Never blocks money. |
| `ARTIFACT_REJECTED` | 422 | Upload failed sniffing, size or type validation. |
| `ATTESTATION_SIGNATURE_INVALID` | 409 | An attestation payload does not verify against its signature. |
| `LLM_OUTPUT_REJECTED` | 409 | The model returned output that failed schema validation after retries. |

The three settlement codes are worth reading as a set: `NO_QUALIFYING_ATTESTATION`,
`CONFIDENCE_BELOW_RELEASE_THRESHOLD` and `UNVERIFIABLE_REQUIRED_CLAUSE` are the machine-readable
forms of I1 and I3. A client that gets one of them has been told *precisely* why the money did not
move.

## 4. Endpoint groups

| group | prefix | notes |
|---|---|---|
| Auth | `/auth/*` | register, login, refresh, logout, verify-email, resend-verification, forgot/reset/change password, `me`, preferences |
| Organizations | `/organizations/*` | current, switch, members, roles, invitations, accept |
| Entities | `/entities` | the counterparty directory |
| Deals | `/deals/*` | list, get, `demo`, sign-terms, fund, cancel, timeline, risk |
| Milestones | `/milestones/*` | get, `start-verify`, `review-queue`, `human-review` |
| Evidence | `/evidence/*` | bundle, upload, submit, `artifacts/{id}/proof`, `verify`, `download/{token}` |
| Verification | `/verification/*` | attestation by milestone, attestation by id |
| Provenance | `/provenance/*` | attestation provenance, deal chain records, `tamper-check` |
| Ledger | `/ledger/deals/{id}` | entries and `verify` |
| Disputes | `/disputes/*`, `/milestones/{id}/disputes` | raise, counter-claim, arbiter, resolve |
| Settlement | `/settlements/deals/{id}` | authorizations, with `consumed_at` and idempotency key |
| Payments | `/payments/*` | payouts, `rail` disclosure, webhook receiver |
| Reputation | `/reputation/entities/{id}` | the counterparty passport |
| Notifications | `/notifications/*` | list, mark-read, preferences |
| Chat | `/chat/deals/{id}` | deal-scoped messages. Never evidence. |
| Realtime | `/realtime/*` | SSE: deals, verification, review, chat, notifications |
| Health | `/health/*` | `live`, `ready`, `metrics`, `eval-summary` |
| Dev | `/dev/*` | `assume`, `state`. Only registered when `DEMO_MODE=true`. |

### Endpoints worth knowing about

**`GET /health/ready`** - the readiness contract. Every dependency reports `ready`, `required` and,
where relevant, `mode`:

Actual response from the running stack:

```json
{
  "ok": true,
  "degraded": ["chain_rpc"],
  "checks": {
    "postgres":     { "ready": true,  "required": true },
    "redis":        { "ready": true,  "required": false },
    "kafka":        { "ready": true,  "required": false },
    "object_store": { "ready": true,  "required": true },
    "chain_rpc":    { "ready": false, "required": false, "reason": "CONTRACT_ADDRESS_NOT_SET" },
    "payment_rail": { "ready": true,  "required": true,  "mode": "SIMULATED" }
  },
  "ai_provider": "fixture"
}
```

`ok` stays `true` while only optional dependencies are degraded. Redis is optional because its two
jobs - rate limiting and the settlement lock fast path - both degrade safely: the atomic DB claim
still serialises settlement without it.

The boot screen and the degraded banner read this, so the interface cannot claim a dependency is fine
when the backend says it is not.

**`GET /payments/rail`** - the honesty table, labelled **per operation**:

```json
{
  "mode": "SIMULATED",
  "configured": "simulated",
  "credentials_present": false,
  "operations": {
    "funding_order_and_capture": "SIMULATED",
    "seller_release": "SIMULATED",
    "refund": "SIMULATED",
    "webhook_verification": "SIMULATED"
  }
}
```

Per operation, not per rail: webhook verification can be real while a payout is simulated, and
collapsing that into one label would be a lie in one direction or the other.

**`GET /health/eval-summary`** - the headline numbers from the last `make eval`, verbatim, so no
figure on a marketing surface can be typed by hand. Returns
`{"available": false, "reason": "…"}` when `evals/out/summary.json` is absent, and the landing page
then shows nothing rather than a number nobody measured.

**`POST /evidence/verify`** - public Merkle verification. Takes `(leaf, proof, root)` and recomputes
the root from the path alone. This is the endpoint that makes a proof a proof: a second party can
check it without trusting the server that produced it.

**`POST /provenance/tamper-check`** - takes `content_b64` and `expected_sha256` and returns the
digest it **actually computed** for those bytes. It changes nothing. This backs the "Tamper one byte"
control in the UI.

**`GET /evidence/download/{token}`** - a short-lived HMAC-signed presigned link, minted on the bundle
view. There is no public path to an artifact and the frontend never constructs one.

## 5. Realtime

Server-Sent Events, tenant-scoped at subscribe time. Event names:

`ready` · `deal.updated` · `deal.funded` · `evidence.submitted` · `verification.stage` ·
`verification.completed` · `review.decided` · `dispute.raised` · `dispute.resolved` ·
`chat.message`

**The payload is only ever a hint.** Every client handler refetches from the API rather than trusting
the event body, so a dropped or duplicated event costs a refresh and never a wrong number on screen.
A 20-second keep-alive comment holds the connection open; the client reconnects with capped
exponential backoff so a backend restart cannot become a reconnect storm.

## 6. Rate limits

Redis token buckets, keyed per organization or per client IP depending on the surface:
`auth:register` and `auth:login` (per IP **and** per account, so one account cannot be brute-forced
from many addresses), `verify`, `upload`, `chat`. Exceeding one returns `RATE_LIMITED` (429) - proven
by its own test rather than disabled in the suite.

## 7. Idempotency

Money endpoints are idempotent on `(milestone_id, direction, attempt_no)`, enforced by a unique
index. The rail receives an explicit idempotency key derived from that triple, so a retry after a
network failure is a no-op at the provider. 20 concurrent release attempts produce **exactly one
payout and exactly one rail call** - measured, in Suite B check 7.
