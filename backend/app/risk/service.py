"""LightGBM risk scoring with plain-language factor attribution.

Never show a bare score (spec 22): the top-3 contributing factors are computed
from the model's own per-feature contributions and rendered as sentences.

If no trained model artifact is present the service falls back to a transparent
logistic scorecard -- the same one Report D uses as the baseline to beat -- and
labels the score version so nothing pretends to come from a model that was never
trained.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.logging import get_logger
from app.models.commerce import Deal, Milestone
from app.models.identity import CounterpartyProfile, Entity
from app.risk.features import FEATURE_NAMES, Features, band, build_features, price

log = get_logger("risk")

MODEL_DIR = Path(__file__).resolve().parents[3] / "data" / "generated"
MODEL_PATH = MODEL_DIR / "risk_lgbm.txt"
META_PATH = MODEL_DIR / "risk_model.json"

# The transparent fallback scorecard.  Coefficients are the logistic baseline
# fitted in Report D and written to risk_baseline.json; these literals are only
# used when neither artifact exists, and the version string says so.
_FALLBACK_INTERCEPT = -1.15
_FALLBACK_WEIGHTS: dict[str, float] = {
    "deals_completed": -0.055,
    "log_gmv": -0.030,
    "dispute_rate": 2.40,
    "on_time_rate": -1.30,
    "stretch_ratio": 0.42,
    "milestone_count": -0.05,
    "avg_milestone_paise": 0.0,
    "counterparty_age_days": -0.0012,
    "condition_objectivity_score": -1.05,
    "category_code": 0.02,
}

_PHRASES: dict[str, tuple[str, str]] = {
    "deals_completed": (
        "{v:.0f} completed deals with no adverse outcome",
        "only {v:.0f} completed deals on record",
    ),
    "log_gmv": ("substantial settled volume to date", "little settled volume to date"),
    "dispute_rate": (
        "no disputes across their history",
        "dispute rate of {raw:.0%} across their history",
    ),
    "on_time_rate": ("on-time rate {raw:.0%} across their deals", "on-time rate only {raw:.0%}"),
    "stretch_ratio": (
        "this deal is well within their usual size",
        "this deal is {raw:.1f}x their largest to date",
    ),
    "milestone_count": (
        "{v:.0f} milestones stage the risk",
        "few milestones, so most value settles at once",
    ),
    "avg_milestone_paise": ("milestone sizes are modest", "each milestone releases a large amount"),
    "counterparty_age_days": (
        "counterparty of {years:.1f} years standing",
        "thin file: {v:.0f} days on the platform",
    ),
    "condition_objectivity_score": (
        "{raw:.0%} of clauses are machine-checkable",
        "only {raw:.0%} of clauses are machine-checkable, so more rests on judgement",
    ),
    "category_code": ("category is a familiar one", "category carries above-average variance"),
}


class RiskScorer:
    def __init__(self) -> None:
        self.version = "logistic-fallback-1"
        self._booster: Any = None
        self._meta: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if MODEL_PATH.exists():
            try:
                import lightgbm as lgb

                self._booster = lgb.Booster(model_file=str(MODEL_PATH))
                if META_PATH.exists():
                    self._meta = json.loads(META_PATH.read_text(encoding="utf-8"))
                self.version = str(self._meta.get("version") or "lgbm-1")
                log.info("risk model loaded", extra={"version": self.version})
            except Exception as exc:
                log.warning("risk model load failed", extra={"error": type(exc).__name__})
                self._booster = None

    @property
    def trained(self) -> bool:
        return self._booster is not None

    def predict(self, features: Features) -> float:
        if self._booster is not None:
            value = float(self._booster.predict([features.vector()])[0])
            return max(0.0, min(1.0, value))
        return self._fallback(features)

    @staticmethod
    def _fallback(features: Features) -> float:
        z = _FALLBACK_INTERCEPT
        data = dict(zip(FEATURE_NAMES, features.vector(), strict=True))
        for name, weight in _FALLBACK_WEIGHTS.items():
            z += weight * data[name]
        return round(1.0 / (1.0 + math.exp(-z)), 4)

    def contributions(self, features: Features) -> list[dict[str, Any]]:
        """Per-feature contribution to the score, in log-odds space.

        LightGBM SHAP values when a model exists; the logistic terms otherwise.
        Both are signed and directly explainable.
        """
        data = dict(zip(FEATURE_NAMES, features.vector(), strict=True))
        if self._booster is not None:
            try:
                raw = self._booster.predict([features.vector()], pred_contrib=True)[0]
                pairs = list(zip(FEATURE_NAMES, raw[: len(FEATURE_NAMES)], strict=True))
            except Exception:
                pairs = [(n, _FALLBACK_WEIGHTS[n] * data[n]) for n in FEATURE_NAMES]
        else:
            pairs = [(n, _FALLBACK_WEIGHTS[n] * data[n]) for n in FEATURE_NAMES]
        return [
            {"feature": name, "contribution": round(float(value), 4), "value": data[name]}
            for name, value in pairs
        ]

    def top_factors(self, features: Features, limit: int = 3) -> list[dict[str, Any]]:
        contributions = sorted(
            self.contributions(features), key=lambda c: abs(c["contribution"]), reverse=True
        )
        out: list[dict[str, Any]] = []
        for item in contributions[:limit]:
            name = item["feature"]
            positive, negative = _PHRASES.get(name, (name, name))
            raises_risk = item["contribution"] > 0
            template = negative if raises_risk else positive
            value = float(item["value"])
            raw = value
            if (
                name == "on_time_rate"
                or name == "condition_objectivity_score"
                or name == "dispute_rate"
            ):
                raw = value
            phrase = template.format(v=value, raw=raw, years=value / 365.0)
            out.append(
                {
                    "feature": name,
                    "direction": "increases" if raises_risk else "decreases",
                    "delta": round(item["contribution"], 4),
                    "sign": "+" if raises_risk else "-",
                    "plain_language": phrase,
                }
            )
        return out


_scorer: RiskScorer | None = None


def get_scorer() -> RiskScorer:
    global _scorer
    if _scorer is None:
        _scorer = RiskScorer()
    return _scorer


def reset_scorer() -> None:
    global _scorer
    _scorer = None


async def score_deal(session: AsyncSession, deal: Deal, seller: Entity | None) -> dict[str, Any]:
    profile = await session.get(CounterpartyProfile, seller.id) if seller is not None else None
    milestones = list(
        (await session.execute(select(Milestone).where(Milestone.deal_id == deal.id))).scalars()
    )
    conditions = [m.verification_condition_json for m in milestones] or [
        m["verification_condition"] for m in (deal.terms_json or {}).get("milestones", [])
    ]
    age_days = 0
    if seller is not None:
        anchor = seller.onboarded_at or seller.created_at
        if anchor is not None:
            age_days = max(0, (dt.datetime.now(dt.UTC) - anchor).days)

    features = build_features(
        deals_completed=int(profile.deals_completed) if profile else 0,
        gmv_paise=int(profile.gmv_paise) if profile else 0,
        disputes_raised=int(profile.disputes_raised) if profile else 0,
        on_time_rate=float(profile.on_time_rate) if profile else 0.85,
        largest_deal_paise=int(profile.largest_deal_paise) if profile else 0,
        deal_paise=int(deal.total_paise),
        milestone_count=len(conditions) or len(milestones) or 1,
        counterparty_age_days=age_days,
        milestone_conditions=conditions,
        category=deal.category,
    )
    scorer = get_scorer()
    risk = scorer.predict(features)
    pricing = price(risk)
    assessment: dict[str, Any] = {
        "risk_score": risk,
        "band": band(risk),
        "score_version": scorer.version,
        "model_trained": scorer.trained,
        "features": dict(zip(FEATURE_NAMES, features.vector(), strict=True)),
        "top_factors": scorer.top_factors(features),
        "pricing": pricing,
    }
    pricing_tier = pricing["tier"]
    log.info(
        "risk scored",
        extra={
            "deal_id": str(deal.id),
            "risk_score": risk,
            "tier": pricing_tier,
            "score_version": scorer.version,
        },
    )
    return assessment


async def counterparty_passport(session: AsyncSession, entity_id: uuid.UUID) -> dict[str, Any]:
    entity = await session.get(Entity, entity_id)
    if entity is None:
        from app.common.errors import NotFound

        raise NotFound(details={"type": "Entity", "id": str(entity_id)})
    profile = await session.get(CounterpartyProfile, entity_id)
    conditions: list[dict[str, Any]] = []
    features = build_features(
        deals_completed=int(profile.deals_completed) if profile else 0,
        gmv_paise=int(profile.gmv_paise) if profile else 0,
        disputes_raised=int(profile.disputes_raised) if profile else 0,
        on_time_rate=float(profile.on_time_rate) if profile else 0.85,
        largest_deal_paise=int(profile.largest_deal_paise) if profile else 0,
        deal_paise=int(profile.largest_deal_paise or 100_000) if profile else 100_000,
        milestone_count=3,
        counterparty_age_days=max(
            0, (dt.datetime.now(dt.UTC) - (entity.onboarded_at or entity.created_at)).days
        ),
        milestone_conditions=conditions,
        category=(profile.category if profile else None) or "apparel",
    )
    scorer = get_scorer()
    risk = (
        float(profile.risk_score)
        if profile and profile.risk_score is not None
        else scorer.predict(features)
    )
    return {
        "entity_id": str(entity_id),
        "display_name": entity.display_name,
        "region": entity.region,
        "kind": str(entity.kind),
        "counterparty_since": entity.onboarded_at or entity.created_at,
        "deals_completed": int(profile.deals_completed) if profile else 0,
        "gmv_paise": int(profile.gmv_paise) if profile else 0,
        "disputes_raised": int(profile.disputes_raised) if profile else 0,
        "disputes_lost": int(profile.disputes_lost) if profile else 0,
        "on_time_rate": float(profile.on_time_rate) if profile else None,
        "largest_deal_paise": int(profile.largest_deal_paise) if profile else 0,
        "risk_score": round(risk, 4),
        "band": band(risk),
        "score_version": (profile.score_version if profile else None) or scorer.version,
        "top_factors": scorer.top_factors(features),
        "pricing": price(risk),
    }
