"""Registration, login, refresh rotation with reuse detection, verification, reset."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    create_access_token,
    dummy_verify,
    hash_password,
    hash_token,
    normalize_email,
    verify_password,
)
from app.common.errors import (
    Conflict,
    InvalidCredentials,
    RefreshTokenReuse,
    TokenInvalid,
    Unauthenticated,
)
from app.common.ids import url_token
from app.common.logging import get_logger
from app.config.settings import settings
from app.models.enums import UserStatus
from app.models.identity import EmailToken, OrganizationMember, RefreshToken, User
from app.notifications.email import get_email_provider, render

log = get_logger("auth")

VERIFY_EMAIL = "VERIFY_EMAIL"
RESET_PASSWORD = "RESET_PASSWORD"
VERIFY_TTL = dt.timedelta(hours=24)
RESET_TTL = dt.timedelta(minutes=30)


@dataclass(slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _issue_refresh(
    session: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID | None = None
) -> tuple[str, RefreshToken]:
    raw = url_token(32)
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        family_id=family_id or uuid.uuid4(),
        expires_at=_now() + dt.timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
    )
    session.add(row)
    await session.flush()
    return raw, row


async def _active_org(session: AsyncSession, user: User) -> uuid.UUID | None:
    if user.active_org_id:
        membership = select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.org_id == user.active_org_id,
        )
        if (await session.execute(membership)).scalar_one_or_none():
            return user.active_org_id
    first = (
        select(OrganizationMember.org_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.joined_at)
        .limit(1)
    )
    return (await session.execute(first)).scalar_one_or_none()


async def issue_session(session: AsyncSession, user: User) -> SessionTokens:
    raw_refresh, row = await _issue_refresh(session, user.id)
    org_id = await _active_org(session, user)
    access = create_access_token(user.id, org_id, str(row.family_id))
    return SessionTokens(access, raw_refresh, settings.ACCESS_TOKEN_TTL_MINUTES * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Registration and verification
# ─────────────────────────────────────────────────────────────────────────────
async def register(
    session: AsyncSession, *, email: str, password: str, name: str
) -> tuple[User, str]:
    normalized = normalize_email(email)
    existing = (
        await session.execute(select(User).where(User.email_normalized == normalized))
    ).scalar_one_or_none()
    if existing is not None:
        raise Conflict(
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with that email already exists.",
        )
    user = User(
        email=email.strip(),
        email_normalized=normalized,
        name=name.strip(),
        password_hash=hash_password(password),
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    raw = await create_email_token(session, user, VERIFY_EMAIL, VERIFY_TTL)
    link = f"{settings.PUBLIC_APP_URL}/verify-email?token={raw}"
    get_email_provider().send(render("verify_email", user.email, name=user.name, link=link))
    log.info("auth register", extra={"user_id": str(user.id), "decision": "created"})
    return user, raw


async def create_email_token(
    session: AsyncSession, user: User, purpose: str, ttl: dt.timedelta
) -> str:
    """Returns the raw token; only its hash is persisted, and it is never logged."""
    raw = url_token(32)
    session.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=_now() + ttl,
        )
    )
    await session.flush()
    return raw


async def consume_email_token(session: AsyncSession, raw: str, purpose: str) -> User:
    row = (
        await session.execute(
            select(EmailToken).where(
                EmailToken.token_hash == hash_token(raw), EmailToken.purpose == purpose
            )
        )
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= _now():
        raise TokenInvalid()
    row.consumed_at = _now()
    user = await session.get(User, row.user_id)
    if user is None:
        raise TokenInvalid()
    return user


async def verify_email(session: AsyncSession, raw: str) -> User:
    user = await consume_email_token(session, raw, VERIFY_EMAIL)
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    log.info("auth verify_email", extra={"user_id": str(user.id), "decision": "verified"})
    return user


async def resend_verification(session: AsyncSession, user: User) -> str | None:
    if user.email_verified_at is not None:
        return None
    raw = await create_email_token(session, user, VERIFY_EMAIL, VERIFY_TTL)
    link = f"{settings.PUBLIC_APP_URL}/verify-email?token={raw}"
    get_email_provider().send(render("verify_email", user.email, name=user.name, link=link))
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Login / refresh / logout
# ─────────────────────────────────────────────────────────────────────────────
async def login(session: AsyncSession, *, email: str, password: str) -> tuple[User, SessionTokens]:
    normalized = normalize_email(email)
    user = (
        await session.execute(select(User).where(User.email_normalized == normalized))
    ).scalar_one_or_none()
    # Identical failure regardless of whether the account exists -- in the body
    # *and* on the clock.  Skipping the hash when there is no account made the
    # two cases tens of milliseconds apart, which is a perfectly usable
    # enumeration oracle no matter how carefully the message is worded.
    if user is None:
        dummy_verify()
        log.warning("auth login", extra={"decision": "rejected", "reason": "bad_credentials"})
        raise InvalidCredentials()
    if not verify_password(user.password_hash, password):
        log.warning("auth login", extra={"decision": "rejected", "reason": "bad_credentials"})
        raise InvalidCredentials()
    if user.status != UserStatus.ACTIVE:
        log.warning(
            "auth login",
            extra={"user_id": str(user.id), "decision": "rejected", "reason": "suspended"},
        )
        raise InvalidCredentials()
    tokens = await issue_session(session, user)
    log.info("auth login", extra={"user_id": str(user.id), "decision": "accepted"})
    return user, tokens


async def refresh(session: AsyncSession, raw_refresh: str) -> tuple[User, SessionTokens]:
    """Rotates the refresh token.  A replay invalidates the whole family (spec 12)."""
    row = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh))
        )
    ).scalar_one_or_none()
    if row is None:
        raise TokenInvalid()

    if row.revoked_at is not None or row.replaced_by is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        # Commit BEFORE raising.  The caller aborts on the exception and never
        # reaches its own commit, so without this the revocation would roll back
        # and the stolen family would stay live -- the detection would be a log
        # line and nothing more.
        await session.commit()
        log.warning(
            "auth refresh reuse detected",
            extra={"user_id": str(row.user_id), "family_id": str(row.family_id)},
        )
        raise RefreshTokenReuse()

    if row.expires_at <= _now():
        raise TokenInvalid(message="The refresh token has expired.")

    user = await session.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise Unauthenticated()

    new_raw, new_row = await _issue_refresh(session, user.id, family_id=row.family_id)
    row.replaced_by = new_row.id
    row.revoked_at = _now()
    org_id = await _active_org(session, user)
    access = create_access_token(user.id, org_id, str(row.family_id))
    log.info("auth refresh", extra={"user_id": str(user.id), "decision": "rotated"})
    return user, SessionTokens(access, new_raw, settings.ACCESS_TOKEN_TTL_MINUTES * 60)


async def logout(session: AsyncSession, raw_refresh: str | None, user_id: uuid.UUID) -> None:
    if raw_refresh:
        row = (
            await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh))
            )
        ).scalar_one_or_none()
        # The cookie must belong to the caller.  Without the ownership test a
        # signed-in user could present somebody else's refresh token and sign
        # *them* out, while their own session stayed alive -- and the caller's
        # own sessions would be left untouched, which is not what "log out"
        # means.  A foreign token falls through to revoking the caller's own.
        if row is not None and row.user_id != user_id:
            log.warning(
                "auth logout",
                extra={"user_id": str(user_id), "decision": "foreign_refresh_token_ignored"},
            )
            row = None
        if row is not None:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
            log.info("auth logout", extra={"user_id": str(user_id), "decision": "family_revoked"})
            return
    await revoke_all_sessions(session, user_id)
    log.info("auth logout", extra={"user_id": str(user_id), "decision": "all_revoked"})


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


# ─────────────────────────────────────────────────────────────────────────────
# Password reset
# ─────────────────────────────────────────────────────────────────────────────
async def forgot_password(session: AsyncSession, email: str) -> str | None:
    """Responds identically whether or not the account exists."""
    normalized = normalize_email(email)
    user = (
        await session.execute(select(User).where(User.email_normalized == normalized))
    ).scalar_one_or_none()
    if user is None:
        log.info("auth forgot_password", extra={"decision": "no_account"})
        return None
    raw = await create_email_token(session, user, RESET_PASSWORD, RESET_TTL)
    link = f"{settings.PUBLIC_APP_URL}/reset-password?token={raw}"
    get_email_provider().send(render("password_reset", user.email, name=user.name, link=link))
    log.info("auth forgot_password", extra={"user_id": str(user.id), "decision": "issued"})
    return raw


async def reset_password(session: AsyncSession, raw: str, new_password: str) -> User:
    user = await consume_email_token(session, raw, RESET_PASSWORD)
    user.password_hash = hash_password(new_password)
    # Every outstanding reset token for this user dies with the reset.
    await session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == RESET_PASSWORD,
            EmailToken.consumed_at.is_(None),
        )
        .values(consumed_at=_now())
    )
    await revoke_all_sessions(session, user.id)
    log.info("auth reset_password", extra={"user_id": str(user.id), "decision": "reset"})
    return user


async def change_password(session: AsyncSession, user: User, current: str, new: str) -> None:
    if not verify_password(user.password_hash, current):
        raise InvalidCredentials(message="The current password is incorrect.")
    user.password_hash = hash_password(new)
    await revoke_all_sessions(session, user.id)
