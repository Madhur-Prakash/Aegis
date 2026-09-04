"use client";

/**
 * The deal's ledger, its on-chain anchors, its settlement authorizations and its
 * payouts -- the four records that together answer "why did this money move?".
 *
 * Authorizations are shown next to payouts on purpose: one authorization with
 * one consumed-at timestamp and one payout is what I6 means in practice, and it
 * is worth being able to see that there is exactly one of each.
 */

import Link from "next/link";
import { useParams } from "next/navigation";

import { ChainPanel } from "@/components/domain/ChainPanel";
import { LedgerPanel } from "@/components/domain/LedgerPanel";
import { RailTag } from "@/components/domain/RailDisclosure";
import { useSession } from "@/components/domain/AppProviders";
import { Reveal } from "@/components/ui/Reveal";
import { CornerMeta, Meta } from "@/components/ui/StateChip";
import { ErrorBlock, Hash, Loading, Panel, ScrollX } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { dateTime, inrExact } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function DealLedgerPage() {
  const dealId = String(useParams().id ?? "");
  const { t } = useI18n();
  const { rail } = useSession();
  const payouts = useAsync(() => api.payouts(dealId), [dealId]);
  const settlements = useAsync(() => api.settlements(dealId), [dealId]);

  return (
    <section className="section">
      <CornerMeta left={t("provenance.ledger")} right={dealId.slice(0, 8)} />
      <div className="row-between">
        <h1 className="display-3">{t("provenance.ledger")}</h1>
        <Link href={`/deals/${dealId}`} className="link" data-cursor="">
          {t("common.back")}
        </Link>
      </div>

      <Reveal>
        <LedgerPanel dealId={dealId} />
      </Reveal>

      <Reveal index={1}>
        <ChainPanel dealId={dealId} />
      </Reveal>

      <Reveal index={2}>
        <Panel title={t("settlement.authorizations")}>
          {settlements.status === "loading" ? <Loading /> : null}
          {settlements.status === "error" ? (
            <ErrorBlock
              code={settlements.error.code}
              message={settlements.error.message}
              onRetry={settlements.reload}
            />
          ) : null}
          {settlements.status === "ready" ? (
            <ScrollX>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">{t("settlement.direction")}</th>
                    <th scope="col">{t("settlement.amount")}</th>
                    <th scope="col">{t("settlement.attempt")}</th>
                    <th scope="col">{t("settlement.authorizedBy")}</th>
                    <th scope="col">{t("settlement.human")}</th>
                    <th scope="col">{t("settlement.consumed")}</th>
                    <th scope="col">{t("settlement.idempotencyKey")}</th>
                  </tr>
                </thead>
                <tbody>
                  {settlements.data.map((authorization) => (
                    <tr key={authorization.id}>
                      <td>{authorization.direction}</td>
                      <td className="num">{inrExact(authorization.amount_paise)}</td>
                      <td className="num">{authorization.attempt_no}</td>
                      <td>{authorization.authorized_by}</td>
                      <td>
                        {authorization.human_approved ? t("common.yes") : t("common.no")}
                      </td>
                      <td className="num">
                        {authorization.consumed_at
                          ? dateTime(authorization.consumed_at)
                          : t("settlement.unconsumed")}
                      </td>
                      <td>
                        <Hash value={authorization.idempotency_key} head={6} tail={6} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollX>
          ) : null}
          <p className="table-note">{t("settlement.note")}</p>
        </Panel>
      </Reveal>

      <Reveal index={3}>
        <Panel
          title={t("settlement.payouts")}
          right={rail ? <RailTag mode={rail.operations.seller_release ?? rail.mode} /> : null}
        >
          {payouts.status === "loading" ? <Loading /> : null}
          {payouts.status === "error" ? (
            <ErrorBlock
              code={payouts.error.code}
              message={payouts.error.message}
              onRetry={payouts.reload}
            />
          ) : null}
          {payouts.status === "ready" ? (
            <ScrollX>
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">{t("settlement.direction")}</th>
                    <th scope="col">{t("settlement.amount")}</th>
                    <th scope="col">{t("settlement.rail")}</th>
                    <th scope="col">{t("settlement.railRef")}</th>
                    <th scope="col">{t("settlement.status")}</th>
                    <th scope="col">{t("provenance.at")}</th>
                  </tr>
                </thead>
                <tbody>
                  {payouts.data.map((payout) => (
                    <tr key={payout.id}>
                      <td>{payout.direction}</td>
                      <td className="num">{inrExact(payout.amount_paise)}</td>
                      <td>{payout.rail}</td>
                      <td className="num">{payout.rail_ref ?? "—"}</td>
                      <td>
                        <div className="stack" style={{ gap: "var(--sp-1)" }}>
                          <span
                            style={{
                              color:
                                payout.status === "SUCCEEDED"
                                  ? "var(--sig-pass)"
                                  : payout.status === "FAILED"
                                    ? "var(--sig-fail)"
                                    : "var(--sig-unverified)",
                            }}
                          >
                            {payout.status}
                          </span>
                          {payout.failure_reason ? (
                            <span className="nano">{payout.failure_reason}</span>
                          ) : null}
                        </div>
                      </td>
                      <td className="num">{dateTime(payout.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollX>
          ) : null}
        </Panel>
      </Reveal>

      <Reveal index={4}>
        <Meta
          label={t("settlement.railDisclosure")}
          value={
            <Link href="/settings#rail" className="link" data-cursor="">
              {t("rail.title")}
            </Link>
          }
        />
      </Reveal>
    </section>
  );
}
