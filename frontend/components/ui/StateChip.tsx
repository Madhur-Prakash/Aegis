"use client";

/**
 * The most-used component (ui/00 §6).
 *
 * The copy for the three verdicts is fixed and must not be softened: `PASS`,
 * `UNVERIFIABLE`, `FAIL`.  Never "unclear", "pending" or "review" -- the whole
 * argument of the product rests on the machine saying plainly that it could not
 * verify something.
 *
 * Semantic state is never conveyed by colour alone: every chip carries its word,
 * and clause rows carry a glyph as well as a hue.
 */

import { motion } from "motion/react";
import type { ReactNode } from "react";

import { chipPop, pick, SPRING } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import type { Tone } from "@/lib/format";

import { ScrambleText } from "./ScrambleText";

const TONE: Record<Tone, [string, string, string]> = {
  pass: ["--sig-pass", "--sig-pass-tint", "--sig-pass-edge"],
  unverified: ["--sig-unverified", "--sig-unverified-tint", "--sig-unverified-edge"],
  fail: ["--sig-fail", "--sig-fail-tint", "--sig-fail-edge"],
  neutral: ["--fg-micro", "transparent", "--border"],
};

export const VERDICT_GLYPH: Record<string, string> = {
  PASS: "✓",
  FAIL: "✕",
  UNVERIFIABLE: "?",
};

export function StateChip({
  tone,
  children,
  index = 0,
  animate = true,
  className = "",
}: {
  tone: Tone;
  children: ReactNode;
  index?: number;
  animate?: boolean;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [fg, bg, edge] = TONE[tone];
  const style = {
    color: `var(${fg})`,
    background: bg === "transparent" ? "transparent" : `var(${bg})`,
    borderColor: `var(${edge})`,
  };
  if (!animate || reduced) {
    return (
      <span className={`chip ${className}`} style={style}>
        {children}
      </span>
    );
  }
  return (
    <motion.span
      className={`chip ${className}`}
      style={style}
      custom={index}
      variants={pick(chipPop, reduced)}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, amount: 0.6 }}
      transition={SPRING.chip}
    >
      {children}
    </motion.span>
  );
}

/**
 * A verdict chip.  `PASS` and `FAIL` snap into place; `UNVERIFIABLE` does not --
 * it scrambles, resolves, and then never fully settles (ui/01 §3.3).
 *
 * Under reduced motion the jitter stops entirely and the chip keeps a static `?`
 * plus a dashed border: the same message, no motion.
 */
export function VerdictChip({
  verdict,
  index = 0,
  active = true,
}: {
  verdict: "PASS" | "FAIL" | "UNVERIFIABLE";
  index?: number;
  active?: boolean;
}) {
  const reduced = useReducedMotion();
  const tone: Tone =
    verdict === "PASS" ? "pass" : verdict === "FAIL" ? "fail" : "unverified";

  if (verdict !== "UNVERIFIABLE") {
    return (
      <StateChip tone={tone} index={index}>
        <span aria-hidden>{VERDICT_GLYPH[verdict]}</span>
        {verdict}
      </StateChip>
    );
  }

  return (
    <StateChip
      tone="unverified"
      index={index}
      animate={false}
      className={reduced ? "chip--unrest-static" : "chip--unrest"}
    >
      <span aria-hidden>{VERDICT_GLYPH.UNVERIFIABLE}</span>
      {reduced ? (
        "UNVERIFIABLE"
      ) : (
        <ScrambleText mode="unrest" phrases={["UNVERIFIABLE"]} active={active} />
      )}
    </StateChip>
  );
}

/** A key/value micro-label pair (ui/00 §3).  A micro-label never wraps. */
export function Meta({
  label,
  value,
  title,
  className = "",
}: {
  label: string;
  value: ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <div className={`meta ${className}`}>
      <span className="meta-k">{label}</span>
      <span className="meta-v" title={title}>
        {value}
      </span>
    </div>
  );
}

/** Corner metadata: section index on the left, a state or count on the right. */
export function CornerMeta({ left, right }: { left: string; right?: string }) {
  return (
    <div className="corner-meta">
      <span className="nano">{left}</span>
      {right ? <span className="nano">{right}</span> : null}
    </div>
  );
}
