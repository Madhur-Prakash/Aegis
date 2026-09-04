"""Organizations, memberships, invitations, last-owner protection."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_token, normalize_email
from app.common.errors import Conflict, LastOwnerProtected, NotFound, ValidationFailed
from app.common.ids import url_token
from app.common.logging import get_logger
from app.config.settings import settings
from app.models.enums import ROLE_RANK, EntityKind, OrgRole
from app.models.identity import (
    AuditRecord,
    Entity,
    Invitation,
    Organization,
    OrganizationMember,
    User,
)
from app.notifications.email import get_email_provider, render

log = get_logger("organizations")

INVITE_TTL = dt.timedelta(days=7)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100] or "org"


async def create_organization(
    session: AsyncSession,
    *,
    name: str,
    owner: User,
    city: str | None = None,
    org_id: uuid.UUID | None = None,
) -> Organization:
    base = slugify(name)
    slug = base
    suffix = 1
    while (
        await session.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
    org = Organization(id=org_id or uuid.uuid4(), name=name.strip(), slug=slug, city=city)
    session.add(org)
    await session.flush()
    session.add(OrganizationMember(org_id=org.id, user_id=owner.id, role=OrgRole.OWNER))
    if owner.active_org_id is None:
        owner.active_org_id = org.id
    session.add(
        AuditRecord(
            org_id=org.id,
            actor_user_id=owner.id,
            action="organization.created",
            target_type="Organization",
            target_id=str(org.id),
            meta_json={"name": org.name, "slug": org.slug},
        )
    )
    await session.flush()
    log.info("organization created", extra={"org_id": str(org.id), "slug": org.slug})
    return org


async def create_entity(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: EntityKind | str,
    display_name: str,
    region: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> Entity:
    entity = Entity(
        id=entity_id or uuid.uuid4(),
        org_id=org_id,
        kind=EntityKind(str(kind)),
        display_name=display_name,
        region=region,
        onboarded_at=dt.datetime.now(dt.UTC),
    )
    session.add(entity)
    await session.flush()
    return entity


async def list_members(session: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                select(OrganizationMember, User)
                .join(User, User.id == OrganizationMember.user_id)
                .where(OrganizationMember.org_id == org_id)
                .order_by(OrganizationMember.joined_at)
            )
        ).all()
    )
    return [
        {
            "user_id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": str(member.role),
            "verified": user.email_verified_at is not None,
            "joined_at": member.joined_at,
        }
        for member, user in rows
    ]


async def owner_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(OrganizationMember)
        .where(OrganizationMember.org_id == org_id, OrganizationMember.role == OrgRole.OWNER)
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def change_role(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    new_role: OrgRole | str,
    actor_user_id: uuid.UUID,
    actor_role: OrgRole,
) -> dict[str, Any]:
    new_role = OrgRole(str(new_role))
    member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFound(details={"type": "OrganizationMember", "user_id": str(target_user_id)})
    if new_role == OrgRole.OWNER and ROLE_RANK[actor_role] < ROLE_RANK[OrgRole.OWNER]:
        raise Conflict(
            code="OWNER_GRANT_REQUIRES_OWNER",
            message="Only an owner can grant ownership.",
        )
    if (
        member.role == OrgRole.OWNER
        and new_role != OrgRole.OWNER
        and await owner_count(session, org_id) <= 1
    ):
        raise LastOwnerProtected()
    previous = str(member.role)
    member.role = new_role
    session.add(
        AuditRecord(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action="organization.role_changed",
            target_type="User",
            target_id=str(target_user_id),
            meta_json={"from": previous, "to": str(new_role)},
        )
    )
    await session.flush()
    log.info(
        "role changed",
        extra={
            "org_id": str(org_id),
            "user_id": str(target_user_id),
            "from": previous,
            "to": str(new_role),
        },
    )
    return {"user_id": str(target_user_id), "role": str(new_role), "previous_role": previous}


async def remove_member(
    session: AsyncSession, *, org_id: uuid.UUID, target_user_id: uuid.UUID, actor_user_id: uuid.UUID
) -> None:
    member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFound(details={"type": "OrganizationMember", "user_id": str(target_user_id)})
    if member.role == OrgRole.OWNER and await owner_count(session, org_id) <= 1:
        raise LastOwnerProtected()
    await session.delete(member)
    session.add(
        AuditRecord(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action="organization.member_removed",
            target_type="User",
            target_id=str(target_user_id),
            meta_json={},
        )
    )
    await session.flush()


async def invite(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
    role: OrgRole | str,
    inviter: User,
) -> tuple[Invitation, str]:
    role = OrgRole(str(role))
    if role == OrgRole.OWNER:
        raise ValidationFailed(
            code="CANNOT_INVITE_OWNER",
            message="Invite as ADMIN or below, then transfer ownership deliberately.",
        )
    normalized = normalize_email(email)
    existing_user = (
        await session.execute(select(User).where(User.email_normalized == normalized))
    ).scalar_one_or_none()
    if existing_user is not None:
        already = (
            await session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.org_id == org_id,
                    OrganizationMember.user_id == existing_user.id,
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            raise Conflict(
                code="ALREADY_A_MEMBER", message="That person is already in this organization."
            )
    raw = url_token(32)
    invitation = Invitation(
        org_id=org_id,
        email=email.strip(),
        role=role,
        token_hash=hash_token(raw),
        expires_at=dt.datetime.now(dt.UTC) + INVITE_TTL,
        invited_by=inviter.id,
    )
    session.add(invitation)
    await session.flush()
    org = await session.get(Organization, org_id)
    get_email_provider().send(
        render(
            "org_invitation",
            invitation.email,
            inviter=inviter.name,
            org=org.name if org else str(org_id),
            role=str(role),
            link=f"{settings.PUBLIC_APP_URL}/invitations/accept?token={raw}",
        )
    )
    log.info("invitation issued", extra={"org_id": str(org_id), "role": str(role)})
    return invitation, raw


async def accept_invitation(session: AsyncSession, *, raw_token: str, user: User) -> Organization:
    invitation = (
        await session.execute(
            select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
        )
    ).scalar_one_or_none()
    if invitation is None or invitation.accepted_at is not None:
        from app.common.errors import TokenInvalid

        raise TokenInvalid(message="That invitation is not valid.")
    if invitation.expires_at <= dt.datetime.now(dt.UTC):
        from app.common.errors import TokenInvalid

        raise TokenInvalid(message="That invitation has expired.")
    if normalize_email(invitation.email) != user.email_normalized:
        raise Conflict(
            code="INVITATION_EMAIL_MISMATCH",
            message="This invitation was issued to a different email address.",
        )
    existing = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == invitation.org_id,
                OrganizationMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            OrganizationMember(org_id=invitation.org_id, user_id=user.id, role=invitation.role)
        )
    invitation.accepted_at = dt.datetime.now(dt.UTC)
    if user.active_org_id is None:
        user.active_org_id = invitation.org_id
    await session.flush()
    org = await session.get(Organization, invitation.org_id)
    if org is None:
        raise NotFound(details={"type": "Organization"})
    log.info("invitation accepted", extra={"org_id": str(org.id), "user_id": str(user.id)})
    return org


async def list_invitations(session: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                select(Invitation)
                .where(Invitation.org_id == org_id)
                .order_by(Invitation.created_at.desc())
            )
        ).scalars()
    )
    return [
        {
            "id": str(r.id),
            "email": r.email,
            "role": str(r.role),
            "accepted": r.accepted_at is not None,
            "expires_at": r.expires_at,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def switch_active_org(session: AsyncSession, user: User, org_id: uuid.UUID) -> Organization:
    member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id, OrganizationMember.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFound(details={"type": "Organization", "id": str(org_id)})
    user.active_org_id = org_id
    await session.flush()
    org = await session.get(Organization, org_id)
    assert org is not None
    return org


async def my_organizations(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                select(OrganizationMember, Organization)
                .join(Organization, Organization.id == OrganizationMember.org_id)
                .where(OrganizationMember.user_id == user.id)
                .order_by(OrganizationMember.joined_at)
            )
        ).all()
    )
    return [
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "city": org.city,
            "role": str(member.role),
            "active": org.id == user.active_org_id,
        }
        for member, org in rows
    ]


async def delete_organization(session: AsyncSession, org_id: uuid.UUID) -> None:
    from sqlalchemy import or_

    from app.models.commerce import Deal

    deals = (
        await session.execute(
            select(func.count())
            .select_from(Deal)
            .where(or_(Deal.org_id_buyer == org_id, Deal.org_id_seller == org_id))
        )
    ).scalar() or 0
    if int(deals) > 0:
        raise Conflict(
            code="ORGANIZATION_HAS_DEALS",
            message="An organization with deals cannot be deleted; its ledger must survive.",
            details={"deal_count": int(deals)},
        )
    org = await session.get(Organization, org_id)
    if org is None:
        raise NotFound(details={"type": "Organization", "id": str(org_id)})
    await session.delete(org)
    await session.flush()


async def transfer_ownership(
    session: AsyncSession, *, org_id: uuid.UUID, from_user_id: uuid.UUID, to_user_id: uuid.UUID
) -> None:
    await change_role(
        session,
        org_id=org_id,
        target_user_id=to_user_id,
        new_role=OrgRole.OWNER,
        actor_user_id=from_user_id,
        actor_role=OrgRole.OWNER,
    )
    await change_role(
        session,
        org_id=org_id,
        target_user_id=from_user_id,
        new_role=OrgRole.ADMIN,
        actor_user_id=from_user_id,
        actor_role=OrgRole.OWNER,
    )
