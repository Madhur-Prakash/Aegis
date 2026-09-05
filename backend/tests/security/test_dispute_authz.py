"""A dispute resolution decides where escrowed money goes, so it needs a side.

This is the sharper twin of the human-review hole in `test_settlement_authz.py`,
and it bypasses more: `REJECTED` is a disputable milestone state, so a seller
whose evidence the verifier **rejected** could raise a dispute on their own
milestone and have their own admin resolve it entirely in their own favour.  No
buyer involvement, no qualifying RELEASE attestation, and the verifier's REJECT
simply routed around.

`resolve_dispute` already refuses a non-admin, and I8 already refuses a
settlement with no `human_decided_by`.  Neither says *whose* human it has to be.
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


async def _rejected_milestone(parties: dict[str, Any]) -> tuple[Any, Any, int]:
    """A milestone the verifier genuinely REJECTED, and its amount.

    Submitting the production photo set against the fabric milestone omits both
    required artifact types, so the deterministic pre-checks reject it before a
    single token is spent.  `REJECTED` is a disputable state -- which is the
    doorway.
    """
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        bundle = await submit_evidence(
            session,
            deal,
            m1,
            org_id=parties["seller_org_id"],
            user_id=parties["seller_user_id"],
            folder="production",
        )
        _attestation, output = await verify_milestone(session, deal, m1, bundle)
        assert output.decision == "REJECT"
        assert str(m1.state) == "REJECTED"
        return deal.id, m1.id, int(m1.amount_paise)


@pytest.mark.asyncio
async def test_a_seller_cannot_resolve_their_own_dispute_in_their_own_favour(
    client, seller, buyer, parties
):
    deal_id, milestone_id, amount = await _rejected_milestone(parties)

    raised = await client.post(
        f"/api/v1/milestones/{milestone_id}/disputes",
        headers=seller,
        json={"claim": "We say the goods were delivered as agreed."},
    )
    assert raised.status_code == 201, raised.text
    dispute_id = raised.json()["id"]

    resolved = await client.post(
        f"/api/v1/disputes/{dispute_id}/resolve",
        headers=seller,
        json={
            "release_paise": amount,
            "refund_paise": 0,
            "reason": "Resolving our own dispute in our own favour.",
        },
    )
    assert resolved.status_code == 403, resolved.text
    assert resolved.json()["error"]["code"] == "ONLY_BUYER_APPROVES_RELEASE"

    # And nothing moved.
    authorizations = await client.get(f"/api/v1/settlements/deals/{deal_id}", headers=buyer)
    assert authorizations.json() == []
    deal = await client.get(f"/api/v1/deals/{deal_id}", headers=buyer)
    assert deal.json()["money"]["released_paise"] == 0


@pytest.mark.asyncio
async def test_the_buyer_can_still_resolve_a_dispute_with_a_split(client, buyer, seller, parties):
    """The demo resolves milestone 3 with a genuine split; that has to keep working."""
    _deal_id, milestone_id, amount = await _rejected_milestone(parties)

    raised = await client.post(
        f"/api/v1/milestones/{milestone_id}/disputes",
        headers=buyer,
        json={"claim": "Sixty units arrived in a condition we did not accept."},
    )
    assert raised.status_code == 201, raised.text
    dispute_id = raised.json()["id"]

    release = amount * 4 // 5
    resolved = await client.post(
        f"/api/v1/disputes/{dispute_id}/resolve",
        headers=buyer,
        json={
            "release_paise": release,
            "refund_paise": amount - release,
            "reason": "Accepted the tolerance deduction on the sixty units.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["release_paise"] == release


@pytest.mark.asyncio
async def test_a_seller_may_still_concede_a_dispute_entirely(client, seller, parties):
    """A resolution that releases nothing pays the seller nothing, so conceding
    is not the self-dealing this refuses."""
    _deal_id, milestone_id, amount = await _rejected_milestone(parties)

    raised = await client.post(
        f"/api/v1/milestones/{milestone_id}/disputes",
        headers=seller,
        json={"claim": "Raising this so the record shows what happened."},
    )
    dispute_id = raised.json()["id"]

    resolved = await client.post(
        f"/api/v1/disputes/{dispute_id}/resolve",
        headers=seller,
        json={
            "release_paise": 0,
            "refund_paise": amount,
            "reason": "We accept that this shipment did not meet the condition.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["refund_paise"] == amount
