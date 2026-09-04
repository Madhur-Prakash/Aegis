"use client";

/**
 * The deal list.
 *
 * A magic list rather than a grid of cards: these rows are dense, ordered and
 * scanned, and the sliding highlight is the affordance that makes a dense list
 * feel handled rather than crowded (ui/04 §3).
 */

import { useRouter } from "next/navigation";

import { StateChip } from "@/components/ui/StateChip";
import { MagicList, type MagicRow } from "@/components/ui/MagicList";
import { Empty, ErrorBlock, Loading, Panel } from "@/components/ui/primitives";
import { CornerMeta } from "@/components/ui/StateChip";
import { useAsync } from "@/hooks/useAsync";
import { useSse } from "@/hooks/useSse";
import { api, sseUrl } from "@/lib/api";
import { dateOnly, dealTone, inr } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function DealsPage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const state = useAsync(() => api.deals(), []);
  const reload = state.reload;

  useSse(sseUrl("/deals"), (event) => {
    if (event !== "ready") reload();
  });

  const deals = state.status === "ready" ? state.data : [];

  const rows: MagicRow[] = deals.map((deal) => ({
    id: deal.id,
    label: (
      <span className="stack" style={{ gap: "var(--sp-1)" }}>
        <span>{deal.title}</span>
        <span className="nano">
          {deal.reference} · {deal.buyer_org.name} → {deal.seller_org.name}
        </span>
      </span>
    ),
    meta: `${inr(deal.total_paise)} · ${t("deal.milestoneCount", {
      count: deal.milestones.length,
    })} · ${dateOnly(deal.created_at, locale)}`,
    trailing: (
      <StateChip tone={dealTone(deal.state)} animate={false}>
        {t(`state.${deal.state}`)}
      </StateChip>
    ),
  }));

  return (
    <section className="section">
      <CornerMeta left={t("nav.deals")} right={`${deals.length}`} />
      <h1 className="display-3">{t("nav.deals")}</h1>

      <Panel>
        {state.status === "loading" ? <Loading /> : null}
        {state.status === "error" ? (
          <ErrorBlock code={state.error.code} message={state.error.message} onRetry={reload} />
        ) : null}
        {state.status === "ready" ? (
          <MagicList
            items={rows}
            onSelect={(id) => router.push(`/deals/${id}`)}
            cursorLabel={t("deal.viewProof")}
            emptyLabel={<Empty label={t("nav.deals")} body={t("deal.emptyList")} />}
          />
        ) : null}
      </Panel>
    </section>
  );
}
