"use client";

/**
 * The hash-chained ledger (ui/06 §5, I8).
 *
 * `GET /ledger/deals/{id}/verify` recomputes every payload hash and re-links the
 * chain server-side, then replays the balances from the events alone.  This
 * panel renders that verdict and, when the chain is broken, the exact index and
 * the expected/found pair -- which is the only useful thing to show a person who
 * has just been told their audit log does not verify.
 *
 * The replayed balances are shown next to the verdict on purpose: a chain that
 * links but replays to a different total is still a broken ledger.
 */

import { Meta } from "@/components/ui/StateChip";
import { Button, ErrorBlock, Hash, Loading, Panel, ScrollX } from "@/components/ui/primitives";
import { Reveal } from "@/components/ui/Reveal";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { dateTime, inrExact, seq as fmtSeq } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function LedgerPanel({ dealId }: { dealId: string }) {
  const { t } = useI18n();
  const entries = useAsync(() => api.ledger(dealId), [dealId]);
  const verdict = useAsync(() => api.verifyLedger(dealId), [dealId]);

  const reload = () => {
    entries.reload();
    verdict.reload();
  };

  return (
    <Panel
      title={t("provenance.ledger")}
      right={
        <Button variant="ghost" onClick={reload}>
          {t("provenance.verifyLedger")}
        </Button>
      }
    >
      {verdict.status === "loading" ? <Loading /> : null}
      {verdict.status === "error" ? (
        <ErrorBlock
          code={verdict.error.code}
          message={verdict.error.message}
          onRetry={verdict.reload}
        />
      ) : null}

      {verdict.status === "ready" ? (
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          <div className="row-between">
            <span
              className="chip"
              style={{
                color: verdict.data.ok ? "var(--sig-pass)" : "var(--sig-fail)",
                background: verdict.data.ok ? "var(--sig-pass-tint)" : "var(--sig-fail-tint)",
                borderColor: verdict.data.ok ? "var(--sig-pass-edge)" : "var(--sig-fail-edge)",
              }}
            >
              <span aria-hidden>{verdict.data.ok ? "✓" : "✕"}</span>
              {verdict.data.ok
                ? t("provenance.chainIntact")
                : t("provenance.chainBroken", { index: String(verdict.data.broken_index ?? -1) })}
            </span>
            <span className="nano">
              {verdict.data.length} {t("provenance.events")}
            </span>
          </div>

          {!verdict.data.ok ? (
            <div className="stack" style={{ gap: "var(--sp-2)" }}>
              <Meta label={t("provenance.reason")} value={verdict.data.reason ?? "-"} />
              <Meta
                label={t("provenance.expected")}
                value={<Hash value={verdict.data.expected} head={8} tail={8} />}
              />
              <Meta
                label={t("provenance.found")}
                value={
                  <span className="num tamper-underline">
                    {verdict.data.found ? verdict.data.found.slice(0, 16) : "-"}…
                  </span>
                }
              />
            </div>
          ) : null}

          <div className="meta-grid">
            <Meta label={t("provenance.head")} value={<Hash value={verdict.data.head} />} />
            <Meta
              label={t("deal.released")}
              value={inrExact(verdict.data.replayed_balances.released_paise)}
            />
            <Meta
              label={t("deal.held")}
              value={inrExact(verdict.data.replayed_balances.held_paise)}
            />
            <Meta
              label={t("deal.refunded")}
              value={inrExact(verdict.data.replayed_balances.refunded_paise)}
            />
          </div>
          <p className="table-note">{t("provenance.replayNote")}</p>
        </div>
      ) : null}

      <hr className="rule" />

      {entries.status === "loading" ? <Loading /> : null}
      {entries.status === "error" ? (
        <ErrorBlock
          code={entries.error.code}
          message={entries.error.message}
          onRetry={entries.reload}
        />
      ) : null}

      {entries.status === "ready" ? (
        <ScrollX>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">SEQ</th>
                <th scope="col">{t("provenance.event")}</th>
                <th scope="col">{t("provenance.actor")}</th>
                <th scope="col">{t("provenance.payloadHash")}</th>
                <th scope="col">{t("provenance.prevHash")}</th>
                <th scope="col">{t("provenance.at")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.data.map((entry, index) => (
                <Reveal as="tr" key={entry.seq} index={index}>
                  <td className="num">{fmtSeq(entry.seq)}</td>
                  <td>
                    <div className="stack" style={{ gap: "var(--sp-1)" }}>
                      <span>{entry.event_type}</span>
                      {entry.reason ? <span className="nano">{entry.reason}</span> : null}
                    </div>
                  </td>
                  <td className="num">{entry.actor}</td>
                  <td>
                    <Hash value={entry.payload_hash} />
                  </td>
                  <td>
                    <Hash value={entry.prev_hash} />
                  </td>
                  <td className="num">{dateTime(entry.created_at)}</td>
                </Reveal>
              ))}
            </tbody>
          </table>
        </ScrollX>
      ) : null}
    </Panel>
  );
}
