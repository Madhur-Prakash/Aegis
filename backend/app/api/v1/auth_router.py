"""/api/v1/auth -- registration, verification, login, refresh, reset."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.v1.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    MeOut,
    Ok,
    PreferencesIn,
    RefreshIn,
    RegisterIn,
    ResendVerificationIn,
    ResetPasswordIn,
    TokenOut,
    VerifyEmailIn,
)
from app.auth import service as auth_service
from app.auth.security import normalize_email
from app.common.deps import ACCESS_COOKIE, REFRESH_COOKIE, MembershipDep, SessionDep, UserDep
from app.common.errors import TokenInvalid
from app.common.redis_client import rate_limit
from app.config.settings import settings
from app.organizations import service as org_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response: Response, tokens: auth_service.SessionTokens) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=tokens.expires_in,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(
    payload: RegisterIn, request: Request, response: Response, session: SessionDep
) -> TokenOut:
    await rate_limit("auth:register", _client_ip(request), settings.RATE_LIMIT_AUTH)
    user, _raw = await auth_service.register(
        session, email=str(payload.email), password=payload.password, name=payload.name
    )
    await org_service.create_organization(
        session,
        name=payload.organization_name or f"{payload.name}'s organization",
        owner=user,
    )
    tokens = await auth_service.issue_session(session, user)
    await session.commit()
    _set_cookies(response, tokens)
    return TokenOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn, request: Request, response: Response, session: SessionDep
) -> TokenOut:
    await rate_limit("auth:login", _client_ip(request), settings.RATE_LIMIT_AUTH)
    await rate_limit(
        "auth:login:account", normalize_email(str(payload.email)), settings.RATE_LIMIT_AUTH
    )
    _user, tokens = await auth_service.login(
        session, email=str(payload.email), password=payload.password
    )
    await session.commit()
    _set_cookies(response, tokens)
    return TokenOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    payload: RefreshIn, request: Request, response: Response, session: SessionDep
) -> TokenOut:
    raw = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise TokenInvalid(message="No refresh token was supplied.")
    _user, tokens = await auth_service.refresh(session, raw)
    await session.commit()
    _set_cookies(response, tokens)
    return TokenOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.post("/logout", response_model=Ok)
async def logout(request: Request, response: Response, user: UserDep, session: SessionDep) -> Ok:
    await auth_service.logout(session, request.cookies.get(REFRESH_COOKIE), user.id)
    await session.commit()
    _clear_cookies(response)
    return Ok()


@router.post("/verify-email", response_model=Ok)
async def verify_email(payload: VerifyEmailIn, session: SessionDep) -> Ok:
    await auth_service.verify_email(session, payload.token)
    await session.commit()
    return Ok()


@router.post("/resend-verification", response_model=Ok)
async def resend_verification(
    payload: ResendVerificationIn, request: Request, session: SessionDep
) -> Ok:
    await rate_limit("auth:resend", _client_ip(request), "3/60")
    from sqlalchemy import select

    from app.models.identity import User

    user = (
        await session.execute(
            select(User).where(User.email_normalized == normalize_email(str(payload.email)))
        )
    ).scalar_one_or_none()
    if user is not None:
        await auth_service.resend_verification(session, user)
        await session.commit()
    # Identical response whether or not the account exists.
    return Ok()


@router.post("/forgot-password", response_model=Ok)
async def forgot_password(payload: ForgotPasswordIn, request: Request, session: SessionDep) -> Ok:
    await rate_limit("auth:forgot", _client_ip(request), settings.RATE_LIMIT_AUTH)
    await auth_service.forgot_password(session, str(payload.email))
    await session.commit()
    return Ok()


@router.post("/reset-password", response_model=Ok)
async def reset_password(payload: ResetPasswordIn, response: Response, session: SessionDep) -> Ok:
    await auth_service.reset_password(session, payload.token, payload.new_password)
    await session.commit()
    _clear_cookies(response)
    return Ok()


@router.post("/change-password", response_model=Ok)
async def change_password(
    payload: ChangePasswordIn, response: Response, user: UserDep, session: SessionDep
) -> Ok:
    await auth_service.change_password(
        session, user, payload.current_password, payload.new_password
    )
    await session.commit()
    _clear_cookies(response)
    return Ok()


@router.get("/me", response_model=MeOut)
async def me(user: UserDep, membership: MembershipDep, session: SessionDep) -> MeOut:
    orgs = await org_service.my_organizations(session, user)
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        email_verified=user.email_verified_at is not None,
        theme=user.theme,
        language=user.language,
        active_org_id=membership.org_id,
        organizations=orgs,
        role=str(membership.role),
    )


@router.patch("/preferences", response_model=Ok)
async def preferences(payload: PreferencesIn, user: UserDep, session: SessionDep) -> Ok:
    if payload.theme:
        user.theme = payload.theme
    if payload.language:
        user.language = payload.language
    await session.commit()
    return Ok()
