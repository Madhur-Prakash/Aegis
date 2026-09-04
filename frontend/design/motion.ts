/* ─────────────────────────────────────────────────────────────────────────
   AEGIS MOTION SYSTEM — the only file that defines a duration or an easing.
   Components import named variants; never inline a curve or a number.
   ───────────────────────────────────────────────────────────────────────── */
import type { Transition, Variants } from "motion/react";

/* ── Duration (seconds, for Framer) ─────────────────────────── */
export const D = {
  instant: 0.09,
  fast:    0.18,
  base:    0.26,
  slow:    0.42,
  reveal:  0.52,
  hero:    0.90,
  wipe:    0.76,
} as const;

/* ── Easing ─────────────────────────────────────────────────── */
export const E = {
  enter:  [0.16, 1, 0.30, 1],
  exit:   [0.55, 0, 0.85, 0.25],
  expo:   [0.19, 1, 0.22, 1],
  back:   [0.34, 1.56, 0.64, 1],
} as const;

/* ── Stagger ────────────────────────────────────────────────── */
export const ST = { tight: 0.04, base: 0.055, loose: 0.09, slat: 0.018 } as const;
export const stagger = (i: number, step: number = ST.base, cap = 0.4) =>
  Math.min(i * step, cap);

/* ── Springs ────────────────────────────────────────────────── */
export const SPRING: Record<string, Transition> = {
  cursor: { type: "spring", stiffness: 420, damping: 34, mass: 0.55 },
  chip:   { type: "spring", stiffness: 520, damping: 26, mass: 0.5 },
  layout: { type: "spring", stiffness: 320, damping: 34, mass: 0.8 },
};

/* ── Base transitions ───────────────────────────────────────── */
const t = (duration: number, ease: readonly number[] = E.enter): Transition =>
  ({ duration, ease: ease as [number, number, number, number] });

/* ── dropIn — THE DEFAULT ENTRANCE (reference A × B) ────────── */
export const dropIn: Variants = {
  hidden: { opacity: 0, y: 28, rotateX: -10, filter: "blur(8px)" },
  show: (i: number = 0) => ({
    opacity: 1, y: 0, rotateX: 0, filter: "blur(0px)",
    transition: { ...t(D.reveal), delay: stagger(i, ST.loose) },
  }),
};

/* ── flipWord — per-word flap reveal (reference A) ──────────── */
export const flipWord: Variants = {
  hidden: { rotateX: -92, opacity: 0, y: 6 },
  show: (i: number = 0) => ({
    rotateX: 0, opacity: 1, y: 0,
    transition: { ...t(0.32, E.enter), delay: stagger(i, ST.base) },
  }),
};

/* ── blurUp — per-line soft rise (reference B) ──────────────── */
export const blurUp: Variants = {
  hidden: { opacity: 0, y: 18, filter: "blur(14px)" },
  show: (i: number = 0) => ({
    opacity: 1, y: 0, filter: "blur(0px)",
    transition: { ...t(0.44), delay: stagger(i, ST.base) },
  }),
};

/* ── slatUp — column mask reveal (reference B) ──────────────── */
export const SLAT_COLUMNS = 24;
export const slatUp: Variants = {
  hidden: { scaleY: 0 },
  show: (i: number = 0) => ({
    scaleY: 1,
    transition: { ...t(D.hero, E.expo), delay: i * ST.slat },
  }),
};

/* ── chipPop (reference A) ──────────────────────────────────── */
export const chipPop: Variants = {
  hidden: { opacity: 0, scale: 0.7 },
  show: (i: number = 0) => ({
    opacity: 1, scale: 1,
    transition: { ...SPRING.chip, delay: stagger(i, ST.tight) },
  }),
};

/* ── panelWipe — hover backdrop (reference D) ───────────────── */
export const panelWipe: Variants = {
  rest:  { scaleX: 0, transition: t(D.base, E.exit) },
  hover: { scaleX: 1, transition: t(D.slow, E.expo) },
};

/* ── mediaSwap — alternate thumbnail (reference D) ──────────── */
export const mediaSwap: Variants = {
  rest:  { opacity: 0, scale: 1.04, transition: t(D.base, E.exit) },
  hover: { opacity: 1, scale: 1.0,  transition: t(D.base, E.enter) },
};

/* ── sonarPulse — flanking arcs (reference C) ───────────────── */
export const sonarPulse = (i: number): Variants => ({
  idle: {
    opacity: [0.10, 0.34, 0.10],
    scale:   [0.96, 1.06, 0.96],
    transition: { duration: 2.8, repeat: Infinity, ease: "easeInOut", delay: i * 0.18 },
  },
});

/* ── stepWipe — boot → app (reference A) ────────────────────── */
export const STEP_WIPE_STEPS = 6;
export const stepWipeClip = (p: number, steps = STEP_WIPE_STEPS) => {
  // Descending staircase sweeping bottom-left → top-right.
  const pts: string[] = ["0% 0%", "100% 0%", "100% 100%"];
  for (let s = steps; s >= 0; s--) {
    const x = (s / steps) * 100;
    const y = Math.min(100, Math.max(0, 100 - (p * 100 - (s / steps) * 100) * 1.6));
    pts.push(`${x}% ${y}%`);
  }
  pts.push("0% 100%");
  return `polygon(${pts.join(",")})`;
};

/* ── Scroll-reveal defaults — ALWAYS once:true (spec §25.3) ─── */
export const inView = { once: true, amount: 0.25 } as const;

/* ── Reduced motion ─────────────────────────────────────────── */
export const reduced: Variants = {
  hidden: { opacity: 0 },
  show:   { opacity: 1, transition: t(D.fast, E.enter) },
};

/** Pick the variant set for the current motion preference. */
export const pick = (v: Variants, prefersReduced: boolean) =>
  prefersReduced ? reduced : v;
