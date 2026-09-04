"use client";

/**
 * The deal's risk score and the pricing it produced.
 *
 * `model_trained` and `model_kind` are shown, not hidden: when the model has not
 * been fitted the score comes from the published prior, and a user is entitled to
 * know which of those two they are looking at.
 */

import Link from "next/link";
import { useParams } from "next/navigation";

import { PricingPanel, RiskFactors, RiskScore } from "@/components/domain/RiskPanel";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta } from "@/components/ui/StateChip";
import { ErrorBlock, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function DealRiskPage() {
  const dealId = String(useParams().id ?? "");
  const { t } = useI18n();
  const state = useAsync(() => api.dealRisk(dealId), [dealId]);

  if (state.status === "loading") return <Loading />;
  if (state.status === "error") {
    return (
      <section className="section">
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={state.reload} />
      </section>
    );
  }

  const risk = state.data;

  return (
    <section className="section">
      <CornerMeta left={t("deal.risk")} right={risk.band} />
      <div className="row-between">
        <h1 className="display-3">{t("deal.risk")}</h1>
        <Link href={`/deals/${dealId}`} className="link" data-cursor="">
          {t("common.back")}
        </Link>
      </div>

      <div className="cockpit" style={{ paddingTop: "var(--sp-5)" }}>
        <Reveal>
          <Panel title={t("reputation.risk")}>
            <RiskScore
              score={risk.risk_score}
              band={risk.band}
              version={risk.score_version}
              modelKind={risk.model_kind}
            />
            <hr className="rule" />
            <div className="meta-grid" style={{ paddingTop: "var(--sp-3)" }}>
              <Meta
                label={t("reputation.modelTrained")}
                value={risk.model_trained ? t("common.yes") : t("common.no")}
              />
              <Meta label={t("reputation.model")} value={risk.model_kind} />
            </div>
            <p className="table-note">{t("reputation.modelNote")}</p>
          </Panel>
        </Reveal>

        <Reveal index={1}>
          <Panel title={t("reputation.topFactors")}>
            <RiskFactors factors={risk.top_factors} />
            <hr className="rule" />
            <div className="meta-grid" style={{ paddingTop: "var(--sp-3)" }}>
              {Object.entries(risk.features).map(([feature, value]) => (
                <Meta key={feature} label={feature} value={num(value, 3)} />
              ))}
            </div>
          </Panel>
        </Reveal>
      </div>

      <Reveal index={2}>
        <PricingPanel pricing={risk.pricing} />
      </Reveal>
    </section>
  );
}
