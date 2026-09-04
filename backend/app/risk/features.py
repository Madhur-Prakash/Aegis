"""Risk features and pricing tiers (spec 22).

``condition_objectivity_score`` -- the fraction of a deal's clauses that are
deterministically checkable -- is the feature that is both genuinely predictive
and a pleasure to explain to a counterparty.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.agents.verifier.clause_rules import DETERMINISTIC_KINDS

FEATURE_NAMES: tuple[str, ...] = (
    "deals_completed",
    "log_gmv",
    "dispute_rate",
    "on_time_rate",
    "stretch_ratio",
    "milestone_count",
    "avg_milestone_paise",
    "counterparty_age_days",
    "condition_objectivity_score",
    "category_code",
)

CATEGORIES: tuple[str, ...] = (
    "apparel",
    "electronics",
    "industrial",
    "agri",
    "services",
    "packaging",
)


@dataclass(slots=True)
class Features:
    deals_completed: float
    log_gmv: float
    dispute_rate: float
    on_time_rate: float
    stretch_ratio: float
    milestone_count: float
    avg_milestone_paise: float
    counterparty_age_days: float
    condition_objectivity_score: float
    category_code: float

    def vector(self) -> list[float]:
        data = asdict(self)
        return [float(data[name]) for name in FEATURE_NAMES]


def category_code(category: str) -> int:
    try:
        return CATEGORIES.index((category or "apparel").lower())
    except ValueError:
        return 0


def condition_objectivity(milestone_conditions: list[dict[str, Any]]) -> float:
    total = 0
    objective = 0
    for condition in milestone_conditions:
        for clause in (condition or {}).get("clauses", []):
            total += 1
            if str(clause.get("kind", "")).upper() in DETERMINISTIC_KINDS:
                objective += 1
    return round(objective / total, 4) if total else 0.0


def build_features(
    *,
    deals_completed: int,
    gmv_paise: int,
    disputes_raised: int,
    on_time_rate: float,
    largest_deal_paise: int,
    deal_paise: int,
    milestone_count: int,
    counterparty_age_days: int,
    milestone_conditions: list[dict[str, Any]],
    category: str,
) -> Features:
    dispute_rate = disputes_raised / deals_completed if deals_completed else 0.0
    stretch = deal_paise / largest_deal_paise if largest_deal_paise else 3.0
    return Features(
        deals_completed=float(deals_completed),
        log_gmv=math.log1p(max(0, gmv_paise)),
        dispute_rate=round(min(1.0, dispute_rate), 4),
        on_time_rate=round(min(1.0, max(0.0, on_time_rate)), 4),
        stretch_ratio=round(min(10.0, stretch), 4),
        milestone_count=float(milestone_count),
        avg_milestone_paise=float(deal_paise / max(1, milestone_count)),
        counterparty_age_days=float(counterparty_age_days),
        condition_objectivity_score=condition_objectivity(milestone_conditions),
        category_code=float(category_code(category)),
    )


# ── Pricing (spec 22) ───────────────────────────────────────────────────────
TIERS: tuple[dict[str, Any], ...] = (
    {
        "tier": "TIER_1",
        "max": 0.10,
        "fee_pct": 0.8,
        "hold_days": 0,
        "prefund_pct": 30,
        "accept": True,
    },
    {
        "tier": "TIER_2",
        "max": 0.25,
        "fee_pct": 1.5,
        "hold_days": 3,
        "prefund_pct": 50,
        "accept": True,
    },
    {
        "tier": "TIER_3",
        "max": 0.50,
        "fee_pct": 2.5,
        "hold_days": 7,
        "prefund_pct": 100,
        "accept": True,
    },
    {
        "tier": "DECLINE",
        "max": 1.01,
        "fee_pct": None,
        "hold_days": None,
        "prefund_pct": None,
        "accept": False,
    },
)


def price(risk_score: float) -> dict[str, Any]:
    for tier in TIERS:
        if risk_score < tier["max"]:
            return {
                "tier": tier["tier"],
                "escrow_fee_pct": tier["fee_pct"],
                "hold_days_after_final_release": tier["hold_days"],
                "buyer_prefund_pct": tier["prefund_pct"],
                "accepted": tier["accept"],
                "risk_score": round(risk_score, 4),
            }
    return {
        "tier": "DECLINE",
        "escrow_fee_pct": None,
        "hold_days_after_final_release": None,
        "buyer_prefund_pct": None,
        "accepted": False,
        "risk_score": round(risk_score, 4),
    }


def band(risk_score: float) -> str:
    if risk_score < 0.10:
        return "low"
    if risk_score < 0.25:
        return "moderate"
    if risk_score < 0.50:
        return "elevated"
    return "high"
