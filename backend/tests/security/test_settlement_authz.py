"""Who is allowed to move the money, and who is allowed to shape the evidence.

Tenant isolation (I12) answers "may this organization see the deal at all".  It
does not answer "which *side* of the deal may take this action", and both parties
to a deal legitimately see the same milestone.  The two holes here were both on
that second question:

* an admin of the **selling** organization could approve the human review of
  their own escalated milestone and release the buyer's escrow to themselves;
* the **buying** organization could add artifacts to the seller's open evidence
  bundle, poisoning the set the verifier reads.

Both are the adversaries named at the top of docs/SECURITY.md, reaching the
outcome that document says they cannot.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager  # type: ignore[import-not-found]
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.commerce import Milestone
from tests.conftest import requires_db
from tests.factories import make_deal, submit_evidence, verify_milestone

pytestmark = requires_db


@pytest.fixture
async def client() -> Any:
    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def buyer(client: httpx.AsyncClient, parties: dict[str, Any]) -> dict[str, str]:
    return await _login(client, "buyer@aegistest.dev", parties["password"])


@pytest.fixture
async def seller(client: httpx.AsyncClient, parties: dict[str, Any]) -> dict[str, str]:
    return await _login(client, "seller@aegistest.dev", parties["password"])


async def _escalated_milestone(parties: dict[str, Any]) -> tuple[Any, Any]:
    """Milestone 2 of the demo deal reaches UNDER_HUMAN_REVIEW on its own.

    Through the ordinary pipeline: photographs cannot establish a unit count, so
    the clause comes back required-UNVERIFIABLE and I3 escalates it.
    """
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m2 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 2)
            )
        ).scalar_one()
        bundle = await submit_evidence(
            session,
            deal,
            m2,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        await verify_milestone(session, deal, m2, bundle)
        assert str(m2.state) == "UNDER_HUMAN_REVIEW"
        return deal.id, m2.id


# ── the seller cannot sign off their own release ────────────────────────────
@pytest.mark.asyncio
async def test_the_seller_cannot_approve_the_release_of_their_own_milestone(
    client, seller, parties
):
    """The dishonest-seller path, end to end.

    The seller is an OWNER of their own organization, so `AdminDep` is satisfied.
    The milestone is theirs and visible to them, so the tenant repo is satisfied.
    `authorize_release` accepts any human approval of an ESCALATE by design --
    that is what human review *is*.  Nothing but the acting side is left to stop
    a seller submitting evidence they know is ambiguous, waiting for the
    escalation, and then paying themselves.
    """
    _deal_id, milestone_id = await _escalated_milestone(parties)

    response = await client.post(
        f"/api/v1/milestones/{milestone_id}/human-review",
        headers=seller,
        json={"action": "APPROVE", "reason": "Approving my own release, thanks."},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "ONLY_BUYER_APPROVES_RELEASE"


@pytest.mark.asyncio
async def test_no_authorization_and_no_payout_follow_the_refused_approval(
    client, seller, buyer, parties
):
    """The refusal has to be a refusal, not a 403 after the row is written."""
    deal_id, milestone_id = await _escalated_milestone(parties)

    await client.post(
        f"/api/v1/milestones/{milestone_id}/human-review",
        headers=seller,
        json={"action": "APPROVE", "reason": "Approving my own release, thanks."},
    )

    authorizations = await client.get(f"/api/v1/settlements/deals/{deal_id}", headers=buyer)
    assert authorizations.status_code == 200
    assert authorizations.json() == []

    payouts = await client.get(f"/api/v1/payments/deals/{deal_id}/payouts", headers=buyer)
    assert payouts.status_code == 200
    assert payouts.json() == []

    deal = await client.get(f"/api/v1/deals/{deal_id}", headers=buyer)
    assert deal.json()["money"]["released_paise"] == 0


@pytest.mark.asyncio
async def test_the_buyer_can_still_approve(client, buyer, parties):
    """The fix must not cost the flow it exists to protect."""
    _deal_id, milestone_id = await _escalated_milestone(parties)

    response = await client.post(
        f"/api/v1/milestones/{milestone_id}/human-review",
        headers=buyer,
        json={"action": "APPROVE", "reason": "Counted on site against the manifest."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["authorized"] is True


@pytest.mark.asyncio
async def test_the_seller_may_still_reject_because_a_reject_moves_no_money(client, seller, parties):
    """Withdrawing your own submission is not the thing being defended against."""
    _deal_id, milestone_id = await _escalated_milestone(parties)

    response = await client.post(
        f"/api/v1/milestones/{milestone_id}/human-review",
        headers=seller,
        json={"action": "REJECT", "reason": "Our own photographs are not good enough."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["authorized"] is False


# ── the buyer cannot put artifacts in the seller's bundle ───────────────────
@pytest.mark.asyncio
async def test_the_buyer_cannot_upload_into_the_sellers_evidence_bundle(client, buyer, parties):
    """`get_or_create_open_bundle` returns the milestone's open bundle to whoever
    asks, so without a side check the buyer's upload joins the seller's evidence
    and is hashed into the same Merkle root."""
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        milestone_id = m1.id

    response = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/upload",
        headers=buyer,
        data={"artifact_type": "INVOICE"},
        files={
            "file": ("planted.pdf", b"%PDF-1.7 Total: 1\nline items sum to 999", "application/pdf")
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "ONLY_SELLER_SUBMITS_EVIDENCE"

    bundle = await client.get(f"/api/v1/evidence/milestones/{milestone_id}/bundle", headers=buyer)
    assert bundle.status_code == 200
    assert bundle.json() is None, "the refused upload must not have created a bundle"


@pytest.mark.asyncio
async def test_the_buyer_cannot_submit_the_sellers_bundle(client, buyer, seller, parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        milestone_id = m1.id

    uploaded = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/upload",
        headers=seller,
        data={"artifact_type": "INVOICE"},
        files={"file": ("invoice.pdf", b"%PDF-1.7 Invoice No: 1\nTotal: 100", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text

    response = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/submit", headers=buyer
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ONLY_SELLER_SUBMITS_EVIDENCE"


@pytest.mark.asyncio
async def test_the_seller_can_still_upload_and_submit(client, seller, parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        milestone_id = m1.id

    uploaded = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/upload",
        headers=seller,
        data={"artifact_type": "INVOICE"},
        files={"file": ("invoice.pdf", b"%PDF-1.7 Invoice No: 1\nTotal: 100", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text

    submitted = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/submit", headers=seller
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["merkle_root"] != "0" * 64


@pytest.mark.asyncio
async def test_an_outsider_still_gets_404_and_not_403(client, parties):
    """The side check must not turn a tenant-isolation 404 into an existence oracle."""
    outsider = await _login(client, "outsider@aegistest.dev", parties["password"])
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        milestone_id = m1.id

    response = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/upload",
        headers=outsider,
        data={"artifact_type": "INVOICE"},
        files={"file": ("x.pdf", b"%PDF-1.7 hello", "application/pdf")},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
