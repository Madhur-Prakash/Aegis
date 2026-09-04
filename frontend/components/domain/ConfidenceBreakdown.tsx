"use client";

/**
 * The confidence breakdown (ui/06 §3) -- mandatory.
 *
 * Four bars plus the arithmetic.  This single panel is what makes the claim
 * "we do not trust the model's self-reported confidence" legible rather than
 * merely asserted.
 */

import { Bar, Panel } from "@/components/ui/primitives";
import { Meta } from "@/components/ui/StateChip";
import type { ConfidenceComponents } from "@/lib/api";
import { confidence as fmtConfidence, pct } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function ConfidenceBreakdown({
  components,
  thresholds,
}: {
  components: ConfidenceComponents;
  thresholds: Record<string, unknown>;
}) {
  const { t } = useI18n();
  const release = Number(thresholds.release ?? 0.85);
  const reject = Number(thresholds.reject ?? 0.35);

  const rows = [
    {
      key: "verifiableFraction",
      label: t("verification.verifiableFraction"),
      value: components.verifiable_fraction,
      weight: components.weights.verifiable_fraction,
      tone: "pass" as const,
    },
    {
      key: "llmComponent",
      label: t("verification.llmComponent"),
      value: components.llm_component,
      weight: components.weights.llm_component,
      tone: "neutral" as const,
    },
    {
      key: "extractionQuality",
      label: t("verification.extractionQuality"),
      value: components.extraction_quality,
      weight: components.weights.extraction_quality,
      tone: "neutral" as const,
    },
    {
      key: "penalty",
      label: t("verification.penalty"),
      value: components.unverifiable_penalty,
      weight: null,
      tone: "unverified" as const,
    },
  ];

  return (
    <Panel title={t("verification.breakdown")}>
      <div className="stack" style={{ gap: "var(--sp-3)" }}>
        {rows.map((row, index) => (
          <div key={row.key} className="breakdown-row">
            <div className="row-between">
              <span className="micro">
                {row.label}
                {row.weight !== null ? (
                  <span className="nano" style={{ marginLeft: "var(--sp-2)" }}>
                    ×{row.weight}
                  </span>
                ) : null}
              </span>
              <span className="num">{row.value.toFixed(4)}</span>
            </div>
            <Bar value={row.value} tone={row.tone} label={row.label} index={index} />
          </div>
        ))}
      </div>

      <hr className="rule" />

      <div className="meta-grid">
        <Meta
          label={t("verification.computed")}
          value={<strong className="num">{fmtConfidence(components.computed)}</strong>}
        />
        <Meta label={t("verification.calibration")} value={components.calibration_version} />
        <Meta
          label={t("verification.threshold")}
          value={`≥ ${fmtConfidence(release)} release · ≤ ${fmtConfidence(reject)} reject`}
        />
        <Meta
          label={t("verification.prechecks")}
          value={`${components.deterministic_required_passed}/${components.total_required_clauses} ${pct(
            components.total_required_clauses
              ? components.deterministic_required_passed / components.total_required_clauses
              : 0,
          )}`}
        />
      </div>

      <p className="table-note">{components.formula}</p>
      <p className="table-note">{t("verification.notTrusted")}</p>
    </Panel>
  );
}
