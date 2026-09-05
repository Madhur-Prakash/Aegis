"use client";

/**
 * The verification result (ui/06 §3).
 *
 * The decision, the confidence, the clause table, and the confidence breakdown --
 * in that order, and the breakdown is not optional.  A decision with a number
 * attached is an assertion; a decision with the arithmetic that produced the
 * number is a claim someone can argue with, which is the entire point.
 *
 * A `RELEASE` gets the seal.  An `ESCALATE` gets a link into the review queue and
 * no seal at all: nothing has been decided yet, and drawing a seal would say
 * otherwise.
 */

import { Tick } from "@/components/ui/icons";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ClauseTable } from "@/components/domain/ClauseTable";
import { ConfidenceBreakdown } from "@/components/domain/ConfidenceBreakdown";
import { RaiseDispute } from "@/components/domain/RaiseDispute";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta, StateChip } from "@/components/ui/StateChip";
import { Empty, ErrorBlock, Hash, Loading, Panel, Seal } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { confidence as fmtConfidence, dateTime, decisionTone, inr } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const OUTCOME_KEY: Record<string, string> = {
  RELEASE: "verification.released",
  REJECT: "verification.rejected",
  ESCALATE: "verification.escalated",
};

export default function VerificationPage() {
  const parameters = useParams();
  const dealId = String(parameters.id ?? "");
  const milestoneId = String(parameters.mid ?? "");
  const { t } = useI18n();

  const milestone = useAsync(() => api.milestone(milestoneId), [milestoneId]);
  const attestation = useAsync(() => api.attestationForMilestone(milestoneId), [milestoneId]);
  // Disputes are listed per organization; the one for this milestone, if any,
  // decides whether the panel below offers to raise one or shows the existing.
  const disputes = useAsync(() => api.disputes(), []);

  if (attestation.status === "loading" || milestone.status === "loading") return <Loading />;
  if (attestation.status === "error") {
    return (
      <section className="section">
        <ErrorBlock
          code={attestation.error.code}
          message={attestation.error.message}
          onRetry={attestation.reload}
        />
      </section>
    );
  }

  if (!attestation.data) {
    return (
      <section className="section">
        <Empty
          label={t("verification.decision")}
          body={t("verification.noAttestation")}
          action={
            <Link
              href={`/deals/${dealId}/milestones/${milestoneId}/evidence`}
              className="link"
              data-cursor=""
            >
              {t("deal.submitEvidence")}
            </Link>
          }
        />
      </section>
    );
  }

  const record = attestation.data;
  const tone = decisionTone(record.decision);
  const prechecks = record.deterministic_prechecks;

  return (
    <section className="section">
      <CornerMeta left={record.reference} right={dateTime(record.created_at)} />

      <div className="row-between">
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          <span className="micro">{t("verification.decision")}</span>
          <h1 className="display-2">{record.decision}</h1>
          <span className="micro">
            {t(OUTCOME_KEY[record.decision] ?? "verification.escalated")}
          </span>
          <div className="row">
            <StateChip tone={tone}>
              {t("verification.confidence")} {fmtConfidence(record.confidence)}
            </StateChip>
            {prechecks.resolved_without_llm ? (
              <StateChip tone="pass" index={1}>
                {t("verification.zeroCost")}
              </StateChip>
            ) : null}
          </div>
        </div>

        {record.decision === "RELEASE" ? (
          <Seal tone="pass" label={record.chain_tx ?? t("provenance.notAnchored")} />
        ) : null}
      </div>

      <div className="row" style={{ paddingTop: "var(--sp-4)" }}>
        <Link href={`/provenance/${record.id}`} className="link" data-cursor="">
          {t("verification.viewProvenance")}
        </Link>
        {record.decision === "ESCALATE" ? (
          <Link href="/review" className="link" data-cursor="">
            {t("verification.sendToReview")}
          </Link>
        ) : null}
        <Link href={`/deals/${dealId}`} className="link" data-cursor="">
          {t("common.back")}
        </Link>
      </div>

      <Reveal>
        <Panel title={t("verification.clauses")}>
          <ClauseTable verdicts={record.clause_verdicts} />
        </Panel>
      </Reveal>

      <div className="cockpit" style={{ paddingTop: "var(--sp-5)" }}>
        <Reveal index={1}>
          <ConfidenceBreakdown
            components={record.confidence_components}
            thresholds={record.thresholds}
          />
        </Reveal>

        <Reveal index={2}>
          <Panel title={t("verification.prechecks")}>
            <div className="stack" style={{ gap: "var(--sp-3)" }}>
              <Meta
                label={t("verification.prechecksPassed", {
                  passed: prechecks.passed,
                  total: prechecks.total,
                })}
                value={prechecks.reason || "-"}
              />
              {prechecks.checks.map((check) => (
                <div className="row-between" key={check.check}>
                  <span style={{ fontSize: "var(--fs-sm)" }}>{check.check}</span>
                  <span
                    className="micro"
                    style={{ color: check.ok ? "var(--sig-pass)" : "var(--sig-fail)" }}
                  >
                    <Tick ok={check.ok} />{" "}
                    {check.ok ? t("verdict.PASS") : t("verdict.FAIL")}
                  </span>
                </div>
              ))}

              {prechecks.integrity_findings.length ? (
                <>
                  <hr className="rule" />
                  <span className="micro">{t("verification.integrity")}</span>
                  {prechecks.integrity_findings.map((finding, index) => (
                    <span key={index} className="table-note">
                      {Object.entries(finding)
                        .map(([key, value]) => `${key}: ${String(value)}`)
                        .join(" · ")}
                    </span>
                  ))}
                </>
              ) : null}

              <hr className="rule" />
              <div className="meta-grid">
                <Meta label={t("verification.provider")} value={record.provider} />
                <Meta label={t("verification.model")} value={record.model_id} />
                <Meta label={t("provenance.modelVersion")} value={record.model_version} />
                <Meta
                  label={t("provenance.promptHash")}
                  value={<Hash value={record.prompt_hash} />}
                />
                <Meta
                  label={t("provenance.evidenceRoot")}
                  value={<Hash value={record.evidence_merkle_root} />}
                />
                <Meta label={t("verification.calibration")} value={record.calibration_version} />
              </div>

              {milestone.status === "ready" ? (
                <Meta label={t("deal.milestones")} value={inr(milestone.data.amount_paise)} />
              ) : null}
            </div>
          </Panel>
        </Reveal>
      </div>

      <Reveal index={3}>
        <Panel title={t("verification.reasoning")}>
          <p className="prose" style={{ whiteSpace: "pre-wrap" }}>
            {record.reasoning}
          </p>
        </Panel>
      </Reveal>

      {milestone.status === "ready" && milestone.data.state !== "REJECTED" ? (
        <Reveal index={4}>
          <RaiseDispute
            milestoneId={milestoneId}
            existing={
              disputes.status === "ready"
                ? (disputes.data.find((dispute) => dispute.milestone_id === milestoneId) ?? null)
                : null
            }
            onRaised={() => {
              milestone.reload();
              disputes.reload();
            }}
          />
        </Reveal>
      ) : null}
    </section>
  );
}
