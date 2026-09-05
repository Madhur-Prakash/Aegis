"""Auth: registration, verification gating, reset single-use, refresh reuse
detection, role escalation, and the DEMO_MODE affordance."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager  # type: ignore[import-not-found]
from sqlalchemy import select

from tests.conftest import requires_db

pytestmark = requires_db

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-correct-horse"


@pytest.fixture
async def client(truncate_all: None) -> Any:
    from app.main import app

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def register(client: httpx.AsyncClient, email: str = "new@aegistest.dev") -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "New Person",
            "organization_name": "New Org",
        },
    )


def latest_token(purpose: str) -> str:
    """Reads the raw token out of the email the development provider captured --
    exactly what a user would click, and proof the token is never returned by
    the API."""
    from app.notifications.email import get_email_provider

    provider = get_email_provider()
    for email in reversed(getattr(provider, "outbox", [])):
        if purpose in email.subject.lower():
            for chunk in email.body.split():
                if "token=" in chunk:
                    return chunk.split("token=", 1)[1]
    raise AssertionError(f"no {purpose} email captured")


# ── registration and verification gating ────────────────────────────────────
@pytest.mark.asyncio
async def test_registration_creates_an_unverified_account(client):
    response = await register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert "password" not in response.text

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email_verified"] is False


@pytest.mark.asyncio
async def test_a_verification_token_is_never_returned_by_the_api(client):
    response = await register(client)
    assert "verify" not in response.text.lower() or "token" not in response.text.lower()
    token = latest_token("verify")  # only reachable through the email
    assert len(token) > 20


@pytest.mark.asyncio
async def test_an_unverified_account_cannot_create_a_deal(client):
    """Enforced in a dependency, not in the UI."""
    response = await register(client)
    token = response.json()["access_token"]
    created = await client.post(
        "/api/v1/deals",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "x",
            "seller_org_slug": "whoever",
            "total_paise": 100,
            "milestones": [
                {
                    "seq": 1,
                    "title": "m",
                    "amount_paise": 100,
                    "verification_condition": {"clauses": [], "required_artifact_types": []},
                }
            ],
        },
    )
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_an_unverified_account_can_still_read(client):
    response = await register(client)
    token = response.json()["access_token"]
    listed = await client.get("/api/v1/deals", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200


@pytest.mark.asyncio
async def test_verification_unlocks_writing(client):
    await register(client)
    token = latest_token("verify")
    verified = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200

    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    access = login.json()["access_token"]
    entity = await client.post(
        "/api/v1/entities",
        headers={"Authorization": f"Bearer {access}"},
        json={"kind": "BUYER", "display_name": "Procurement"},
    )
    assert entity.status_code == 201


@pytest.mark.asyncio
async def test_a_verification_token_is_single_use(client):
    await register(client)
    token = latest_token("verify")
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    replay = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.asyncio
async def test_duplicate_registration_is_a_typed_conflict(client):
    await register(client)
    again = await register(client)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.asyncio
async def test_a_weak_password_is_refused(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@aegistest.dev", "password": "password123", "name": "W"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_short_password_is_refused(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "short@aegistest.dev", "password": "short", "name": "S"},
    )
    assert response.status_code == 422


# ── login ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bad_credentials_do_not_reveal_whether_the_email_exists(client):
    await register(client)
    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": "wrong-password-xx"}
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@aegistest.dev", "password": "wrong-password-xx"},
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"]


@pytest.mark.asyncio
async def test_the_password_hash_is_argon2id():
    from app.auth.security import hash_password, verify_password

    digest = hash_password(PASSWORD)
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, PASSWORD)
    assert not verify_password(digest, PASSWORD + "x")


@pytest.mark.asyncio
async def test_hashes_are_salted(client):
    from app.auth.security import hash_password

    assert hash_password(PASSWORD) != hash_password(PASSWORD)


# ── refresh rotation and reuse detection ────────────────────────────────────
@pytest.mark.asyncio
async def test_refresh_rotates_and_the_old_token_dies(client):
    await register(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    first = login.json()["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first


@pytest.mark.asyncio
async def test_replaying_a_refresh_token_kills_the_whole_family(client):
    await register(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    first = login.json()["refresh_token"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    second = rotated.json()["refresh_token"]

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSE"

    # The currently-valid token is revoked too: the family is gone.
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_an_unknown_refresh_token_is_refused(client):
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_an_expired_access_token_is_refused(client):
    import jwt

    from app.config.settings import settings

    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "org": None,
            "sid": "x",
            "iat": 0,
            "exp": 1,
            "iss": "aegis",
            "typ": "access",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = await client.get("/api/v1/deals", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.asyncio
async def test_a_token_signed_with_the_wrong_key_is_refused(client):
    import jwt

    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "org": None,
            "sid": "x",
            "iat": 0,
            "exp": 4_000_000_000,
            "iss": "aegis",
            "typ": "access",
        },
        "not-the-real-secret",
        algorithm="HS256",
    )
    response = await client.get("/api/v1/deals", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_refresh_token_cannot_be_used_as_an_access_token(client):
    await register(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    refresh = login.json()["refresh_token"]
    response = await client.get("/api/v1/deals", headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401


# ── password reset ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_forgot_password_answers_identically_for_unknown_accounts(client):
    await register(client)
    known = await client.post("/api/v1/auth/forgot-password", json={"email": "new@aegistest.dev"})
    unknown = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@aegistest.dev"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


@pytest.mark.asyncio
async def test_a_reset_token_is_single_use_and_revokes_every_session(client):
    await register(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    old_refresh = login.json()["refresh_token"]
    old_access = login.json()["access_token"]

    await client.post("/api/v1/auth/forgot-password", json={"email": "new@aegistest.dev"})
    token = latest_token("reset")

    reset = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert reset.status_code == 200

    replay = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "third-password-xyz"}
    )
    assert replay.status_code == 401

    stale = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert stale.status_code == 401, "every session must be revoked by a reset"

    # And the access token already in hand must stop working *immediately*.
    # Revoking only the refresh token left a bearer token valid for the rest of
    # its 15-minute TTL, which is precisely the window that matters to someone
    # resetting a password because they think it was stolen.
    stale_access = await client.get(
        "/api/v1/auth/me", headers={"authorization": f"Bearer {old_access}"}
    )
    assert stale_access.status_code == 401, (
        "an access token from a revoked session must be refused, not honoured until it expires"
    )

    old = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": NEW_PASSWORD}
    )
    assert new.status_code == 200


@pytest.mark.asyncio
async def test_reset_tokens_are_hashed_at_rest(client):
    from app.db.session import get_session_factory
    from app.models.identity import EmailToken

    await register(client)
    await client.post("/api/v1/auth/forgot-password", json={"email": "new@aegistest.dev"})
    raw = latest_token("reset")
    async with get_session_factory()() as session:
        rows = list((await session.execute(select(EmailToken))).scalars())
    assert rows
    assert all(row.token_hash != raw for row in rows)
    assert all(len(row.token_hash) == 64 for row in rows)


@pytest.mark.asyncio
async def test_an_expired_reset_token_is_refused(client):
    from app.db.session import get_session_factory
    from app.models.identity import EmailToken

    await register(client)
    await client.post("/api/v1/auth/forgot-password", json={"email": "new@aegistest.dev"})
    raw = latest_token("reset")
    async with get_session_factory()() as session:
        from app.auth.security import hash_token

        row = (
            await session.execute(
                select(EmailToken).where(EmailToken.token_hash == hash_token(raw))
            )
        ).scalar_one()
        row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        await session.commit()
    response = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 401


# ── logout ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_logout_revokes_the_session(client):
    await register(client)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@aegistest.dev", "password": PASSWORD}
    )
    access = login.json()["access_token"]
    refresh = login.json()["refresh_token"]
    out = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert out.status_code == 200
    after = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert after.status_code == 401

    # The access token goes with it.  "Signed out" that leaves a working bearer
    # token for another fifteen minutes is not signed out.
    reused = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert reused.status_code == 401, "logout must invalidate the access token too"


@pytest.mark.asyncio
async def test_logout_with_somebody_elses_refresh_cookie_does_not_sign_them_out(client):
    """The refresh cookie has to belong to the caller.

    `logout` looked the token up by hash and revoked *its* family without ever
    checking whose it was, so a signed-in account presenting another user's
    refresh token signed that user out -- and left its own session running,
    which is not what the button says either.
    """
    await register(client, "victim@aegistest.dev")
    victim = await client.post(
        "/api/v1/auth/login", json={"email": "victim@aegistest.dev", "password": PASSWORD}
    )
    victim_access = victim.json()["access_token"]
    victim_refresh = victim.json()["refresh_token"]

    await register(client, "attacker@aegistest.dev")
    attacker = await client.post(
        "/api/v1/auth/login", json={"email": "attacker@aegistest.dev", "password": PASSWORD}
    )
    attacker_access = attacker.json()["access_token"]

    out = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {attacker_access}"},
        cookies={"aegis_refresh": victim_refresh},
    )
    assert out.status_code == 200

    still_signed_in = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {victim_access}"}
    )
    assert still_signed_in.status_code == 200, "the victim's session must survive"

    # And the caller's own session is the one that ended.
    own = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {attacker_access}"}
    )
    assert own.status_code == 401


# ── account enumeration ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_login_for_an_unknown_account_still_spends_a_password_verification(
    client, monkeypatch
):
    """Argon2id at 64 MiB is tens of milliseconds, and a clock anyone can read.

    Returning `InvalidCredentials` without hashing anything when the account did
    not exist made "no such account" and "wrong password" trivially separable by
    response time, whatever the body said.  Asserting on the *work* rather than
    on the wall clock keeps the test honest on a loaded machine.
    """
    import app.auth.service as auth_service

    calls: list[int] = []
    real = auth_service.dummy_verify
    monkeypatch.setattr(auth_service, "dummy_verify", lambda: (calls.append(1), real())[1])

    await register(client, "known@aegistest.dev")

    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-at-all@aegistest.dev", "password": PASSWORD},
    )
    assert unknown.status_code == 401
    assert calls == [1], "an unknown account must still pay for a hash comparison"

    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "known@aegistest.dev", "password": "wrong-password-x"}
    )
    assert wrong.status_code == 401
    # The real hash was verified on this path, so no equaliser was needed.
    assert calls == [1]

    # Indistinguishable in the body, too.
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


# ── rate limiting ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_login_is_rate_limited(client):
    from app.common.redis_client import redis_ready

    if not await redis_ready():
        pytest.skip("rate limiting needs Redis")
    await register(client)
    codes = []
    for _ in range(14):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "new@aegistest.dev", "password": "wrong-password-xx"},
        )
        codes.append(response.status_code)
        if response.status_code == 429:
            body = response.json()["error"]
            assert body["code"] == "RATE_LIMITED"
            assert body["details"]["retry_after"] >= 0
            break
    assert 429 in codes, codes


# ── roles ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_member_cannot_approve_a_dispute(client, parties):
    """Role escalation attempt: MEMBER approving a dispute (spec 31)."""
    from app.auth.security import hash_password
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.models.identity import OrganizationMember, User

    async with get_session_factory()() as session:
        member = User(
            email="member@aegistest.dev",
            email_normalized="member@aegistest.dev",
            name="Member",
            password_hash=hash_password(PASSWORD),
            email_verified_at=dt.datetime.now(dt.UTC),
            active_org_id=parties["buyer_org_id"],
        )
        session.add(member)
        await session.flush()
        session.add(
            OrganizationMember(
                org_id=parties["buyer_org_id"], user_id=member.id, role=OrgRole.MEMBER
            )
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login", json={"email": "member@aegistest.dev", "password": PASSWORD}
    )
    token = login.json()["access_token"]
    response = await client.post(
        f"/api/v1/disputes/{uuid.uuid4()}/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={"release_paise": 1, "refund_paise": 0, "reason": "a written reason here"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_a_member_cannot_invite(client, parties):
    from app.auth.security import hash_password
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.models.identity import OrganizationMember, User

    async with get_session_factory()() as session:
        member = User(
            email="member2@aegistest.dev",
            email_normalized="member2@aegistest.dev",
            name="Member Two",
            password_hash=hash_password(PASSWORD),
            email_verified_at=dt.datetime.now(dt.UTC),
            active_org_id=parties["buyer_org_id"],
        )
        session.add(member)
        await session.flush()
        session.add(
            OrganizationMember(
                org_id=parties["buyer_org_id"], user_id=member.id, role=OrgRole.MEMBER
            )
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login", json={"email": "member2@aegistest.dev", "password": PASSWORD}
    )
    response = await client.post(
        "/api/v1/organizations/invitations",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"email": "x@aegistest.dev", "role": "MEMBER"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_last_owner_cannot_be_demoted(client, parties):
    from app.common.errors import LastOwnerProtected
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.organizations.service import change_role

    async with get_session_factory()() as session:
        with pytest.raises(LastOwnerProtected):
            await change_role(
                session,
                org_id=parties["buyer_org_id"],
                target_user_id=parties["buyer_user_id"],
                new_role=OrgRole.ADMIN,
                actor_user_id=parties["buyer_user_id"],
                actor_role=OrgRole.OWNER,
            )


async def _admin_alongside_the_owner(client, parties) -> dict[str, str]:
    """A second member of the buyer org, ADMIN, signed in."""
    import datetime as dt

    from app.auth.security import hash_password
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.models.identity import OrganizationMember, User

    async with get_session_factory()() as session:
        admin = User(
            email="admin@aegistest.dev",
            email_normalized="admin@aegistest.dev",
            name="An Admin",
            password_hash=hash_password(PASSWORD),
            email_verified_at=dt.datetime.now(dt.UTC),
            active_org_id=parties["buyer_org_id"],
        )
        session.add(admin)
        await session.flush()
        session.add(
            OrganizationMember(org_id=parties["buyer_org_id"], user_id=admin.id, role=OrgRole.ADMIN)
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@aegistest.dev", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_an_admin_cannot_demote_an_owner(client, parties):
    """`AdminDep` gates the route, and the only further checks were "granting
    OWNER needs OWNER" and last-owner protection.  Neither says anything about
    the *target's* rank, so an admin could strip the people above them as long as
    a second owner existed."""
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.models.identity import OrganizationMember

    headers = await _admin_alongside_the_owner(client, parties)

    # A second owner, so last-owner protection is not what refuses this.
    async with get_session_factory()() as session:
        session.add(
            OrganizationMember(
                org_id=parties["buyer_org_id"],
                user_id=parties["outsider_user_id"],
                role=OrgRole.OWNER,
            )
        )
        await session.commit()

    response = await client.patch(
        f"/api/v1/organizations/members/{parties['buyer_user_id']}/role",
        headers=headers,
        json={"role": "VIEWER"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ROLE_RANK_INSUFFICIENT"

    async with get_session_factory()() as session:
        member = (
            await session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.org_id == parties["buyer_org_id"],
                    OrganizationMember.user_id == parties["buyer_user_id"],
                )
            )
        ).scalar_one()
        assert str(member.role) == "OWNER"


@pytest.mark.asyncio
async def test_an_admin_cannot_remove_an_owner(client, parties):
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.models.identity import OrganizationMember

    headers = await _admin_alongside_the_owner(client, parties)
    async with get_session_factory()() as session:
        session.add(
            OrganizationMember(
                org_id=parties["buyer_org_id"],
                user_id=parties["outsider_user_id"],
                role=OrgRole.OWNER,
            )
        )
        await session.commit()

    response = await client.delete(
        f"/api/v1/organizations/members/{parties['buyer_user_id']}", headers=headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROLE_RANK_INSUFFICIENT"


@pytest.mark.asyncio
async def test_an_admin_may_still_manage_members_below_them(client, parties):
    """The rank check must not cost an admin the job they are there to do."""
    import datetime as dt

    from app.auth.security import hash_password
    from app.db.session import get_session_factory
    from app.models.enums import OrgRole
    from app.models.identity import OrganizationMember, User

    headers = await _admin_alongside_the_owner(client, parties)
    async with get_session_factory()() as session:
        junior = User(
            email="junior@aegistest.dev",
            email_normalized="junior@aegistest.dev",
            name="A Member",
            password_hash=hash_password(PASSWORD),
            email_verified_at=dt.datetime.now(dt.UTC),
        )
        session.add(junior)
        await session.flush()
        session.add(
            OrganizationMember(
                org_id=parties["buyer_org_id"], user_id=junior.id, role=OrgRole.MEMBER
            )
        )
        await session.commit()
        junior_id = junior.id

    promoted = await client.patch(
        f"/api/v1/organizations/members/{junior_id}/role",
        headers=headers,
        json={"role": "VIEWER"},
    )
    assert promoted.status_code == 200, promoted.text

    removed = await client.delete(f"/api/v1/organizations/members/{junior_id}", headers=headers)
    assert removed.status_code == 200, removed.text


@pytest.mark.asyncio
async def test_transfer_ownership_still_works(client, parties):
    """It demotes the acting owner, which the rank check has to keep allowing."""
    from app.db.session import get_session_factory
    from app.models.identity import OrganizationMember

    await _admin_alongside_the_owner(client, parties)
    owner_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "buyer@aegistest.dev", "password": parties["password"]},
    )
    owner = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    async with get_session_factory()() as session:
        admin_member = (
            await session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.org_id == parties["buyer_org_id"],
                    OrganizationMember.role == "ADMIN",
                )
            )
        ).scalar_one()
        admin_user_id = admin_member.user_id

    response = await client.post(
        f"/api/v1/organizations/transfer-ownership/{admin_user_id}", headers=owner
    )
    assert response.status_code == 200, response.text


# ── the DEMO_MODE affordance ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dev_assume_issues_a_real_session(client):
    """It must not bypass authorization: the session it returns is an ordinary
    one, obtained through the normal login path."""
    from app.config.settings import settings
    from scripts.seed import run_seed

    await run_seed()
    response = await client.post("/api/v1/dev/assume", json={"role": "buyer"})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == settings.DEMO_BUYER_EMAIL

    # And that session is still tenant-scoped like any other.
    foreign = await client.get(
        f"/api/v1/deals/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert foreign.status_code == 404


def test_the_dev_router_is_not_registered_when_demo_mode_is_off(monkeypatch):
    """A registration-time decision, not a runtime flag check inside a handler."""
    import importlib

    import app.config.settings as settings_module

    monkeypatch.setenv("DEMO_MODE", "false")
    settings_module.get_settings.cache_clear()
    importlib.reload(settings_module)
    assert settings_module.settings.DEMO_MODE is False

    import app.main as main_module

    reloaded = importlib.reload(main_module)
    paths = {getattr(r, "path", "") for r in reloaded.app.routes}
    assert "/api/v1/dev/assume" not in paths
    assert "/api/v1/dev/state" not in paths

    # Restore, so later tests see the demo affordance again.
    monkeypatch.setenv("DEMO_MODE", "true")
    settings_module.get_settings.cache_clear()
    importlib.reload(settings_module)
    importlib.reload(main_module)
