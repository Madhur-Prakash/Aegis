# 01 - MOTION SYSTEM

Every duration, easing and named variant in the product. Measured off the reference recordings at
4–12fps and rounded to a coherent scale.

Library: **Framer Motion** (`motion` package) for React. Tailwind/CSS transitions for trivial
hovers. **Do not add a second animation library** (spec §39).

---

## 1. Measured from the references

| Behaviour | Reference | Measured | Adopted |
|---|---|---|---|
| Preloader node pop-in | A | ~7 frames @30fps ≈ 230ms, bounce | `240ms`, `back` |
| Stepped wipe out | A | ~24 frames ≈ 800ms | `760ms`, `expo-out` |
| Per-word `rotateX` flip | A | ~9 frames ≈ 300ms, ~60ms stagger | `320ms`, `55ms` |
| Vertical slat reveal | B | ~30 frames ≈ 1.0s, per-column stagger | `900ms`, `18ms/col` |
| Blur-up line entrance | B | ~12 frames ≈ 400ms | `440ms` |
| Per-char scramble cycle | C | phrase holds ~2.5s, transition ~700ms | `hold 2600ms`, `xfade 720ms` |
| Cursor dot→disc | D | ~4 frames @12fps ≈ 330ms, trailing | `spring`, lerp `0.16` |
| Hover panel wipe | D | ~5 frames ≈ 420ms | `420ms`, `expo-out` |
| Media swap on hover | D | ~3 frames ≈ 250ms | `260ms` crossfade |

---

## 2. Duration and easing scale

```
--d-instant   90ms    state feedback, chip toggle
--d-fast     180ms    micro-interaction, hover in/out
--d-base     260ms    default transition, media swap
--d-slow     420ms    panel wipe, card entrance
--d-reveal   520ms    section reveal
--d-hero     900ms    hero slat reveal
--d-wipe     760ms    stepped page wipe
```

| Easing | Curve | Use |
|---|---|---|
| `enter` | `cubic-bezier(0.16, 1, 0.30, 1)` | Everything arriving. The house curve. |
| `exit` | `cubic-bezier(0.55, 0, 0.85, 0.25)` | Everything leaving. Faster in, no lingering. |
| `expo` | `cubic-bezier(0.19, 1, 0.22, 1)` | Wipes and masks. Long tail, decisive start. |
| `back` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Chips, badges, the boot nodes. Slight overshoot. |
| `linear` | `linear` | Progress tracks, counters, marquees only. |

**Never** use `ease-in-out` on an entrance. It makes a 300ms animation feel like 500ms.

### Stagger

`--st-tight 40ms` (characters) · `--st-base 55ms` (words, list rows) ·
`--st-loose 90ms` (cards, sections) · `--st-slat 18ms` (slat columns).

Cap total stagger at **400ms**. A 14-item list staggered at 55ms is 770ms of waiting - clamp with
`Math.min(i * 55, 400)`.

---

## 3. The five meaning-bearing moments

Spec §25.3 says the animation budget goes here. These are the five, and each has a required
mechanic. Get these right and the rest can be plain.

### 3.1 The money bar re-splitting
`held → released` after a settlement. The bar is a single flex track of three segments. On
settlement, the segments **animate their flex-basis** (layout animation via Framer's `layout`
prop), the released segment's hue crossfades amber→mint, and the numerals **count up** to the new
value over `--d-reveal`. The sum label re-renders last. Because it is a layout animation, the
invariant `held + released + refunded = funded` is visibly conserved on screen - the bar never
changes total width.

### 3.2 The clause table resolving row by row
Rows arrive with `dropIn` staggered at `--st-base`. Each row's verdict chip resolves as it lands:
`PASS` and `FAIL` **snap** (`--d-fast`, `back`) into place. **`UNVERIFIABLE` does not snap** - see
3.3. Verdict order in the DOM is source order, not sorted by severity; the machine's honesty is
the point, not a tidy list.

### 3.3 `UNVERIFIABLE` arrives differently - the signature moment
Reference C's per-character glyph scramble is reused here with a twist that is the best idea in
this design: **the scramble never fully settles.**

A `PASS` chip's label types in and locks. An `UNVERIFIABLE` chip's label scrambles, resolves to
the word, and then **continues to jitter one random character every 1.8–3.2s, indefinitely**, at
low amplitude. Amber is the only hue on screen. The effect reads instantly and correctly as *the
machine is still not sure* - a live, unresolved state rather than a badge.

Amplitude is deliberately small (one glyph, 90ms, no layout shift). Under
`prefers-reduced-motion` the jitter stops entirely and the chip gains a static `?` glyph plus a
1px dashed border instead. Implementation in `05-SCRAMBLE-CTA.md` § 4.

### 3.4 The attestation seal forming
On sign+anchor: a circular SVG `stroke-dasharray` draws clockwise (`--d-reveal`, `expo`), the
inner sigil scales `0.85 → 1` with `back`, then the truncated tx hash types in beneath in mono at
`--st-tight` per character. One-shot, never replayed on re-render. This is the shot that sells
"provenance" in the video.

### 3.5 The tamper check failing
Deliberately violent, and the only place a shake is allowed: the evidence row translates
`x: [0, -6, 5, -3, 2, 0]` over `--d-slow`, the Merkle path renders in `--sig-fail`, and the
mismatching byte range is marked with a 1px red underline that draws left→right. Then the row
settles into a static failed state. Reduced motion: no shake, straight to the static failed state
with the red path and underline already drawn.

---

## 4. Named variants - the full vocabulary

| Variant | Mechanic | Origin | Applied to |
|---|---|---|---|
| `dropIn` | `y +28 → 0`, `opacity 0→1`, `blur 8→0`, `rotateX -10° → 0` | **A × B** | The default entrance for every element |
| `flipWord` | `rotateX -92° → 0`, per-word, `transform-origin: 50% 100%` | A | Hero and section headlines |
| `blurUp` | `y +18 → 0`, `blur 14→0`, per line | B | Body paragraphs, sub-headlines |
| `slatUp` | Column masks `scaleY 0→1` from bottom, staggered | B | Hero backdrop, image reveals |
| `stepWipe` | Stepped `clip-path` polygon sweep | A | Boot → app transition, route change |
| `chipPop` | `scale 0.7→1`, `opacity 0→1`, `back` | A | Chips, badges, boot nodes, verdict chips |
| `panelWipe` | `scaleX 0→1` from the leading edge | D | Item hover backdrop |
| `mediaSwap` | Crossfade + `scale 1.04→1` | D | Evidence thumbnail on hover |
| `magicBar` | Shared-layout bar sliding between rows | C | List hover, tab indicator |
| `countUp` | Numeric interpolation, tabular-nums | - | Money figures, confidence, counters |
| `sealDraw` | `stroke-dasharray` draw + `back` scale | - | Attestation seal |
| `scrambleCycle` | Per-char randomised crossfade between phrases | C | CTA headline |
| `scrambleUnrest` | Endless single-glyph low-amplitude jitter | C | `UNVERIFIABLE` chips only |
| `sonarPulse` | Nested arc `opacity`+`scale` loop, staggered | C | CTA flanks, "listening" states |

---

## 5. `frontend/design/motion.ts` - copy verbatim

```ts
/* ─────────────────────────────────────────────────────────────────────────
   AEGIS MOTION SYSTEM - the only file that defines a duration or an easing.
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

/* ── dropIn - THE DEFAULT ENTRANCE (reference A × B) ────────── */
export const dropIn: Variants = {
  hidden: { opacity: 0, y: 28, rotateX: -10, filter: "blur(8px)" },
  show: (i: number = 0) => ({
    opacity: 1, y: 0, rotateX: 0, filter: "blur(0px)",
    transition: { ...t(D.reveal), delay: stagger(i, ST.loose) },
  }),
};

/* ── flipWord - per-word flap reveal (reference A) ──────────── */
export const flipWord: Variants = {
  hidden: { rotateX: -92, opacity: 0, y: 6 },
  show: (i: number = 0) => ({
    rotateX: 0, opacity: 1, y: 0,
    transition: { ...t(0.32, E.enter), delay: stagger(i, ST.base) },
  }),
};

/* ── blurUp - per-line soft rise (reference B) ──────────────── */
export const blurUp: Variants = {
  hidden: { opacity: 0, y: 18, filter: "blur(14px)" },
  show: (i: number = 0) => ({
    opacity: 1, y: 0, filter: "blur(0px)",
    transition: { ...t(0.44), delay: stagger(i, ST.base) },
  }),
};

/* ── slatUp - column mask reveal (reference B) ──────────────── */
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

/* ── panelWipe - hover backdrop (reference D) ───────────────── */
export const panelWipe: Variants = {
  rest:  { scaleX: 0, transition: t(D.base, E.exit) },
  hover: { scaleX: 1, transition: t(D.slow, E.expo) },
};

/* ── mediaSwap - alternate thumbnail (reference D) ──────────── */
export const mediaSwap: Variants = {
  rest:  { opacity: 0, scale: 1.04, transition: t(D.base, E.exit) },
  hover: { opacity: 1, scale: 1.0,  transition: t(D.base, E.enter) },
};

/* ── sonarPulse - flanking arcs (reference C) ───────────────── */
export const sonarPulse = (i: number): Variants => ({
  idle: {
    opacity: [0.10, 0.34, 0.10],
    scale:   [0.96, 1.06, 0.96],
    transition: { duration: 2.8, repeat: Infinity, ease: "easeInOut", delay: i * 0.18 },
  },
});

/* ── stepWipe - boot → app (reference A) ────────────────────── */
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

/* ── Scroll-reveal defaults - ALWAYS once:true (spec §25.3) ─── */
export const inView = { once: true, amount: 0.25 } as const;

/* ── Reduced motion ─────────────────────────────────────────── */
export const reduced: Variants = {
  hidden: { opacity: 0 },
  show:   { opacity: 1, transition: t(D.fast, E.enter) },
};

/** Pick the variant set for the current motion preference. */
export const pick = (v: Variants, prefersReduced: boolean) =>
  prefersReduced ? reduced : v;
```

---

## 6. Reduced motion - one hook, honoured globally

```ts
// frontend/hooks/useReducedMotion.ts
"use client";
import { useEffect, useState } from "react";

export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}
```

Under reduced motion:

| Normally | Reduced |
|---|---|
| `dropIn`, `flipWord`, `blurUp`, `slatUp` | Opacity-only crossfade, `--d-fast` |
| `stepWipe` boot transition | Instant swap; the boot panel simply unmounts |
| `sonarPulse` | Static arcs at final opacity |
| `scrambleCycle` | Phrase crossfades, no per-character scrambling |
| `scrambleUnrest` (UNVERIFIABLE jitter) | **Stops.** Static `?` glyph + 1px dashed amber border |
| `countUp` | Final value rendered immediately |
| Tamper shake | No shake; static failed state |
| Parallax, marquee, ambient loops | Disabled entirely |

Every state change stays perceivable. Nothing becomes invisible or unreachable.

Also add the CSS backstop, for anything that slips past the hook:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important; animation-iteration-count: 1 !important;
    transition-duration: .01ms !important; scroll-behavior: auto !important;
  }
}
```

---

## 7. Performance rules

1. **`transform` and `opacity` only** in anything that repeats. `filter: blur()` is permitted in
   one-shot entrances only - never in a loop, never on a large surface.
2. Never animate `width`, `height`, `top`, `left`, `margin`, or `box-shadow`. The money bar's
   width change is the sole exception and uses Framer `layout`, which compensates with transforms.
3. `will-change: transform` **only** on the cursor and on an element currently animating; remove
   it on completion. A page-wide `will-change` costs more than it saves.
4. Scroll reveals use `whileInView` with `viewport={inView}` (`once: true`). No scroll event
   listeners anywhere.
5. Entrance animations run once per mount. Guard with `once: true` or a mounted ref - never
   re-animate on re-render or on scrolling back up.
6. The slat reveal uses **24 columns maximum**, and unmounts its mask elements when complete.
7. Skeletons (not spinners) for loading on the deal cockpit, verification result and review queue.
8. Budget: no more than **~12 simultaneously animating elements**. The clause table stagger caps
   at 400ms precisely so a 30-row table doesn't animate 30 things at once.
9. Verify on a throttled CPU (6× slowdown in devtools) at 375px width before declaring done.
