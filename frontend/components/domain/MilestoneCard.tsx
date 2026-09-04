"use client";

/**
 * The milestone card (ui/04 §2 applied to ui/06 §1).
 *
 * The hover panel is not decorative: it is tinted with the milestone's semantic
 * state, so hovering tells you the state through the wipe colour itself. The
 * panel is inset negatively so it reads as a backdrop growing out from behind
 * the card. Nothing lifts and nothing gains a shadow -- reference D's restraint
 * is what makes it feel expensive.
 *
 * `whileFocus` mirrors the hover state: the keyboard gets the same affordance,
 * and nothing is reachable by hover alone.
 */

import Link from "next/link";
import { motion } from "motion/react";

import { StateChip, Meta } from "@/components/ui/StateChip";
import { mediaSwap, panelWipe } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import type { MilestoneSummary } from "@/lib/api";
import { confidence as fmtConfidence, inr, milestoneTone, seq } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function MilestoneCard({
  milestone,
  dealId,
  total,
  index,
}: {
  milestone: MilestoneSummary;
  dealId: string;
  total: number;
  index: number;
}) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const tone = milestoneTone(milestone.state);
  const href = milestone.attestation_id
    ? `/deals/${dealId}/milestones/${milestone.id}/verification`
    : `/deals/${dealId}/milestones/${milestone.id}/evidence`;

  return (
    <motion.div
      className="hcard"
      initial="rest"
      whileHover={reduced ? "rest" : "hover"}
      whileFocus="hover"
      data-cursor={`label:${t("deal.viewProof")}`}
    >
      <motion.span
        className="hcard-panel"
        variants={panelWipe}
        style={{
          background: tone === "neutral" ? "var(--ink-700)" : `var(--sig-${tone}-tint)`,
          borderColor: tone === "neutral" ? "var(--border)" : `var(--sig-${tone}-edge)`,
          transformOrigin: index % 2 === 0 ? "0% 50%" : "100% 50%",
        }}
        aria-hidden
      />
      <Link href={href} className="hcard-body" data-cursor={`label:${t("deal.viewProof")}`}>
        <div className="row-between">
          <span className="micro num">{seq(milestone.seq, total)}</span>
          <StateChip tone={tone} index={index}>
            {t(`state.${milestone.state}`)}
          </StateChip>
        </div>
        <span className="hcard-amount">{inr(milestone.amount_paise)}</span>
        <span className="hcard-title">{milestone.title}</span>
        {milestone.confidence !== null && milestone.decision ? (
          <motion.span variants={mediaSwap} className="micro">
            {milestone.decision} · {t("verification.confidence")}{" "}
            {fmtConfidence(milestone.confidence)}
          </motion.span>
        ) : (
          <span className="micro">
            {milestone.has_evidence ? t("evidence.submitted") : t("evidence.notProvided")}
          </span>
        )}
        <Meta
          label={t("verification.clauses")}
          value={`${milestone.verification_condition.clauses?.length ?? 0}`}
        />
      </Link>
    </motion.div>
  );
}
