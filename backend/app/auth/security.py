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

# A short, explicit weak list.  No composition theatre, just a length floor and
# a refusal of the passwords that actually appear in breach corpora.
_WEAK = frozenset(
    {
        "password",
        "password1",
        "password123",
        "passw0rd",
        "letmein123",
        "12345678",
        "123456789",
        "1234567890",
        "qwertyuiop",
        "iloveyou1",
        "welcome123",
        "admin12345",
        "changeme123",
        "aegis12345",
        "abcd123456",
        "monkey12345",
        "football123",
        "dragon12345",
        "sunshine123",
        "princess123",
    }
)


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def validate_password(password: str) -> None:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValidationFailed(
            message=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.",
            details={"field": "password", "min_length": settings.PASSWORD_MIN_LENGTH},
        )
    if password.lower() in _WEAK:
        raise ValidationFailed(
            message="That password is too common. Choose another.",
            details={"field": "password"},
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
