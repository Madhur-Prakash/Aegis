"use client";

/**
 * The human decision (ui/06 §4).
 *
 * Two shapes, one component, because a reviewer should not have to learn two
 * forms: approve/reject for an escalated milestone, and an editable split for a
 * dispute.  In both cases the reason is mandatory and the button says
 * `signs as you` -- the decision is written into the ledger with the reviewer's
 * user id, and it should be obvious that it is not anonymous.
 *
 * The split is validated here *and* on the server.  The client check exists so a
 * reviewer is told immediately, not so the server can trust it: the engine
 * re-derives the split and refuses anything that does not conserve the milestone
 * amount to the paise (I4).
 */

import { Tick } from "@/components/ui/icons";
import { useMemo, useState } from "react";

import { Meta } from "@/components/ui/StateChip";
import { Button, Field, Input, Panel, Textarea } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import { inr, inrExact, rupeesToPaise } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const MIN_REASON = 12;

export function ReviewDecision({
  milestoneId,
  disputeId,
  amountPaise,
  suggestedReleasePaise,
  onDone,
}: {
  milestoneId: string;
  disputeId: string | null;
  amountPaise: number;
  suggestedReleasePaise?: number | null;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [releaseRupees, setReleaseRupees] = useState<string>(() =>
    ((suggestedReleasePaise ?? amountPaise) / 100).toFixed(2),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const releasePaise = useMemo(() => {
    const parsed = Number.parseFloat(releaseRupees);
    return Number.isFinite(parsed) ? rupeesToPaise(parsed) : Number.NaN;
  }, [releaseRupees]);
  const refundPaise = Number.isFinite(releasePaise) ? amountPaise - releasePaise : Number.NaN;

  const splitValid =
    Number.isFinite(releasePaise) &&
    releasePaise >= 0 &&
    releasePaise <= amountPaise &&
    releasePaise + refundPaise === amountPaise;
  const reasonValid = reason.trim().length >= MIN_REASON;

  const act = async (action: "APPROVE" | "REJECT" | "SPLIT") => {
    setBusy(true);
    setError(null);
    try {
      if (action === "SPLIT") {
        if (!disputeId) throw new Error("no dispute");
        const result = await api.resolveDispute(disputeId, {
          release_paise: releasePaise,
          refund_paise: refundPaise,
          reason: reason.trim(),
        });
        setDone(
          t("review.resolved", {
            release: inr(result.release_paise),
            refund: inr(result.refund_paise),
          }),
        );
      } else {
        const result = await api.humanReview(milestoneId, action, reason.trim());
        setDone(
          t("review.recorded", {
            action: result.action,
            state: t(`state.${result.milestone_state}`),
          }),
        );
      }
      onDone();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title={t("review.decision")}>
      <div className="stack">
        <Field
          label={t("review.reason")}
          hint={t("review.reasonHint")}
          error={reason.length > 0 && !reasonValid ? t("review.reasonTooShort") : null}
        >
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t("review.reasonPlaceholder")}
            rows={4}
            maxLength={2000}
          />
        </Field>

        {disputeId ? (
          <>
            <Field
              label={t("review.override")}
              error={
                releaseRupees.length > 0 && !splitValid
                  ? t("review.splitMustBalance", { amount: inrExact(amountPaise) })
                  : null
              }
            >
              <Input
                className="input input--money"
                type="number"
                min={0}
                max={amountPaise / 100}
                step="0.01"
                value={releaseRupees}
                onChange={(event) => setReleaseRupees(event.target.value)}
                aria-label={t("review.release")}
              />
            </Field>
            <div className="meta-grid">
              <Meta
                label={t("review.release")}
                value={Number.isFinite(releasePaise) ? inrExact(releasePaise) : "-"}
              />
              <Meta
                label={t("review.refund")}
                value={Number.isFinite(refundPaise) ? inrExact(refundPaise) : "-"}
              />
              <Meta label={t("deal.funded")} value={inrExact(amountPaise)} />
              <Meta
                label={t("review.balances")}
                value={
                  <span style={{ color: splitValid ? "var(--sig-pass)" : "var(--sig-fail)" }}>
                    <Tick ok={splitValid} />
                  </span>
                }
              />
            </div>
          </>
        ) : null}

        {error ? (
          <span className="field-error" role="alert">
            {error}
          </span>
        ) : null}
        {done ? (
          <span className="micro" style={{ color: "var(--sig-pass)" }} role="status">
            {done}
          </span>
        ) : null}

        <div className="row">
          {disputeId ? (
            <Button
              onClick={() => void act("SPLIT")}
              disabled={busy || !reasonValid || !splitValid}
            >
              {t("review.confirm")}
            </Button>
          ) : (
            <>
              <Button
                tone="pass"
                onClick={() => void act("APPROVE")}
                disabled={busy || !reasonValid}
              >
                {t("review.approve")}
              </Button>
              <Button
                variant="danger"
                onClick={() => void act("REJECT")}
                disabled={busy || !reasonValid}
              >
                {t("review.reject")}
              </Button>
            </>
          )}
          <span className="nano">{t("review.signsAsYou")}</span>
        </div>
      </div>
    </Panel>
  );
}
