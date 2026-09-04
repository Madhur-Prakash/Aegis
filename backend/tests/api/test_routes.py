"""Every route, happy path and typed error (I9)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager  # type: ignore[import-not-found]
from sqlalchemy import select

from app.config.settings import settings
from app.db.session import get_session_factory
from app.models.commerce import Milestone
from tests.conftest import requires_db
from tests.factories import drain_outbox, make_deal, submit_evidence, verify_milestone

pytestmark = requires_db


@pytest.fixture
async def client() -> Any:
    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest.fixture
async def buyer(client: httpx.AsyncClient, parties: dict[str, Any]) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "buyer@aegistest.dev", "password": parties["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def seller(client: httpx.AsyncClient, parties: dict[str, Any]) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "seller@aegistest.dev", "password": parties["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ── the typed error envelope (I9) ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_every_error_uses_the_typed_envelope(client, buyer):
    response = await client.get(f"/api/v1/deals/{uuid.uuid4()}", headers=buyer)
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "request_id"}
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"].startswith("req_")


@pytest.mark.asyncio
async def test_a_business_failure_is_never_a_bare_500(client, buyer, parties):
    """A confidence-threshold refusal comes back as a typed 409 with the numbers."""
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
        milestone_id = m2.id

    # An escalated milestone cannot be verified again.
    response = await client.post(f"/api/v1/milestones/{milestone_id}/start-verify", headers=buyer)
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] in {"ILLEGAL_TRANSITION", "VERIFICATION_IN_PROGRESS"}
    assert body["message"]
    assert body["request_id"]


@pytest.mark.asyncio
async def test_a_request_id_is_echoed_on_every_response(client, buyer):
    response = await client.get("/api/v1/deals", headers=buyer)
    assert response.headers["x-request-id"].startswith("req_")
    supplied = await client.get(
        "/api/v1/deals", headers={**buyer, "x-request-id": "req_supplied_by_caller"}
    )
    assert supplied.headers["x-request-id"] == "req_supplied_by_caller"


@pytest.mark.asyncio
async def test_a_validation_failure_lists_the_fields(client, buyer):
    response = await client.post(
        "/api/v1/deals", headers=buyer, json={"title": "", "total_paise": -1, "milestones": []}
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_FAILED"
    assert body["details"]["errors"]


# ── health and disclosure ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_liveness_and_readiness(client):
    live = await client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.json()["ok"] is True

    ready = await client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["ok"] is True
    for dependency in ("postgres", "redis", "kafka", "object_store", "chain_rpc", "payment_rail"):
        assert dependency in body["checks"]
        assert "ready" in body["checks"][dependency]
    assert body["ai_provider"] in {"fixture", "anthropic", "groq"}


@pytest.mark.asyncio
async def test_a_degraded_dependency_is_reported_not_hidden(client):
    ready = (await client.get("/api/v1/health/ready")).json()
    # The chain is disabled in tests, so it must appear as degraded with a reason.
    chain = ready["checks"]["chain_rpc"]
    assert chain["ready"] is False
    assert chain["required"] is False
    assert chain["reason"]
    assert "chain_rpc" in ready["degraded"]


@pytest.mark.asyncio
async def test_the_rail_disclosure_is_honest(client):
    response = await client.get("/api/v1/payments/rail")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "SIMULATED"
    for operation, label in body["operations"].items():
        assert label in {"REAL TEST MODE", "SIMULATED"}, operation
    # With no Razorpay credentials configured, nothing may claim to be real.
    assert set(body["operations"].values()) == {"SIMULATED"}


@pytest.mark.asyncio
async def test_the_openapi_document_is_served(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "Aegis"
    assert "/api/v1/deals" in document["paths"]
    assert "/api/v1/milestones/{milestone_id}/start-verify" in document["paths"]


# ── the deal lifecycle over HTTP ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_sign_fund_and_read_a_deal(client, buyer, parties):
    from app.models.identity import Organization

    async with get_session_factory()() as session:
        seller_org = await session.get(Organization, parties["seller_org_id"])
        slug = seller_org.slug

    created = await client.post(
        "/api/v1/deals",
        headers=buyer,
        json={
            "title": "500 custom kurtas",
            "seller_org_slug": slug,
            "total_paise": 42_000_000,
            "dispute_window_days": 7,
            "category": "apparel",
            "tolerance": {
                "total_units": 500,
                "unit_price_paise": 84_000,
                "variance_deduction_pct": 20,
            },
            "milestones": [
                {
                    "seq": 1,
                    "title": "Fabric procured",
                    "amount_paise": 42_000_000,
                    "verification_condition": {
                        "clauses": [
                            {
                                "id": "c1",
                                "kind": "ARTIFACT_PRESENT",
                                "description": "invoice present",
                                "params": {"artifact_types": ["INVOICE"]},
                                "required": True,
                            }
                        ],
                        "required_artifact_types": ["INVOICE"],
                    },
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    deal = created.json()
    assert deal["state"] == "DRAFT"
    assert deal["money"]["balanced"] is True
    assert deal["money"]["funded_paise"] == 0
    assert deal["viewer_side"] == "buyer"
    assert deal["risk_score"] is not None
    assert deal["pricing_tier"]

    signed = await client.post(f"/api/v1/deals/{deal['id']}/sign-terms", headers=buyer, json={})
    assert signed.status_code == 200
    assert signed.json()["state"] == "TERMS_SIGNED"

    funded = await client.post(f"/api/v1/deals/{deal['id']}/fund", headers=buyer, json={})
    assert funded.status_code == 200
    body = funded.json()
    assert body["state"] == "FUNDED"
    assert body["money"]["funded_paise"] == 42_000_000
    assert body["money"]["held_paise"] == 42_000_000
    assert body["money"]["balanced"] is True

    listed = await client.get("/api/v1/deals", headers=buyer)
    assert listed.status_code == 200
    assert any(d["id"] == deal["id"] for d in listed.json())

    timeline = await client.get(f"/api/v1/deals/{deal['id']}/timeline", headers=buyer)
    assert timeline.status_code == 200
    events = timeline.json()
    assert events[0]["prev_hash"] == "0" * 64
    assert all(e["payload_hash"] for e in events)

    risk = await client.get(f"/api/v1/deals/{deal['id']}/risk", headers=buyer)
    assert risk.status_code == 200
    assert len(risk.json()["top_factors"]) == 3


@pytest.mark.asyncio
async def test_only_the_buyer_can_fund(client, seller, parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties, fund=False)
        deal_id = deal.id
    response = await client.post(f"/api/v1/deals/{deal_id}/fund", headers=seller, json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ONLY_BUYER_FUNDS"


# ── evidence over HTTP ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_upload_submit_verify_and_read_provenance(client, seller, buyer, parties):
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "demo_evidence"
    manifest = json.loads((fixtures / "manifest.json").read_text(encoding="utf-8"))

    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        deal_id, milestone_id = deal.id, m1.id

    for entry in manifest["fabric"]:
        data = (fixtures / "fabric" / entry["filename"]).read_bytes()
        response = await client.post(
            f"/api/v1/evidence/milestones/{milestone_id}/upload",
            headers=seller,
            data={"artifact_type": entry["artifact_type"]},
            files={"file": (entry["filename"], data, entry["mime"])},
        )
        assert response.status_code == 201, response.text
        artifact = response.json()
        assert len(artifact["sha256"]) == 64
        assert artifact["sha256"] == hashlib.sha256(data).hexdigest()
        assert artifact["download_url"]

    submitted = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/submit", headers=seller
    )
    assert submitted.status_code == 200
    bundle = submitted.json()
    assert bundle["merkle_root"] != "0" * 64
    assert len(bundle["artifacts"]) == 2

    # The buyer can read the seller's evidence: it belongs to the deal.
    read = await client.get(f"/api/v1/evidence/milestones/{milestone_id}/bundle", headers=buyer)
    assert read.status_code == 200
    assert read.json()["merkle_root"] == bundle["merkle_root"]

    verified = await client.post(f"/api/v1/milestones/{milestone_id}/start-verify", headers=seller)
    assert verified.status_code == 200, verified.text
    result = verified.json()
    assert result["decision"] == "RELEASE"
    assert result["confidence"] >= 0.85
    assert result["provider"] in {"fixture", "anthropic", "groq"}

    attestation = await client.get(f"/api/v1/verification/milestones/{milestone_id}", headers=buyer)
    assert attestation.status_code == 200
    body = attestation.json()
    assert body["decision"] == "RELEASE"
    assert body["clause_verdicts"]
    assert body["confidence_components"]["formula"]
    assert body["thresholds"]["release"] == 0.85
    assert len(body["prompt_hash"]) == 64

    breakdown = await client.get(
        f"/api/v1/verification/attestations/{body['id']}/confidence", headers=buyer
    )
    assert breakdown.status_code == 200
    assert breakdown.json()["components"]["weights"]

    provenance = await client.get(f"/api/v1/provenance/attestations/{body['id']}", headers=buyer)
    assert provenance.status_code == 200
    prov = provenance.json()
    assert prov["signature_verified"] is True
    assert prov["chain"]["available"] is False
    assert prov["chain"]["reason"]
    assert prov["artifacts"]

    artifact_id = prov["artifacts"][0]["id"]
    proof = await client.get(f"/api/v1/evidence/artifacts/{artifact_id}/proof", headers=buyer)
    assert proof.status_code == 200
    proof_body = proof.json()
    assert proof_body["valid"] is True

    # The public verifier accepts the real proof and rejects a tampered leaf.
    ok = await client.post(
        "/api/v1/evidence/verify",
        json={"leaf": proof_body["leaf"], "proof": proof_body["proof"], "root": proof_body["root"]},
    )
    assert ok.status_code == 200 and ok.json()["ok"] is True
    tampered_leaf = ("f" if proof_body["leaf"][0] != "f" else "0") + proof_body["leaf"][1:]
    bad = await client.post(
        "/api/v1/evidence/verify",
        json={"leaf": tampered_leaf, "proof": proof_body["proof"], "root": proof_body["root"]},
    )
    assert bad.status_code == 200 and bad.json()["ok"] is False

    ledger = await client.get(f"/api/v1/ledger/deals/{deal_id}", headers=buyer)
    assert ledger.status_code == 200
    verify = await client.get(f"/api/v1/ledger/deals/{deal_id}/verify", headers=buyer)
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
    assert verify.json()["replayed_balances"]["funded_paise"] == 42_000_000

    chain = await client.get(f"/api/v1/provenance/deals/{deal_id}/chain", headers=buyer)
    assert chain.status_code == 200
    assert chain.json()["chain_available"] is False
    assert chain.json()["anchors"]


@pytest.mark.asyncio
async def test_an_unrecognised_artifact_type_is_refused(client, seller, parties):
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
        headers=seller,
        data={"artifact_type": "NOT_A_TYPE"},
        files={"file": ("x.pdf", b"%PDF-1.7 something", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_ARTIFACT_TYPE"


@pytest.mark.asyncio
async def test_a_mislabelled_file_is_refused(client, seller, parties):
    """A real content sniff, not the extension."""
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
        headers=seller,
        data={"artifact_type": "INVOICE"},
        files={"file": ("invoice.pdf", b"\x89PNG\r\n\x1a\nnot a pdf", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MIME_MISMATCH"


@pytest.mark.asyncio
async def test_an_empty_file_is_refused(client, seller, parties):
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
        headers=seller,
        data={"artifact_type": "INVOICE"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_FILE"


@pytest.mark.asyncio
async def test_a_presigned_download_expires_and_cannot_be_forged(client, seller, parties):
    from app.storage.store import get_store

    key = "probe/artifact.txt"
    get_store().put(key, b"hello", "text/plain")
    url = get_store().presign_get(key, 600)
    token = url.rsplit("/", 1)[-1]

    good = await client.get(f"/api/v1/evidence/download/{token}")
    assert good.status_code == 200
    assert good.content == b"hello"

    forged = (
        base64.urlsafe_b64encode(b"probe/artifact.txt|9999999999|deadbeef").decode().rstrip("=")
    )
    bad = await client.get(f"/api/v1/evidence/download/{forged}")
    assert bad.status_code == 404


# ── review queue, disputes, chat, notifications ─────────────────────────────
@pytest.mark.asyncio
async def test_the_review_queue_names_what_could_not_be_verified(client, buyer, parties):
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
        milestone_id = m2.id

    queue = await client.get("/api/v1/milestones/review-queue", headers=buyer)
    assert queue.status_code == 200
    rows = queue.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["milestone_id"] == str(milestone_id)
    assert row["state"] == "UNDER_HUMAN_REVIEW"
    assert row["could_not_verify"]
    assert "cannot establish" in row["could_not_verify"][0]["note"]

    decided = await client.post(
        f"/api/v1/milestones/{milestone_id}/human-review",
        headers=buyer,
        json={"action": "APPROVE", "reason": "Counted on site against the manifest."},
    )
    assert decided.status_code == 200
    assert decided.json()["authorized"] is True

    after = await client.get("/api/v1/milestones/review-queue", headers=buyer)
    assert after.json() == []


@pytest.mark.asyncio
async def test_a_human_review_without_a_reason_is_refused(client, buyer, parties):
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
        milestone_id = m2.id
    response = await client.post(
        f"/api/v1/milestones/{milestone_id}/human-review",
        headers=buyer,
        json={"action": "APPROVE", "reason": "fine"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_dispute_flow_over_http(client, buyer, parties):
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
            folder="fabric",
        )
        await verify_milestone(session, deal, m1, bundle)
        milestone_id, _deal_id = m1.id, deal.id

    raised = await client.post(
        f"/api/v1/milestones/{milestone_id}/disputes",
        headers=buyer,
        json={"claim": "60 of 500 units show colour variance beyond the swatch."},
    )
    assert raised.status_code == 201
    dispute = raised.json()
    assert dispute["settlement_blocked_until_human_decision"] is True

    arbiter = await client.post(f"/api/v1/disputes/{dispute['id']}/arbiter", headers=buyer)
    assert arbiter.status_code == 200
    recommendation = arbiter.json()["recommendation"]
    assert recommendation["advisory_only"] is True
    assert recommendation["release_paise"] + recommendation["refund_paise"] == 12_600_000

    unbalanced = await client.post(
        f"/api/v1/disputes/{dispute['id']}/resolve",
        headers=buyer,
        json={"release_paise": 1, "refund_paise": 1, "reason": "a written reason here"},
    )
    assert unbalanced.status_code == 422
    assert unbalanced.json()["error"]["code"] == "SPLIT_DOES_NOT_BALANCE"

    resolved = await client.post(
        f"/api/v1/disputes/{dispute['id']}/resolve",
        headers=buyer,
        json={
            "release_paise": recommendation["release_paise"],
            "refund_paise": recommendation["refund_paise"],
            "reason": "Accepted the arbiter split; the condition report supports it.",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["release_paise"] == recommendation["release_paise"]

    fetched = await client.get(f"/api/v1/disputes/{dispute['id']}", headers=buyer)
    assert fetched.json()["settlement_blocked_until_human_decision"] is False
    assert fetched.json()["human_decided_by"]


@pytest.mark.asyncio
async def test_chat_and_notifications(client, buyer, seller, parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        deal_id = deal.id

    sent = await client.post(
        f"/api/v1/chat/deals/{deal_id}", headers=seller, json={"body": "Photos uploaded."}
    )
    assert sent.status_code == 201
    assert sent.json()["mine"] is True

    read = await client.get(f"/api/v1/chat/deals/{deal_id}", headers=buyer)
    assert read.status_code == 200
    messages = read.json()
    assert len(messages) == 1
    assert messages[0]["body"] == "Photos uploaded."
    assert messages[0]["mine"] is False

    async with get_session_factory()() as session:
        await drain_outbox(session)

    notifications = await client.get("/api/v1/notifications", headers=buyer)
    assert notifications.status_code == 200
    body = notifications.json()
    assert body["unread"] >= 1
    assert body["items"]

    marked = await client.post("/api/v1/notifications/mark-read", headers=buyer, json={})
    assert marked.status_code == 200
    assert marked.json()["marked"] >= 1
    assert (await client.get("/api/v1/notifications", headers=buyer)).json()["unread"] == 0

    preferences = await client.get("/api/v1/notifications/preferences", headers=buyer)
    assert preferences.status_code == 200
    assert any(p["kind"] == "HUMAN_REVIEW_REQUIRED" for p in preferences.json())
    updated = await client.put(
        "/api/v1/notifications/preferences",
        headers=buyer,
        json={"kind": "DEAL_FUNDED", "in_app": True, "email": True},
    )
    assert updated.status_code == 200


@pytest.mark.asyncio
async def test_reputation_shows_factors_not_a_bare_score(client, buyer, parties):
    response = await client.get(
        f"/api/v1/reputation/entities/{parties['seller_entity_id']}", headers=buyer
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deals_completed"] == 11
    assert body["on_time_rate"] == 0.91
    assert 0.0 <= body["risk_score"] <= 1.0
    assert body["band"] in {"low", "moderate", "elevated", "high"}
    assert len(body["top_factors"]) == 3
    assert body["pricing"]["tier"]


@pytest.mark.asyncio
async def test_organizations_members_and_invitations(client, buyer, parties):
    orgs = await client.get("/api/v1/organizations", headers=buyer)
    assert orgs.status_code == 200
    assert any(o["active"] for o in orgs.json())

    current = await client.get("/api/v1/organizations/current", headers=buyer)
    assert current.status_code == 200
    assert current.json()["role"] == "OWNER"

    members = await client.get("/api/v1/organizations/members", headers=buyer)
    assert members.status_code == 200
    assert len(members.json()) == 1

    invited = await client.post(
        "/api/v1/organizations/invitations",
        headers=buyer,
        json={"email": "invitee@aegistest.dev", "role": "MEMBER"},
    )
    assert invited.status_code == 201
    assert invited.json()["role"] == "MEMBER"
    assert "accept_token" in invited.json(), "DEMO_MODE echoes the token for the demo"

    listed = await client.get("/api/v1/organizations/invitations", headers=buyer)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    entities = await client.get("/api/v1/entities", headers=buyer)
    assert entities.status_code == 200
    assert len(entities.json()) == 1


@pytest.mark.asyncio
async def test_user_preferences_round_trip(client, buyer):
    updated = await client.patch(
        "/api/v1/auth/preferences", headers=buyer, json={"theme": "dark", "language": "hi"}
    )
    assert updated.status_code == 200
    me = await client.get("/api/v1/auth/me", headers=buyer)
    assert me.json()["theme"] == "dark"
    assert me.json()["language"] == "hi"


# ── webhooks ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_webhook_without_a_valid_signature_is_refused(client):
    response = await client.post(
        "/api/v1/payments/webhooks/razorpay",
        content=b'{"id":"evt_1","event":"payment.captured"}',
        headers={"x-razorpay-signature": "nope", "content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


@pytest.mark.asyncio
async def test_a_signed_webhook_is_accepted_once_and_replays_are_ignored(client, monkeypatch):
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    body = json.dumps({"id": "evt_signed_1", "event": "transfer.processed"}).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-razorpay-signature": signature, "content-type": "application/json"}

    first = await client.post("/api/v1/payments/webhooks/razorpay", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"accepted": True, "duplicate": False, "event": "transfer.processed"}

    replay = await client.post("/api/v1/payments/webhooks/razorpay", content=body, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_a_malformed_signed_webhook_is_a_typed_error(client, monkeypatch):
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    body = b"not json at all"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    response = await client.post(
        "/api/v1/payments/webhooks/razorpay",
        content=body,
        headers={"x-razorpay-signature": signature},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WEBHOOK_MALFORMED"


# ── settlements and payouts ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_settlements_and_payouts_are_readable(client, buyer, parties):
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
            folder="fabric",
        )
        await verify_milestone(session, deal, m1, bundle)
        await drain_outbox(session)
        deal_id = deal.id

    authorizations = await client.get(f"/api/v1/settlements/deals/{deal_id}", headers=buyer)
    assert authorizations.status_code == 200
    assert len(authorizations.json()) == 1
    assert authorizations.json()[0]["authorized_by"] == "ENGINE"
    assert len(authorizations.json()[0]["idempotency_key"]) == 64

    payouts = await client.get(f"/api/v1/payments/deals/{deal_id}/payouts", headers=buyer)
    assert payouts.status_code == 200
    assert payouts.json()[0]["status"] == "SUCCEEDED"
    assert payouts.json()[0]["amount_paise"] == 12_600_000


# ── the tamper widget ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_tamper_check_endpoint_detects_a_flipped_byte(client):
    content = b"%PDF-1.7 invoice contents"
    digest = hashlib.sha256(content).hexdigest()
    ok = await client.post(
        "/api/v1/provenance/tamper-check",
        json={"content_b64": base64.b64encode(content).decode(), "expected_sha256": digest},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    tampered = bytearray(content)
    tampered[10] ^= 0x01
    bad = await client.post(
        "/api/v1/provenance/tamper-check",
        json={"content_b64": base64.b64encode(bytes(tampered)).decode(), "expected_sha256": digest},
    )
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert bad.json()["actual_sha256"] != digest


# ── SSE ─────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_sse_stream_requires_authentication(client):
    response = await client.get("/api/v1/realtime/deals")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_sse_subscription_does_not_pin_a_database_transaction(parties):
    """The stream must not hold the request's session open.

    A dependency-provided session is closed when the *response* finishes, and an
    SSE response finishes minutes or hours later -- so every subscriber used to
    sit `idle in transaction`, holding a pooled connection and an
    ACCESS SHARE lock.  That blocked `ALTER TABLE ... DISABLE TRIGGER` and hung
    this very test suite's database reset.  The handler now closes the session
    before returning the stream, and this pins that.
    """
    from app.api.v1.misc_router import sse_deals
    from app.common.deps import Membership
    from app.models.enums import OrgRole
    from app.models.identity import Organization, User

    async with get_session_factory()() as session:
        user = (
            await session.execute(select(User).where(User.id == parties["buyer_user_id"]))
        ).scalar_one()
        org = (
            await session.execute(
                select(Organization).where(Organization.id == parties["buyer_org_id"])
            )
        ).scalar_one()
        membership = Membership(user=user, org=org, role=OrgRole.OWNER)
        assert session.in_transaction()

        response = await sse_deals(membership, session)

        assert not session.in_transaction(), "the SSE handler left a transaction open"
        assert response.media_type == "text/event-stream"
        # The generator is never consumed here; closing it releases the hub slot.
        await response.body_iterator.aclose()

    from app.realtime.hub import get_hub

    assert get_hub().depth() == 0, "the subscription outlived the response"


@pytest.mark.asyncio
async def test_the_realtime_hub_delivers_to_the_right_tenant_only():
    """Exercised directly rather than over HTTP: an SSE response never
    completes, so a test that reads one has to be bounded by hand.  The
    behaviour that matters is the fan-out, and that is here."""
    import asyncio

    from app.realtime.hub import Hub

    hub = Hub()
    org_a, org_b = uuid.uuid4(), uuid.uuid4()

    async def first_event(target: uuid.UUID) -> str:
        stream = hub.subscribe("deals", target)
        chunks: list[str] = []
        async for chunk in stream:
            chunks.append(chunk)
            if len(chunks) == 2:  # ready, then the real event
                break
        return chunks[-1]

    task_a = asyncio.create_task(first_event(org_a))
    task_b = asyncio.create_task(first_event(org_b))
    await asyncio.sleep(0.05)  # let both subscribe

    await hub.publish("deals", org_a, "deal.updated", {"deal_id": "for-a"})

    received = await asyncio.wait_for(task_a, timeout=2)
    assert "deal.updated" in received
    assert "for-a" in received

    # org_b subscribed to the same concern and must not see org_a's event.
    task_b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_b
