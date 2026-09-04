"use client";

/**
 * The provenance explorer (ui/06 §5) -- "for this rupee".
 *
 * One page that answers the audit question end to end: which model decided, on
 * which prompt, over which evidence, signed by which key, approved by which
 * human if any, paid on which rail reference, anchored in which transaction.
 *
 * The signature check is rendered from the backend's `signature_verified`, which
 * recovers the signer address from the canonical hash rather than comparing a
 * stored string.  If it ever came back false this page would say so in red --
 * which is why the field is rendered at all rather than assumed.
 */

import Link from "next/link";
import { useParams } from "next/navigation";

import { LedgerPanel } from "@/components/domain/LedgerPanel";
import { MerklePanel } from "@/components/domain/MerklePanel";
import { RailTag } from "@/components/domain/RailDisclosure";
import { useSession } from "@/components/domain/AppProviders";
import { Reveal, Rule } from "@/components/ui/Reveal";
import { CornerMeta, Meta, StateChip } from "@/components/ui/StateChip";
import { ErrorBlock, Hash, Loading, Panel, Seal } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { confidence as fmtConfidence, dateTime, decisionTone, inrExact } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function ProvenancePage() {
  const attestationId = String(useParams().attestationId ?? "");
  const { t } = useI18n();
  const { rail } = useSession();
  const state = useAsync(() => api.provenance(attestationId), [attestationId]);
  const milestoneId = state.status === "ready" ? state.data.milestone.id : null;
  const bundle = useAsync(
    () => (milestoneId ? api.bundle(milestoneId) : Promise.resolve(null)),
    [milestoneId],
  );

  if (state.status === "loading") return <Loading />;
  if (state.status === "error") {
    return (
      <section className="section">
        <ErrorBlock code={state.error.code} message={state.error.message} onRetry={state.reload} />
      </section>
    );
  }

  const record = state.data;
  const attestation = record.attestation;
  const tone = decisionTone(attestation.decision);

  return (
    <section className="section">
      <CornerMeta left={attestation.reference} right={dateTime(attestation.created_at)} />

      <div className="row-between">
        <div className="stack" style={{ gap: "var(--sp-3)" }}>
          <span className="micro">{t("provenance.title")}</span>
          <h1 className="display-2">{inrExact(record.milestone.amount_paise)}</h1>
          <span className="micro">
            {record.deal.reference} · #{record.milestone.seq} {record.milestone.title}
          </span>
          <div className="row">
            <StateChip tone={tone}>{attestation.decision}</StateChip>
            <StateChip tone={tone} index={1}>
              {t("provenance.confidence")} {fmtConfidence(attestation.confidence)}
            </StateChip>
            <StateChip
              tone={record.signature_verified ? "pass" : "fail"}
              index={2}
            >
              <span aria-hidden>{record.signature_verified ? "✓" : "✕"}</span>
              {record.signature_verified
                ? t("provenance.signatureValid")
                : t("provenance.signatureInvalid")}
            </StateChip>
          </div>
        </div>
        {record.signature_verified ? (
          <Seal
            tone={tone === "neutral" ? "pass" : tone}
            label={
              record.chain.anchors.find((anchor) => anchor.tx_hash)?.tx_hash ??
              t("provenance.notAnchored")
            }
          />
        ) : null}
      </div>

      <div className="row" style={{ paddingTop: "var(--sp-4)" }}>
        <Link href={`/deals/${record.deal.id}`} className="link" data-cursor="">
          {record.deal.reference}
        </Link>
        <Link
          href={`/deals/${record.deal.id}/milestones/${record.milestone.id}/verification`}
          className="link"
          data-cursor=""
        >
          {t("verification.decision")}
        </Link>
      </div>

      <Rule />

      <div className="cockpit" style={{ paddingTop: "var(--sp-5)" }}>
        <Reveal>
          <Panel title={t("provenance.attestation")}>
            <div className="meta-grid">
              <Meta label={t("provenance.model")} value={attestation.model_id} />
              <Meta label={t("provenance.modelVersion")} value={attestation.model_version} />
              <Meta label={t("verification.provider")} value={attestation.provider} />
              <Meta
                label={t("provenance.promptHash")}
                value={<Hash value={attestation.prompt_hash} head={8} tail={8} />}
              />
              <Meta
                label={t("provenance.evidenceRoot")}
                value={<Hash value={attestation.evidence_merkle_root} head={8} tail={8} />}
              />
              <Meta
                label={t("provenance.canonicalHash")}
                value={<Hash value={attestation.canonical_hash} head={8} tail={8} />}
              />
              <Meta
                label={t("provenance.signer")}
                value={<Hash value={attestation.signer_address} head={6} tail={6} />}
              />
              <Meta label={t("provenance.signerKey")} value={attestation.signer_key_id} />
              <Meta
                label={t("provenance.signature")}
                value={<Hash value={attestation.signature} head={8} tail={8} />}
              />
              <Meta label={t("verification.calibration")} value={attestation.calibration_version} />
              <Meta
                label={t("provenance.humanApprover")}
                value={record.human_approver ?? t("provenance.noHuman")}
              />
              <Meta label={t("deal.terms")} value={<Hash value={record.deal.terms_hash} />} />
            </div>
          </Panel>
        </Reveal>

        <Reveal index={1}>
          <Panel title={t("settlement.payouts")}>
            {record.payouts.length === 0 ? (
              <p className="state-body">{t("settlement.noPayouts")}</p>
            ) : null}
            <div className="stack" style={{ gap: "var(--sp-3)" }}>
              {record.payouts.map((payout) => (
                <div className="stack" key={payout.id} style={{ gap: "var(--sp-2)" }}>
                  <div className="row-between">
                    <span className="micro">
                      {payout.direction} · {inrExact(payout.amount_paise)}
                    </span>
                    {rail ? (
                      <RailTag mode={rail.operations.seller_release ?? rail.mode} />
                    ) : null}
                  </div>
                  <div className="meta-grid">
                    <Meta label={t("settlement.rail")} value={payout.rail} />
                    <Meta label={t("settlement.status")} value={payout.status} />
                    <Meta label={t("settlement.railRef")} value={payout.rail_ref ?? "-"} />
                    <Meta
                      label={t("settlement.railRefHash")}
                      value={<Hash value={payout.rail_ref_hash} />}
                    />
                    <Meta label={t("provenance.at")} value={dateTime(payout.created_at)} />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </Reveal>
      </div>

      <Reveal index={2}>
        {bundle.status === "ready" && bundle.data && bundle.data.artifacts.length > 0 ? (
          <MerklePanel
            artifacts={bundle.data.artifacts}
            root={attestation.evidence_merkle_root}
          />
        ) : (
          <Panel title={t("provenance.tamperCheck")}>
            {bundle.status === "loading" ? (
              <Loading />
            ) : (
              <p className="state-body">{t("provenance.noArtifacts")}</p>
            )}
          </Panel>
        )}
      </Reveal>

      <Reveal index={3}>
        <Panel title={t("chain.title")}>
          <div className="meta-grid">
            <Meta
              label={t("chain.available")}
              value={
                <span
                  style={{
                    color: record.chain.available ? "var(--sig-pass)" : "var(--sig-unverified)",
                  }}
                >
                  {record.chain.available ? t("common.yes") : t("common.no")}
                </span>
              }
            />
            <Meta label={t("chain.chainId")} value={String(record.chain.chain_id)} />
            <Meta
              label={t("chain.contract")}
              value={<Hash value={record.chain.contract_address} head={6} tail={6} />}
            />
            <Meta label={t("chain.dealId")} value={record.deal.chain_deal_id ?? "-"} />
          </div>
          {!record.chain.available ? (
            <p className="table-note">
              {t("chain.unavailable")}
              {record.chain.reason ? ` - ${record.chain.reason}` : ""}
            </p>
          ) : null}
          <div className="stack" style={{ gap: "var(--sp-3)", paddingTop: "var(--sp-4)" }}>
            {record.chain.anchors.map((anchor) => (
              <div className="row-between" key={anchor.id}>
                <span className="micro">{anchor.kind}</span>
                <span className="row">
                  <span className="nano">{anchor.status}</span>
                  {anchor.explorer_url && anchor.tx_hash ? (
                    <a
                      className="link num"
                      href={anchor.explorer_url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {anchor.tx_hash.slice(0, 10)}…
                    </a>
                  ) : (
                    <span className="nano">{t("provenance.anchorQueued")}</span>
                  )}
                  {anchor.last_error ? (
                    <span className="nano" style={{ color: "var(--sig-fail)" }}>
                      {anchor.last_error}
                    </span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </Reveal>

      <Reveal index={4}>
        <LedgerPanel dealId={record.deal.id} />
      </Reveal>

      <Reveal index={5}>
        <p className="prose" style={{ paddingTop: "var(--sp-6)" }}>
          {t("provenance.closing")}
        </p>
      </Reveal>
    </section>
  );
}
