"""Typed error envelope (I9). Expected business failures are never a bare 500."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AegisError(Exception):
    """Base class for every expected, machine-readable failure."""

    code = "INTERNAL_ERROR"
    http_status = 500
    message = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status
        super().__init__(self.message)

    def envelope(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id,
            }
        }


# ── Generic ─────────────────────────────────────────────────────────────────
class NotFound(AegisError):
    code = "NOT_FOUND"
    http_status = 404
    message = "Resource not found."


class ValidationFailed(AegisError):
    code = "VALIDATION_FAILED"
    http_status = 422
    message = "The request was not valid."


class Conflict(AegisError):
    code = "CONFLICT"
    http_status = 409
    message = "The request conflicts with the current state."


class RateLimited(AegisError):
    code = "RATE_LIMITED"
    http_status = 429
    message = "Too many requests."


class ServiceUnavailable(AegisError):
    code = "SERVICE_UNAVAILABLE"
    http_status = 503
    message = "A required dependency is unavailable."


# ── Auth / tenancy ──────────────────────────────────────────────────────────
class Unauthenticated(AegisError):
    code = "UNAUTHENTICATED"
    http_status = 401
    message = "Authentication required."


class InvalidCredentials(AegisError):
    code = "INVALID_CREDENTIALS"
    http_status = 401
    # Deliberately generic: never reveal whether the email exists (spec §12).
    message = "Email or password is incorrect."


class Forbidden(AegisError):
    code = "FORBIDDEN"
    http_status = 403
    message = "Your role does not permit this action."


class EmailNotVerified(AegisError):
    code = "EMAIL_NOT_VERIFIED"
    http_status = 403
    message = "Verify your email address before performing this action."


class TokenInvalid(AegisError):
    code = "TOKEN_INVALID"
    http_status = 401
    message = "The token is invalid or has expired."


class RefreshTokenReuse(AegisError):
    code = "REFRESH_TOKEN_REUSE"
    http_status = 401
    message = "This session was revoked because a refresh token was replayed."


class LastOwnerProtected(AegisError):
    code = "LAST_OWNER_PROTECTED"
    http_status = 409
    message = "An organization must always have at least one owner."


# ── Domain ──────────────────────────────────────────────────────────────────
class IllegalTransition(AegisError):
    code = "ILLEGAL_TRANSITION"
    http_status = 409
    message = "That state transition is not permitted."


class MoneyInvariantViolation(AegisError):
    code = "MONEY_INVARIANT_VIOLATION"
    http_status = 409
    message = "The operation would break held + released + refunded == funded."


class NoQualifyingAttestation(AegisError):
    code = "NO_QUALIFYING_ATTESTATION"
    http_status = 409
    message = "No qualifying attestation exists for this milestone."


class ConfidenceBelowReleaseThreshold(AegisError):
    code = "CONFIDENCE_BELOW_RELEASE_THRESHOLD"
    http_status = 409
    message = "Evidence cannot be released automatically."


class UnverifiableRequiredClause(AegisError):
    code = "UNVERIFIABLE_REQUIRED_CLAUSE"
    http_status = 409
    message = "A required clause could not be verified, so automatic release is impossible."


class HumanDecisionRequired(AegisError):
    code = "HUMAN_DECISION_REQUIRED"
    http_status = 409
    message = "A human decision is required before this dispute can settle."


class RailFailure(AegisError):
    code = "RAIL_FAILURE"
    http_status = 502
    message = "The payment rail rejected the operation."


class ChainUnavailable(AegisError):
    code = "CHAIN_UNAVAILABLE"
    http_status = 503
    message = "Chain anchoring is unavailable; the anchor has been queued."


class ArtifactRejected(AegisError):
    code = "ARTIFACT_REJECTED"
    http_status = 422
    message = "The uploaded artifact was rejected."


class AttestationSignatureInvalid(AegisError):
    code = "ATTESTATION_SIGNATURE_INVALID"
    http_status = 409
    message = "The attestation signature does not verify."


class LLMOutputRejected(AegisError):
    code = "LLM_OUTPUT_REJECTED"
    http_status = 409
    message = "The model produced output that failed deterministic validation."


def error_response(exc: AegisError, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "req_unknown")
    return JSONResponse(status_code=exc.http_status, content=exc.envelope(request_id))
