"use client";

/**
 * On-chain anchors (ui/06 §5, spec 20).
 *
 * When the RPC is unavailable this panel says so and shows the local hash that
 * *would* be anchored, with the queued anchor rows.  It never renders a
 * transaction hash that does not exist, and it never dresses a queued anchor up
 * as a confirmed one: an explorer link appears only when the backend returns
 * one.
 *
 * `matches` is the comparison that matters -- the locally stored attestation
 * hash against the value actually read back from the contract.  If they differ
 * the row is red, because that is a real integrity failure rather than a
 * cosmetic one.
 */

import { Meta } from "@/components/ui/StateChip";
import { ErrorBlock, Hash, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const STATUS_TONE: Record<string, string> = {
  CONFIRMED: "var(--sig-pass)",
  PENDING: "var(--sig-unverified)",
  QUEUED: "var(--sig-unverified)",
  FAILED: "var(--sig-fail)",
};

export function ChainPanel({ dealId }: { dealId: string }) {
  const { t } = useI18n();
  const state = useAsync(() => api.chainRecords(dealId), [dealId]);

  return (
    <Panel title={t("chain.title")}>
      {state.status === "loading" ? <Loading /> : null}
      {state.status === "error" ? (
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={state.reload} />
      ) : null}

      {state.status === "ready" ? (
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          <div className="meta-grid">
            <Meta
              label={t("chain.available")}
              value={
                <span
                  style={{
                    color: state.data.chain_available
                      ? "var(--sig-pass)"
                      : "var(--sig-unverified)",
                  }}
                >
                  {state.data.chain_available ? t("common.yes") : t("common.no")}
                </span>
              }
            />
            <Meta label={t("chain.dealId")} value={state.data.chain_deal_id ?? "-"} />
          </div>

          {!state.data.chain_available ? (
            <p className="table-note">
              {t("chain.unavailable")}
              {state.data.chain_unavailable_reason
                ? ` - ${state.data.chain_unavailable_reason}`
                : ""}
            </p>
          ) : null}

          {state.data.anchors.length === 0 ? (
            <p className="state-body">{t("chain.noAnchors")}</p>
          ) : null}

          {state.data.anchors.map((anchor) => (
            <div className="tamper-row" key={anchor.anchor_id} data-failed={anchor.matches === false && anchor.onchain !== null}>
              <div className="row-between">
                <span className="micro">
                  {anchor.kind}
                  {anchor.milestone_seq !== null ? ` · #${anchor.milestone_seq}` : ""}
                </span>
                <span
                  className="micro"
                  style={{ color: STATUS_TONE[anchor.status] ?? "var(--fg-micro)" }}
                >
                  {anchor.status}
                </span>
              </div>
              <Meta
                label={t("chain.localHash")}
                value={<Hash value={anchor.local_attestation_hash} head={8} tail={8} />}
              />
              <Meta
                label={t("chain.tx")}
                value={
                  anchor.tx_hash ? (
                    anchor.explorer_url ? (
                      <a
                        className="link num"
                        href={anchor.explorer_url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        {anchor.tx_hash.slice(0, 10)}…{anchor.tx_hash.slice(-8)}
                      </a>
                    ) : (
                      <Hash value={anchor.tx_hash} head={8} tail={8} />
                    )
                  ) : (
                    t("provenance.notAnchored")
                  )
                }
              />
              {anchor.onchain ? (
                <Meta
                  label={t("chain.matches")}
                  value={
                    <span
                      style={{ color: anchor.matches ? "var(--sig-pass)" : "var(--sig-fail)" }}
                    >
                      {anchor.matches ? t("chain.readBackMatches") : t("chain.readBackDiffers")}
                    </span>
                  }
                />
              ) : null}
            </div>
          ))}

          <p className="table-note">{t("chain.note")}</p>
        </div>
      ) : null}
    </Panel>
  );
}
