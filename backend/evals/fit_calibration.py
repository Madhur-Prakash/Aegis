"""Fit the confidence calibration map.

Two steps, both fitted on the **calibration corpus** -- a separate corpus
generated with a different seed -- so the 150 evaluation bundles are never
touched by fitting:

1. An isotonic (monotone) estimate of ``p(raw) = P(RELEASE is the correct action
   | raw score)``.
2. A monotone, threshold-anchored transform of ``p`` into the reported
   ``confidence``, so the two thresholds of I3 mean something exact:

       confidence >= 0.85  <=>  p(raw) == 1.0  -- release was always correct here
       confidence <= 0.35  <=>  p(raw) == 0.0  -- release was never correct here
       in between          <=>  genuinely uncertain

   Concretely, with ``r0 = max{raw : p == 0}`` and ``r1 = min{raw : p == 1}``:

       raw <= r0      ->  0.35 * raw / r0                    in [0.00, 0.35]
       r0 < raw < r1  ->  0.35 + 0.50 * p(raw)               in (0.35, 0.85)
       raw >= r1      ->  0.85 + 0.15 * (raw - r1)/(1 - r1)  in [0.85, 1.00]

   Confidence therefore stays on the same 0-1 scale as the raw score, remains
   monotone in it, and is anchored to the empirical release-correctness of the
   calibration corpus rather than to a chosen curve.

    python -m evals.fit_calibration

Writes ``data/generated/calibration.json``.  Until it exists the verifier uses
the identity map and every attestation records
``calibration_version="identity-fallback"``, because a fabricated calibration
would be worse than none.
"""

from __future__ import annotations

import json

from app.agents.verifier.confidence import reset_calibration_cache
from app.config.settings import CALIBRATION_VERSION, REJECT_THRESHOLD, RELEASE_THRESHOLD
from evals.runner import GENERATED, load_corpus, provider_banner, run_corpus

GRID = 81  # knots exported for the piecewise-linear map


def isotonic(xs: list[float], ys: list[float], grid: list[float]) -> list[float]:
    """Monotone non-decreasing fit of ``ys`` on ``xs``, evaluated on ``grid``."""
    try:
        from sklearn.isotonic import IsotonicRegression

        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
        model.fit(xs, ys)
        return [float(v) for v in model.predict(grid)]
    except Exception:
        # Dependency-free fallback: equal-width buckets, then a running maximum
        # so the result is still monotone.
        buckets: list[list[float]] = [[] for _ in range(16)]
        for x, y in zip(xs, ys, strict=True):
            buckets[min(15, int(max(0.0, min(1.0, x)) * 16))].append(y)
        centres = [(i + 0.5) / 16 for i in range(16)]
        values: list[float] = []
        running = 0.0
        for bucket in buckets:
            value = sum(bucket) / len(bucket) if bucket else running
            running = max(running, value)
            values.append(running)
        out: list[float] = []
        for g in grid:
            nearest = min(range(16), key=lambda i: abs(centres[i] - g))
            out.append(values[nearest])
        return out


def main() -> None:
    reset_calibration_cache()
    folder = GENERATED / "calibration"
    if not (folder / "manifest.json").exists():
        raise SystemExit("calibration corpus missing -- run `make dataset` first")

    cases = load_corpus(folder)
    results = run_corpus(cases)

    xs: list[float] = []
    ys: list[float] = []
    for r in results:
        # `raw` is pre-calibration by construction: with no map on disk the
        # identity applies, so breakdown.raw is the uncalibrated score.
        xs.append(max(0.0, min(1.0, float(r.output.breakdown.raw))))
        ys.append(1.0 if r.case.expected == "RELEASE" else 0.0)

    grid = [i / (GRID - 1) for i in range(GRID)]
    p = isotonic(xs, ys, grid)

    # Anchors, from the data rather than from the smoothed curve.
    #
    #   r0 = the highest raw score at which release was NEVER correct
    #   r1 = the lowest raw score at which release was ALWAYS correct
    #
    # When the two classes separate cleanly these are just the class extremes.
    # When they overlap, fall back to the isotonic crossings, which are defined
    # for any corpus.
    release_raw = [x for x, y in zip(xs, ys, strict=True) if y >= 1.0]
    other_raw = [x for x, y in zip(xs, ys, strict=True) if y < 1.0]
    separable = bool(release_raw and other_raw and max(other_raw) < min(release_raw))
    if separable:
        r0 = max(other_raw)
        r1 = min(release_raw)
        anchor_method = "class-separated extremes"
    else:
        zeros = [g for g, v in zip(grid, p, strict=True) if v <= 1e-9]
        ones = [g for g, v in zip(grid, p, strict=True) if v >= 1.0 - 1e-9]
        r0 = max(zeros) if zeros else 0.0
        r1 = min(ones) if ones else 1.0
        anchor_method = "isotonic crossings"
    if r1 <= r0:  # degenerate corpus: keep the map monotone and conservative
        r1 = min(1.0, r0 + 1e-6)
        anchor_method += " (degenerate: forced monotone)"

    confidence: list[float] = []
    for g, pv in zip(grid, p, strict=True):
        if g <= r0 and r0 > 0:
            value = REJECT_THRESHOLD * (g / r0)
        elif g >= r1:
            span = (1.0 - r1) or 1e-9
            value = RELEASE_THRESHOLD + (1.0 - RELEASE_THRESHOLD) * min(1.0, (g - r1) / span)
        else:
            value = REJECT_THRESHOLD + (RELEASE_THRESHOLD - REJECT_THRESHOLD) * pv
        confidence.append(round(max(0.0, min(1.0, value)), 6))

    # Enforce monotonicity explicitly; the interpolator in confidence.py assumes it.
    for i in range(1, len(confidence)):
        confidence[i] = max(confidence[i], confidence[i - 1])

    payload = {
        "version": CALIBRATION_VERSION,
        "x": [round(v, 6) for v in grid],
        "y": confidence,
        "p_release_x": [round(v, 6) for v in grid],
        "p_release_y": [round(v, 6) for v in p],
        "anchors": {
            "method": anchor_method,
            "separable": separable,
            "r0_last_raw_with_zero_release_probability": round(r0, 6),
            "r1_first_raw_with_certain_release": round(r1, 6),
            "max_raw_among_non_release": round(max(other_raw), 6) if other_raw else None,
            "min_raw_among_release": round(min(release_raw), 6) if release_raw else None,
            "reject_threshold": REJECT_THRESHOLD,
            "release_threshold": RELEASE_THRESHOLD,
        },
        "fitted_on": {
            "corpus": "data/generated/calibration",
            "bundles": len(cases),
            "release_rate": round(sum(ys) / len(ys), 4),
            "raw_min": round(min(xs), 6),
            "raw_max": round(max(xs), 6),
            "provider": provider_banner()["ai_provider_effective"],
        },
        "target": "P(RELEASE is the correct action | raw), then threshold-anchored",
        "method": (
            "isotonic regression on the separate calibration corpus, then a monotone "
            "piecewise-linear transform anchored so confidence>=0.85 iff p==1 and "
            "confidence<=0.35 iff p==0"
        ),
        "note": (
            "Fitted on a corpus generated with a different seed. The 150 evaluation "
            "bundles are never used for fitting, so Suite A is a held-out measurement."
        ),
    }
    out = GENERATED / "calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    reset_calibration_cache()

    print(f"calibration {CALIBRATION_VERSION} fitted on {len(cases)} bundles -> {out}")
    print(f"  release rate            {payload['fitted_on']['release_rate']}")
    print(f"  raw range               [{min(xs):.3f}, {max(xs):.3f}]")
    print(f"  anchor method           {anchor_method}")
    print(f"  r0 (release never ok)   {r0:.4f}")
    print(f"  r1 (release always ok)  {r1:.4f}")
    print(f"  confidence range        [{min(confidence):.3f}, {max(confidence):.3f}]")


if __name__ == "__main__":
    main()
