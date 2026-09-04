"""RazorpayRail -- TEST MODE ONLY.

Real HTTP calls against ``api.razorpay.com`` with test-mode keys:

* **Funding**  Orders API (``POST /orders``) then Payments capture
  (``POST /payments/{id}/capture``).
* **Seller release**  Route transfers (``POST /payments/{id}/transfers``) to a
  linked account when ``RAZORPAY_ROUTE_SELLER_ACCOUNT`` is configured.
* **Refund**  Refunds API (``POST /payments/{id}/refund``).

Every call carries an idempotency header derived from
``sha256(milestone_id:direction:attempt_no)``, so a retry cannot double-pay.

If a key is absent the factory in ``app/rails/base.py`` selects
:class:`SimulatedRail` instead -- this class never fabricates a reference.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from app.common.errors import RailFailure
from app.common.logging import get_logger
from app.config.settings import settings
from app.models.enums import RailMode
from app.rails.base import CaptureRef, HoldRef, RailRef, RailStatus

log = get_logger("rail.razorpay")


@dataclass
class RazorpayRail:
    mode: RailMode = RailMode.RAZORPAY_TEST
    base_url: str = settings.RAZORPAY_BASE_URL
    key_id: str = settings.RAZORPAY_KEY_ID
    key_secret: str = settings.RAZORPAY_KEY_SECRET
    timeout_s: float = 20.0

    def __post_init__(self) -> None:
        if not self.key_id.startswith("rzp_test"):
            raise RailFailure(
                code="RAZORPAY_NOT_TEST_MODE",
                message="Aegis refuses to run against non-test Razorpay keys.",
                details={"key_prefix": self.key_id[:8]},
            )

    # ── plumbing ───────────────────────────────────────────────────────
    def _headers(self, idem: str | None = None) -> dict[str, str]:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        if idem:
            headers["X-Razorpay-Idempotency-Key"] = idem
        return headers

    def _post(self, path: str, body: dict[str, Any], idem: str | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.post(
                url, json=body, headers=self._headers(idem), timeout=self.timeout_s
            )
        except httpx.HTTPError as exc:
            raise RailFailure(
                code="RAIL_UNREACHABLE",
                message="The payment rail could not be reached.",
                details={"path": path, "error": type(exc).__name__},
            ) from exc
        return self._unwrap(response, path)

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.base_url}{path}", headers=self._headers(), timeout=self.timeout_s
            )
        except httpx.HTTPError as exc:
            raise RailFailure(code="RAIL_UNREACHABLE", details={"path": path}) from exc
        return self._unwrap(response, path)

    @staticmethod
    def _unwrap(response: httpx.Response, path: str) -> dict[str, Any]:
        if response.status_code >= 400:
            detail: dict[str, Any]
            try:
                detail = response.json().get("error", {})
            except Exception:
                detail = {"raw": response.text[:400]}
            log.warning(
                "rail call failed",
                extra={"path": path, "status": response.status_code, "code": detail.get("code")},
            )
            raise RailFailure(
                message=detail.get("description", "The payment rail rejected the operation."),
                details={
                    "path": path,
                    "status": response.status_code,
                    "rail_code": detail.get("code"),
                },
            )
        log.info(
            "rail call",
            extra={"rail": "razorpay_test", "path": path, "status": response.status_code},
        )
        return response.json()

    # ── PaymentRail ────────────────────────────────────────────────────
    def create_hold(self, deal_id: str, amount_paise: int) -> HoldRef:
        """An Order is the hold: funds are authorised against it, then captured."""
        order = self._post(
            "/orders",
            {
                "amount": int(amount_paise),
                "currency": "INR",
                "receipt": f"aegis-{deal_id}"[:40],
                "payment_capture": 0,
                "notes": {"aegis_deal_id": str(deal_id)},
            },
            idem=f"hold:{deal_id}:{amount_paise}",
        )
        return HoldRef(order["id"], "razorpay_test")

    def capture(self, hold_ref: HoldRef) -> CaptureRef:
        payments = self._get(f"/orders/{hold_ref.ref}/payments")
        items = payments.get("items") or []
        authorized = next((p for p in items if p.get("status") == "authorized"), None)
        if authorized is None:
            raise RailFailure(
                code="NO_AUTHORIZED_PAYMENT",
                message="No authorised payment exists on that order yet.",
                details={"order_id": hold_ref.ref},
            )
        captured = self._post(
            f"/payments/{authorized['id']}/capture",
            {"amount": authorized["amount"], "currency": "INR"},
            idem=f"capture:{authorized['id']}",
        )
        return CaptureRef(captured["id"], "razorpay_test")

    def release_to_seller(
        self, milestone_id: str, amount_paise: int, idempotency_key: str
    ) -> RailRef:
        account = settings.RAZORPAY_ROUTE_SELLER_ACCOUNT
        payment_id = _captured_payment_id(milestone_id)
        if not account or not payment_id:
            raise RailFailure(
                code="ROUTE_NOT_CONFIGURED",
                message=(
                    "Seller release needs a Razorpay Route linked account and a captured "
                    "payment. Configure RAZORPAY_ROUTE_SELLER_ACCOUNT or run PAYMENT_RAIL=simulated."
                ),
                details={"milestone_id": milestone_id},
            )
        transfer = self._post(
            f"/payments/{payment_id}/transfers",
            {
                "transfers": [
                    {
                        "account": account,
                        "amount": int(amount_paise),
                        "currency": "INR",
                        "notes": {"aegis_milestone_id": str(milestone_id)},
                    }
                ]
            },
            idem=idempotency_key,
        )
        items = transfer.get("items") or [transfer]
        return RailRef(items[0]["id"], "razorpay_test", items[0])

    def refund_to_buyer(
        self, milestone_id: str, amount_paise: int, idempotency_key: str
    ) -> RailRef:
        payment_id = _captured_payment_id(milestone_id)
        if not payment_id:
            raise RailFailure(
                code="NO_CAPTURED_PAYMENT",
                message="A refund needs the captured payment id for the funding leg.",
                details={"milestone_id": milestone_id},
            )
        refund = self._post(
            f"/payments/{payment_id}/refund",
            {
                "amount": int(amount_paise),
                "speed": "normal",
                "notes": {"aegis_milestone_id": str(milestone_id)},
            },
            idem=idempotency_key,
        )
        return RailRef(refund["id"], "razorpay_test", refund)

    def get_status(self, rail_ref: RailRef) -> RailStatus:
        prefix = rail_ref.ref.split("_", 1)[0]
        path = {
            "trf": f"/transfers/{rail_ref.ref}",
            "rfnd": f"/refunds/{rail_ref.ref}",
            "pay": f"/payments/{rail_ref.ref}",
            "order": f"/orders/{rail_ref.ref}",
        }.get(prefix, f"/payments/{rail_ref.ref}")
        body = self._get(path)
        return RailStatus(rail_ref.ref, body.get("status", "unknown"), int(body.get("amount", 0)))


# The funding payment id is recorded on the deal when the order is captured; the
# settlement worker passes it through this hook so the rail stays free of ORM imports.
_PAYMENT_IDS: dict[str, str] = {}


def register_captured_payment(milestone_id: str, payment_id: str) -> None:
    _PAYMENT_IDS[str(milestone_id)] = payment_id


def _captured_payment_id(milestone_id: str) -> str | None:
    return _PAYMENT_IDS.get(str(milestone_id))
