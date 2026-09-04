# 02 — BOOT SEQUENCE & HERO

The hero is the mix you asked for: **reference A's structure** (staged progress preloader → stepped
wipe → per-word flip headline) on **reference B's canvas** (near-black, vertical slat reveal,
blur-up lines, pinned type with scroll occlusion), with reference D's numeric counter.

Total boot-to-interactive target: **2.6s**, and it must be skippable.

---

## 1. Why the preloader earns its place here

A loading screen is usually a vanity tax. In Aegis it is not, because the app genuinely has four
dependencies that must be ready before money can move — Postgres, Kafka, the chain RPC, and the
payment rail — and the spec already requires a `/health` endpoint that reports each one
(spec §32).

So reference A's progress-node track is wired to **real readiness data**. Each node is a subsystem;
it fills when `/health` reports it ready; if one is degraded the node turns amber and the app boots
into a visibly degraded state rather than lying. The boot screen becomes the product's first
argument: *this system knows what it depends on.*

That also satisfies spec §27's requirement that a missing chain RPC degrades with a visible banner
instead of crashing.

---

## 2. Boot sequence — shot by shot

### Frame 0 → 0.2s · Black
`--ink-900` fill. Nothing. Sets the contrast for everything after.

### 0.2 → 0.6s · Mark and counter arrive
- Centre: the Aegis mark (a 28px seal glyph) fades in with `chipPop`.
- Top-left: `nano` label `AEGIS — PROGRAMMABLE ESCROW`.
- Top-right: `nano` counter `000` → climbing. Mono, tabular, three digits, from reference D.
- Bottom-left: `nano` label `BOOT`.

### 0.6 → 1.9s · The readiness track (reference A)
A `1px` horizontal hairline spans `min(560px, 72vw)`, centred, 88px below the mark. Four node
badges sit on it at 0% / 33% / 66% / 100%.

```
POSTGRES ──●── KAFKA ──●── CHAIN ──●── RAIL ──●
```

- Each node: 28px circle, `--ink-800` fill, `1px solid var(--line-2)`, containing an 11px mono
  glyph (`DB` `KF` `CH` `RL`).
- The **fill line** animates `scaleX 0→1` between nodes, `linear`, as each check returns.
- On ready: node border → `--sig-pass`, glyph → `--sig-pass`, `chipPop` overshoot.
- On degraded: node border → `--sig-unverified`, and a `micro` line appears beneath the track:
  `CHAIN RPC UNAVAILABLE — ANCHORING DISABLED`.
- On hard fail (Postgres): node → `--sig-fail`, boot halts, retry button appears. Do not proceed
  into a broken app.
- Counter reaches `100` as the fourth node resolves.

Minimum on-screen time **1.1s** even if health returns instantly — otherwise it flashes and reads
as a glitch. Maximum **4s**, after which boot proceeds with whatever is ready and the degraded
banner shows.

### 1.9 → 2.66s · Stepped wipe out (reference A — keep this, it is the signature)
The black boot panel exits as a **descending staircase**, sweeping bottom-left → top-right, over
`--d-wipe` (760ms) with `expo`. Six discrete steps. The app is already mounted and painted
underneath, so the wipe reveals a live interface, not a second loading state.

```tsx
<motion.div
  className="boot"
  initial={{ clipPath: stepWipeClip(0) }}
  animate={{ clipPath: stepWipeClip(1) }}
  transition={{ duration: D.wipe, ease: E.expo }}
  onAnimationComplete={onDone}
/>
```

Use the `stepWipeClip(p, steps)` helper from `motion.ts`. If `clip-path` polygon animation stutters
on a target device, fall back to **six sibling `div`s** each scaling `scaleY 1→0` from the top with
an `18ms` stagger — visually near-identical and cheaper.

### Skip and repeat rules
- Any key, click or scroll during boot jumps straight to the wipe.
- Show the full boot **once per session** (`sessionStorage`). Subsequent navigations get a 180ms
  crossfade. Nobody should watch this twice, least of all a judge.
- Reduced motion: no wipe. The panel unmounts after the readiness check with a `--d-fast` fade.

---

## 3. Hero — layout

`100svh`, three stacked layers.

```
┌──────────────────────────────────────────────────────────────┐
│ nano: 01 / 06                            nano: BASE SEPOLIA  │  ← corner metadata (B)
│                                                              │
│                                                              │
│        Every rupee    has a                                  │  ← display-1, two-tone (A)
│        provable       reason.                                │     per-word flip reveal
│                                                              │
│        ┌──────────────────────────────────────────┐          │
│        │ blurUp paragraph, max 52ch                │          │  ← B
│        └──────────────────────────────────────────┘          │
│                                                              │
│        [ OPEN A DEAL ]   [ SEE THE PROOF ]                   │  ← chipPop, staggered
│                                                              │
│ ─────────────────────────────────────────────────────────────│  ← hairline
│ HELD ₹4,20,000   RELEASED ₹1,26,000   FALSE RELEASES 0        │  ← live micro stats (B/D)
└──────────────────────────────────────────────────────────────┘
      slat-revealed backdrop, 6% opacity, behind everything
```

Copy — the headline is the product's thesis, and the stat row is its proof:

- H1: `Every rupee has a provable reason.` (two-tone: solid / muted / solid / solid)
- Sub: `Milestone escrow for deals between strangers. An AI verifies the evidence, a deterministic
  engine moves the money, and every decision is signed and anchored.`
- Stat row: `HELD` · `RELEASED` · `FALSE RELEASES 0` — the last one pulled from the live eval
  result. Putting `0` in the hero is the boldest claim the product makes; make it real.

### Backdrop
Not a photograph (reference B's hero image is not adopted — Aegis has no lifestyle imagery). Use a
**generated hairline lattice**: a 24-column × 14-row grid of `1px` `--line-1` lines at 6% opacity,
with a subtle radial vignette masking the edges. It reveals via `slatUp` and is otherwise static.
Cheap, on-brand, and it gives the slat reveal something to reveal.

---

## 4. Hero entrance — the composite (A × B)

Timeline begins on wipe completion, `t = 0`:

| t | Element | Variant | Detail |
|---|---|---|---|
| 0ms | Backdrop lattice | `slatUp` | 24 columns, `18ms` stagger, `900ms`, `expo`. Bottom-anchored. |
| 180ms | Corner metadata | `blurUp` | Both corners together. |
| 240ms | H1 line 1 words | `flipWord` | Per **word**, `55ms` stagger, `320ms`, `transform-origin: 50% 100%`, `perspective: 800px`. |
| 240 + n | H1 line 2 words | `flipWord` | Continues the same stagger index across lines — do not restart per line, or the rhythm breaks. |
| 620ms | Sub-paragraph | `blurUp` | Per line via `<span>` wrapping, `55ms`. |
| 800ms | CTA buttons | `chipPop` | `40ms` stagger. |
| 900ms | Hairline + stat row | `dropIn` | Rule scales `scaleX 0→1` from left, then stats stagger, then `countUp` on each figure. |

Total ≈ **1.35s**, fully overlapping. It should feel like one gesture, not seven.

### The `flipWord` implementation

This is A's most distinctive move — words rotate about their bottom edge like a flap, so mid-flight
they read mirrored. Split on words, never on characters, at display size (character-splitting a
9rem headline is 40 animated nodes for no gain).

```tsx
"use client";
import { motion } from "motion/react";
import { flipWord, blurUp, inView, pick } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

type Tone = "solid" | "muted";

export function FlipHeadline({ lines }: { lines: { text: string; tone: Tone }[][] }) {
  const reduced = useReducedMotion();
  const v = pick(flipWord, reduced);
  let i = 0;                                  // continuous index across all lines
  return (
    <h1 className="display-1" style={{ perspective: 800 }}>
      {lines.map((line, li) => (
        <span key={li} style={{ display: "block", overflow: "hidden", paddingBottom: ".06em" }}>
          {line.map((w) => (
            <motion.span
              key={i}
              custom={i++}
              variants={v}
              initial="hidden"
              whileInView="show"
              viewport={inView}
              className={w.tone === "solid" ? "w-solid" : "w-muted"}
              style={{ display: "inline-block", transformOrigin: "50% 100%",
                       marginRight: ".26em", willChange: "transform" }}
            >
              {w.text}
            </motion.span>
          ))}
        </span>
      ))}
    </h1>
  );
}
```

Notes that matter:
- `overflow: hidden` on the **line** wrapper is what makes the flip read as a reveal rather than a
  loose spin. Add `padding-bottom: .06em` or descenders get clipped in the resting state.
- `margin-right: .26em` replaces the space that `inline-block` swallows. Tune per font.
- Remove `will-change` after the animation if you animate long lists of these; on a single hero
  it's fine to leave.
- `aria`: the `<h1>` text content is intact and readable in DOM order, so screen readers get the
  full sentence. Do not add `aria-hidden` to the spans.

### The `slatUp` backdrop

```tsx
const cols = Array.from({ length: SLAT_COLUMNS });
<div className="slat-wrap" aria-hidden>
  {cols.map((_, i) => (
    <motion.span key={i} custom={i} variants={slatUp}
      initial="hidden" animate="show" className="slat" />
  ))}
</div>
```

```css
.slat-wrap { position:absolute; inset:0; display:grid;
             grid-template-columns:repeat(var(--slats,24),1fr);
             pointer-events:none; z-index:0; }
.slat      { background:var(--ink-800); transform-origin:50% 100%; }
```

The slats sit **above** the lattice and **below** the type, and they wipe *away* to reveal it
(`scaleY 1→0`) — or wipe *in* as a fill, depending on which reads better against your lattice.
Reference B wipes in from the bottom; start there. Unmount the wrapper on completion.

---

## 5. Scroll behaviour — pinned hero with occlusion (reference B)

B's most memorable scroll move: the hero headline stays put while the next section slides over it,
progressively covering the type. Adopted, with restraint.

```tsx
<section className="hero" style={{ position: "sticky", top: 0, zIndex: 0 }}>…</section>
<section className="next" style={{ position: "relative", zIndex: 1,
         background: "var(--bg)", borderTop: "var(--hairline)" }}>…</section>
```

- The hero is `position: sticky; top: 0`, the following section is `relative` with an opaque
  background and a `1px` top hairline. Pure CSS — **no scroll listener, no scroll-linked JS.**
- Add a scroll-linked fade on the hero content only: `opacity 1 → 0.35` and `scale 1 → 0.97`
  across the first `60vh`, via Framer's `useScroll` + `useTransform` (which uses a passive
  scroll observer, permitted).
- **Do not** replicate B's per-letter jitter on the pinned type. On a financial interface, type
  that appears to glitch reads as a rendering fault, not as style. This is the one place the
  reference is deliberately not followed; note it in `docs/DECISIONS.md`.
- Mobile: disable the sticky pin below `768px` (`position: static`). The occlusion effect needs
  vertical room it doesn't have, and on a phone it just feels broken.

---

## 6. Section openers — the repeating pattern

Every subsequent section reuses one pattern, so the page feels composed rather than assembled:

```
nano: 03 / 06                                        nano: VERIFIER
───────────────────────────────────────────────────────────────────  ← rule, scaleX from left
It said what it        ← display-2, flipWord, two-tone
could not verify.
                       ← blurUp paragraph, 52ch max
[content]              ← dropIn, staggered --st-loose
```

Rule → index labels → headline words → paragraph → content. Same order, every time, `--st-loose`
between groups. Sections are numbered `01/06` through `06/06` in the corner metadata; the number
is real and matches the nav.

---

## 7. Mobile hero

| Property | ≥1024px | 768–1023 | <768px |
|---|---|---|---|
| H1 size | `--fs-display-1` (up to 9rem) | ~5.5rem | `clamp(3.25rem, 11vw, 4rem)` |
| Lines | 2 | 2 | 3 — rebreak the copy, don't let it wrap arbitrarily |
| Sticky pin | on | on | **off** |
| Slat columns | 24 | 16 | 10 |
| Stat row | 3 across | 3 across | 2 across + 1 wrapped, or horizontal `scroll-x` |
| CTA buttons | inline | inline | full-width stacked, `--sp-3` gap |
| Boot track | 560px | 72vw | 84vw, node glyphs only, labels hidden |
| Corner metadata | both corners | both | top-left only |

Test at exactly **375 × 667** (the small end of real traffic in India) as well as 390/412. The H1
must not overflow, and the CTA must be reachable without scrolling.
