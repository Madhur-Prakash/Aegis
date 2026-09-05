"use client";

/**
 * The money bar (ui/06 §1) -- the most important component in the app.
 *
 * Three flex segments in one fixed-width track.  On settlement the segments
 * animate their `flexGrow` via Framer's `layout` prop, so the total width never
 * changes and `held + released + refunded = funded` is *visibly* conserved
 * (I4 on screen).  The figures count up; the sum line renders last.
 *
 * The tick is computed client-side from the actual numbers, never hardcoded. If
 * `balanced` is false the sum line turns red and shows a cross. That should be
 * impossible; showing it anyway is how the invariant is meant seriously.
 */

import { Tick } from "@/components/ui/icons";
import { motion } from "motion/react";

import { CountUp } from "@/components/ui/primitives";
import { SPRING } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import type { Money } from "@/lib/api";
import { inr } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export function MoneyBar({ money }: { money: Money }) {
  const { t } = useI18n();
  const reduced = useReducedMotion();

  const { funded_paise: funded, released_paise: released, refunded_paise: refunded } = money;
  const held = money.held_paise;
  // Recomputed here rather than trusted from the payload: the screen's claim
  // about conservation should hold even if the API ever disagreed with itself.
  const balanced = held + released + refunded === funded && held >= 0;

  const segments = [
    { key: "released", value: released, colour: "var(--money-released)", label: t("deal.released") },
    { key: "held", value: held, colour: "var(--money-held)", label: t("deal.held") },
    { key: "refunded", value: refunded, colour: "var(--money-refunded)", label: t("deal.refunded") },
  ];

  const ariaLabel = `${t("deal.released")} ${inr(released)}, ${t("deal.held")} ${inr(
    held,
  )}, ${t("deal.refunded")} ${inr(refunded)}, ${t("deal.funded")} ${inr(funded)}`;

  return (
    <div className="money">
      <div className="money-track" role="img" aria-label={ariaLabel}>
        {segments.map((segment) =>
          segment.value > 0 ? (
            <motion.span
              key={segment.key}
              layout={!reduced}
              transition={SPRING.layout}
              className="money-seg"
              style={{ flexGrow: segment.value, background: segment.colour }}
            />
          ) : null,
        )}
        {funded === 0 ? <span className="money-seg" style={{ flexGrow: 1 }} /> : null}
      </div>

      <div className="money-legend">
        {segments.map((segment) => (
          <div className="meta" key={segment.key}>
            <span className="meta-k">
              <span className="money-dot" style={{ background: segment.colour }} aria-hidden />{" "}
              {segment.label}
            </span>
            <span className="meta-v">
              <CountUp value={segment.value} format={inr} />
            </span>
          </div>
        ))}
      </div>

      <p className="money-sum micro" data-balanced={balanced}>
        {t("deal.sumLine")} <CountUp value={funded} format={inr} />{" "}
        <Tick ok={balanced} />
        <span className="visually-hidden">
          {balanced ? t("deal.conserved") : t("deal.broken")}
        </span>
      </p>
    </div>
  );
}
