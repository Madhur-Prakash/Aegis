"use client";

/**
 * Raising a dispute.
 *
 * The panel is placed on the verification result rather than tucked away,
 * because the moment a party disagrees with a decision is the moment they are
 * reading it. The claim is mandatory and is written into the ledger with the
 * raiser's user id.
 *
 * The copy states the consequence plainly: a dispute **blocks settlement until
 * a human decides** (I8). It does not reverse a completed payout, and saying so
 * here is better than letting someone discover it afterwards.
 */

import { useState } from "react";

import { Button, Field, Panel, Textarea } from "@/components/ui/primitives";
import { Meta } from "@/components/ui/StateChip";
import { ApiError, api, type Dispute } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const MIN_CLAIM = 12;

export function RaiseDispute({
  milestoneId,
  existing,
  onRaised,
}: {
  milestoneId: string;
  existing?: Dispute | null;
  onRaised?: () => void;
}) {
  const { t } = useI18n();
  const [claim, setClaim] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [raised, setRaised] = useState<Dispute | null>(existing ?? null);

  const valid = claim.trim().length >= MIN_CLAIM;

  if (raised) {
    return (
      <Panel title={t("dispute.title")}>
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          <p className="state-body">{raised.claim}</p>
          <div className="meta-grid">
            <Meta label={t("dispute.raisedAt")} value={dateTime(raised.created_at)} />
            <Meta
              label={t("dispute.blocksSettlement")}
              value={
                <span
                  style={{
                    color: raised.settlement_blocked_until_human_decision
                      ? "var(--sig-unverified)"
                      : "var(--sig-pass)",
                  }}
                >
                  {raised.settlement_blocked_until_human_decision
                    ? t("common.yes")
                    : t("common.no")}
                </span>
              }
            />
            <Meta
              label={t("dispute.resolved")}
              value={raised.resolved_at ? dateTime(raised.resolved_at) : t("dispute.open")}
            />
          </div>
          <p className="table-note">{t("dispute.blockedNote")}</p>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title={t("deal.raiseDispute")}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          void api
            .raiseDispute(milestoneId, claim.trim())
            .then(
              (dispute) => {
                setRaised(dispute);
                onRaised?.();
              },
              (caught: unknown) =>
                setError(
                  caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught),
                ),
            )
            .finally(() => setBusy(false));
        }}
      >
        <Field
          label={t("dispute.claim")}
          hint={t("dispute.claimHint")}
          error={claim.length > 0 && !valid ? t("review.reasonTooShort") : null}
        >
          <Textarea
            value={claim}
            onChange={(event) => setClaim(event.target.value)}
            placeholder={t("dispute.claimPlaceholder")}
            rows={4}
            maxLength={4000}
          />
        </Field>

        {error ? (
          <span className="field-error" role="alert">
            {error}
          </span>
        ) : null}

        <div className="row">
          <Button
            type="submit"
            variant="danger"
            disabled={busy || !valid}
          >
            {t("deal.raiseDispute")}
          </Button>
          <span className="nano">{t("dispute.blocksNote")}</span>
        </div>
      </form>
    </Panel>
  );
}
