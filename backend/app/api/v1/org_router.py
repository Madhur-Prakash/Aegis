"""/api/v1/organizations and /api/v1/entities."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.v1.schemas import (
    AcceptInviteIn,
    EntityIn,
    InviteIn,
    Ok,
    OrgIn,
    OrgOut,
    RoleIn,
)
from app.common.deps import (
    AdminDep,
    MembershipDep,
    OwnerDep,
    SessionDep,
    UserDep,
    VerifiedUserDep,
    ViewerDep,
)
from app.models.enums import OrgRole
from app.organizations import service as org_service

router = APIRouter(tags=["organizations"])


@router.get("/organizations", response_model=list[dict])
async def list_my_orgs(user: UserDep, session: SessionDep) -> list[dict]:
    return await org_service.my_organizations(session, user)


@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_org(payload: OrgIn, user: VerifiedUserDep, session: SessionDep) -> OrgOut:
    org = await org_service.create_organization(
        session, name=payload.name, owner=user, city=payload.city
    )
    await session.commit()
    return OrgOut(id=org.id, name=org.name, slug=org.slug, city=org.city, role=str(OrgRole.OWNER))


@router.get("/organizations/current", response_model=OrgOut)
async def current_org(membership: MembershipDep) -> OrgOut:
    return OrgOut(
        id=membership.org.id,
        name=membership.org.name,
        slug=membership.org.slug,
        city=membership.org.city,
        role=str(membership.role),
    )


@router.post("/organizations/{org_id}/switch", response_model=OrgOut)
async def switch(org_id: uuid.UUID, user: UserDep, session: SessionDep) -> OrgOut:
    org = await org_service.switch_active_org(session, user, org_id)
    await session.commit()
    return OrgOut(id=org.id, name=org.name, slug=org.slug, city=org.city)


@router.get("/organizations/members", response_model=list[dict])
async def members(membership: ViewerDep, session: SessionDep) -> list[dict]:
    return await org_service.list_members(session, membership.org_id)


@router.post("/organizations/invitations", response_model=dict, status_code=201)
async def create_invite(payload: InviteIn, membership: AdminDep, session: SessionDep) -> dict:
    invitation, raw = await org_service.invite(
        session,
        org_id=membership.org_id,
        email=str(payload.email),
        role=payload.role,
        inviter=membership.user,
    )
    await session.commit()
    from app.config.settings import settings

    body = {
        "id": str(invitation.id),
        "email": invitation.email,
        "role": str(invitation.role),
        "expires_at": invitation.expires_at,
    }
    # The raw token is echoed only in DEMO_MODE, so the demo can accept an invite
    # without opening Mailpit.  It is never returned in a real deployment.
    if settings.DEMO_MODE:
        body["accept_token"] = raw
    return body


@router.get("/organizations/invitations", response_model=list[dict])
async def invitations(membership: AdminDep, session: SessionDep) -> list[dict]:
    return await org_service.list_invitations(session, membership.org_id)


@router.post("/organizations/invitations/accept", response_model=OrgOut)
async def accept_invite(
    payload: AcceptInviteIn, user: VerifiedUserDep, session: SessionDep
) -> OrgOut:
    org = await org_service.accept_invitation(session, raw_token=payload.token, user=user)
    await session.commit()
    return OrgOut(id=org.id, name=org.name, slug=org.slug, city=org.city)


@router.patch("/organizations/members/{user_id}/role", response_model=dict)
async def change_role(
    user_id: uuid.UUID, payload: RoleIn, membership: AdminDep, session: SessionDep
) -> dict:
    result = await org_service.change_role(
        session,
        org_id=membership.org_id,
        target_user_id=user_id,
        new_role=payload.role,
        actor_user_id=membership.user.id,
        actor_role=membership.role,
    )
    await session.commit()
    return result


@router.delete("/organizations/members/{user_id}", response_model=Ok)
async def remove_member(user_id: uuid.UUID, membership: AdminDep, session: SessionDep) -> Ok:
    await org_service.remove_member(
        session,
        org_id=membership.org_id,
        target_user_id=user_id,
        actor_user_id=membership.user.id,
    )
    await session.commit()
    return Ok()


@router.post("/organizations/transfer-ownership/{user_id}", response_model=Ok)
async def transfer(user_id: uuid.UUID, membership: OwnerDep, session: SessionDep) -> Ok:
    await org_service.transfer_ownership(
        session, org_id=membership.org_id, from_user_id=membership.user.id, to_user_id=user_id
    )
    await session.commit()
    return Ok()


@router.delete("/organizations/current", response_model=Ok)
async def delete_org(membership: OwnerDep, session: SessionDep) -> Ok:
    await org_service.delete_organization(session, membership.org_id)
    await session.commit()
    return Ok()


# ── Entities ────────────────────────────────────────────────────────────────
@router.get("/entities", response_model=list[dict])
async def list_entities(membership: ViewerDep, session: SessionDep) -> list[dict]:
    from app.db.repo import TenantRepo
    from app.models.identity import Entity

    repo = TenantRepo(session, membership.org_id)
    rows = list((await session.execute(repo.scoped(Entity))).scalars())
    return [
        {
            "id": str(e.id),
            "kind": str(e.kind),
            "display_name": e.display_name,
            "region": e.region,
            "created_at": e.created_at,
        }
        for e in rows
    ]


@router.post("/entities", response_model=dict, status_code=201)
async def create_entity(payload: EntityIn, membership: AdminDep, session: SessionDep) -> dict:
    entity = await org_service.create_entity(
        session,
        org_id=membership.org_id,
        kind=payload.kind,
        display_name=payload.display_name,
        region=payload.region,
    )
    await session.commit()
    return {"id": str(entity.id), "kind": str(entity.kind), "display_name": entity.display_name}
