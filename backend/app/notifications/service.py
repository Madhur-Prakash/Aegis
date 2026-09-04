"""Notification fan-out.  Kafka ``aegis.notifications`` is the async source."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.logging import get_logger
from app.config.settings import settings
from app.models.enums import NotificationKind
from app.models.identity import (
    Notification,
    NotificationPreference,
    Organization,
    OrganizationMember,
    User,
)
from app.notifications.email import get_email_provider, render

log = get_logger("notifications")

_TITLES: dict[str, str] = {
    NotificationKind.DEAL_CREATED: "Deal created",
    NotificationKind.TERMS_SIGNED: "Terms signed",
    NotificationKind.DEAL_FUNDED: "Escrow funded",
    NotificationKind.EVIDENCE_SUBMITTED: "Evidence submitted",
    NotificationKind.VERIFICATION_COMPLETED: "Verification completed",
    NotificationKind.HUMAN_REVIEW_REQUIRED: "Human review required",
    NotificationKind.DISPUTE_RAISED: "Dispute raised",
    NotificationKind.DISPUTE_RESOLVED: "Dispute resolved",
    NotificationKind.PAYOUT_COMPLETED: "Payout completed",
    NotificationKind.PAYOUT_FAILED: "Payout failed",
    NotificationKind.INVITATION_RECEIVED: "Organization invitation",
    NotificationKind.MESSAGE_RECEIVED: "New message",
}

EMAIL_BY_DEFAULT = frozenset(
    {
        str(NotificationKind.HUMAN_REVIEW_REQUIRED),
        str(NotificationKind.DISPUTE_RAISED),
        str(NotificationKind.PAYOUT_FAILED),
        str(NotificationKind.INVITATION_RECEIVED),
    }
)


def _body(kind: str, payload: dict[str, Any]) -> str:
    reference = payload.get("deal_reference") or payload.get("deal_id", "")
    seq = payload.get("milestone_seq")
    milestone = f" milestone {seq:02d}" if isinstance(seq, int) else ""
    if kind == str(NotificationKind.VERIFICATION_COMPLETED):
        return (
            f"{reference}{milestone}: the verifier returned {payload.get('decision')} "
            f"at confidence {payload.get('confidence')}."
        )
    if kind == str(NotificationKind.HUMAN_REVIEW_REQUIRED):
        clauses = ", ".join(payload.get("unverifiable") or []) or "one or more clauses"
        return (
            f"{reference}{milestone} was escalated at confidence {payload.get('confidence')}. "
            f"The verifier could not verify: {clauses}."
        )
    if kind == str(NotificationKind.PAYOUT_COMPLETED):
        return (
            f"{reference}{milestone}: {payload.get('direction')} of "
            f"{int(payload.get('amount_paise') or 0) / 100:.2f} INR settled."
        )
    if kind == str(NotificationKind.PAYOUT_FAILED):
        return f"{reference}{milestone}: the payout failed ({payload.get('reason')})."
    if kind == str(NotificationKind.DEAL_FUNDED):
        return f"{reference}: escrow funded with {int(payload.get('funded_paise') or 0) / 100:.2f} INR."
    if kind == str(NotificationKind.DISPUTE_RAISED):
        return f"{reference}{milestone}: a dispute was raised."
    if kind == str(NotificationKind.DISPUTE_RESOLVED):
        return (
            f"{reference}{milestone}: resolved -- release "
            f"{int(payload.get('release_paise') or 0) / 100:.2f} INR, refund "
            f"{int(payload.get('refund_paise') or 0) / 100:.2f} INR."
        )
    if kind == str(NotificationKind.MESSAGE_RECEIVED):
        return f"{reference}: new message from {payload.get('sender_name', 'the counterparty')}."
    return f"{reference}{milestone}: {kind.replace('_', ' ').lower()}."


async def fan_out(session: AsyncSession, payload: dict[str, Any]) -> int:
    """Creates one in-app notification per member of both organizations."""
    kind = str(payload.get("kind"))
    org_ids = [
        payload.get("org_id_buyer"),
        payload.get("org_id_seller"),
    ]
    targets: list[tuple[uuid.UUID, User]] = []
    for raw in org_ids:
        if not raw:
            continue
        org_id = uuid.UUID(str(raw))
        rows = list(
            (
                await session.execute(
                    select(OrganizationMember, User)
                    .join(User, User.id == OrganizationMember.user_id)
                    .where(OrganizationMember.org_id == org_id)
                )
            ).all()
        )
        targets.extend((org_id, user) for _, user in rows)

    title = _TITLES.get(kind, kind.replace("_", " ").title())
    body = _body(kind, payload)
    created = 0
    for org_id, user in targets:
        session.add(
            Notification(
                org_id=org_id,
                user_id=user.id,
                kind=kind,
                title=title,
                body=body,
                deal_id=uuid.UUID(str(payload["deal_id"])) if payload.get("deal_id") else None,
            )
        )
        created += 1
        if await _wants_email(session, user.id, kind):
            link = f"{settings.PUBLIC_APP_URL}/deals/{payload.get('deal_id')}"
            if kind == str(NotificationKind.HUMAN_REVIEW_REQUIRED):
                get_email_provider().send(
                    render(
                        "human_review_required",
                        user.email,
                        deal=payload.get("deal_reference", ""),
                        milestone=payload.get("milestone_seq"),
                        unverifiable="\n".join(payload.get("unverifiable") or []),
                        link=f"{settings.PUBLIC_APP_URL}/review",
                    )
                )
            elif kind == str(NotificationKind.DISPUTE_RAISED):
                get_email_provider().send(
                    render(
                        "dispute_raised",
                        user.email,
                        deal=payload.get("deal_reference", ""),
                        milestone=payload.get("milestone_seq"),
                        claim=payload.get("claim", ""),
                        link=link,
                    )
                )
    await session.flush()
    log.info("notifications fanned out", extra={"kind": kind, "recipients": created})
    return created


async def _wants_email(session: AsyncSession, user_id: uuid.UUID, kind: str) -> bool:
    pref = (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if pref is not None:
        return bool(pref.email)
    return kind in EMAIL_BY_DEFAULT


async def list_notifications(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, *, limit: int = 50
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id, Notification.org_id == org_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def unread_count(session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> int:
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.org_id == org_id,
            Notification.read_at.is_(None),
        )
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, ids: list[uuid.UUID] | None
) -> int:
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.org_id == org_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=dt.datetime.now(dt.UTC))
    )
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def set_preference(
    session: AsyncSession, user_id: uuid.UUID, kind: str, *, in_app: bool, email: bool
) -> NotificationPreference:
    pref = (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id, NotificationPreference.kind == kind
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user_id, kind=kind, in_app=in_app, email=email)
        session.add(pref)
    else:
        pref.in_app = in_app
        pref.email = email
    await session.flush()
    return pref


async def default_preferences(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    existing = {
        p.kind: p
        for p in (
            await session.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == user_id)
            )
        ).scalars()
    }
    out = []
    for kind in NotificationKind:
        pref = existing.get(str(kind))
        out.append(
            {
                "kind": str(kind),
                "title": _TITLES.get(kind, str(kind)),
                "in_app": bool(pref.in_app) if pref else True,
                "email": bool(pref.email) if pref else str(kind) in EMAIL_BY_DEFAULT,
            }
        )
    return out


async def organization_name(session: AsyncSession, org_id: uuid.UUID) -> str:
    org = await session.get(Organization, org_id)
    return org.name if org else str(org_id)
