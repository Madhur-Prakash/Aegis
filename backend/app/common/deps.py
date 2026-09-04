"""The authorization dependency chain.

``current_user -> current_membership -> require_role(...) -> repo``

Cross-tenant access returns **404**, not 403, so ids cannot be probed (I12).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.common.errors import (
    EmailNotVerified,
    Forbidden,
    NotFound,
    TokenInvalid,
    Unauthenticated,
)
from app.db.repo import TenantRepo
from app.db.session import db_session
from app.models.enums import ROLE_RANK, OrgRole
from app.models.identity import Organization, OrganizationMember, RefreshToken, User

ACCESS_COOKIE = "aegis_access"
REFRESH_COOKIE = "aegis_refresh"

SessionDep = Annotated[AsyncSession, Depends(db_session)]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


async def current_user(request: Request, session: SessionDep) -> User:
    token = _bearer(request)
    if not token:
        raise Unauthenticated()
    claims = decode_access_token(token)
    user = await session.get(User, uuid.UUID(claims["sub"]))
    if user is None:
        raise Unauthenticated()
    await _require_live_session(session, claims)
    request.state.user_id = str(user.id)
    return user


async def _require_live_session(session: AsyncSession, claims: dict[str, Any]) -> None:
    """Rejects an access token whose session family has been revoked.

    The access token is a stateless JWT, so without this check `logout`, a
    password reset and refresh-reuse detection all only killed the *refresh*
    token -- an access token already in hand kept working for the rest of its
    TTL. "Every other session is signed out" has to be true the moment it is
    said, especially on a reset, which is what someone does when they believe
    their credentials were stolen.

    The `sid` claim is the refresh family id, and a family with no unrevoked row
    is a signed-out session. One indexed lookup per request buys the guarantee.
    """
    family = claims.get("sid")
    if not family:
        return
    try:
        family_id = uuid.UUID(str(family))
    except ValueError as exc:
        raise TokenInvalid() from exc
    live = await session.execute(
        select(RefreshToken.id)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .limit(1)
    )
    if live.first() is None:
        raise TokenInvalid(message="This session has been signed out.")


UserDep = Annotated[User, Depends(current_user)]


async def verified_user(user: UserDep) -> User:
    """Unverified accounts may sign in but cannot act.  Enforced here, not in the UI."""
    if user.email_verified_at is None:
        raise EmailNotVerified()
    return user


VerifiedUserDep = Annotated[User, Depends(verified_user)]


@dataclass(slots=True)
class Membership:
    user: User
    org: Organization
    role: OrgRole

    @property
    def org_id(self) -> uuid.UUID:
        return self.org.id

    def at_least(self, role: OrgRole) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


async def current_membership(request: Request, user: UserDep, session: SessionDep) -> Membership:
    """Resolves the active organization from the header, then the JWT, then the default."""
    header_org = request.headers.get("x-aegis-org")
    token = _bearer(request)
    claim_org = None
    if token:
        try:
            claim_org = decode_access_token(token).get("org")
        except Exception:
            claim_org = None

    candidates = [header_org, claim_org, str(user.active_org_id) if user.active_org_id else None]
    stmt = (
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.org_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.joined_at)
    )
    rows = list((await session.execute(stmt)).all())
    if not rows:
        raise Forbidden(
            code="NO_ORGANIZATION",
            message="Your account is not a member of any organization.",
        )
    by_id = {str(m.org_id): (m, o) for m, o in rows}
    for candidate in candidates:
        if candidate and candidate in by_id:
            member, org = by_id[candidate]
            request.state.org_id = str(org.id)
            return Membership(user=user, org=org, role=OrgRole(member.role))
    member, org = rows[0]
    request.state.org_id = str(org.id)
    return Membership(user=user, org=org, role=OrgRole(member.role))


MembershipDep = Annotated[Membership, Depends(current_membership)]


def require_role(minimum: OrgRole) -> Callable[[Membership], Awaitable[Membership]]:
    async def _guard(membership: MembershipDep) -> Membership:
        if not membership.at_least(minimum):
            raise Forbidden(
                details={"required_role": str(minimum), "your_role": str(membership.role)}
            )
        return membership

    return _guard


def require_verified_role(minimum: OrgRole) -> Callable[..., Awaitable[Membership]]:
    """Role floor *and* a verified email -- the combination every write path needs."""

    async def _guard(membership: MembershipDep) -> Membership:
        if membership.user.email_verified_at is None:
            raise EmailNotVerified()
        if not membership.at_least(minimum):
            raise Forbidden(
                details={"required_role": str(minimum), "your_role": str(membership.role)}
            )
        return membership

    return _guard


async def tenant_repo(membership: MembershipDep, session: SessionDep) -> TenantRepo:
    return TenantRepo(session, membership.org_id)


RepoDep = Annotated[TenantRepo, Depends(tenant_repo)]

# Convenience aliases used by the routers.
ViewerDep = Annotated[Membership, Depends(require_role(OrgRole.VIEWER))]
MemberDep = Annotated[Membership, Depends(require_verified_role(OrgRole.MEMBER))]
AdminDep = Annotated[Membership, Depends(require_verified_role(OrgRole.ADMIN))]
OwnerDep = Annotated[Membership, Depends(require_verified_role(OrgRole.OWNER))]


async def require_org_membership(
    session: AsyncSession, user: User, org_id: uuid.UUID
) -> OrganizationMember:
    stmt = select(OrganizationMember).where(
        OrganizationMember.user_id == user.id, OrganizationMember.org_id == org_id
    )
    member = (await session.execute(stmt)).scalar_one_or_none()
    if member is None:
        # 404, not 403: another tenant's organization must not be discoverable.
        raise NotFound(details={"type": "Organization", "id": str(org_id)})
    return member
