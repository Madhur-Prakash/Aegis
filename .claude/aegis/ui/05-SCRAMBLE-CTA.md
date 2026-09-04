# 05 - THE SCRAMBLE CTA (+ the `UNVERIFIABLE` reuse)

This is the component from your screenshot - reference **C** at **0:12**, the *"Got Project? /
LET'S TALK"* block. It is the best piece of motion in the four references, and it gets used twice
in Aegis: once as the closing CTA, and once - repurposed - as the visual signature of the
product's most important state.

---

## 1. What the reference actually does

Frame-by-frame at 6fps across 0:09–0:16, the mechanics are:

1. A small label sits above the display line: `Got Project?`, regular weight, ~18px.
2. The display line cycles between phrases: **`LET'S TALK` → `PING US` → `JOIN US` → repeat.**
3. The transition is **not** a fade of the whole word. Each character is handled independently:
   outgoing characters drop out **in randomised order**, not left-to-right, some passing through a
   dimmed intermediate state; incoming characters arrive **in a different randomised order**.
   Mid-transition frames show genuine hybrids - `LP⌐ G`, `LE S K` - letters from both phrases on
   screen at once at different opacities and slight baseline offsets.
4. Characters hold their **horizontal slot** during the swap, so the line never reflows. The
   jitter is vertical and sub-pixel-ish, a few pixels at most.
5. Flanking both sides: **four nested arcs** per side, like `(((` and `)))` - thin white strokes,
   low opacity, breathing in a slow staggered pulse. Sonar.
6. A **capsule cursor** carrying a label (`START ●` in your screenshot) rides over the type.
7. Background pure black, type white, geometric grotesk, very large, tight tracking.
8. Phrase hold ≈ 2.5s, crossfade ≈ 700ms.

---

## 2. Aegis version - the closing CTA

Same mechanics, Aegis content. This is section `06/06`, full-bleed `--ink-900`, `100svh` minus nav.

```
        nano: 06 / 06                              nano: OPEN AN ESCROW

                      Got a deal you don't trust?          ← label, --fs-h4, --fg-secondary

        ((( ((       O P E N   A   D E A L        )) )))   ← display-1, scrambling
                                                              flanked by sonar arcs

              ┌──────────────────────────────────┐
              │  ●  START                        │          ← capsule button (from the screenshot)
              └──────────────────────────────────┘

        ──────────────────────────────────────────────────
        NO CARD REQUIRED · TEST MODE · ₹0 TO TRY           ← micro
```

Cycling phrases - each is a real thing the product does, so the cycle *informs* rather than
decorates:

```ts
const PHRASES = ["OPEN A DEAL", "FUND ESCROW", "SEE THE PROOF"];
```

All three are the same character length band (10–13) so the flanking arcs don't jump. If you add
one, keep it in that band or the layout breathes visibly.

### The capsule button

Straight from your screenshot: a pill with a leading dot and a label. The dot is the live state.

```css
.capsule {
  display:inline-flex; align-items:center; gap:.7em;
  padding:.85rem 1.6rem; border-radius:var(--r-full);
  background:var(--bone-100); color:var(--ink-900);
  font:600 var(--fs-micro)/1 var(--font-mono);
  letter-spacing:.12em; text-transform:uppercase;
  border:0; transition:background var(--d-fast) ease;
}
.capsule:hover { background:#fff; }
.capsule-dot   { width:.6em; height:.6em; border-radius:var(--r-full);
                 background:var(--sig-pass); }
```

---

## 3. `ScrambleText` - implementation

One component serves both uses. Two modes: `cycle` (the CTA) and `unrest` (the `UNVERIFIABLE`
chip, §4).

```tsx
"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "@/hooks/useReducedMotion";

/** Glyphs the scramble draws from. Deliberately includes the target alphabet plus
 *  a few technical marks - it should look like a machine resolving, not like static. */
const POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/\\|<>-+·";

const rand = (s: string) => s[Math.floor(Math.random() * s.length)];

type Props = {
  phrases: string[];
  mode?: "cycle" | "unrest";
  holdMs?: number;        // how long a resolved phrase sits
  swapMs?: number;        // crossfade duration
  className?: string;
};

export function ScrambleText({
  phrases, mode = "cycle", holdMs = 2600, swapMs = 720, className,
}: Props) {
  const reduced = useReducedMotion();
  const [idx, setIdx] = useState(0);
  const target = phrases[idx];
  const width = useMemo(() => Math.max(...phrases.map((p) => p.length)), [phrases]);
  const [chars, setChars] = useState<string[]>(() => target.padEnd(width).split(""));
  const raf = useRef<number>(0);

  /* ── resolved-phrase renderer for reduced motion ───────────── */
  useEffect(() => {
    if (!reduced || mode !== "cycle") return;
    const id = setInterval(() => setIdx((i) => (i + 1) % phrases.length), holdMs + swapMs);
    return () => clearInterval(id);
  }, [reduced, mode, phrases.length, holdMs, swapMs]);

  useEffect(() => {
    if (reduced) { setChars(target.padEnd(width).split("")); return; }

    const from = chars.slice();
    const to = target.padEnd(width).split("");

    /* Each slot gets its own randomised start and end frame - this is what
       produces the reference's out-of-order dissolve. */
    const plan = to.map((_, i) => {
      const start = Math.random() * 0.45;            // 0–45% of the swap
      const dur   = 0.30 + Math.random() * 0.35;     // 30–65% of the swap
      return { start, end: Math.min(1, start + dur) };
    });

    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / swapMs);
      setChars(
        to.map((ch, i) => {
          const { start, end } = plan[i];
          if (p < start) return from[i] ?? " ";                  // still the old glyph
          if (p >= end)  return ch;                              // resolved
          return ch === " " ? " " : rand(POOL);                  // scrambling
        }),
      );
      if (p < 1) raf.current = requestAnimationFrame(tick);
      else if (mode === "cycle") {
        setTimeout(() => setIdx((i) => (i + 1) % phrases.length), holdMs);
      }
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, reduced]);

  return (
    <span className={className} aria-label={target} role="text">
      {chars.map((c, i) => (
        <span key={i} aria-hidden className="sc-ch"
          style={{ opacity: c === target[i] ? 1 : 0.55 }}>
          {c === " " ? " " : c}
        </span>
      ))}
    </span>
  );
}
```

```css
.sc-ch {
  display:inline-block;
  width:.62em;                       /* fixed slot - the line never reflows */
  text-align:center;
  transition:opacity 90ms linear;
  font-variant-ligatures:none;
}
```

Implementation notes that matter:

- **Fixed-width slots** (`width: .62em`) are the reason the line stays still while glyphs churn.
  Without them the headline jitters horizontally and looks broken. Tune `.62em` to your font's
  cap-width; measure with `ZZZZZ` versus `IIIII`.
- Unresolved glyphs render at `opacity .55`. That dimmed intermediate is clearly visible in the
  reference and is what makes the effect read as *resolving* rather than *flickering*.
- `padEnd(width)` to the longest phrase so the arcs never move.
- One `requestAnimationFrame` loop, no per-character timers. A 13-character headline with 13
  `setInterval`s will drop frames.
- `aria-label` carries the resolved phrase; every glyph span is `aria-hidden`. A screen reader must
  never be read a wall of random characters.
- `font-variant-ligatures: none` - otherwise pairs like `TT` or `fi` re-ligate mid-scramble and
  the slot width breaks.

---

## 4. The reuse - `UNVERIFIABLE` that never settles

This is the idea worth building the design around.

A `PASS` chip's label types in and **locks**. A `FAIL` chip snaps in hard. But an
`UNVERIFIABLE` chip resolves to the word and then **keeps disturbing one random character,
indefinitely**, at low amplitude:

```tsx
<ScrambleText mode="unrest" phrases={["UNVERIFIABLE"]} />
```

In `unrest` mode: after resolving, every **1.8–3.2s** pick one character slot, replace it with a
random glyph for **90ms**, then restore it. One glyph, briefly, forever.

```ts
/* add inside ScrambleText, after the resolve completes */
if (mode === "unrest") {
  const loop = () => {
    const i = Math.floor(Math.random() * target.trim().length);
    setChars((c) => { const n = c.slice(); n[i] = rand(POOL); return n; });
    setTimeout(() => setChars(target.padEnd(width).split("")), 90);
    timer.current = setTimeout(loop, 1800 + Math.random() * 1400);
  };
  timer.current = setTimeout(loop, 1200);
}
```

**Why this is the right decision.** Aegis's entire pitch is *"it did not guess and it did not
block - it said what it could not verify."* A static amber badge says "warning." A label that
cannot hold still says *the machine is still not sure* - which is the literal truth of the state.
It is the only element in the product that never reaches rest, and it is the only one that
shouldn't. Combined with amber being the sole hue that appears nowhere decorative, the escalation
moment in the demo video is unmistakable without a word of narration.

Constraints:
- **One glyph at a time, 90ms, no layout shift.** If it reads as "broken text" you have overdone
  it. Subtle enough that a viewer notices it on the second look.
- Never on `PASS` or `FAIL`. Never on more than the chips currently in view - pause the loop when
  the chip leaves the viewport (`useInView`) so a 40-row table isn't running 40 timers.
- **Reduced motion: the jitter stops entirely.** The chip instead gains a static `?` glyph and a
  `1px dashed var(--sig-unverified-edge)` border. Same message, no motion.

---

## 5. The sonar arcs

Four nested arcs per side, mirrored. Thin, low-opacity, slow staggered breathing pulse.

```tsx
export function SonarArcs({ side = "left", count = 4 }:
  { side?: "left" | "right"; count?: number }) {
  const reduced = useReducedMotion();
  return (
    <svg className={`sonar sonar--${side}`} viewBox="0 0 60 160" fill="none" aria-hidden>
      {Array.from({ length: count }).map((_, i) => {
        const r = 26 + i * 15;
        return (
          <motion.path
            key={i}
            d={`M ${58 - i * 14} ${80 - r} A ${r} ${r} 0 0 ${side === "left" ? 1 : 0} ${58 - i * 14} ${80 + r}`}
            stroke="var(--fg-display)" strokeWidth="1"
            variants={reduced ? undefined : sonarPulse(i)}
            animate={reduced ? undefined : "idle"}
            style={reduced ? { opacity: 0.22 } : undefined}
          />
        );
      })}
    </svg>
  );
}
```

```css
.sonar         { position:absolute; top:50%; translate:0 -50%;
                 width:clamp(48px,7vw,84px); height:auto; opacity:1; }
.sonar--left   { left:clamp(.5rem,4vw,4rem); }
.sonar--right  { right:clamp(.5rem,4vw,4rem); transform:scaleX(-1) translateY(-50%); }
@media (max-width:767px) { .sonar { display:none; } }   /* no room; drop them */
```

Pulse: `opacity [0.10, 0.34, 0.10]`, `scale [0.96, 1.06, 0.96]`, `2.8s`, infinite, `easeInOut`,
`180ms` stagger per arc - outward-travelling. Under reduced motion they hold static at `0.22`.

**Second use:** the same arcs, at `--sig-unverified`, flank the "awaiting human review" empty state
in the review queue. Sonar = *listening for a decision*. Reusing one motif for two related meanings
is what makes a design system feel authored.

---

## 6. Composition of the CTA section

| t | Element | Variant |
|---|---|---|
| 0ms | Corner metadata + rule | `blurUp` / `scaleX` |
| 120ms | Label (`Got a deal you don't trust?`) | `blurUp` |
| 240ms | Display line - first phrase resolves from full scramble | `ScrambleText` initial resolve, `900ms` |
| 240ms | Sonar arcs fade in and begin pulsing | `opacity 0→1`, `--d-reveal` |
| 700ms | Capsule button | `chipPop` |
| 820ms | Micro line beneath | `dropIn` |

The section starts cycling only **after** it enters the viewport (`useInView`, `once: false` here -
this is the one place a repeating animation is correct, since it's an ambient loop, not an
entrance). Pause the cycle when out of view to save cycles on mobile.

---

## 7. Where this component appears

| Location | Mode | Content |
|---|---|---|
| Landing, section 06/06 | `cycle` | `OPEN A DEAL` / `FUND ESCROW` / `SEE THE PROOF` |
| Clause verdict chips | `unrest` | `UNVERIFIABLE` only |
| Review queue empty state | `cycle`, slow (`holdMs: 4000`) | `AWAITING REVIEW` / `NOTHING QUEUED` + amber arcs |
| Verification in progress | `cycle`, fast (`holdMs: 900`) | `EXTRACTING` / `EVALUATING` / `SIGNING` - mirrors the real pipeline stage, driven by SSE |

That last one is worth doing properly: while the verifier runs, the headline scrambles between the
actual pipeline stage names streamed from the backend. The scramble stops being decoration and
becomes a progress indicator for a process that genuinely is resolving.
