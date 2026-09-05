"use client";

/**
 * The milestone lifecycle strip (ui/06 §1).
 *
 * The whole state machine, drawn once, with the current node emphasised and
 * everything already passed marked in mint.  The two endings -- SETTLED and
 * REJECTED -- are drawn with equal weight, because the product's claim is that
 * refusing to release is as legitimate an outcome as releasing.
 *
 * The states are exactly the backend's `MilestoneState` values; nothing here is
 * a display-only invention.
 */

import { ArrowRight, CornerDownRight } from "lucide-react";
import { motion } from "motion/react";

import { SPRING } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { milestoneTone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

/** The happy path, in order.  Branch states hang off `VERIFYING`. */
const SPINE = ["PENDING", "EVIDENCE_SUBMITTED", "VERIFYING"] as const;
const BRANCH = ["RELEASE_APPROVED", "UNDER_HUMAN_REVIEW", "REJECTED", "DISPUTED"] as const;
const TERMINAL = "SETTLED";

const ORDER: readonly string[] = [...SPINE, ...BRANCH, TERMINAL];

export function StateStrip({ state }: { state: string }) {
  const { t } = useI18n();
  const reduced = useReducedMotion();
  const current = ORDER.indexOf(state);

  const node = (name: string, index: number) => {
    const active = name === state;
    // "Past" is only meaningful along the spine: a branch state is not a
    // predecessor of another branch state.
    const past = current > -1 && index < current && index < SPINE.length;
    const tone = milestoneTone(name);
    return (
      <motion.span
        key={name}
        className={`state-step ${active ? "is-current" : past ? "is-past" : ""}`}
        style={active && tone !== "neutral" ? { color: `var(--sig-${tone})` } : undefined}
        initial={reduced ? false : { opacity: 0, y: 3 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...SPRING.chip, delay: reduced ? 0 : index * 0.03 }}
        aria-current={active ? "step" : undefined}
      >
        {t(`state.${name}`)}
      </motion.span>
    );
  };

  return (
    <nav className="stack" aria-label={t("deal.lifecycle")} style={{ gap: "var(--sp-2)" }}>
      <div className="states">
        {SPINE.map((name, index) => (
          <span className="states" key={name}>
            {node(name, index)}
            {index < SPINE.length - 1 ? (
              <span className="state-sep" aria-hidden>
                <ArrowRight size={12} strokeWidth={2} />
              </span>
            ) : null}
          </span>
        ))}
      </div>
      <div className="states">
        <span className="state-sep" aria-hidden>
          <CornerDownRight size={12} strokeWidth={2} />
        </span>
        {BRANCH.map((name, index) => node(name, SPINE.length + index))}
      </div>
      <div className="states">
        <span className="state-sep" aria-hidden>
          <CornerDownRight size={12} strokeWidth={2} />
        </span>
        {node(TERMINAL, ORDER.length - 1)}
      </div>
    </nav>
  );
}
