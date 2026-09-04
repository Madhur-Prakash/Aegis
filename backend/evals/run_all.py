"""``make eval`` -- run every suite and regenerate every number in the README.

Writes ``evals/out/*.json`` plus ``evals/out/RESULTS.md``, which the README links
to.  No metric is hardcoded anywhere in the documentation: every one of them is
produced here.

Reproducibility: delete ``evals/out/`` and re-run; the JSON files are identical
apart from timing fields, which are noted as such.

    python -m evals.run_all
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from evals.runner import OUT, provider_banner

HERE = Path(__file__).resolve().parent
STEPS: tuple[tuple[str, str], ...] = (
    ("fit_calibration", "evals.fit_calibration"),
    ("suite_a", "evals.suite_a.run"),
    ("suite_b", "evals.suite_b.run"),
    ("suite_c", "evals.suite_c.run"),
    ("report_d", "evals.report_d.run"),
    ("report_e", "evals.report_e.run"),
)

TIMING_FIELDS = ("latency_ms", "wall_ms", "mean_latency_ms", "p50", "p95", "max")


def run(module: str) -> int:
    print(f"\n{'=' * 72}\n{module}\n{'=' * 72}")
    result = subprocess.run(
        [sys.executable, "-m", module],
        cwd=HERE.parent,
        check=False,
    )
    return result.returncode


def load(name: str) -> dict[str, Any]:
    path = OUT / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    codes: dict[str, int] = {}
    for name, module in STEPS:
        codes[name] = run(module)

    a, b, c, d, e = (load(n) for n in ("suite_a", "suite_b", "suite_c", "report_d", "report_e"))
    banner = provider_banner()

    false_releases = a.get("false_releases")
    gate_ok = false_releases == 0

    summary = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "provider": banner,
        "exit_codes": codes,
        "headline": {
            "false_releases": false_releases,
            "labelled_bundles": (a.get("corpus") or {}).get("bundles"),
            "adversarial_bundles": (a.get("corpus") or {}).get("adversarial"),
            "accuracy": a.get("accuracy"),
            "escalation_rate": a.get("escalation_rate"),
            "escalation_in_band": a.get("escalation_in_band"),
            "brier_score": a.get("brier_score"),
            "resolved_by_prechecks_pct": a.get("resolved_by_deterministic_prechecks_pct"),
            "suite_b": b.get("status"),
            "suite_c": c.get("status"),
            "risk_selected_model": d.get("selected_model"),
            "risk_test_auc": ((d.get("metrics") or {}).get("lightgbm") or {}).get("test_auc")
            if d.get("selected_model") == "lightgbm"
            else ((d.get("metrics") or {}).get("baseline") or {}).get("test_auc"),
            "risk_baseline_test_auc": ((d.get("metrics") or {}).get("baseline") or {}).get(
                "test_auc"
            ),
            "cost_usd_per_verification_measured": (
                (e.get("cost") or {}).get("mean_usd_per_verification")
            ),
            "cost_inr_per_verification_projected": (
                ((e.get("cost") or {}).get("projection_at_pinned_anthropic_prices") or {}).get(
                    "inr_per_verification"
                )
            ),
            "prompt_cache_hit_rate": (e.get("prompt_cache") or {}).get("hit_rate"),
        },
        "hard_gate_false_releases_zero": gate_ok,
        "all_green": gate_ok
        and b.get("status") == "PASS"
        and c.get("status") == "PASS"
        and bool(d.get("ok"))
        and all(code == 0 for code in codes.values()),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    parts = [
        "# Aegis evaluation results",
        "",
        f"Generated {summary['generated_at']} by `make eval`.",
        "",
        f"**AI provider for this run: `{banner['ai_provider_effective']}`** "
        f"(configured `{banner['ai_provider_configured']}`).",
        "",
        f"> {banner['note']}",
        "",
        "## Headline",
        "",
        "| metric | value |",
        "|---|---|",
        f"| False releases (hard gate: must be 0) | **{false_releases}** |",
        f"| Labelled evidence bundles | {summary['headline']['labelled_bundles']} "
        f"({summary['headline']['adversarial_bundles']} adversarial) |",
        f"| Decision accuracy | {summary['headline']['accuracy']} |",
        f"| Escalation rate | {summary['headline']['escalation_rate']} "
        f"({'in band' if summary['headline']['escalation_in_band'] else 'out of band'}) |",
        f"| Brier score (confidence vs release-correctness) | "
        f"{summary['headline']['brier_score']} |",
        f"| Decisions resolved by deterministic pre-checks | "
        f"{summary['headline']['resolved_by_prechecks_pct']} |",
        f"| Suite B (settlement integrity) | {summary['headline']['suite_b']} |",
        f"| Suite C (provenance integrity) | {summary['headline']['suite_c']} |",
        f"| Risk model selected | {summary['headline']['risk_selected_model']} "
        f"(test AUC {summary['headline']['risk_test_auc']}, "
        f"baseline {summary['headline']['risk_baseline_test_auc']}) |",
        f"| Cost per verification (measured) | "
        f"{summary['headline']['cost_usd_per_verification_measured']} USD |",
        f"| Cost per verification (projected at pinned prices) | "
        f"INR {summary['headline']['cost_inr_per_verification_projected']} |",
        f"| Prompt-cache hit rate | {summary['headline']['prompt_cache_hit_rate']} |",
        "",
    ]
    for name in ("suite_a", "suite_b", "suite_c", "report_d", "report_e"):
        md = OUT / f"{name}.md"
        if md.exists():
            parts.append(md.read_text(encoding="utf-8"))
            parts.append("")
    (OUT / "RESULTS.md").write_text("\n".join(parts), encoding="utf-8")

    print(f"\n{'=' * 72}")
    print("EVAL SUMMARY")
    print(f"{'=' * 72}")
    for key, value in summary["headline"].items():
        print(f"  {key:48s} {value}")
    print(f"\n  hard gate (false releases == 0): {'PASS' if gate_ok else 'FAIL'}")
    print(f"  all green: {summary['all_green']}")
    print(f"\n  wrote {OUT / 'RESULTS.md'} and {OUT / 'summary.json'}")
    if not gate_ok:
        print("\n" + "!" * 72)
        print("!! THE BUILD IS FAILING: a false release is unrecoverable money.")
        print("!" * 72)
    return 0 if summary["all_green"] else 1


if __name__ == "__main__":
    sys.exit(main())
