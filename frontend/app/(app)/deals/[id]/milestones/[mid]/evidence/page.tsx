"use client";

/**
 * Evidence submission (ui/06 §2).
 *
 * The condition is shown first, in full, before the dropzone: the seller should
 * be able to read exactly what will be checked before choosing what to upload.
 * Hiding the clauses behind the upload would turn verification into a guess.
 *
 * `Run verification` appears only once a bundle has been submitted, because that
 * is the only point at which the backend will accept it.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { EvidenceUploader } from "@/components/domain/EvidenceUploader";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta } from "@/components/ui/StateChip";
import { Button, ErrorBlock, Loading, Panel } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { ApiError, api } from "@/lib/api";
import { inr, seq as fmtSeq } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function EvidencePage() {
  const parameters = useParams();
  const dealId = String(parameters.id ?? "");
  const milestoneId = String(parameters.mid ?? "");
  const { t } = useI18n();
  const router = useRouter();

  const milestone = useAsync(() => api.milestone(milestoneId), [milestoneId]);
  const bundle = useAsync(() => api.bundle(milestoneId), [milestoneId]);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    milestone.reload();
    bundle.reload();
  }, [milestone, bundle]);

  const runVerification = useCallback(async () => {
    setVerifying(true);
    setError(null);
    try {
      await api.startVerify(milestoneId);
      router.push(`/deals/${dealId}/milestones/${milestoneId}/verification`);
    } catch (caught) {
      setError(caught instanceof ApiError ? `${caught.code}: ${caught.message}` : String(caught));
    } finally {
      setVerifying(false);
    }
  }, [milestoneId, dealId, router]);

  if (milestone.status === "loading") return <Loading />;
  if (milestone.status === "error") {
    return (
      <section className="section">
        <ErrorBlock
          code={milestone.error.code}
          message={milestone.error.message}
          onRetry={milestone.reload}
        />
      </section>
    );
  }

  const data = milestone.data;
  const condition = data.verification_condition;
  const submitted = Boolean(bundle.status === "ready" && bundle.data?.submitted_at);

  return (
    <section className="section">
      <CornerMeta
        left={`${fmtSeq(data.seq)} · ${data.title}`}
        right={t(`state.${data.state}`)}
      />

      <div className="row-between">
        <div className="stack" style={{ gap: "var(--sp-2)" }}>
          <h1 className="display-3">{t("evidence.title")}</h1>
          <span className="micro">
            {data.title} · {inr(data.amount_paise)}
          </span>
        </div>
        <Link href={`/deals/${dealId}`} className="link" data-cursor="">
          {t("common.back")}
        </Link>
      </div>

      <div className="two-col" style={{ paddingTop: "var(--sp-5)" }}>
        <Reveal>
          <Panel title={t("verification.clauses")}>
            <div className="stack" style={{ gap: "var(--sp-3)" }}>
              {condition.clauses.map((clause) => (
                <div className="stack" key={clause.id} style={{ gap: "var(--sp-1)" }}>
                  <div className="row-between">
                    <span className="micro">{clause.id}</span>
                    <span className="nano">
                      {clause.required ? t("evidence.required") : t("verification.optional")}
                    </span>
                  </div>
                  <span style={{ fontSize: "var(--fs-sm)" }}>{clause.description}</span>
                  <span className="nano">{clause.kind}</span>
                </div>
              ))}
              <hr className="rule" />
              <Meta
                label={t("verification.tolerance")}
                value={
                  Object.keys(condition.tolerance).length
                    ? Object.entries(condition.tolerance)
                        .map(([key, value]) => `${key}=${String(value)}`)
                        .join(" · ")
                    : "—"
                }
              />
            </div>
          </Panel>
        </Reveal>

        <div className="stack">
          {bundle.status === "loading" ? <Loading /> : null}
          {bundle.status === "error" ? (
            <ErrorBlock
              code={bundle.error.code}
              message={bundle.error.message}
              onRetry={bundle.reload}
            />
          ) : null}
          {bundle.status === "ready" ? (
            <EvidenceUploader
              milestoneId={milestoneId}
              condition={condition}
              bundle={bundle.data}
              onChanged={refresh}
            />
          ) : null}

          {error ? (
            <span className="field-error" role="alert">
              {error}
            </span>
          ) : null}

          {submitted ? (
            <div className="row">
              <Button
                onClick={() => void runVerification()}
                disabled={verifying}
                cursorLabel={t("deal.verify")}
              >
                {verifying ? t("verification.running") : t("deal.verify")}
              </Button>
              {data.attestation_id ? (
                <Link
                  href={`/deals/${dealId}/milestones/${milestoneId}/verification`}
                  className="link"
                  data-cursor=""
                >
                  {t("verification.viewProvenance")}
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
