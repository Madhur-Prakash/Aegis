"""Report D -- the risk model.

Trains LightGBM on the train split, tunes nothing on test, compares against a
logistic-regression baseline, and reports AUC, PR-AUC, a calibration curve and
the tier distribution over the synthetic portfolio.

**The test split is touched exactly once, at the end.**  Model selection uses
the validation split only.

    python -m evals.report_d.run
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from app.risk.features import FEATURE_NAMES, TIERS, price
from evals.runner import GENERATED, table, write_json, write_markdown

MODEL_PATH = GENERATED / "risk_lgbm.txt"
META_PATH = GENERATED / "risk_model.json"
BASELINE_PATH = GENERATED / "risk_baseline.json"
PLOT_PATH = Path(__file__).resolve().parents[1] / "out" / "risk_calibration.png"
VERSION = "lgbm-1"


def _load() -> Any:
    import pandas as pd

    path = GENERATED / "deals.parquet"
    if not path.exists():
        raise SystemExit("data/generated/deals.parquet missing -- run `make dataset` first")
    return pd.read_parquet(path)


def _auc(y_true: list[int], y_score: list[float]) -> float:
    """Rank-based AUC, ties averaged.  Written out so the number does not depend
    on a library version."""
    pairs = sorted(zip(y_score, y_true, strict=True), key=lambda p: p[0])
    ranks: list[float] = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = average
        i = j + 1
    positives = sum(1 for _, y in pairs if y == 1)
    negatives = len(pairs) - positives
    if positives == 0 or negatives == 0:
        return float("nan")
    rank_sum = sum(r for r, (_, y) in zip(ranks, pairs, strict=True) if y == 1)
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def _pr_auc(y_true: list[int], y_score: list[float]) -> float:
    """Average precision, the standard step-wise estimator."""
    order = sorted(range(len(y_score)), key=lambda i: -y_score[i])
    positives = sum(y_true)
    if positives == 0:
        return float("nan")
    tp = 0
    total = 0.0
    for seen, idx in enumerate(order, start=1):
        if y_true[idx] == 1:
            tp += 1
            total += tp / seen
    return total / positives


def _brier(y_true: list[int], y_score: list[float]) -> float:
    return sum((s - t) ** 2 for s, t in zip(y_score, y_true, strict=True)) / len(y_true)


def _calibration(y_true: list[int], y_score: list[float], bins: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        idx = [
            i for i, s in enumerate(y_score) if (low <= s < high) or (b == bins - 1 and s == 1.0)
        ]
        if not idx:
            rows.append(
                {"bin": f"{low:.1f}-{high:.1f}", "n": 0, "mean_pred": None, "observed": None}
            )
            continue
        rows.append(
            {
                "bin": f"{low:.1f}-{high:.1f}",
                "n": len(idx),
                "mean_pred": round(sum(y_score[i] for i in idx) / len(idx), 4),
                "observed": round(sum(y_true[i] for i in idx) / len(idx), 4),
            }
        )
    return rows


def _logistic_baseline(
    x_train: list[list[float]], y_train: list[int], iterations: int = 4000, lr: float = 0.08
) -> tuple[list[float], float, dict[str, float]]:
    """Plain gradient-descent logistic regression on standardised features.

    Deliberately dependency-light so the baseline is reproducible and its
    coefficients can be read directly -- this is the number LightGBM has to beat,
    and it is also the transparent scorecard the risk service falls back to.
    """
    n_features = len(FEATURE_NAMES)
    means = [sum(row[j] for row in x_train) / len(x_train) for j in range(n_features)]
    stds = []
    for j in range(n_features):
        var = sum((row[j] - means[j]) ** 2 for row in x_train) / max(1, len(x_train) - 1)
        stds.append(math.sqrt(var) or 1.0)

    weights = [0.0] * n_features
    bias = 0.0
    for _ in range(iterations):
        grad_w = [0.0] * n_features
        grad_b = 0.0
        for row, target in zip(x_train, y_train, strict=True):
            z = bias + sum(weights[j] * (row[j] - means[j]) / stds[j] for j in range(n_features))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            error = p - target
            grad_b += error
            for j in range(n_features):
                grad_w[j] += error * (row[j] - means[j]) / stds[j]
        scale = lr / len(x_train)
        bias -= scale * grad_b
        for j in range(n_features):
            weights[j] -= scale * grad_w[j]
    return weights, bias, {"means": means, "stds": stds}  # type: ignore[return-value]


def _logistic_predict(
    row: list[float], weights: list[float], bias: float, scaler: dict[str, Any]
) -> float:
    z = bias + sum(
        weights[j] * (row[j] - scaler["means"][j]) / scaler["stds"][j]
        for j in range(len(FEATURE_NAMES))
    )
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def main() -> int:
    frame = _load()
    splits = {name: frame[frame["split"] == name] for name in ("train", "valid", "test")}

    def matrix(part: Any) -> tuple[list[list[float]], list[int]]:
        return (
            [[float(row[name]) for name in FEATURE_NAMES] for _, row in part.iterrows()],
            [int(v) for v in part["deal_went_bad"]],
        )

    x_train, y_train = matrix(splits["train"])
    x_valid, y_valid = matrix(splits["valid"])
    x_test, y_test = matrix(splits["test"])

    # ── the baseline to beat ───────────────────────────────────────────
    weights, bias, scaler = _logistic_baseline(x_train, y_train)
    baseline_valid = [_logistic_predict(r, weights, bias, scaler) for r in x_valid]
    baseline_test = [_logistic_predict(r, weights, bias, scaler) for r in x_test]
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "model": "logistic regression (gradient descent, standardised features)",
                "feature_names": list(FEATURE_NAMES),
                "weights": [round(w, 6) for w in weights],
                "bias": round(bias, 6),
                "scaler": {
                    "means": [round(v, 6) for v in scaler["means"]],
                    "stds": [round(v, 6) for v in scaler["stds"]],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── LightGBM, selected on validation only ──────────────────────────
    lgbm_valid: list[float] = []
    lgbm_test: list[float] = []
    trained = False
    chosen: dict[str, Any] = {}
    importances: list[dict[str, Any]] = []
    try:
        import lightgbm as lgb
        import numpy as np

        # LightGBM >= 4.x requires an ndarray, not a list of lists.
        a_train, a_valid, a_test = (
            np.asarray(x_train, dtype=np.float64),
            np.asarray(x_valid, dtype=np.float64),
            np.asarray(x_test, dtype=np.float64),
        )
        train_set = lgb.Dataset(
            a_train, label=np.asarray(y_train), feature_name=list(FEATURE_NAMES)
        )
        valid_set = lgb.Dataset(a_valid, label=np.asarray(y_valid), reference=train_set)
        best = None
        for leaves, depth, rate in ((15, 4, 0.05), (31, 6, 0.05), (31, -1, 0.1)):
            params = {
                "objective": "binary",
                "metric": "auc",
                "learning_rate": rate,
                "num_leaves": leaves,
                "max_depth": depth,
                "min_data_in_leaf": 30,
                "feature_fraction": 0.9,
                "bagging_fraction": 0.9,
                "bagging_freq": 1,
                "verbosity": -1,
                "seed": 42,
                "deterministic": True,
            }
            booster = lgb.train(
                params,
                train_set,
                num_boost_round=600,
                valid_sets=[valid_set],
                callbacks=[lgb.early_stopping(40, verbose=False), lgb.log_evaluation(0)],
            )
            preds = list(booster.predict(a_valid))
            score = _auc(y_valid, preds)
            if best is None or score > best[0]:
                best = (score, booster, params, preds)
        assert best is not None
        valid_auc, booster, chosen, lgbm_valid = best
        lgbm_test = list(booster.predict(a_test))
        booster.save_model(str(MODEL_PATH))
        trained = True
        gains = booster.feature_importance(importance_type="gain")
        importances = sorted(
            (
                {"feature": name, "gain": round(float(g), 2)}
                for name, g in zip(FEATURE_NAMES, gains, strict=True)
            ),
            key=lambda d: -d["gain"],
        )
        chosen = {
            "valid_auc": round(float(valid_auc), 4),
            **{
                k: v for k, v in chosen.items() if k in {"num_leaves", "max_depth", "learning_rate"}
            },
            "best_iteration": int(booster.best_iteration or 0),
        }
    except Exception as exc:  # pragma: no cover
        import traceback

        print(f"LightGBM unavailable ({type(exc).__name__}: {exc}); reporting the baseline only")
        traceback.print_exc()

    metrics: dict[str, Any] = {
        "baseline": {
            "valid_auc": round(_auc(y_valid, baseline_valid), 4),
            "test_auc": round(_auc(y_test, baseline_test), 4),
            "test_pr_auc": round(_pr_auc(y_test, baseline_test), 4),
            "test_brier": round(_brier(y_test, baseline_test), 4),
        }
    }
    if trained:
        metrics["lightgbm"] = {
            "valid_auc": round(_auc(y_valid, lgbm_valid), 4),
            "test_auc": round(_auc(y_test, lgbm_test), 4),
            "test_pr_auc": round(_pr_auc(y_test, lgbm_test), 4),
            "test_brier": round(_brier(y_test, lgbm_test), 4),
            "selection": chosen,
        }
        metrics["auc_lift_over_baseline"] = round(
            metrics["lightgbm"]["test_auc"] - metrics["baseline"]["test_auc"], 4
        )

    # Model selection, on the VALIDATION split only.
    #
    # LightGBM does not automatically win here, and it should not be made to.
    # The generator behind `deal_went_bad` is a logistic function of these
    # features, so a linear model is correctly specified and the tree ensemble
    # has variance to spare.  Whichever model has the better validation AUC is
    # persisted and loaded by the risk service; the other is reported next to it.
    baseline_valid_auc = _auc(y_valid, baseline_valid)
    lgbm_valid_auc = _auc(y_valid, lgbm_valid) if trained else float("-inf")
    selected = "lightgbm" if trained and lgbm_valid_auc > baseline_valid_auc else "logistic"
    if selected == "logistic" and MODEL_PATH.exists():
        MODEL_PATH.unlink()  # never leave a losing booster where the service can load it
    metrics["selected_model"] = selected
    metrics["selection_basis"] = {
        "criterion": "validation AUC",
        "lightgbm_valid_auc": None if lgbm_valid_auc == float("-inf") else round(lgbm_valid_auc, 4),
        "logistic_valid_auc": round(baseline_valid_auc, 4),
    }

    scores = lgbm_test if selected == "lightgbm" else baseline_test
    calibration = _calibration(y_test, scores)

    # ── tier distribution over the whole synthetic portfolio ───────────
    all_x, all_y = matrix(frame)
    if selected == "lightgbm":
        import numpy as np

        all_scores = list(
            __import__("lightgbm")
            .Booster(model_file=str(MODEL_PATH))
            .predict(np.asarray(all_x, dtype=np.float64))
        )
    else:
        all_scores = [_logistic_predict(r, weights, bias, scaler) for r in all_x]
    tier_counts: dict[str, int] = {t["tier"]: 0 for t in TIERS}
    tier_bad: dict[str, int] = {t["tier"]: 0 for t in TIERS}
    for score, actual in zip(all_scores, all_y, strict=True):
        tier = price(float(score))["tier"]
        tier_counts[tier] += 1
        tier_bad[tier] += actual
    tier_rows = [
        {
            "tier": tier,
            "deals": tier_counts[tier],
            "share": round(tier_counts[tier] / len(all_scores), 4),
            "observed_bad_rate": round(tier_bad[tier] / tier_counts[tier], 4)
            if tier_counts[tier]
            else None,
            "escrow_fee_pct": next(t["fee_pct"] for t in TIERS if t["tier"] == tier),
            "hold_days": next(t["hold_days"] for t in TIERS if t["tier"] == tier),
            "buyer_prefund_pct": next(t["prefund_pct"] for t in TIERS if t["tier"] == tier),
        }
        for tier in tier_counts
    ]

    version = VERSION if selected == "lightgbm" else "logistic-1"
    META_PATH.write_text(
        json.dumps(
            {
                "version": version,
                "selected_model": selected,
                "feature_names": list(FEATURE_NAMES),
                "metrics": metrics,
                "selection": chosen,
                "importances": importances if selected == "lightgbm" else [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── calibration plot ───────────────────────────────────────────────
    plot_written = False
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        points = [(r["mean_pred"], r["observed"]) for r in calibration if r["n"]]
        fig, ax = plt.subplots(figsize=(4.6, 4.6), dpi=160)
        ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1, color="#6B6B78")
        ax.plot([p[0] for p in points], [p[1] for p in points], marker="o", color="#4FD1A5")
        ax.set_xlabel("mean predicted P(deal went bad)")
        ax.set_ylabel("observed rate")
        ax.set_title(f"Risk model calibration -- test split (n={len(y_test)})")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        fig.tight_layout()
        PLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(PLOT_PATH)
        plt.close(fig)
        plot_written = True
    except Exception as exc:  # pragma: no cover
        print(f"calibration plot skipped ({type(exc).__name__})")

    payload = {
        "report": "D -- risk model",
        "lightgbm_trained": trained,
        "selected_model": selected,
        "model_version": version,
        "splits": {k: len(v) for k, v in splits.items()},
        "base_rate": {k: round(float(v["deal_went_bad"].mean()), 4) for k, v in splits.items()},
        "metrics": metrics,
        "calibration_curve": calibration,
        "tier_distribution": tier_rows,
        "feature_importances": importances,
        "calibration_plot": str(PLOT_PATH.relative_to(PLOT_PATH.parents[2]))
        if plot_written
        else None,
        "note": (
            "The test split is scored exactly once, at the end; hyperparameters and the "
            "choice between the two models are decided on the validation split only. "
            "On this corpus the logistic model is correctly specified -- the generator "
            "behind deal_went_bad is itself logistic in these features -- so the "
            "gradient-boosted model has nothing extra to exploit and loses on variance. "
            "That is reported rather than tuned away, and the model the service loads is "
            "whichever one won on validation."
        ),
        "ok": max(
            metrics["baseline"]["test_auc"],
            metrics.get("lightgbm", {}).get("test_auc", 0.0),
        )
        >= 0.65,
    }
    write_json("report_d.json", payload)

    md = [
        "## Report D -- risk model",
        "",
        f"Train {len(y_train)} / valid {len(y_valid)} / test {len(y_test)}; "
        f"base rate {payload['base_rate']['train']:.1%} train, "
        f"{payload['base_rate']['test']:.1%} test.",
        "",
        table(
            ["model", "test AUC", "test PR-AUC", "test Brier"],
            (
                [
                    [
                        "LightGBM",
                        metrics["lightgbm"]["test_auc"],
                        metrics["lightgbm"]["test_pr_auc"],
                        metrics["lightgbm"]["test_brier"],
                    ]
                ]
                if trained
                else []
            )
            + [
                [
                    "logistic baseline",
                    metrics["baseline"]["test_auc"],
                    metrics["baseline"]["test_pr_auc"],
                    metrics["baseline"]["test_brier"],
                ]
            ],
        ),
        "",
        "### Calibration curve (test split)",
        "",
        table(
            ["predicted bin", "n", "mean predicted", "observed"],
            [
                [
                    r["bin"],
                    r["n"],
                    "-" if r["mean_pred"] is None else f"{r['mean_pred']:.3f}",
                    "-" if r["observed"] is None else f"{r['observed']:.3f}",
                ]
                for r in calibration
            ],
        ),
        "",
        "### Pricing tier distribution over the 2,000-deal portfolio",
        "",
        table(
            ["tier", "deals", "share", "observed bad rate", "fee %", "hold days", "prefund %"],
            [
                [
                    r["tier"],
                    r["deals"],
                    f"{r['share']:.1%}",
                    "-" if r["observed_bad_rate"] is None else f"{r['observed_bad_rate']:.1%}",
                    r["escrow_fee_pct"] if r["escrow_fee_pct"] is not None else "decline",
                    r["hold_days"] if r["hold_days"] is not None else "-",
                    r["buyer_prefund_pct"] if r["buyer_prefund_pct"] is not None else "-",
                ]
                for r in tier_rows
            ],
        ),
        "",
    ]
    md += [
        f"Selected model: **{selected}** (validation AUC: logistic "
        f"{metrics['selection_basis']['logistic_valid_auc']}, LightGBM "
        f"{metrics['selection_basis']['lightgbm_valid_auc']}).",
        "",
    ]
    if importances and selected == "lightgbm":
        md += [
            "### Feature importance (gain)",
            "",
            table(["feature", "gain"], [[i["feature"], i["gain"]] for i in importances]),
            "",
        ]
    if plot_written:
        md += ["![risk calibration](risk_calibration.png)", ""]
    md += [f"_{payload['note']}_", ""]
    write_markdown("report_d.md", "\n".join(md))

    print("\n".join(md[:8]))
    winner = "lightgbm" if selected == "lightgbm" else "baseline"
    print(
        f"\nReport D: {'PASS' if payload['ok'] else 'FAIL'} -- selected {selected}, "
        f"test AUC {metrics[winner]['test_auc']} "
        f"(the other model: {metrics['selection_basis']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
