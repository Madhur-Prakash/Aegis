"use client";

/**
 * The arbiter recommendation (ui/06 §4, spec 15).
 *
 * Everything here is advisory and the panel says so twice: once in the header
 * chip and once as a sentence.  The split it proposes is a *suggestion* that
 * pre-fills the human's form; settlement stays blocked until a person decides,
 * and the number that moves money is the one in the human's own field.
 *
 * The open questions are given as much room as the reasoning.  An arbiter that
 * admits what it does not know is more useful than one that does not, and hiding
 * that list behind a disclosure would be a way of quietly not showing it.
 */

import { Meta } from "@/components/ui/StateChip";
import { Panel } from "@/components/ui/primitives";
import type { ArbiterRecommendation } from "@/lib/api";
import { confidence as fmtConfidence, inr } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function ArbiterPanel({
  recommendation,
  amountPaise,
}: {
  recommendation: ArbiterRecommendation | null;
  amountPaise: number;
}) {
  const { t } = useI18n();

  if (!recommendation || !recommendation.available) {
    return (
      <Panel title={t("review.arbiterRecommends")}>
        <div className="state-block" role="status">
          <span className="micro">{t("review.arbiterUnavailable")}</span>
          <p className="state-body">
            {recommendation?.rejection_reason ?? t("review.arbiterUnavailableBody")}
          </p>
        </div>
      </Panel>
    );
  }

  const release = recommendation.release_paise ?? 0;
  const refund = recommendation.refund_paise ?? 0;
  const balanced = release + refund === amountPaise;

  return (
    <Panel
      title={t("review.arbiterRecommends")}
      right={
        <span
          className="chip"
          style={{
            color: "var(--sig-unverified)",
            background: "var(--sig-unverified-tint)",
            borderColor: "var(--sig-unverified-edge)",
          }}
        >
          {t("review.advisory")}
        </span>
      }
    >
      <div className="stack" style={{ gap: "var(--sp-4)" }}>
        <div className="meta-grid">
          <Meta label={t("review.outcome")} value={recommendation.outcome ?? "—"} />
          <Meta label={t("review.release")} value={inr(release)} />
          <Meta label={t("review.refund")} value={inr(refund)} />
          <Meta
            label={t("review.balances")}
            value={
              <span style={{ color: balanced ? "var(--sig-pass)" : "var(--sig-fail)" }}>
                {balanced ? inr(amountPaise) : t("review.doesNotBalance")}
              </span>
            }
          />
          <Meta
            label={t("verification.confidence")}
            value={
              recommendation.confidence === undefined
                ? "—"
                : fmtConfidence(recommendation.confidence)
            }
          />
          <Meta
            label={t("verification.model")}
            value={`${recommendation.provider ?? "—"} · ${recommendation.model_id ?? "—"}`}
          />
        </div>

        {recommendation.reasoning_steps?.length ? (
          <div className="stack" style={{ gap: "var(--sp-2)" }}>
            <span className="micro">{t("review.reasoning")}</span>
            <ol className="stack" style={{ gap: "var(--sp-2)", paddingLeft: "var(--sp-5)" }}>
              {recommendation.reasoning_steps.map((step, index) => (
                <li key={index} style={{ fontSize: "var(--fs-sm)" }}>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        {recommendation.terms_clauses_relied_on?.length ? (
          <div className="stack" style={{ gap: "var(--sp-2)" }}>
            <span className="micro">{t("review.reliedOn")}</span>
            <div className="row">
              {recommendation.terms_clauses_relied_on.map((clause) => (
                <span key={clause} className="chip">
                  {clause}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {recommendation.open_questions?.length ? (
          <div className="stack" style={{ gap: "var(--sp-2)" }}>
            <span className="micro">{t("review.openQuestions")}</span>
            <ul className="stack" style={{ gap: "var(--sp-2)", paddingLeft: "var(--sp-5)" }}>
              {recommendation.open_questions.map((question, index) => (
                <li key={index} className="table-note">
                  {question}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <p className="table-note">{t("review.advisoryOnly")}</p>
      </div>
    </Panel>
  );
}
