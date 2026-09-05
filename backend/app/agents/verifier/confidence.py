"""Stage 4: confidence, computed in Python.

We do not trust the model's self-reported confidence.  Confidence is computed
from how much of the condition was checkable deterministically, and calibrated
against a labelled set.

    verifiable_fraction = deterministic_required_clauses_passed / total_required
    llm_component       = mean(clause_confidence for non-UNVERIFIABLE clauses)
    penalty             = 0.5 * (unverifiable_required / total_required)
    raw                 = 0.45*verifiable_fraction + 0.45*llm_component
                          + 0.10*mean(extraction_quality)
    confidence          = calibrate(raw - penalty)

The calibration map is an isotonic (monotone, piecewise-linear) fit of raw score
to the empirical probability that a release is the correct action.  It is fitted
on a **separate** calibration corpus generated with a different seed, so the 150
evaluation bundles are never touched by fitting.  Without a fitted map the
identity is used and the version string says so, because a fabricated
calibration would be worse than none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config.settings import CALIBRATION_VERSION

# app/agents/verifier/confidence.py -> app/agents/verifier -> agents -> app -> backend -> repo root
CALIBRATION_PATH = Path(__file__).resolve().parents[4] / "data" / "generated" / "calibration.json"


@dataclass(slots=True)
class ConfidenceBreakdown:
    verifiable_fraction: float
    llm_component: float
    extraction_quality: float
    unverifiable_penalty: float
    raw: float
    calibrated: float
    calibration_version: str
    total_required_clauses: int
    deterministic_required_passed: int
    unverifiable_required: int
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "verifiable_fraction": 0.45,
            "llm_component": 0.45,
            "extraction_quality": 0.10,
        }
    )

    def as_json(self) -> dict[str, Any]:
        return {
            "verifiable_fraction": round(self.verifiable_fraction, 4),
            "llm_component": round(self.llm_component, 4),
            "extraction_quality": round(self.extraction_quality, 4),
            "unverifiable_penalty": round(-self.unverifiable_penalty, 4),
            "raw": round(self.raw, 4),
            "computed": round(self.calibrated, 3),
            "weights": self.weights,
            "calibration_version": self.calibration_version,
            "total_required_clauses": self.total_required_clauses,
            "deterministic_required_passed": self.deterministic_required_passed,
            "unverifiable_required_clauses": self.unverifiable_required,
            "formula": (
                "0.45*verifiable_fraction + 0.45*llm_component + 0.10*extraction_quality "
                "- 0.5*(unverifiable_required/total_required), then calibrated"
            ),
        }


_map_cache: dict[str, Any] | None = None


def load_calibration() -> dict[str, Any]:
    global _map_cache
    if _map_cache is None:
        if CALIBRATION_PATH.exists():
            try:
                _map_cache = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
            except Exception:
                _map_cache = {"version": "identity-fallback", "x": [], "y": []}
        else:
            _map_cache = {"version": "identity-fallback", "x": [], "y": []}
    return _map_cache


def reset_calibration_cache() -> None:
    global _map_cache
    _map_cache = None


def calibrate(raw: float) -> tuple[float, str]:
    """Piecewise-linear interpolation over the fitted monotone map."""
    clipped = max(0.0, min(1.0, raw))
    payload = load_calibration()
    xs: list[float] = payload.get("x") or []
    ys: list[float] = payload.get("y") or []
    version = str(payload.get("version") or CALIBRATION_VERSION)
    if len(xs) < 2 or len(xs) != len(ys):
        return round(clipped, 3), "identity-fallback"
    if clipped <= xs[0]:
        return round(max(0.0, min(1.0, ys[0])), 3), version
    if clipped >= xs[-1]:
        return round(max(0.0, min(1.0, ys[-1])), 3), version
    for i in range(1, len(xs)):
        if clipped <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            span = (x1 - x0) or 1e-9
            value = y0 + (y1 - y0) * (clipped - x0) / span
            return round(max(0.0, min(1.0, value)), 3), version
    return round(clipped, 3), version


def _clamp_unit(value: Any) -> float:
    """A model-supplied score, forced into [0, 1].  NaN and infinity become 0.0."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, min(1.0, number))


def compute_confidence(
    *,
    clause_verdicts: list[dict[str, Any]],
    deterministic_clause_results: dict[str, dict[str, Any]],
    extraction_qualities: list[float],
) -> ConfidenceBreakdown:
    required = [v for v in clause_verdicts if v.get("required", True)]
    total_required = max(1, len(required))

    deterministic_passed = sum(
        1
        for v in required
        if deterministic_clause_results.get(str(v["clause_id"]), {}).get("verdict") == "PASS"
    )
    verifiable_fraction = deterministic_passed / total_required

    # `clause_confidence` is the one number in this computation that comes from
    # the model, so it is the one number an injected prompt can choose.  Clamped
    # to [0, 1] per clause, not merely at the end: `calibrate` clips its input,
    # but it clips *after* the unverifiable penalty has been subtracted, so a
    # single clause reporting 1e6 washed the penalty out entirely and drove the
    # calibrated confidence to 1.0.  That turns an ESCALATE -- a milestone a
    # human was supposed to look at -- into an auto-RELEASE, which is precisely
    # the model reaching the money that I2 exists to prevent.  A non-finite value
    # is treated as no answer at all rather than propagating a NaN through the
    # comparison in `decide`, where every ordering test would silently be False.
    judged = [
        _clamp_unit(v.get("clause_confidence"))
        for v in clause_verdicts
        if v.get("verdict") != "UNVERIFIABLE"
    ]
    llm_component = sum(judged) / len(judged) if judged else 0.0

    quality = sum(extraction_qualities) / len(extraction_qualities) if extraction_qualities else 0.0

    unverifiable_required = sum(1 for v in required if v.get("verdict") == "UNVERIFIABLE")
    penalty = 0.5 * (unverifiable_required / total_required)

    raw = 0.45 * verifiable_fraction + 0.45 * llm_component + 0.10 * quality
    calibrated, version = calibrate(raw - penalty)

    return ConfidenceBreakdown(
        verifiable_fraction=verifiable_fraction,
        llm_component=llm_component,
        extraction_quality=quality,
        unverifiable_penalty=penalty,
        raw=raw - penalty,
        calibrated=calibrated,
        calibration_version=version,
        total_required_clauses=total_required,
        deterministic_required_passed=deterministic_passed,
        unverifiable_required=unverifiable_required,
    )
