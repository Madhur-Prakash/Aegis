"use client";

/**
 * Risk and pricing (ui/06 §6).
 *
 * A score on its own is an accusation.  The three factors that moved it, in
 * plain language and with their signed contribution, are an explanation -- so
 * the score is never rendered without them.
 *
 * `model_kind` is shown as measured, not as marketing: when the gradient-boosted
 * model loses to the logistic baseline on validation AUC, this panel says
 * `logistic`, because that is what is actually scoring the deal.
 */

import { Meta } from "@/components/ui/StateChip";
import { Bar, Panel } from "@/components/ui/primitives";
import type { Passport, RiskFactor } from "@/lib/api";
import { inr, num, pct, riskTone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function RiskFactors({ factors }: { factors: RiskFactor[] }) {
  const { t } = useI18n();
  const largest = Math.max(...factors.map((factor) => Math.abs(factor.delta)), 0.0001);
  return (
    <div className="stack" style={{ gap: "var(--sp-3)" }}>
      <span className="micro">{t("reputation.topFactors")}</span>
      {factors.length === 0 ? <p className="state-body">{t("reputation.noFactors")}</p> : null}
      {factors.map((factor, index) => (
        <div className="breakdown-row" key={factor.feature}>
          <div className="row-between">
            <span style={{ fontSize: "var(--fs-sm)" }}>{factor.plain_language}</span>
            <span
              className="num"
              style={{
                color: factor.direction === "increases" ? "var(--sig-fail)" : "var(--sig-pass)",
              }}
            >
              {factor.sign}
              {num(Math.abs(factor.delta), 4)}
            </span>
          </div>
          <Bar
            value={Math.abs(factor.delta) / largest}
            tone={factor.direction === "increases" ? "fail" : "pass"}
            label={factor.plain_language}
            index={index}
          />
        </div>
      ))}
    </div>
  );
}

export function RiskScore({
  score,
  band,
  version,
  modelKind,
}: {
  score: number;
  band: string;
  version: string;
  modelKind?: string;
}) {
  const { t } = useI18n();
  const tone = riskTone(score);
  return (
    <div className="stack" style={{ gap: "var(--sp-3)" }}>
      <div className="row-between">
        <span className="micro">{t("reputation.risk")}</span>
        <span className="num" style={{ color: `var(--sig-${tone})`, fontSize: "var(--fs-h3)" }}>
          {score.toFixed(3)}
        </span>
      </div>
      <Bar value={score} tone={tone} label={t("reputation.risk")} />
      <div className="meta-grid">
        <Meta label={t("reputation.band")} value={band} />
        <Meta label={t("reputation.scoreVersion")} value={version} />
        {modelKind ? <Meta label={t("reputation.model")} value={modelKind} /> : null}
      </div>
    </div>
  );
}

export function PricingPanel({ pricing }: { pricing: Passport["pricing"] }) {
  const { t } = useI18n();
  return (
    <Panel title={t("reputation.pricing")}>
      {pricing.accepted ? (
        <div className="meta-grid">
          <Meta label={t("reputation.tier")} value={pricing.tier} />
          {/* The tiers quote whole percents (spec 22: 0.8 is 0.8%, 30 is 30%);
              pct() formats a fraction, so divide before formatting. */}
          <Meta
            label={t("reputation.escrowFee")}
            value={pricing.escrow_fee_pct === null ? "-" : pct(pricing.escrow_fee_pct / 100, 2)}
          />
          <Meta
            label={t("reputation.hold")}
            value={
              pricing.hold_days_after_final_release === null
                ? "-"
                : `${pricing.hold_days_after_final_release} ${t("reputation.days")}`
            }
          />
          <Meta
            label={t("reputation.prefund")}
            value={pricing.buyer_prefund_pct === null ? "-" : pct(pricing.buyer_prefund_pct / 100, 0)}
          />
        </div>
      ) : (
        <div className="state-block state-block--error" role="status">
          <span className="mono-code">{pricing.tier}</span>
          <p className="state-body">{t("reputation.declined")}</p>
        </div>
      )}
    </Panel>
  );
}

export function PassportPanel({ passport }: { passport: Passport }) {
  const { t } = useI18n();
  return (
    <Panel title={t("reputation.counterparty")}>
      <div className="stack" style={{ gap: "var(--sp-4)" }}>
        <div className="row-between">
          <h3 className="display-3">{passport.display_name}</h3>
          <span className="micro">
            {passport.kind}
            {passport.region ? ` · ${passport.region}` : ""}
          </span>
        </div>
        <div className="meta-grid">
          <Meta label={t("reputation.since")} value={passport.counterparty_since} />
          <Meta label={t("reputation.dealsCompleted")} value={num(passport.deals_completed)} />
          <Meta label={t("reputation.gmv")} value={inr(passport.gmv_paise)} />
          <Meta
            label={t("reputation.disputes")}
            value={`${passport.disputes_raised} / ${passport.disputes_lost} ${t(
              "reputation.lost",
            )}`}
          />
          <Meta
            label={t("reputation.onTime")}
            value={passport.on_time_rate === null ? "-" : pct(passport.on_time_rate, 0)}
          />
          <Meta label={t("reputation.largestDeal")} value={inr(passport.largest_deal_paise)} />
        </div>
      </div>
    </Panel>
  );
}
