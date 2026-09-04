"use client";

/**
 * The ledger index: the platform's operational counters, then a way into each
 * deal's own hash-chained ledger.
 *
 * `outbox_backlog` and `dlq_depth` are on this page deliberately.  They are the
 * two numbers that say whether the transactional outbox is keeping up (I13), and
 * an operator should not have to open a terminal to find them.
 */

import { useRouter } from "next/navigation";

import { RailDisclosurePanel } from "@/components/domain/RailDisclosure";
import { useSession } from "@/components/domain/AppProviders";
import { MagicList, type MagicRow } from "@/components/ui/MagicList";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta, StateChip } from "@/components/ui/StateChip";
import { Empty, ErrorBlock, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { dealTone, inr, num } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

type Metrics = {
  verifications_by_decision?: Record<string, number>;
  settlements_by_status?: Record<string, number>;
  dlq_depth?: number;
  outbox_backlog?: number;
  sse_subscribers?: number;
  authorizations?: number;
  deals?: number;
  ai_spend?: {
    calls: number;
    cost_micro_usd: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
  };
};

export default function LedgerIndexPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { rail } = useSession();
  const deals = useAsync(() => api.deals(), []);
  const metrics = useAsync(() => api.metrics() as Promise<Metrics>, []);

  const rows: MagicRow[] = (deals.status === "ready" ? deals.data : []).map((deal) => ({
    id: deal.id,
    label: (
      <span className="stack" style={{ gap: "var(--sp-1)" }}>
        <span>{deal.title}</span>
        <span className="nano">{deal.reference}</span>
      </span>
    ),
    meta: inr(deal.total_paise),
    trailing: (
      <StateChip tone={dealTone(deal.state)} animate={false}>
        {t(`state.${deal.state}`)}
      </StateChip>
    ),
  }));

  const spend = metrics.status === "ready" ? metrics.data.ai_spend : undefined;

  return (
    <section className="section">
      <CornerMeta left={t("nav.ledger")} right={t("ledger.counters")} />
      <h1 className="display-3">{t("nav.ledger")}</h1>

      <Reveal>
        <Panel title={t("ledger.counters")}>
          {metrics.status === "loading" ? <Loading /> : null}
          {metrics.status === "error" ? (
            <ErrorBlock
              code={metrics.error.code}
              message={metrics.error.message}
              onRetry={metrics.reload}
            />
          ) : null}
          {metrics.status === "ready" ? (
            <div className="meta-grid">
              <Meta label={t("ledger.deals")} value={num(metrics.data.deals ?? 0)} />
              <Meta
                label={t("ledger.authorizations")}
                value={num(metrics.data.authorizations ?? 0)}
              />
              <Meta
                label={t("ledger.outboxBacklog")}
                value={
                  <span
                    style={{
                      color:
                        (metrics.data.outbox_backlog ?? 0) > 0
                          ? "var(--sig-unverified)"
                          : "var(--sig-pass)",
                    }}
                  >
                    {num(metrics.data.outbox_backlog ?? 0)}
                  </span>
                }
              />
              <Meta
                label={t("ledger.dlqDepth")}
                value={
                  <span
                    style={{
                      color:
                        (metrics.data.dlq_depth ?? 0) > 0
                          ? "var(--sig-fail)"
                          : "var(--sig-pass)",
                    }}
                  >
                    {num(metrics.data.dlq_depth ?? 0)}
                  </span>
                }
              />
              <Meta
                label={t("ledger.sseSubscribers")}
                value={num(metrics.data.sse_subscribers ?? 0)}
              />
              <Meta
                label={t("ledger.decisions")}
                value={
                  Object.entries(metrics.data.verifications_by_decision ?? {})
                    .map(([decision, count]) => `${decision} ${count}`)
                    .join(" · ") || "—"
                }
              />
              <Meta
                label={t("ledger.settlements")}
                value={
                  Object.entries(metrics.data.settlements_by_status ?? {})
                    .map(([status, count]) => `${status} ${count}`)
                    .join(" · ") || "—"
                }
              />
              <Meta
                label={t("ledger.aiSpend")}
                value={
                  spend
                    ? `${spend.calls} ${t("ledger.calls")} · $${(
                        spend.cost_micro_usd / 1_000_000
                      ).toFixed(4)}`
                    : "—"
                }
              />
            </div>
          ) : null}
          <p className="table-note">{t("ledger.note")}</p>
        </Panel>
      </Reveal>

      <Reveal index={1}>
        <Panel title={t("nav.deals")}>
          {deals.status === "loading" ? <Loading /> : null}
          {deals.status === "error" ? (
            <ErrorBlock
              code={deals.error.code}
              message={deals.error.message}
              onRetry={deals.reload}
            />
          ) : null}
          {deals.status === "ready" ? (
            <MagicList
              items={rows}
              onSelect={(id) => router.push(`/deals/${id}/ledger`)}
              cursorLabel={t("provenance.verifyLedger")}
              emptyLabel={<Empty label={t("nav.deals")} body={t("deal.emptyList")} />}
            />
          ) : null}
        </Panel>
      </Reveal>

      {rail ? (
        <Reveal index={2}>
          <div id="rail">
            <RailDisclosurePanel rail={rail} />
          </div>
        </Reveal>
      ) : null}
    </section>
  );
}
