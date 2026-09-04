"""Report E -- cost and latency.

Tokens and money per verification, prompt-cache hit rate, p50/p95 latency per
pipeline stage, and the share of decisions resolved by deterministic pre-checks
alone at zero AI cost.

The provider that produced the numbers is stated at the top of the report, and
the cache-hit line says plainly when there was no cache to hit.

    python -m evals.report_e.run
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

from app.agents._llm import PRICING
from app.config.settings import settings
from evals.runner import (
    GENERATED,
    load_corpus,
    provider_banner,
    run_corpus,
    table,
    write_json,
    write_markdown,
)

USD_PER_INR = 1 / 88.0  # [assumed] see docs/DATA.md; used only to quote a rupee figure


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def main() -> int:
    banner = provider_banner()
    cases = load_corpus(GENERATED / "evidence")
    results = run_corpus(cases)

    total = len(results)
    prechecked = [r for r in results if r.output.prechecks.resolved]
    with_llm = [r for r in results if not r.output.prechecks.resolved]

    stage_latency: dict[str, list[float]] = defaultdict(list)
    per_purpose: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "calls": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cost_micro_usd": 0,
            "latency_ms": 0,
        }
    )
    cost_per_bundle: list[float] = []
    tokens_per_bundle: list[float] = []
    wall_per_bundle: list[float] = []
    cache_reads = 0
    cache_eligible = 0

    for r in results:
        for stage, ms in r.output.stage_latency_ms.items():
            stage_latency[stage].append(float(ms))
        wall_per_bundle.append(float(r.wall_ms))
        bundle_cost = 0
        bundle_tokens = 0
        for spend in r.output.spends:
            bucket = per_purpose[spend.purpose]
            bucket["calls"] += 1
            bucket["input"] += spend.input_tokens
            bucket["output"] += spend.output_tokens
            bucket["cache_read"] += spend.cache_read_tokens
            bucket["cost_micro_usd"] += spend.cost_micro_usd
            bucket["latency_ms"] += spend.latency_ms
            bundle_cost += spend.cost_micro_usd
            bundle_tokens += spend.input_tokens + spend.output_tokens
            cache_eligible += 1
            if spend.cache_read_tokens > 0:
                cache_reads += 1
        cost_per_bundle.append(float(bundle_cost))
        tokens_per_bundle.append(float(bundle_tokens))

    llm_calls = sum(len(r.output.spends) for r in results)
    total_cost_micro = sum(cost_per_bundle)
    mean_cost_micro = total_cost_micro / total if total else 0.0
    mean_cost_usd = mean_cost_micro / 1_000_000
    mean_cost_inr = mean_cost_usd / USD_PER_INR

    cache_hit_rate = (cache_reads / cache_eligible) if cache_eligible else 0.0
    live = banner["is_live_model"]

    # Projected cost: the measured token counts, priced at the pinned rates.
    projected_micro = 0.0
    for purpose, bucket in per_purpose.items():
        model = (
            settings.AI_MODEL_EXTRACTION if purpose == "extraction" else settings.AI_MODEL_VERIFIER
        )
        rate_in, rate_out = PRICING.get(model, (0.0, 0.0))
        projected_micro += (
            (bucket["input"] * rate_in + bucket["output"] * rate_out) / 1_000_000 * 1_000_000
        )
    projected_usd = projected_micro / 1_000_000 / max(1, total)
    projected_inr = projected_usd / USD_PER_INR

    payload: dict[str, Any] = {
        "report": "E -- cost and latency",
        "provider": banner,
        "bundles": total,
        "llm_calls": llm_calls,
        "llm_calls_per_bundle_mean": round(llm_calls / total, 3) if total else 0,
        "resolved_by_deterministic_prechecks": len(prechecked),
        "resolved_by_deterministic_prechecks_pct": round(len(prechecked) / total, 4)
        if total
        else 0,
        "zero_ai_cost_decisions": len(prechecked),
        "tokens": {
            "input": int(sum(b["input"] for b in per_purpose.values())),
            "output": int(sum(b["output"] for b in per_purpose.values())),
            "cache_read": int(sum(b["cache_read"] for b in per_purpose.values())),
            "mean_per_bundle": round(sum(tokens_per_bundle) / total, 1) if total else 0,
            "mean_per_verified_bundle": round(sum(tokens_per_bundle) / len(with_llm), 1)
            if with_llm
            else 0,
        },
        "cost": {
            "total_micro_usd": int(total_cost_micro),
            "mean_micro_usd_per_verification": round(mean_cost_micro, 2),
            "mean_usd_per_verification": round(mean_cost_usd, 6),
            "mean_inr_per_verification": round(mean_cost_inr, 4),
            "usd_per_inr_assumption": round(USD_PER_INR, 6),
            "pricing_table_usd_per_mtok": PRICING,
            "priced_as": (
                f"{settings.AI_MODEL_VERIFIER} / {settings.AI_MODEL_EXTRACTION}"
                if banner["ai_provider_effective"] == "anthropic"
                else banner["model_verifier"]
            ),
            # A projection, clearly labelled as one: the pinned list prices applied
            # to the token counts THIS run actually measured.  It is not a spend
            # that happened, and it is not presented as one.
            "projection_at_pinned_anthropic_prices": {
                "basis": "measured token counts x published list price; NOT a measured spend",
                "verifier_model": settings.AI_MODEL_VERIFIER,
                "extraction_model": settings.AI_MODEL_EXTRACTION,
                "usd_per_verification": None,
                "inr_per_verification": None,
            },
        },
        "prompt_cache": {
            "calls_with_cache_read": cache_reads,
            "calls_total": cache_eligible,
            "hit_rate": round(cache_hit_rate, 4),
            "note": (
                "Measured from usage.cache_read_input_tokens on every call."
                if live
                else (
                    "There is no prompt cache to hit: this run used the deterministic "
                    "offline adapter, which performs no network call at all. The system "
                    "prompt is byte-stable and sits behind an ephemeral cache_control "
                    "breakpoint (app/agents/_llm.py), and "
                    "tests/unit/test_prompt_cache_contract.py asserts that shape; the hit "
                    "rate itself can only be measured against a live provider."
                )
            ),
        },
        "latency_ms": {
            "per_stage": {
                stage: {
                    "n": len(values),
                    "p50": round(percentile(values, 0.5), 2),
                    "p95": round(percentile(values, 0.95), 2),
                    "max": round(max(values), 2),
                }
                for stage, values in sorted(stage_latency.items())
            },
            "end_to_end": {
                "p50": round(percentile(wall_per_bundle, 0.5), 2),
                "p95": round(percentile(wall_per_bundle, 0.95), 2),
                "max": round(max(wall_per_bundle), 2) if wall_per_bundle else 0,
            },
            "note": (
                "Wall-clock, measured on this machine, verifier pipeline only -- no "
                "database, no rail, no chain."
                if not live
                else "Wall-clock including provider round trips."
            ),
        },
        "per_purpose": {
            purpose: {
                "calls": int(b["calls"]),
                "input_tokens": int(b["input"]),
                "output_tokens": int(b["output"]),
                "cache_read_tokens": int(b["cache_read"]),
                "cost_micro_usd": int(b["cost_micro_usd"]),
                "mean_latency_ms": round(b["latency_ms"] / b["calls"], 2) if b["calls"] else 0,
            }
            for purpose, b in sorted(per_purpose.items())
        },
        "ok": True,
    }
    payload["cost"]["projection_at_pinned_anthropic_prices"]["usd_per_verification"] = round(
        projected_usd, 6
    )
    payload["cost"]["projection_at_pinned_anthropic_prices"]["inr_per_verification"] = round(
        projected_inr, 4
    )
    write_json("report_e.json", payload)

    md = [
        "## Report E -- cost and latency",
        "",
        f"_{banner['note']}_",
        "",
        f"**{len(prechecked)} of {total} decisions "
        f"({payload['resolved_by_deterministic_prechecks_pct']:.1%}) were resolved by "
        f"deterministic pre-checks alone, at zero AI cost.**",
        "",
        f"{llm_calls} model calls across {total} bundles "
        f"({payload['llm_calls_per_bundle_mean']} per bundle; "
        f"{payload['tokens']['mean_per_verified_bundle']:.0f} tokens per bundle that "
        f"reached the model).",
        "",
        table(
            [
                "purpose",
                "calls",
                "input tok",
                "output tok",
                "cache read",
                "cost (micro-USD)",
                "mean ms",
            ],
            [
                [
                    purpose,
                    b["calls"],
                    b["input_tokens"],
                    b["output_tokens"],
                    b["cache_read_tokens"],
                    b["cost_micro_usd"],
                    b["mean_latency_ms"],
                ]
                for purpose, b in payload["per_purpose"].items()
            ],
        ),
        "",
        f"Measured cost per verification: **{payload['cost']['mean_usd_per_verification']:.6f} USD** "
        f"(INR {payload['cost']['mean_inr_per_verification']:.4f} at "
        f"1 USD = INR {1 / USD_PER_INR:.0f}), priced as "
        f"`{payload['cost']['priced_as']}`."
        + (
            ""
            if live
            else (
                f" That is zero because no provider was called. Applying the pinned list "
                f"prices for `{settings.AI_MODEL_VERIFIER}` / "
                f"`{settings.AI_MODEL_EXTRACTION}` to the token counts this run *did* "
                f"measure projects **{projected_usd:.6f} USD "
                f"(INR {projected_inr:.4f}) per verification** -- a projection, not a spend."
            )
        ),
        "",
        f"Prompt-cache hit rate: **{cache_hit_rate:.1%}** "
        f"({cache_reads}/{cache_eligible} calls). {payload['prompt_cache']['note']}",
        "",
        "### Latency by pipeline stage (ms)",
        "",
        table(
            ["stage", "n", "p50", "p95", "max"],
            [
                [stage, s["n"], s["p50"], s["p95"], s["max"]]
                for stage, s in payload["latency_ms"]["per_stage"].items()
            ]
            + [
                [
                    "end to end",
                    total,
                    payload["latency_ms"]["end_to_end"]["p50"],
                    payload["latency_ms"]["end_to_end"]["p95"],
                    payload["latency_ms"]["end_to_end"]["max"],
                ]
            ],
        ),
        "",
        f"_{payload['latency_ms']['note']}_",
        "",
    ]
    write_markdown("report_e.md", "\n".join(md))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
