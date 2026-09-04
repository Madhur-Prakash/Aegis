"""Tenant-scoped repository layer.

I12 is architectural, not per-endpoint discipline.  Every read of a tenant-owned
entity goes through :class:`TenantRepo`, which *requires* an ``org_id`` and filters
on it.  A developer cannot forget the filter because there is no unscoped accessor
for these types, and a miss returns 404 -- never 403 -- so ids do not leak by
probing.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import NotFound
from app.models.commerce import (
    Artifact,
    Attestation,
    ChainAnchor,
    Deal,
    Dispute,
    EvidenceBundle,
    LedgerEvent,
    Milestone,
    Payout,
    SettlementAuthorization,
)
from app.models.identity import DealMessage, Entity, Notification, Organization

T = TypeVar("T")

# Two kinds of tenant ownership, and the distinction is load-bearing.
#
# 1. Rows that belong to exactly ONE organization -- its entities, its members'
#    notifications.  Scoped on their own ``org_id``.
#
# 2. Rows that belong to a DEAL, which has two parties.  Evidence, attestations,
#    payouts, ledger events and messages fall here.  Scoping these on the
#    submitting organization's ``org_id`` would be wrong in a way that breaks the
#    product: the seller uploads the evidence, and the buyer is precisely the
#    party who needs to read it.  They are scoped through the deal, which is
#    visible to the buyer org and the seller org and to nobody else.
_OWN_ORG: dict[Any, Any] = {
    Entity: Entity.org_id,
    Notification: Notification.org_id,
}

# model -> the chain of joins that reaches Deal, innermost first.
_VIA_DEAL: dict[Any, tuple[tuple[Any, Any], ...]] = {
    Milestone: ((Deal, Deal.id == Milestone.deal_id),),
    EvidenceBundle: (
        (Milestone, Milestone.id == EvidenceBundle.milestone_id),
        (Deal, Deal.id == Milestone.deal_id),
    ),
    Artifact: (
        (EvidenceBundle, EvidenceBundle.id == Artifact.bundle_id),
        (Milestone, Milestone.id == EvidenceBundle.milestone_id),
        (Deal, Deal.id == Milestone.deal_id),
    ),
    Attestation: (
        (Milestone, Milestone.id == Attestation.milestone_id),
        (Deal, Deal.id == Milestone.deal_id),
    ),
    Dispute: ((Deal, Deal.id == Dispute.deal_id),),
    LedgerEvent: ((Deal, Deal.id == LedgerEvent.deal_id),),
    DealMessage: ((Deal, Deal.id == DealMessage.deal_id),),
    Payout: ((Deal, Deal.id == Payout.deal_id),),
    SettlementAuthorization: ((Deal, Deal.id == SettlementAuthorization.deal_id),),
    ChainAnchor: ((Deal, Deal.id == ChainAnchor.deal_id),),
}


def deal_visibility(org_id: uuid.UUID) -> Any:
    """A deal is visible to the buyer org and to the seller org, and to nobody else."""
    return or_(Deal.org_id_buyer == org_id, Deal.org_id_seller == org_id)


class TenantRepo:
    """All tenant-owned reads and writes flow through here."""

    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        if org_id is None:
            raise ValueError("TenantRepo requires an org_id -- there is no unscoped variant")
        self.session = session
        self.org_id = org_id

    # ── generic ────────────────────────────────────────────────────────
    def scoped(self, model: type[T]) -> Select[tuple[T]]:
        stmt = select(model)
        if model is Deal:
            return stmt.where(deal_visibility(self.org_id))
        column = _OWN_ORG.get(model)
        if column is not None:
            return stmt.where(column == self.org_id)
        joins = _VIA_DEAL.get(model)
        if joins is not None:
            for target, condition in joins:
                stmt = stmt.join(target, condition)
            return stmt.where(deal_visibility(self.org_id))
        raise TypeError(
            f"{model.__name__} is not registered as tenant-owned. "
            "Register it in app/db/repo._OWN_ORG or _VIA_DEAL, or query it explicitly."
        )

    async def get_or_404(self, model: type[T], entity_id: uuid.UUID | str) -> T:
        stmt = self.scoped(model).where(model.id == entity_id)  # type: ignore[attr-defined]
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFound(details={"type": model.__name__, "id": str(entity_id)})
        return row

    async def count(self, model: type[T]) -> int:
        stmt = self.scoped(model).with_only_columns(func.count()).order_by(None)
        return int((await self.session.execute(stmt)).scalar() or 0)

    # ── deals ──────────────────────────────────────────────────────────
    async def get_deal(self, deal_id: uuid.UUID | str) -> Deal:
        return await self.get_or_404(Deal, deal_id)

    async def get_deal_for_update(self, deal_id: uuid.UUID | str) -> Deal:
        """Row-locks the deal.  Every settlement path takes this lock first."""
        stmt = (
            select(Deal).where(Deal.id == deal_id, deal_visibility(self.org_id)).with_for_update()
        )
        deal = (await self.session.execute(stmt)).scalar_one_or_none()
        if deal is None:
            raise NotFound(details={"type": "Deal", "id": str(deal_id)})
        return deal

    async def list_deals(self, limit: int = 50, cursor: str | None = None) -> list[Deal]:
        stmt = self.scoped(Deal).order_by(Deal.created_at.desc(), Deal.id.desc()).limit(limit)
        if cursor:
            stmt = stmt.where(Deal.created_at < cursor)
        return list((await self.session.execute(stmt)).scalars())

    # ── milestones (scoped through their parent deal) ───────────────────
    async def get_milestone(self, milestone_id: uuid.UUID | str) -> Milestone:
        return await self.get_or_404(Milestone, milestone_id)

    async def list_milestones(self, deal_id: uuid.UUID | str) -> list[Milestone]:
        stmt = self.scoped(Milestone).where(Milestone.deal_id == deal_id).order_by(Milestone.seq)
        return list((await self.session.execute(stmt)).scalars())

    # ── evidence ───────────────────────────────────────────────────────
    async def get_bundle(self, bundle_id: uuid.UUID | str) -> EvidenceBundle:
        return await self.get_or_404(EvidenceBundle, bundle_id)

    async def latest_bundle(self, milestone_id: uuid.UUID | str) -> EvidenceBundle | None:
        stmt = (
            self.scoped(EvidenceBundle)
            .where(EvidenceBundle.milestone_id == milestone_id)
            .order_by(EvidenceBundle.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_artifact(self, artifact_id: uuid.UUID | str) -> Artifact:
        return await self.get_or_404(Artifact, artifact_id)

    # ── attestations ───────────────────────────────────────────────────
    async def latest_attestation(self, milestone_id: uuid.UUID | str) -> Attestation | None:
        stmt = (
            self.scoped(Attestation)
            .where(Attestation.milestone_id == milestone_id)
            .order_by(Attestation.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_attestation(self, attestation_id: uuid.UUID | str) -> Attestation:
        return await self.get_or_404(Attestation, attestation_id)

    # ── disputes ───────────────────────────────────────────────────────
    async def get_dispute(self, dispute_id: uuid.UUID | str) -> Dispute:
        return await self.get_or_404(Dispute, dispute_id)

    # ── settlement / payouts (scoped through the deal) ──────────────────
    async def list_payouts(self, deal_id: uuid.UUID | str) -> list[Payout]:
        await self.get_deal(deal_id)  # 404 for a foreign deal, not an empty list
        stmt = self.scoped(Payout).where(Payout.deal_id == deal_id).order_by(Payout.created_at)
        return list((await self.session.execute(stmt)).scalars())

    async def list_authorizations(self, deal_id: uuid.UUID | str) -> list[SettlementAuthorization]:
        await self.get_deal(deal_id)
        stmt = (
            self.scoped(SettlementAuthorization)
            .where(SettlementAuthorization.deal_id == deal_id)
            .order_by(SettlementAuthorization.authorized_at)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_anchors(self, deal_id: uuid.UUID | str) -> list[ChainAnchor]:
        await self.get_deal(deal_id)
        stmt = (
            self.scoped(ChainAnchor)
            .where(ChainAnchor.deal_id == deal_id)
            .order_by(ChainAnchor.created_at)
        )
        return list((await self.session.execute(stmt)).scalars())

    # ── ledger ─────────────────────────────────────────────────────────
    async def list_ledger(self, deal_id: uuid.UUID | str) -> list[LedgerEvent]:
        await self.get_deal(deal_id)
        stmt = (
            self.scoped(LedgerEvent).where(LedgerEvent.deal_id == deal_id).order_by(LedgerEvent.seq)
        )
        return list((await self.session.execute(stmt)).scalars())

    # ── organization (the tenant itself) ───────────────────────────────
    async def organization(self) -> Organization:
        row = await self.session.get(Organization, self.org_id)
        if row is None:
            raise NotFound(details={"type": "Organization", "id": str(self.org_id)})
        return row
