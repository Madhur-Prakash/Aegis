"""Suite A -- verifier accuracy over the 150 labelled bundles.

HARD GATE: false releases must be exactly 0.  A false release is unrecoverable
money, so if this is not zero the build is failing, and it is printed loudly.

    python -m evals.suite_a.run
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

from app.config.settings import REJECT_THRESHOLD, RELEASE_THRESHOLD
from evals.runner import (
    DECISIONS,
    GENERATED,
    Result,
    confusion,
    false_releases,
    load_corpus,
    provider_banner,
    run_corpus,
    table,
    write_json,
    write_markdown,
)

# Stated target band, with the reason it is a band and not a number.
ESCALATION_TARGET = (0.12, 0.25)
ESCALATION_RATIONALE = (
    "Too high and the product is a queue with extra steps -- a human ends up "
    "reviewing everything, and the automation has bought nothing. Too low and it "
    "is guessing: the only way to escalate rarely on evidence this varied is to "
    "resolve uncertainty in favour of release, which is exactly the failure mode "
    "the design exists to prevent."
)

BUCKETS = ((0.0, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 0.65), (0.65, 0.85), (0.85, 1.01))


def _calibration(results: list[Result]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for low, high in BUCKETS:
        in_bucket = [r for r in results if low <= float(r.output.confidence) < high]
        if not in_bucket:
            rows.append(
                {
                    "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
                    "n": 0,
                    "mean_confidence": None,
                    "empirical_release_rate": None,
                    "gap": None,
                }
            )
            continue
        mean_conf = sum(float(r.output.confidence) for r in in_bucket) / len(in_bucket)
        empirical = sum(1 for r in in_bucket if r.case.expected == "RELEASE") / len(in_bucket)
        rows.append(
            {
                "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
                "n": len(in_bucket),
                "mean_confidence": round(mean_conf, 4),
                "empirical_release_rate": round(empirical, 4),
                "gap": round(mean_conf - empirical, 4),
            }
        )
    return rows


def _brier(results: list[Result]) -> float:
    """Brier score of confidence against 'RELEASE was the correct action'."""
    total = 0.0
    for r in results:
        outcome = 1.0 if r.case.expected == "RELEASE" else 0.0
        total += (float(r.output.confidence) - outcome) ** 2
    return round(total / len(results), 4)


def _per_category(results: list[Result]) -> list[dict[str, Any]]:
    groups: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        groups[r.case.adversarial or "clean"].append(r)
    rows: list[dict[str, Any]] = []
    for name, group in groups.items():
        correct = sum(1 for r in group if r.correct)
        rows.append(
            {
                "category": name,
                "n": len(group),
                "correct": correct,
                "accuracy": round(correct / len(group), 4),
                "false_releases": sum(
                    1
                    for r in group
                    if r.output.decision == "RELEASE" and r.case.expected != "RELEASE"
                ),
            }
        )
    # Worst category first: the honest way round.
    rows.sort(key=lambda r: (r["accuracy"], -r["n"]))
    return rows


def main() -> int:
    cases = load_corpus(GENERATED / "evidence")
    results = run_corpus(cases)
    matrix = confusion(results)
    bad = false_releases(results)

    total = len(results)
    correct = sum(1 for r in results if r.correct)
    escalated = sum(1 for r in results if r.output.decision == "ESCALATE")
    escalation_rate = escalated / total
    prechecked = sum(1 for r in results if r.output.prechecks.resolved)

    per_category = _per_category(results)
    payload: dict[str, Any] = {
        "suite": "A -- verifier accuracy",
        "provider": provider_banner(),
        "corpus": {
            "bundles": total,
            "adversarial": sum(1 for r in results if r.case.adversarial),
            "labels": {
                label: sum(1 for r in results if r.case.label == label)
                for label in ("should_release", "should_reject", "should_escalate")
            },
        },
        "thresholds": {"release": RELEASE_THRESHOLD, "reject": REJECT_THRESHOLD},
        "calibration_version": results[0].output.breakdown.calibration_version if results else None,
        "accuracy": round(correct / total, 4),
        "confusion_matrix": matrix,
        "false_releases": len(bad),
        "false_release_detail": [
            {
                "bundle_id": r.case.bundle_id,
                "expected": r.case.expected,
                "confidence": float(r.output.confidence),
                "note": r.case.note,
            }
            for r in bad
        ],
        "escalation_rate": round(escalation_rate, 4),
        "escalation_target_band": list(ESCALATION_TARGET),
        "escalation_in_band": ESCALATION_TARGET[0] <= escalation_rate <= ESCALATION_TARGET[1],
        "escalation_rationale": ESCALATION_RATIONALE,
        "brier_score": _brier(results),
        "calibration_buckets": _calibration(results),
        "per_adversarial_category": per_category,
        "worst_category": per_category[0] if per_category else None,
        "resolved_by_deterministic_prechecks": prechecked,
        "resolved_by_deterministic_prechecks_pct": round(prechecked / total, 4),
        "unverifiable_bundles": sum(
            1
            for r in results
            if any(
                v["verdict"] == "UNVERIFIABLE" and v["required"] for v in r.output.clause_verdicts
            )
        ),
        "per_bundle": [
            {
                "bundle_id": r.case.bundle_id,
                "milestone_type": r.case.milestone_type,
                "adversarial": r.case.adversarial,
                "expected": r.case.expected,
                "decision": r.output.decision,
                "confidence": float(r.output.confidence),
                "raw": round(float(r.output.breakdown.raw), 4),
                "correct": r.correct,
                "llm_calls": r.output.llm_calls,
                "unverifiable_required": r.output.breakdown.unverifiable_required,
            }
            for r in results
        ],
    }
    write_json("suite_a.json", payload)

    md = [
        "## Suite A -- verifier accuracy",
        "",
        f"_{payload['provider']['note']}_",
        "",
        f"**False releases: {len(bad)}** across {total} labelled evidence bundles "
        f"({payload['corpus']['adversarial']} adversarial).",
        "",
        "### Confusion matrix (rows = correct label, columns = decision)",
        "",
        table(
            ["expected \\ decided", *DECISIONS],
            [[e, *[matrix[e][d] for d in DECISIONS]] for e in DECISIONS],
        ),
        "",
        f"Accuracy **{payload['accuracy']:.1%}** · escalation rate "
        f"**{escalation_rate:.1%}** (target band "
        f"{ESCALATION_TARGET[0]:.0%}-{ESCALATION_TARGET[1]:.0%}, "
        f"{'in band' if payload['escalation_in_band'] else 'OUT OF BAND'}) · "
        f"Brier **{payload['brier_score']}**",
        "",
        f"{prechecked} of {total} decisions "
        f"({payload['resolved_by_deterministic_prechecks_pct']:.1%}) were resolved by "
        "deterministic pre-checks at zero AI cost.",
        "",
        "### Confidence calibration by bucket",
        "",
        table(
            ["confidence bucket", "n", "mean confidence", "empirical release rate", "gap"],
            [
                [
                    b["bucket"],
                    b["n"],
                    "-" if b["mean_confidence"] is None else f"{b['mean_confidence']:.3f}",
                    "-"
                    if b["empirical_release_rate"] is None
                    else f"{b['empirical_release_rate']:.3f}",
                    "-" if b["gap"] is None else f"{b['gap']:+.3f}",
                ]
                for b in payload["calibration_buckets"]
            ],
        ),
        "",
        "### Per-adversarial-category accuracy (worst first)",
        "",
        table(
            ["category", "n", "correct", "accuracy", "false releases"],
            [
                [c["category"], c["n"], c["correct"], f"{c['accuracy']:.1%}", c["false_releases"]]
                for c in per_category
            ],
        ),
        "",
        f"_Escalation band rationale._ {ESCALATION_RATIONALE}",
        "",
    ]
    write_markdown("suite_a.md", "\n".join(md))

    print("\n".join(md[:12]))
    if bad:
        print("\n" + "!" * 72)
        print(f"!! SUITE A HARD GATE FAILED: {len(bad)} FALSE RELEASE(S)")
        for r in bad:
            print(
                f"!!   {r.case.bundle_id} expected {r.case.expected}, decided RELEASE "
                f"at confidence {float(r.output.confidence):.3f}"
            )
        print("!" * 72)
        return 1
    print(f"\nSuite A: {correct}/{total} correct, 0 false releases (hard gate passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
