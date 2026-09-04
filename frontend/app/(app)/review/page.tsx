"use client";

/**
 * The human review queue (ui/06 §4).
 *
 * A two-pane screen: the queue on the left, the selected item on the right.  The
 * right pane leads with `WHAT THE AGENT COULD NOT VERIFY`, because that is the
 * only reason this row is here, and because a reviewer who has to hunt for it
 * will start rubber-stamping.
 *
 * Nothing on this screen releases money on its own.  The decision panel writes a
 * human authorization and the engine settles from it; the reviewer's reason is
 * mandatory and is stored with their user id.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ArbiterPanel } from "@/components/domain/ArbiterPanel";
import { ReviewDecision } from "@/components/domain/ReviewDecision";
import { MagicList, type MagicRow } from "@/components/ui/MagicList";
import { Reveal } from "@/components/ui/Reveal";
import { ScrambleText } from "@/components/ui/ScrambleText";
import { CornerMeta, Meta, StateChip, VerdictChip } from "@/components/ui/StateChip";
import { Button, Empty, ErrorBlock, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { useSse } from "@/hooks/useSse";
import { ApiError, api, sseUrl } from "@/lib/api";
import { confidence as fmtConfidence, decisionTone, inr, relative } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function ReviewQueuePage() {
  const { t, list } = useI18n();
  const state = useAsync(() => api.reviewQueue(), []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [arbiterBusy, setArbiterBusy] = useState(false);
  const [arbiterError, setArbiterError] = useState<string | null>(null);

  const reload = state.reload;
  useSse(sseUrl("/review"), (event) => {
    if (event !== "ready") reload();
  });

  // Memoised so the selection effect below does not see a new array identity on
  // every render and re-run forever.
  const rows = useMemo(
    () => (state.status === "ready" ? state.data : []),
    [state.status, state.data],
  );

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !rows.some((row) => row.milestone_id === selectedId)) {
      setSelectedId(rows[0]?.milestone_id ?? null);
    }
  }, [rows, selectedId]);

  const selected = rows.find((row) => row.milestone_id === selectedId) ?? null;

  const items: MagicRow[] = rows.map((row) => ({
    id: row.milestone_id,
    label: (
      <span className="stack" style={{ gap: "var(--sp-1)" }}>
        <span>{row.milestone_title}</span>
        <span className="nano">
          {row.deal_reference} · #{row.milestone_seq} · {relative(row.created_at)}
        </span>
      </span>
    ),
    meta: `${inr(row.amount_paise)}${
      row.confidence === null ? "" : ` · ${fmtConfidence(row.confidence)}`
    }`,
    trailing: row.decision ? (
      <StateChip tone={decisionTone(row.decision)} animate={false}>
        {row.decision}
      </StateChip>
    ) : null,
  }));

  const runArbiter = async () => {
    if (!selected?.dispute_id) return;
    setArbiterBusy(true);
    setArbiterError(null);
    try {
      await api.runArbiter(selected.dispute_id);
      reload();
    } catch (caught) {
      setArbiterError(
        caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught),
      );
    } finally {
      setArbiterBusy(false);
    }
  };

  return (
    <section className="section">
      <CornerMeta
        left={t("review.queue")}
        right={t("review.awaiting", { count: rows.length })}
      />
      <h1 className="display-3">{t("review.queue")}</h1>

      <div className="two-col" style={{ paddingTop: "var(--sp-5)" }}>
        <Panel title={t("review.queue")}>
          {state.status === "loading" ? <Loading /> : null}
          {state.status === "error" ? (
            <ErrorBlock code={state.error.code} message={state.error.message} onRetry={reload} />
          ) : null}
          {state.status === "ready" ? (
            <MagicList
              items={items}
              selectedId={selectedId}
              onSelect={setSelectedId}
              cursorLabel={t("review.selected")}
              emptyLabel={
                <div className="stack" style={{ gap: "var(--sp-3)" }}>
                  <div className="micro">
                    <ScrambleText phrases={list("review.emptyPhrases")} />
                  </div>
                  <Empty label={t("review.queue")} body={t("review.empty")} />
                </div>
              }
            />
          ) : null}
        </Panel>

        {selected ? (
          <div className="stack">
            <Reveal>
              <Panel
                title={t("review.couldNotVerify")}
                right={
                  <Link
                    href={`/deals/${selected.deal_id}`}
                    className="link"
                    data-cursor=""
                  >
                    {selected.deal_reference}
                  </Link>
                }
              >
                <div className="stack" style={{ gap: "var(--sp-3)" }}>
                  {selected.could_not_verify.length === 0 ? (
                    <p className="state-body">{t("review.nothingUnverifiable")}</p>
                  ) : null}
                  {selected.could_not_verify.map((clause, index) => (
                    <div className="stack" key={clause.clause_id} style={{ gap: "var(--sp-2)" }}>
                      <div className="row">
                        <VerdictChip verdict="UNVERIFIABLE" index={index} />
                        <span className="micro">{clause.clause_id}</span>
                      </div>
                      <p className="table-note">{clause.note}</p>
                    </div>
                  ))}

                  <hr className="rule" />
                  <div className="meta-grid">
                    <Meta label={t("deal.milestones")} value={selected.milestone_title} />
                    <Meta label={t("review.release")} value={inr(selected.amount_paise)} />
                    <Meta
                      label={t("verification.confidence")}
                      value={
                        selected.confidence === null ? "-" : fmtConfidence(selected.confidence)
                      }
                    />
                    <Meta label={t("verification.decision")} value={selected.decision ?? "-"} />
                  </div>

                  <div className="row">
                    {selected.attestation_id ? (
                      <>
                        <Link
                          href={`/deals/${selected.deal_id}/milestones/${selected.milestone_id}/verification`}
                          className="link"
                          data-cursor=""
                        >
                          {t("review.evidence")}
                        </Link>
                        <Link
                          href={`/provenance/${selected.attestation_id}`}
                          className="link"
                          data-cursor=""
                        >
                          {t("verification.viewProvenance")}
                        </Link>
                      </>
                    ) : null}
                  </div>
                </div>
              </Panel>
            </Reveal>

            {selected.dispute_id ? (
              <Reveal index={1}>
                <div className="stack">
                  <ArbiterPanel
                    recommendation={selected.arbiter_recommendation}
                    amountPaise={selected.amount_paise}
                  />
                  <div className="row">
                    <Button
                      variant="ghost"
                      onClick={() => void runArbiter()}
                      disabled={arbiterBusy}
                    >
                      {arbiterBusy ? t("review.arbiterRunning") : t("review.runArbiter")}
                    </Button>
                    {arbiterError ? (
                      <span className="field-error" role="alert">
                        {arbiterError}
                      </span>
                    ) : null}
                  </div>
                </div>
              </Reveal>
            ) : null}

            <Reveal index={2}>
              <ReviewDecision
                milestoneId={selected.milestone_id}
                disputeId={selected.dispute_id}
                amountPaise={selected.amount_paise}
                suggestedReleasePaise={
                  selected.arbiter_recommendation?.release_paise ?? selected.amount_paise
                }
                onDone={reload}
              />
            </Reveal>
          </div>
        ) : null}
      </div>
    </section>
  );
}
