"use client";

/**
 * The deal cockpit (ui/06 §1) -- the screen the demo opens on.
 *
 * Order is deliberate: money first, then state, then the milestones, then the
 * console and the chat.  A person who lands here wants to know where their money
 * is before anything else, and the money bar answers that in one glance while
 * showing that the parts still sum to the whole.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";

import { useSession } from "@/components/domain/AppProviders";
import { AgentConsole } from "@/components/domain/AgentConsole";
import { DealChat } from "@/components/domain/DealChat";
import { MilestoneCard } from "@/components/domain/MilestoneCard";
import { MoneyBar } from "@/components/domain/MoneyBar";
import { StateStrip } from "@/components/domain/StateStrip";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta, StateChip } from "@/components/ui/StateChip";
import { Button, ErrorBlock, Hash, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { useSse } from "@/hooks/useSse";
import { ApiError, api, sseUrl } from "@/lib/api";
import { dateOnly, dealTone, inr, riskTone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function DealCockpit() {
  // `useParams` rather than the `params` prop: this is a client component, and in
  // the App Router `params` arrives there as a promise.
  const dealId = String(useParams().id ?? "");
  const { t, locale } = useI18n();
  const { me } = useSession();
  const state = useAsync(() => api.deal(dealId), [dealId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = state.reload;
  useSse(sseUrl("/deals"), (event, data) => {
    const payload = (data ?? {}) as { deal_id?: string };
    if (event !== "ready" && (!payload.deal_id || payload.deal_id === dealId)) reload();
  });

  const act = useCallback(
    async (name: "sign" | "fund", run: () => Promise<unknown>) => {
      setBusy(name);
      setError(null);
      try {
        await run();
        reload();
      } catch (caught) {
        setError(caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught));
      } finally {
        setBusy(null);
      }
    },
    [reload],
  );

  if (state.status === "loading") return <Loading />;
  if (state.status === "error") {
    return (
      <section className="section">
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={reload} />
      </section>
    );
  }

  const deal = state.data;
  const activeMilestone =
    deal.milestones.find((milestone) => milestone.state === "VERIFYING") ??
    deal.milestones.find((milestone) => milestone.state === "EVIDENCE_SUBMITTED") ??
    null;
  const canSign = deal.state === "DRAFT";
  const canFund = deal.state === "TERMS_SIGNED" && deal.viewer_side === "buyer";
  const verified = me?.email_verified ?? false;

  return (
    <section className="section">
      <CornerMeta
        left={`${deal.reference} · ${t(`state.${deal.state}`)}`}
        right={`${deal.milestones.length} ${t("deal.milestones")}`}
      />

      <div className="row-between">
        <div className="stack" style={{ gap: "var(--sp-2)" }}>
          <h1 className="display-3">{deal.title}</h1>
          <span className="micro">
            {deal.buyer_org.name} → {deal.seller_org.name} ·{" "}
            {t("deal.openedOn")} {dateOnly(deal.created_at, locale)}
          </span>
        </div>
        <div className="row">
          <StateChip tone={dealTone(deal.state)}>{t(`state.${deal.state}`)}</StateChip>
          {canSign ? (
            <Button
              onClick={() => void act("sign", () => api.signTerms(dealId))}
              disabled={busy !== null || !verified}
              cursorLabel={t("deal.signTerms")}
            >
              {t("deal.signTerms")}
            </Button>
          ) : null}
          {canFund ? (
            <Button
              onClick={() => void act("fund", () => api.fund(dealId))}
              disabled={busy !== null || !verified}
              cursorLabel={t("deal.fund")}
            >
              {t("deal.fund")}
            </Button>
          ) : null}
        </div>
      </div>

      {error ? (
        <span className="field-error" role="alert">
          {error}
        </span>
      ) : null}
      {!verified ? <span className="nano">{t("deal.verifyFirst")}</span> : null}

      <Reveal>
        <Panel title={t("deal.money")}>
          <MoneyBar money={deal.money} />
          <hr className="rule" />
          <div className="meta-grid" style={{ paddingTop: "var(--sp-3)" }}>
            <Meta label={t("deal.terms")} value={<Hash value={deal.terms_hash} head={8} tail={8} />} />
            <Meta
              label={t("deal.disputeWindow")}
              value={`${deal.dispute_window_days} ${t("reputation.days")}`}
            />
            <Meta label={t("deal.riskTier")} value={deal.pricing_tier ?? "—"} />
            <Meta
              label={t("deal.risk")}
              value={
                deal.risk_score === null ? (
                  "—"
                ) : (
                  <span style={{ color: `var(--sig-${riskTone(deal.risk_score)})` }}>
                    {deal.risk_score.toFixed(3)}
                  </span>
                )
              }
            />
          </div>
          <div className="row" style={{ paddingTop: "var(--sp-4)" }}>
            <Link href={`/deals/${dealId}/risk`} className="link" data-cursor="">
              {t("deal.viewRisk")}
            </Link>
            <Link href={`/deals/${dealId}/ledger`} className="link" data-cursor="">
              {t("provenance.ledger")}
            </Link>
            <Link
              href={`/entities/${deal.viewer_side === "buyer" ? deal.seller_org.entity_id : deal.buyer_org.entity_id}`}
              className="link"
              data-cursor=""
            >
              {t("reputation.counterparty")}
            </Link>
          </div>
        </Panel>
      </Reveal>

      <Reveal index={1}>
        <Panel title={t("deal.state")}>
          <StateStrip state={activeMilestone?.state ?? deal.milestones[0]?.state ?? "PENDING"} />
        </Panel>
      </Reveal>

      <Reveal index={2}>
        <Panel
          title={t("deal.milestones")}
          right={<span className="nano">{inr(deal.total_paise)}</span>}
        >
          <div className="grid-cards">
            {deal.milestones.map((milestone, index) => (
              <MilestoneCard
                key={milestone.id}
                milestone={milestone}
                dealId={dealId}
                total={deal.milestones.length}
                index={index}
              />
            ))}
          </div>
        </Panel>
      </Reveal>

      <div className="cockpit" style={{ paddingTop: "var(--sp-6)" }}>
        <AgentConsole
          dealId={dealId}
          milestoneId={activeMilestone?.id ?? null}
          onCompleted={reload}
        />
        <DealChat dealId={dealId} />
      </div>
    </section>
  );
}
