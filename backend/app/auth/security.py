"""Password hashing, JWTs, token hashing.  Argon2id only (spec 12)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.common.errors import TokenInvalid, ValidationFailed
from app.config.settings import settings

# Argon2id with sensible memory/time cost.  Never MD5/SHA/bcrypt-by-hand.
_hasher = PasswordHasher(
    time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16
)


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, Exception):
        return False


# Argon2id at 64 MiB and t=3 takes tens of milliseconds, which is the whole
# point of it -- and also a clock anyone can read.  Returning `InvalidCredentials`
# without hashing anything when the account does not exist made "no such account"
# and "wrong password" trivially distinguishable by response time, whatever the
# response body said.  `dummy_verify` burns the same work against a real hash so
# the two paths cost the same.
# secret-scan-allow: not a credential -- a throwaway string hashed at runtime so
# a login for a non-existent account costs the same as one for a real account.
_DUMMY_PASSWORD = "aegis-timing-equaliser"
_dummy_hash: str | None = None


def dummy_verify() -> None:
    """Spend one password verification against a throwaway hash.

    Built on first use rather than at import: an Argon2id hash at 64 MiB is tens
    of milliseconds, and every process in the system -- API, worker, each script
    -- imports this module.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(_DUMMY_PASSWORD)
    try:
        _hasher.verify(_dummy_hash, "")
    except Exception:
        return


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def validate_password(password: str) -> None:
    """The length floor is the whole policy.

    There is deliberately no composition rule and no common-password denylist:
    a breach-corpus password such as ``password123`` is accepted.  ``max_length``
    on the request schemas is not part of this policy -- it bounds the input to
    Argon2id, which is a denial-of-service guard rather than a strength one.
    """
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValidationFailed(
            message=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.",
            details={"field": "password", "min_length": settings.PASSWORD_MIN_LENGTH},
        )


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(raw: str) -> str:
    """Tokens are hashed at rest.  The raw value never touches the database."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID | None, session_id: str) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "sid": session_id,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)).timestamp()),
        "iss": "aegis",
        "typ": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM], issuer="aegis"
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalid(message="The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalid() from exc
    if claims.get("typ") != "access":
        raise TokenInvalid()
    return claims
