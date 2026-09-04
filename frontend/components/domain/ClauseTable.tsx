"use client";

/**
 * The clause table (ui/06 §3, motion moment 3.2).
 *
 * Rows arrive in DOM order -- source order, never sorted by severity. The
 * machine's honesty is the point, not a tidy list.
 *
 * `PASS` and `FAIL` chips snap. `UNVERIFIABLE` does not: it scrambles, resolves,
 * and then keeps disturbing one glyph forever. The note for an `UNVERIFIABLE`
 * verdict is rendered in full and never truncated -- it is the product's thesis
 * in one sentence.
 *
 * Below 768px the table becomes cards. This is the screen a judge will open on a
 * phone, and it must not scroll sideways.
 */

import { Reveal } from "@/components/ui/Reveal";
import { VerdictChip } from "@/components/ui/StateChip";
import { ScrollX } from "@/components/ui/primitives";
import type { ClauseVerdict } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function ClauseTable({
  verdicts,
  onEvidenceClick,
}: {
  verdicts: ClauseVerdict[];
  onEvidenceClick?: (artifactId: string) => void;
}) {
  const { t } = useI18n();

  const refs = (verdict: ClauseVerdict) =>
    verdict.evidence_refs.length ? (
      <span className="row" style={{ gap: "var(--sp-2)" }}>
        {verdict.evidence_refs.map((ref) => (
          <button
            key={ref}
            type="button"
            className="link num"
            style={{ fontSize: "var(--fs-micro)" }}
            onClick={() => onEvidenceClick?.(ref)}
            data-cursor=""
          >
            {ref.split(":").pop()?.slice(0, 10)}…
          </button>
        ))}
      </span>
    ) : (
      <span className="num">-</span>
    );

  return (
    <>
      <div className="clause-table-wrap">
        <ScrollX>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">{t("verification.clauses")}</th>
                <th scope="col">{t("verification.decision")}</th>
                <th scope="col">{t("review.evidence")}</th>
              </tr>
            </thead>
            <tbody>
              {verdicts.map((verdict, index) => (
                <Reveal as="tr" key={verdict.clause_id} index={index}>
                  <td className="num">{verdict.clause_id}</td>
                  <td>
                    <div className="stack" style={{ gap: "var(--sp-1)" }}>
                      <span>{verdict.description || verdict.clause_id}</span>
                      {verdict.verdict === "UNVERIFIABLE" ? (
                        <span className="table-note">{verdict.note}</span>
                      ) : verdict.note ? (
                        <span className="micro" style={{ whiteSpace: "normal" }}>
                          {verdict.note}
                        </span>
                      ) : null}
                      {!verdict.required ? (
                        <span className="nano">optional</span>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    <VerdictChip verdict={verdict.verdict} index={index} />
                  </td>
                  <td>{refs(verdict)}</td>
                </Reveal>
              ))}
            </tbody>
          </table>
        </ScrollX>
      </div>

      <div className="clause-cards">
        {verdicts.map((verdict, index) => (
          <Reveal as="article" key={verdict.clause_id} index={index} className="clause-card">
            <div className="row-between">
              <span className="micro">{verdict.clause_id}</span>
              <VerdictChip verdict={verdict.verdict} index={index} />
            </div>
            <span style={{ fontSize: "var(--fs-sm)" }}>
              {verdict.description || verdict.clause_id}
            </span>
            {verdict.note ? (
              <span className={verdict.verdict === "UNVERIFIABLE" ? "table-note" : "micro"}>
                {verdict.note}
              </span>
            ) : null}
            <div>{refs(verdict)}</div>
          </Reveal>
        ))}
      </div>
    </>
  );
}
