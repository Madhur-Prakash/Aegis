"""Pydantic request/response schemas.  ORM models never leave the repository layer."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class Ok(BaseModel):
    ok: bool = True


# ── Pagination ──────────────────────────────────────────────────────────────
class Page(BaseModel):
    items: list[Any]
    next_cursor: str | None = None
    has_more: bool = False


# ── Auth ────────────────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    organization_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_token: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class VerifyEmailIn(BaseModel):
    token: str


class ResendVerificationIn(BaseModel):
    email: EmailStr


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=6, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=200)


class MeOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    email_verified: bool
    theme: str
    language: str
    active_org_id: uuid.UUID | None
    organizations: list[dict[str, Any]] = Field(default_factory=list)
    role: str | None = None


class PreferencesIn(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    language: Literal["en", "hi"] | None = None


# ── Organizations ───────────────────────────────────────────────────────────
class OrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = None


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    city: str | None
    role: str | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["ADMIN", "MEMBER", "VIEWER"]


class AcceptInviteIn(BaseModel):
    token: str


class RoleIn(BaseModel):
    role: Literal["OWNER", "ADMIN", "MEMBER", "VIEWER"]


class EntityIn(BaseModel):
    kind: Literal["BUYER", "SELLER"]
    display_name: str = Field(min_length=1, max_length=200)
    region: str | None = None


# ── Deals ───────────────────────────────────────────────────────────────────
class ClauseIn(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    kind: Literal[
        "ARTIFACT_PRESENT",
        "DATE_WITHIN",
        "AMOUNT_AT_LEAST",
        "QUANTITY_AT_LEAST",
        "FIELD_EQUALS",
        "FIELD_MATCHES_SPEC",
        "VISUAL_CONSISTENT_WITH",
    ]
    description: str = Field(min_length=1, max_length=400)
    params: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class ConditionIn(BaseModel):
    # Bounded because every clause is rendered into the verifier's prompt and
    # evaluated once per verification run: an unbounded list let one deal make
    # every later `start-verify` on it arbitrarily expensive.
    clauses: list[ClauseIn] = Field(max_length=32)
    required_artifact_types: list[str] = Field(default_factory=list, max_length=16)
    tolerance: dict[str, Any] = Field(default_factory=dict)


class MilestoneIn(BaseModel):
    seq: int = Field(ge=1, le=64)
    title: str = Field(min_length=1, max_length=200)
    amount_paise: int = Field(gt=0)
    verification_condition: ConditionIn


class DealIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seller_org_slug: str | None = None
    seller_org_id: uuid.UUID | None = None
    buyer_entity_id: uuid.UUID | None = None
    seller_entity_id: uuid.UUID | None = None
    total_paise: int = Field(gt=0)
    dispute_window_days: int = Field(default=7, ge=0, le=90)
    category: str = "apparel"
    tolerance: dict[str, Any] = Field(default_factory=dict)
    milestones: list[MilestoneIn] = Field(max_length=64)

    @field_validator("milestones")
    @classmethod
    def _unique_seq(cls, v: list[MilestoneIn]) -> list[MilestoneIn]:
        seqs = [m.seq for m in v]
        if len(set(seqs)) != len(seqs):
            raise ValueError("milestone seq values must be unique")
        return v


class MoneyOut(BaseModel):
    funded_paise: int
    released_paise: int
    refunded_paise: int
    held_paise: int
    balanced: bool


class MilestoneOut(BaseModel):
    id: uuid.UUID
    seq: int
    title: str
    amount_paise: int
    state: str
    verification_condition: dict[str, Any]
    released_at: dt.datetime | None = None
    has_evidence: bool = False
    attestation_id: uuid.UUID | None = None
    decision: str | None = None
    confidence: float | None = None


class DealOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    state: str
    total_paise: int
    money: MoneyOut
    buyer_org: dict[str, Any]
    seller_org: dict[str, Any]
    terms_hash: str
    chain_deal_id: str | None
    chain_tx: str | None
    dispute_window_days: int
    risk_score: float | None
    pricing_tier: str | None
    milestones: list[MilestoneOut]
    created_at: dt.datetime
    viewer_side: Literal["buyer", "seller"]


class FundIn(BaseModel):
    amount_paise: int | None = None


class SignTermsIn(BaseModel):
    accept: bool = True


class CancelIn(BaseModel):
    reason: str = Field(min_length=12, max_length=500)


# ── Evidence ────────────────────────────────────────────────────────────────
class ArtifactOut(BaseModel):
    id: uuid.UUID
    artifact_type: str
    filename: str
    mime: str
    size_bytes: int
    sha256: str
    extraction_quality: float | None
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    unreadable_fields: list[str] = Field(default_factory=list)
    download_url: str | None = None
    created_at: dt.datetime


class BundleOut(BaseModel):
    id: uuid.UUID
    milestone_id: uuid.UUID
    merkle_root: str
    submitted_at: dt.datetime | None
    artifacts: list[ArtifactOut]


class ProofStepIn(BaseModel):
    """One sibling on the path from a leaf to the root."""

    position: Literal["left", "right"]
    hash: str = Field(min_length=64, max_length=66)


class VerifyProofIn(BaseModel):
    """`POST /evidence/verify` is public, so its bounds are load-bearing.

    ``proof`` used to be an unvalidated ``list[dict[str, str]]``: unbounded in
    length, and free to carry a ``position`` the verifier does not understand or
    a ``hash`` that is not hex, which reached ``bytes.fromhex`` and came back as
    a 500 rather than "that proof does not verify".  A bundle holds a few dozen
    artifacts, so 64 steps is a tree of 2^64 leaves and then some.
    """

    leaf: str = Field(min_length=64, max_length=66)
    proof: list[ProofStepIn] = Field(default_factory=list, max_length=64)
    root: str = Field(min_length=64, max_length=66)


class TamperCheckIn(BaseModel):
    """`POST /provenance/tamper-check` is public too, and it decodes what it is given.

    The handler took a bare ``dict`` and ran ``base64.b64decode`` over whatever
    ``content_b64`` held, with no ceiling: a few hundred megabytes of base64 from
    an anonymous client became a few hundred megabytes of ``bytes`` in the API
    process.  The UI flips one byte of one artifact, so the artifact cap is the
    honest bound.
    """

    content_b64: str = Field(default="", max_length=(20 * 1024 * 1024 * 4) // 3 + 8)
    expected_sha256: str = Field(default="", max_length=66)


# ── Verification ────────────────────────────────────────────────────────────
class ClauseVerdictOut(BaseModel):
    clause_id: str
    verdict: str
    required: bool
    clause_confidence: float
    note: str
    evidence_refs: list[str]
    description: str = ""
    kind: str = ""
    resolved_by: str = ""


class AttestationOut(BaseModel):
    id: uuid.UUID
    reference: str
    milestone_id: uuid.UUID
    bundle_id: uuid.UUID
    decision: str
    confidence: float
    confidence_components: dict[str, Any]
    clause_verdicts: list[ClauseVerdictOut]
    reasoning: str
    provider: str
    model_id: str
    model_version: str
    prompt_hash: str
    evidence_merkle_root: str
    deterministic_prechecks: dict[str, Any]
    thresholds: dict[str, Any]
    calibration_version: str
    canonical_hash: str
    signature: str
    signer_key_id: str
    signer_address: str
    chain_tx: str | None
    chain_block: int | None
    created_at: dt.datetime


# ── Human review / disputes ─────────────────────────────────────────────────
class HumanReviewIn(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=12, max_length=1000)


class DisputeIn(BaseModel):
    claim: str = Field(min_length=12, max_length=2000)


class CounterClaimIn(BaseModel):
    counter_claim: str = Field(min_length=12, max_length=2000)


class ResolveDisputeIn(BaseModel):
    release_paise: int = Field(ge=0)
    refund_paise: int = Field(ge=0)
    reason: str = Field(min_length=12, max_length=1000)


# ── Chat ────────────────────────────────────────────────────────────────────
class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: uuid.UUID
    deal_id: uuid.UUID
    sender_user_id: uuid.UUID
    sender_name: str
    sender_org_id: uuid.UUID
    body: str
    created_at: dt.datetime
    mine: bool = False


# ── Notifications ───────────────────────────────────────────────────────────
class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    deal_id: uuid.UUID | None
    read_at: dt.datetime | None
    created_at: dt.datetime


class MarkReadIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class NotificationPreferenceIn(BaseModel):
    kind: str
    in_app: bool
    email: bool


# ── Dev ─────────────────────────────────────────────────────────────────────
class AssumeIn(BaseModel):
    role: Literal["buyer", "seller"]
