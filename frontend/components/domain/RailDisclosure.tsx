"use client";

/**
 * The rail honesty table (spec 22, 27).
 *
 * Two components render this data: the README (from `make eval`) and this panel.
 * Both read the same `/payments/rail` disclosure, so the interface cannot claim
 * a real payout while the backend is simulating one.  Every row is labelled
 * `SIMULATED` or `REAL TEST MODE` per operation, never once for the whole rail:
 * webhook verification can be real while a payout is simulated, and pretending
 * otherwise in either direction would be a lie.
 */

import { Meta } from "@/components/ui/StateChip";
import { Panel } from "@/components/ui/primitives";
import type { RailDisclosure as Disclosure } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const OPERATION_LABEL: Record<string, string> = {
  funding_order_and_capture: "FUNDING ORDER + CAPTURE",
  seller_release: "SELLER RELEASE",
  refund: "REFUND",
  webhook_verification: "WEBHOOK VERIFICATION",
};

/** A single operation's mode, as a word, never as a colour alone. */
export function RailTag({ mode }: { mode: string }) {
  const real = mode === "REAL TEST MODE";
  return (
    <span
      className="chip"
      style={{
        color: real ? "var(--sig-pass)" : "var(--sig-unverified)",
        background: real ? "var(--sig-pass-tint)" : "var(--sig-unverified-tint)",
        borderColor: real ? "var(--sig-pass-edge)" : "var(--sig-unverified-edge)",
      }}
    >
      {mode}
    </span>
  );
}

export function RailDisclosurePanel({ rail }: { rail: Disclosure }) {
  const { t } = useI18n();
  return (
    <Panel title={t("rail.title")}>
      <div className="meta-grid">
        <Meta label={t("rail.mode")} value={rail.mode} />
        <Meta label={t("rail.configured")} value={rail.configured} />
        <Meta
          label={t("rail.credentials")}
          value={rail.credentials_present ? t("common.yes") : t("common.no")}
        />
      </div>
      <hr className="rule" />
      <div className="stack" style={{ gap: "var(--sp-2)", paddingTop: "var(--sp-3)" }}>
        {Object.entries(rail.operations).map(([operation, mode]) => (
          <div className="row-between" key={operation}>
            <span className="micro">{OPERATION_LABEL[operation] ?? operation}</span>
            <RailTag mode={mode} />
          </div>
        ))}
      </div>
      <p className="table-note">{t("rail.note")}</p>
    </Panel>
  );
}
