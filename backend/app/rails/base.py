"""PaymentRail protocol and the deterministic SimulatedRail (spec 20)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.common.errors import RailFailure
from app.common.logging import get_logger
from app.config.settings import settings
from app.models.enums import RailMode

log = get_logger("rail")


@dataclass(slots=True)
class HoldRef:
    ref: str
    provider: str


@dataclass(slots=True)
class CaptureRef:
    ref: str
    provider: str


@dataclass(slots=True)
class RailRef:
    ref: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RailStatus:
    ref: str
    status: str
    amount_paise: int


class PaymentRail(Protocol):
    mode: RailMode

    def create_hold(self, deal_id: str, amount_paise: int) -> HoldRef: ...
    def capture(self, hold_ref: HoldRef) -> CaptureRef: ...
    def release_to_seller(
        self, milestone_id: str, amount_paise: int, idempotency_key: str
    ) -> RailRef: ...
    def refund_to_buyer(
        self, milestone_id: str, amount_paise: int, idempotency_key: str
    ) -> RailRef: ...
    def get_status(self, rail_ref: RailRef) -> RailStatus: ...


def idempotency_key(milestone_id: str, direction: str, attempt_no: int) -> str:
    """I6: ``sha256(milestone_id:direction:attempt_no)``, UNIQUE in Postgres."""
    return hashlib.sha256(f"{milestone_id}:{direction}:{attempt_no}".encode()).hexdigest()


@dataclass
class SimulatedRail:
    """Deterministic local adapter.

    Writes the same Payout rows, ledger events and Kafka events as the real rail,
    so the whole flow is identical.  Every reference it produces is prefixed
    ``sim_`` and the UI and README label it SIMULATED -- never as a real call.
    """

    mode: RailMode = RailMode.SIMULATED
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail_next: bool = False

    def _ref(self, kind: str, seed: str) -> str:
        return f"sim_{kind}_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"

    def _record(self, op: str, **kwargs: Any) -> None:
        self.calls.append({"op": op, **kwargs})
        log.info("rail call", extra={"rail": "simulated", "op": op, **kwargs})

    def create_hold(self, deal_id: str, amount_paise: int) -> HoldRef:
        self._record("create_hold", deal_id=deal_id, amount_paise=amount_paise)
        return HoldRef(self._ref("hold", f"{deal_id}:{amount_paise}"), "simulated")

    def capture(self, hold_ref: HoldRef) -> CaptureRef:
        self._record("capture", hold_ref=hold_ref.ref)
        return CaptureRef(self._ref("cap", hold_ref.ref), "simulated")

    def release_to_seller(
        self, milestone_id: str, amount_paise: int, idempotency_key: str
    ) -> RailRef:
        if self.fail_next:
            self.fail_next = False
            raise RailFailure(
                message="Simulated rail failure (injected).",
                details={"milestone_id": milestone_id},
            )
        self._record("release_to_seller", milestone_id=milestone_id, amount_paise=amount_paise)
        return RailRef(
            self._ref("rel", idempotency_key), "simulated", {"amount_paise": amount_paise}
        )

    def refund_to_buyer(
        self, milestone_id: str, amount_paise: int, idempotency_key: str
    ) -> RailRef:
        if self.fail_next:
            self.fail_next = False
            raise RailFailure(message="Simulated rail failure (injected).")
        self._record("refund_to_buyer", milestone_id=milestone_id, amount_paise=amount_paise)
        return RailRef(
            self._ref("ref", idempotency_key), "simulated", {"amount_paise": amount_paise}
        )

    def get_status(self, rail_ref: RailRef) -> RailStatus:
        return RailStatus(rail_ref.ref, "processed", int(rail_ref.raw.get("amount_paise", 0)))


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """Razorpay's scheme: hex HMAC-SHA256 of the raw body.  Verified before anything else."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


_rail: PaymentRail | None = None


def get_rail() -> PaymentRail:
    global _rail
    if _rail is None:
        if settings.PAYMENT_RAIL == "razorpay" and settings.RAZORPAY_KEY_ID:
            from app.rails.razorpay import RazorpayRail

            _rail = RazorpayRail()
        else:
            _rail = SimulatedRail()
    return _rail


def set_rail(rail: PaymentRail) -> None:
    global _rail
    _rail = rail


def rail_disclosure() -> dict[str, Any]:
    """The per-operation honesty table the README and the UI both render."""
    rail = get_rail()
    real = rail.mode == RailMode.RAZORPAY_TEST
    label = "REAL TEST MODE" if real else "SIMULATED"
    return {
        "mode": str(rail.mode),
        "configured": settings.PAYMENT_RAIL,
        "credentials_present": bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET),
        "operations": {
            "funding_order_and_capture": label,
            "seller_release": label if real else "SIMULATED",
            "refund": label,
            "webhook_verification": "REAL TEST MODE"
            if settings.RAZORPAY_WEBHOOK_SECRET
            and not settings.RAZORPAY_WEBHOOK_SECRET.startswith("PLACEHOLDER")
            else "SIMULATED",
        },
    }
