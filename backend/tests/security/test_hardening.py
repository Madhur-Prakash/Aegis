"""Untrusted input: bounds, sniffing, and the promise that nothing returns a bare 500.

Three of these endpoints -- the Razorpay webhook, `provenance/tamper-check` and
`evidence/verify` -- take a body from an unauthenticated caller.  I9 says an
expected failure is a typed error and never a bare 500, and it is easiest to
break exactly there, because the handler is the first thing to touch the bytes.

The rest are resource bounds.  A 20 MB cap on an artifact says nothing about what
that artifact costs to *read*: a 47 KB PNG can declare forty-nine million pixels,
and `enforce_size` ran only after the whole upload was already in memory.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager  # type: ignore[import-not-found]
from sqlalchemy import select

from app.config.settings import settings
from app.db.session import get_session_factory
from app.models.commerce import Milestone
from tests.conftest import requires_db
from tests.factories import make_deal

pytestmark = requires_db


@pytest.fixture
async def client() -> Any:
    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest.fixture
async def seller(client: httpx.AsyncClient, parties: dict[str, Any]) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "seller@aegistest.dev", "password": parties["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ── the webhook: verified before parsing, and total on hostile headers ──────
def test_a_non_ascii_signature_is_a_refusal_and_not_a_crash():
    """`hmac.compare_digest` *raises* on two strs when either is non-ASCII.

    Starlette hands headers over latin-1 decoded, so a single high byte in
    `x-razorpay-signature` reached that call as a `str` with a non-ASCII
    character and came back as a `TypeError`.  Comparing bytes keeps it
    constant-time and total.
    """
    from app.rails.base import verify_webhook_signature

    assert verify_webhook_signature(b"{}", "Ã©Â©", "secret") is False
    assert verify_webhook_signature(b"{}", "￿" * 64, "secret") is False


def test_the_webhook_signature_is_still_checked_properly():
    from app.rails.base import verify_webhook_signature

    body = b'{"id":"evt_1","event":"transfer.processed"}'
    good = hmac.new(b"shh", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, good, "shh") is True
    assert verify_webhook_signature(body, good[:-1] + "0", "shh") is False
    assert verify_webhook_signature(body + b" ", good, "shh") is False
    assert verify_webhook_signature(body, good, "") is False
    assert verify_webhook_signature(body, "", "shh") is False


@pytest.mark.asyncio
async def test_the_webhook_route_answers_400_not_500_on_a_hostile_signature(client):
    # Raw bytes on the wire: Starlette decodes headers as latin-1, so these
    # arrive at the handler as a `str` carrying non-ASCII characters -- which is
    # exactly what `hmac.compare_digest` refuses to compare.
    response = await client.post(
        "/api/v1/payments/webhooks/razorpay",
        content=b'{"id":"evt_x"}',
        headers=[
            (b"x-razorpay-signature", b"\xc3\xa9\xc3\xa9\xff\xfe"),
            (b"content-type", b"application/json"),
        ],
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


@pytest.mark.asyncio
async def test_an_unsigned_webhook_never_reaches_the_json_parser(client):
    """Malformed JSON *and* a bad signature must report the signature."""
    response = await client.post(
        "/api/v1/payments/webhooks/razorpay",
        content=b"{not json at all",
        headers={"x-razorpay-signature": "00" * 32},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


# ── tamper-check: public, and it decodes whatever it is handed ──────────────
@pytest.mark.asyncio
async def test_the_tamper_check_still_works(client):
    content = b"%PDF-1.7 invoice contents"
    digest = hashlib.sha256(content).hexdigest()
    response = await client.post(
        "/api/v1/provenance/tamper-check",
        json={"content_b64": base64.b64encode(content).decode(), "expected_sha256": digest},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_the_tamper_check_refuses_a_body_beyond_the_artifact_cap(client):
    """Unbounded base64 from an anonymous client was unbounded `bytes` in the API."""
    oversized = "A" * (((20 * 1024 * 1024 * 4) // 3) + 64)
    response = await client.post(
        "/api/v1/provenance/tamper-check",
        json={"content_b64": oversized, "expected_sha256": "ab" * 32},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_the_tamper_check_types_a_base64_failure(client):
    response = await client.post(
        "/api/v1/provenance/tamper-check",
        json={"content_b64": "!!!! not base64 !!!!", "expected_sha256": "ab" * 32},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONTENT_NOT_BASE64"


# ── the public Merkle verifier ─────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proof",
    [
        [{"position": "right", "hash": "not hex"}],
        [{"position": "sideways", "hash": "ab" * 32}],
        [{"hash": "ab" * 32}],
        [{"position": "right", "hash": "ab" * 32}] * 65,
    ],
)
async def test_a_malformed_proof_is_a_typed_422_and_never_a_500(client, proof):
    response = await client.post(
        "/api/v1/evidence/verify",
        json={"leaf": "ab" * 32, "proof": proof, "root": "cd" * 32},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_a_well_formed_but_wrong_proof_is_a_200_saying_no(client):
    response = await client.post(
        "/api/v1/evidence/verify",
        json={
            "leaf": "ab" * 32,
            "proof": [{"position": "right", "hash": "cd" * 32}],
            "root": "ef" * 32,
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


# ── uploads: bounded before they are buffered, and bounded when decoded ─────
@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused_without_being_buffered(client, seller, parties):
    async with get_session_factory()() as session:
        deal = await make_deal(session, parties)
        m1 = (
            await session.execute(
                select(Milestone).where(Milestone.deal_id == deal.id, Milestone.seq == 1)
            )
        ).scalar_one()
        milestone_id = m1.id

    oversized = b"%PDF-1.7 " + b"A" * settings.MAX_ARTIFACT_BYTES
    response = await client.post(
        f"/api/v1/evidence/milestones/{milestone_id}/upload",
        headers=seller,
        data={"artifact_type": "INVOICE"},
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_a_decompression_bomb_is_refused_on_its_header():
    """A 47 KB PNG that declares 49 megapixels.

    Pillow's own ceiling only *warns* at 89 MP and does not raise until twice
    that, by which point the RGB buffer alone is half a gigabyte -- and this
    analyser then runs `convert`, `FIND_EDGES` and `resize` over it.  The header
    is enough to know, so nothing is decoded.
    """
    from PIL import Image

    from app.evidence.analyse import MAX_IMAGE_PIXELS, analyse_image

    canvas = Image.new("L", (7000, 7000), 0)
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    payload = buffer.getvalue()

    assert len(payload) < 1_000_000, "the point is that the wire size is tiny"
    assert MAX_IMAGE_PIXELS < 7000 * 7000

    observation = analyse_image(payload)
    assert observation.parseable is False
    assert any("budget" in note for note in observation.notes)
    assert observation.image == {}


def test_an_ordinary_photograph_is_still_analysed():
    from PIL import Image

    from app.evidence.analyse import analyse_image

    canvas = Image.new("RGB", (1200, 900), (14, 120, 200))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")

    observation = analyse_image(buffer.getvalue())
    assert observation.parseable is True
    assert observation.image["width"] == 1200


# ── the presigned download ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_downloaded_artifact_cannot_be_sniffed_into_markup(client, seller, parties):
    """`text/plain` is an accepted artifact type and the API is same-origin with
    the app, so a browser sniffing one of these into HTML would be running script
    on the app's own origin."""
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
        data={"artifact_type": "CONDITION_REPORT"},
        files={"file": ("note.txt", b"<script>alert(1)</script> condition ok", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    url = uploaded.json()["download_url"]

    downloaded = await client.get(url.replace("/api/v1", "/api/v1"))
    assert downloaded.status_code == 200
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"] == "attachment"
    assert downloaded.headers["content-type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_a_tampered_presign_token_is_a_404(client):
    from app.storage.store import LocalStore

    token = LocalStore().presign_get("some/key", 600).rsplit("/", 1)[-1]
    forged = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    response = await client.get(f"/api/v1/evidence/download/{forged}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_expired_presign_token_is_a_404(client):
    from app.storage.store import LocalStore

    token = LocalStore().presign_get("some/key", -10).rsplit("/", 1)[-1]
    response = await client.get(f"/api/v1/evidence/download/{token}")
    assert response.status_code == 404
