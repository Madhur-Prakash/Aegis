"use client";

/**
 * The counterparty passport (ui/06 §6).
 *
 * The reputation view exists to make the pricing tier legible: a buyer being
 * asked to prefund 100% should be able to see the three facts that produced
 * that ask.  A tier with no explanation is a fee dressed up as a policy.
 */

import { useParams } from "next/navigation";

import { PassportPanel, PricingPanel, RiskFactors, RiskScore } from "@/components/domain/RiskPanel";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta } from "@/components/ui/StateChip";
import { ErrorBlock, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function EntityPassportPage() {
  const entityId = String(useParams().entityId ?? "");
  const { t } = useI18n();
  const state = useAsync(() => api.passport(entityId), [entityId]);

  if (state.status === "loading") return <Loading />;
  if (state.status === "error") {
    return (
      <section className="section">
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={state.reload} />
      </section>
    );
  }

  const passport = state.data;

  return (
    <section className="section">
      <CornerMeta left={t("reputation.counterparty")} right={passport.band} />
      <h1 className="display-3">{passport.display_name}</h1>

      <Reveal>
        <PassportPanel passport={passport} />
      </Reveal>

      <div className="cockpit" style={{ paddingTop: "var(--sp-5)" }}>
        <Reveal index={1}>
          <Panel title={t("reputation.risk")}>
            <RiskScore
              score={passport.risk_score}
              band={passport.band}
              version={passport.score_version}
            />
          </Panel>
        </Reveal>
        <Reveal index={2}>
          <Panel title={t("reputation.topFactors")}>
            <RiskFactors factors={passport.top_factors} />
          </Panel>
        </Reveal>
      </div>

      <Reveal index={3}>
        <PricingPanel pricing={passport.pricing} />
      </Reveal>
    </section>
  );
}
