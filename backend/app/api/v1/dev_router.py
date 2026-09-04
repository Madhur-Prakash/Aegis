"""/api/v1/dev -- registered ONLY when DEMO_MODE=true (spec 14).

``POST /dev/assume`` issues a **genuine** session for a seeded user through the
normal login path.  Every downstream request is then an ordinary authenticated,
tenant-scoped request: the switch does not bypass authorization, and there is no
runtime flag check inside a handler that could be flipped.  When
``DEMO_MODE=false`` this router is never registered, so the route does not exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.v1.auth_router import _set_cookies
from app.api.v1.schemas import AssumeIn, TokenOut
from app.auth import service as auth_service
from app.common.deps import SessionDep
from app.common.errors import NotFound
from app.common.logging import get_logger
from app.config.settings import settings
from app.rails.base import rail_disclosure

log = get_logger("dev")
router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/assume", response_model=TokenOut)
async def assume(payload: AssumeIn, response: Response, session: SessionDep) -> TokenOut:
    email, password = (
        (settings.DEMO_BUYER_EMAIL, settings.DEMO_BUYER_PASSWORD)
        if payload.role == "buyer"
        else (settings.DEMO_SELLER_EMAIL, settings.DEMO_SELLER_PASSWORD)
    )
    # The ordinary login path -- password verification included.  If the seed has
    # not run, this fails exactly as a real login would.
    try:
        _user, tokens = await auth_service.login(session, email=email, password=password)
    except Exception as exc:
        raise NotFound(
            details={
                "hint": "run `make seed` and set DEMO_BUYER_PASSWORD / DEMO_SELLER_PASSWORD",
                "role": payload.role,
            }
        ) from exc
    await session.commit()
    _set_cookies(response, tokens)
    log.info("demo assume", extra={"role": payload.role})
    return TokenOut(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        refresh_token=tokens.refresh_token,
    )


@router.get("/state", response_model=dict)
async def state() -> dict[str, Any]:
    return {
        "demo_mode": settings.DEMO_MODE,
        "ai_provider_configured": settings.AI_PROVIDER,
        "ai_provider_effective": settings.ai_effective_provider,
        "rail": rail_disclosure(),
        "chain_enabled": settings.CHAIN_ENABLED,
        "contract_address": settings.CONTRACT_ADDRESS or None,
    }
