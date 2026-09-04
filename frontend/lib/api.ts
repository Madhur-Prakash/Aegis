/**
 * The typed API client.  ORM shapes never reach a component: everything below
 * mirrors the Pydantic response schemas.
 *
 * Requests go to `/api/v1/*` on this origin and are rewritten to the backend by
 * `next.config.ts`, so the httpOnly session cookie is first-party.
 */

export type ErrorEnvelope = {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string;
  };
};

/** A typed error, so a component can branch on `code` rather than parse prose. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = envelope.error.code;
    this.details = envelope.error.details ?? {};
    this.requestId = envelope.error.request_id;
  }
}

const BASE = "/api/v1";

async function request<T>(
  path: string,
  init: RequestInit & { form?: FormData } = {},
): Promise<T> {
  const { form, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (!form && rest.body !== undefined) headers.set("content-type", "application/json");

  const response = await fetch(`${BASE}${path}`, {
    ...rest,
    body: form ?? rest.body,
    headers,
    credentials: "include",
    cache: "no-store",
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    if (payload && typeof payload === "object" && "error" in payload) {
      throw new ApiError(response.status, payload as ErrorEnvelope);
    }
    throw new ApiError(response.status, {
      error: {
        code: "UNEXPECTED",
        message: `Request failed with ${response.status}`,
        details: {},
        request_id: response.headers.get("x-request-id") ?? "",
      },
    });
  }
  return payload as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) });

// ── Types ────────────────────────────────────────────────────────────────────
export type Money = {
  funded_paise: number;
  released_paise: number;
  refunded_paise: number;
  held_paise: number;
  balanced: boolean;
};

export type MilestoneSummary = {
  id: string;
  seq: number;
  title: string;
  amount_paise: number;
  state: string;
  verification_condition: Condition;
  released_at: string | null;
  has_evidence: boolean;
  attestation_id: string | null;
  decision: string | null;
  confidence: number | null;
};

export type Clause = {
  id: string;
  kind: string;
  description: string;
  params: Record<string, unknown>;
  required: boolean;
};

export type Condition = {
  clauses: Clause[];
  required_artifact_types: string[];
  tolerance: Record<string, unknown>;
};

export type OrgRef = {
  id: string;
  name: string;
  city: string | null;
  entity_id: string;
  entity_name: string;
};

export type Deal = {
  id: string;
  reference: string;
  title: string;
  state: string;
  total_paise: number;
  money: Money;
  buyer_org: OrgRef;
  seller_org: OrgRef;
  terms_hash: string;
  chain_deal_id: string | null;
  chain_tx: string | null;
  dispute_window_days: number;
  risk_score: number | null;
  pricing_tier: string | null;
  milestones: MilestoneSummary[];
  created_at: string;
  viewer_side: "buyer" | "seller";
};

export type ClauseVerdict = {
  clause_id: string;
  verdict: "PASS" | "FAIL" | "UNVERIFIABLE";
  required: boolean;
  clause_confidence: number;
  note: string;
  evidence_refs: string[];
  description: string;
  kind: string;
  resolved_by: string;
};

export type ConfidenceComponents = {
  verifiable_fraction: number;
  llm_component: number;
  extraction_quality: number;
  unverifiable_penalty: number;
  raw: number;
  computed: number;
  weights: Record<string, number>;
  calibration_version: string;
  total_required_clauses: number;
  deterministic_required_passed: number;
  unverifiable_required_clauses: number;
  formula: string;
};

export type Attestation = {
  id: string;
  reference: string;
  milestone_id: string;
  bundle_id: string;
  decision: "RELEASE" | "REJECT" | "ESCALATE";
  confidence: number;
  confidence_components: ConfidenceComponents;
  clause_verdicts: ClauseVerdict[];
  reasoning: string;
  provider: string;
  model_id: string;
  model_version: string;
  prompt_hash: string;
  evidence_merkle_root: string;
  deterministic_prechecks: {
    resolved_without_llm: boolean;
    decision: string | null;
    reason: string;
    checks: { check: string; ok: boolean; detail: Record<string, unknown> }[];
    integrity_findings: Record<string, unknown>[];
    passed: number;
    total: number;
  };
  thresholds: Record<string, unknown>;
  calibration_version: string;
  canonical_hash: string;
  signature: string;
  signer_key_id: string;
  signer_address: string;
  chain_tx: string | null;
  chain_block: number | null;
  created_at: string;
};

export type Artifact = {
  id: string;
  artifact_type: string;
  filename: string;
  mime: string;
  size_bytes: number;
  sha256: string;
  extraction_quality: number | null;
  extracted_fields: Record<string, unknown>;
  unreadable_fields: string[];
  download_url: string | null;
  created_at: string;
};

export type Bundle = {
  id: string;
  milestone_id: string;
  merkle_root: string;
  submitted_at: string | null;
  artifacts: Artifact[];
};

export type ReviewRow = {
  deal_id: string;
  deal_reference: string;
  milestone_id: string;
  milestone_seq: number;
  milestone_title: string;
  amount_paise: number;
  state: string;
  confidence: number | null;
  decision: string | null;
  attestation_id: string | null;
  could_not_verify: { clause_id: string; note: string }[];
  dispute_id: string | null;
  arbiter_recommendation: ArbiterRecommendation | null;
  created_at: string;
};

export type ArbiterRecommendation = {
  available: boolean;
  outcome?: "FULL_RELEASE" | "PARTIAL" | "FULL_REFUND";
  release_paise?: number;
  refund_paise?: number;
  reasoning_steps?: string[];
  terms_clauses_relied_on?: string[];
  confidence?: number;
  open_questions?: string[];
  balanced?: boolean;
  attempts?: number;
  provider?: string;
  model_id?: string;
  advisory_only?: boolean;
  rejection_reason?: string;
};

export type Dispute = {
  id: string;
  deal_id: string;
  milestone_id: string;
  claim: string;
  counter_claim: string | null;
  arbiter_recommendation: ArbiterRecommendation | null;
  human_decision: Record<string, unknown> | null;
  human_decided_by: string | null;
  human_decided_at: string | null;
  override_delta_paise: number;
  resolved_at: string | null;
  created_at: string;
  settlement_blocked_until_human_decision: boolean;
};

export type LedgerEntry = {
  seq: number;
  event_type: string;
  actor: string;
  reason: string;
  payload: Record<string, unknown>;
  payload_hash: string;
  prev_hash: string;
  chain_anchor_tx: string | null;
  created_at: string;
};

export type LedgerVerdict = {
  ok: boolean;
  broken_index: number | null;
  reason?: string;
  expected?: string;
  found?: string;
  length: number;
  head?: string;
  replayed_balances: Money;
};

export type Provenance = {
  attestation: Attestation;
  deal: { id: string; reference: string; terms_hash: string; chain_deal_id: string | null };
  milestone: {
    id: string;
    seq: number;
    title: string;
    amount_paise: number;
    state: string;
    released_at: string | null;
  };
  signature_verified: boolean;
  human_approver: string | null;
  payouts: {
    id: string;
    direction: string;
    amount_paise: number;
    rail: string;
    rail_ref: string | null;
    rail_ref_hash: string;
    status: string;
    created_at: string;
  }[];
  chain: {
    available: boolean;
    reason: string | null;
    chain_id: number;
    contract_address: string | null;
    anchors: {
      id: string;
      kind: string;
      status: string;
      tx_hash: string | null;
      block_number: number | null;
      explorer_url: string | null;
      attempts: number;
      last_error: string | null;
    }[];
  };
  artifacts: { id: string; filename: string; artifact_type: string; sha256: string }[];
};

export type RiskFactor = {
  feature: string;
  direction: "increases" | "decreases";
  delta: number;
  sign: "+" | "-";
  plain_language: string;
};

export type Passport = {
  entity_id: string;
  display_name: string;
  region: string | null;
  kind: string;
  counterparty_since: string;
  deals_completed: number;
  gmv_paise: number;
  disputes_raised: number;
  disputes_lost: number;
  on_time_rate: number | null;
  largest_deal_paise: number;
  risk_score: number;
  band: string;
  score_version: string;
  top_factors: RiskFactor[];
  pricing: {
    tier: string;
    escrow_fee_pct: number | null;
    hold_days_after_final_release: number | null;
    buyer_prefund_pct: number | null;
    accepted: boolean;
    risk_score: number;
  };
};

export type Me = {
  id: string;
  email: string;
  name: string;
  email_verified: boolean;
  theme: string;
  language: string;
  active_org_id: string | null;
  organizations: {
    id: string;
    name: string;
    slug: string;
    city: string | null;
    role: string;
    active: boolean;
  }[];
  role: string | null;
};

export type Health = {
  ok: boolean;
  degraded: string[];
  checks: Record<
    string,
    { ready: boolean; required: boolean; reason?: string | null; mode?: string }
  >;
  ai_provider: string;
};

export type RailDisclosure = {
  mode: string;
  configured: string;
  credentials_present: boolean;
  operations: Record<string, string>;
};

export type EvalSummary = {
  available: boolean;
  reason?: string;
  all_green?: boolean;
  generated_at?: string;
  hard_gate_false_releases_zero?: boolean;
  headline?: {
    accuracy: number;
    adversarial_bundles: number;
    brier_score: number;
    cost_inr_per_verification_projected: number;
    cost_usd_per_verification_measured: number;
    escalation_in_band: boolean;
    escalation_rate: number;
    false_releases: number;
    labelled_bundles: number;
    prompt_cache_hit_rate: number;
    resolved_by_prechecks_pct: number;
    risk_baseline_test_auc: number;
    risk_selected_model: string;
    risk_test_auc: number;
    suite_b: string;
    suite_c: string;
  };
  provider?: {
    ai_provider_configured: string;
    ai_provider_effective: string;
    is_live_model: boolean;
    model_verifier: string;
    note: string;
  };
};

export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  deal_id: string | null;
  read_at: string | null;
  created_at: string;
};

export type Message = {
  id: string;
  deal_id: string;
  sender_user_id: string;
  sender_name: string;
  sender_org_id: string;
  body: string;
  created_at: string;
  mine: boolean;
};

export type MerkleProof = {
  artifact_id: string;
  leaf: string;
  proof: { position: "left" | "right"; hash: string }[];
  root: string;
  valid: boolean;
};

export type Settlement = {
  id: string;
  milestone_id: string;
  attestation_id: string;
  direction: string;
  amount_paise: number;
  attempt_no: number;
  authorized_by: string;
  human_approved: boolean;
  authorized_at: string;
  consumed_at: string | null;
  idempotency_key: string;
};

export type Payout = {
  id: string;
  milestone_id: string;
  direction: string;
  amount_paise: number;
  rail: string;
  rail_ref: string | null;
  status: string;
  failure_reason: string | null;
  created_at: string;
};

// ── Endpoints ────────────────────────────────────────────────────────────────
export const api = {
  // auth
  me: () => get<Me>("/auth/me"),
  login: (email: string, password: string) =>
    post<{ access_token: string; expires_in: number }>("/auth/login", { email, password }),
  register: (body: {
    email: string;
    password: string;
    name: string;
    organization_name?: string;
  }) => post<{ access_token: string }>("/auth/register", body),
  logout: () => post<{ ok: boolean }>("/auth/logout"),
  verifyEmail: (token: string) => post<{ ok: boolean }>("/auth/verify-email", { token }),
  resendVerification: (email: string) =>
    post<{ ok: boolean }>("/auth/resend-verification", { email }),
  forgotPassword: (email: string) => post<{ ok: boolean }>("/auth/forgot-password", { email }),
  resetPassword: (token: string, newPassword: string) =>
    post<{ ok: boolean }>("/auth/reset-password", { token, new_password: newPassword }),
  savePreferences: (body: { theme?: string; language?: string }) =>
    patch<{ ok: boolean }>("/auth/preferences", body),

  // demo affordance (DEMO_MODE only)
  assume: (role: "buyer" | "seller") =>
    post<{ access_token: string }>("/dev/assume", { role }),
  devState: () => get<Record<string, unknown>>("/dev/state"),

  // organizations
  organizations: () => get<Me["organizations"]>("/organizations"),
  currentOrganization: () =>
    get<{ id: string; name: string; slug: string; city: string | null; role: string }>(
      "/organizations/current",
    ),
  switchOrganization: (id: string) => post<unknown>(`/organizations/${id}/switch`),
  members: () =>
    get<
      {
        user_id: string;
        name: string;
        email: string;
        role: string;
        verified: boolean;
        joined_at: string;
      }[]
    >("/organizations/members"),
  invite: (email: string, role: string) =>
    post<{ id: string; email: string; role: string; accept_token?: string }>(
      "/organizations/invitations",
      { email, role },
    ),
  invitations: () =>
    get<{ id: string; email: string; role: string; accepted: boolean; expires_at: string }[]>(
      "/organizations/invitations",
    ),
  acceptInvitation: (token: string) => post<unknown>("/organizations/invitations/accept", { token }),
  changeRole: (userId: string, role: string) =>
    patch<unknown>(`/organizations/members/${userId}/role`, { role }),
  removeMember: (userId: string) =>
    request<{ ok: boolean }>(`/organizations/members/${userId}`, { method: "DELETE" }),
  entities: () =>
    get<{ id: string; kind: string; display_name: string; region: string | null }[]>("/entities"),

  // deals
  deals: () => get<Deal[]>("/deals"),
  deal: (id: string) => get<Deal>(`/deals/${id}`),
  demoDeal: () => get<Deal>("/deals/demo"),
  signTerms: (id: string) => post<Deal>(`/deals/${id}/sign-terms`, { accept: true }),
  fund: (id: string) => post<Deal>(`/deals/${id}/fund`, {}),
  cancel: (id: string, reason: string) => post<Deal>(`/deals/${id}/cancel`, { reason }),
  timeline: (id: string) => get<LedgerEntry[]>(`/deals/${id}/timeline`),
  dealRisk: (id: string) =>
    get<{
      risk_score: number;
      band: string;
      score_version: string;
      model_trained: boolean;
      model_kind: string;
      features: Record<string, number>;
      top_factors: RiskFactor[];
      pricing: Passport["pricing"];
    }>(`/deals/${id}/risk`),

  // milestones
  milestone: (id: string) => get<MilestoneSummary>(`/milestones/${id}`),
  startVerify: (id: string) =>
    post<{
      attestation_id: string;
      decision: string;
      confidence: number;
      milestone_state: string;
      llm_calls: number;
      resolved_by_prechecks: boolean;
      provider: string;
    }>(`/milestones/${id}/start-verify`),
  reviewQueue: () => get<ReviewRow[]>("/milestones/review-queue"),
  humanReview: (id: string, action: "APPROVE" | "REJECT", reason: string) =>
    post<{ action: string; milestone_state: string; authorized: boolean; amount_paise?: number }>(
      `/milestones/${id}/human-review`,
      { action, reason },
    ),

  // evidence
  bundle: (milestoneId: string) => get<Bundle | null>(`/evidence/milestones/${milestoneId}/bundle`),
  upload: (milestoneId: string, artifactType: string, file: File) => {
    const form = new FormData();
    form.append("artifact_type", artifactType);
    form.append("file", file);
    return request<Artifact>(`/evidence/milestones/${milestoneId}/upload`, {
      method: "POST",
      form,
    });
  },
  submitBundle: (milestoneId: string) =>
    post<Bundle>(`/evidence/milestones/${milestoneId}/submit`),
  proof: (artifactId: string) => get<MerkleProof>(`/evidence/artifacts/${artifactId}/proof`),
  verifyProof: (body: { leaf: string; proof: MerkleProof["proof"]; root: string }) =>
    post<{ ok: boolean; leaf: string; root: string; steps: number }>("/evidence/verify", body),

  // verification and provenance
  attestationForMilestone: (milestoneId: string) =>
    get<Attestation | null>(`/verification/milestones/${milestoneId}`),
  attestation: (id: string) => get<Attestation>(`/verification/attestations/${id}`),
  provenance: (attestationId: string) =>
    get<Provenance>(`/provenance/attestations/${attestationId}`),
  chainRecords: (dealId: string) =>
    get<{
      deal_id: string;
      chain_deal_id: string | null;
      chain_available: boolean;
      chain_unavailable_reason: string | null;
      anchors: {
        anchor_id: string;
        kind: string;
        status: string;
        milestone_seq: number | null;
        tx_hash: string | null;
        explorer_url: string | null;
        local_attestation_hash: string | null;
        onchain: Record<string, unknown> | null;
        matches: boolean;
      }[];
    }>(`/provenance/deals/${dealId}/chain`),
  tamperCheck: (contentB64: string, expectedSha256: string) =>
    post<{
      expected_sha256: string;
      actual_sha256: string;
      ok: boolean;
      byte_length: number;
    }>("/provenance/tamper-check", {
      content_b64: contentB64,
      expected_sha256: expectedSha256,
    }),

  // ledger
  ledger: (dealId: string) => get<LedgerEntry[]>(`/ledger/deals/${dealId}`),
  verifyLedger: (dealId: string) => get<LedgerVerdict>(`/ledger/deals/${dealId}/verify`),

  // disputes
  raiseDispute: (milestoneId: string, claim: string) =>
    post<Dispute>(`/milestones/${milestoneId}/disputes`, { claim }),
  disputes: () => get<Dispute[]>("/disputes"),
  dispute: (id: string) => get<Dispute>(`/disputes/${id}`),
  counterClaim: (id: string, counterClaim: string) =>
    post<Dispute>(`/disputes/${id}/counter-claim`, { counter_claim: counterClaim }),
  runArbiter: (id: string) =>
    post<{ dispute_id: string; recommendation: ArbiterRecommendation }>(
      `/disputes/${id}/arbiter`,
    ),
  resolveDispute: (
    id: string,
    body: { release_paise: number; refund_paise: number; reason: string },
  ) =>
    post<{
      dispute_id: string;
      authorizations: string[];
      release_paise: number;
      refund_paise: number;
      override_delta_paise: number;
      decision_hash: string;
    }>(`/disputes/${id}/resolve`, body),

  // settlement and payments
  settlements: (dealId: string) => get<Settlement[]>(`/settlements/deals/${dealId}`),
  payouts: (dealId: string) => get<Payout[]>(`/payments/deals/${dealId}/payouts`),
  rail: () => get<RailDisclosure>("/payments/rail"),

  // reputation
  passport: (entityId: string) => get<Passport>(`/reputation/entities/${entityId}`),

  // notifications and chat
  notifications: () => get<{ unread: number; items: Notification[] }>("/notifications"),
  markRead: (ids?: string[]) => post<{ marked: number }>("/notifications/mark-read", { ids }),
  notificationPreferences: () =>
    get<{ kind: string; title: string; in_app: boolean; email: boolean }[]>(
      "/notifications/preferences",
    ),
  saveNotificationPreference: (body: { kind: string; in_app: boolean; email: boolean }) =>
    put<{ ok: boolean }>("/notifications/preferences", body),
  messages: (dealId: string) => get<Message[]>(`/chat/deals/${dealId}`),
  sendMessage: (dealId: string, body: string) => post<Message>(`/chat/deals/${dealId}`, { body }),

  // health
  health: () => get<Health>("/health/ready"),
  evalSummary: () => get<EvalSummary>("/health/eval-summary"),
  metrics: () => get<Record<string, unknown>>("/health/metrics"),
};

export const sseUrl = (path: string) => `${BASE}/realtime${path}`;
