"use client";

/**
 * The scramble component (ui/05), used twice: as the closing CTA, and -- in
 * `unrest` mode -- as the visual signature of `UNVERIFIABLE`.
 *
 * `unrest` is the idea the design is built around.  A `PASS` chip's label locks.
 * An `UNVERIFIABLE` chip's label resolves and then keeps disturbing one random
 * character, indefinitely, at low amplitude.  It is the only element in the
 * product that never reaches rest, and it is the only one that should not: a
 * static amber badge says "warning", while a label that cannot hold still says
 * *the machine is still not sure*, which is the literal truth of the state.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { useReducedMotion } from "@/hooks/useReducedMotion";

/** Deliberately the target alphabet plus a few technical marks: it should look
 *  like a machine resolving, not like static. */
const POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/\\|<>-+·";

const rand = (source: string) => source[Math.floor(Math.random() * source.length)] ?? "·";

/**
 * Every phrase occupies the same number of slots, so the line cannot reflow
 * while its glyphs churn -- and the spare slots are split evenly between the
 * two ends, so the words stay centred.
 *
 * `padEnd` alone put all of them on the right: measured, the ink of both
 * eleven-character phrases sat 89px left of centre in a thirteen-slot line,
 * which is exactly one slot at display size. The longest phrase looked correct
 * and the other two did not.
 */
const slotted = (text: string, width: number) => {
  const spare = Math.max(0, width - text.length);
  const left = Math.floor(spare / 2);
  return " ".repeat(left) + text + " ".repeat(spare - left);
};

/** Where `text` starts inside its slots -- the offset `unrest` has to add. */
const slotOffset = (text: string, width: number) =>
  Math.floor(Math.max(0, width - text.length) / 2);

type Props = {
  phrases: string[];
  mode?: "cycle" | "unrest";
  holdMs?: number;
  swapMs?: number;
  className?: string;
  /** Pause the loop when the element is off screen, so a 40-row table does not
   *  run 40 timers. */
  active?: boolean;
};

export function ScrambleText({
  phrases,
  mode = "cycle",
  holdMs = 2600,
  swapMs = 720,
  className,
  active = true,
}: Props) {
  const reduced = useReducedMotion();
  const [idx, setIdx] = useState(0);
  const target = phrases[idx] ?? phrases[0] ?? "";
  const width = useMemo(() => Math.max(...phrases.map((p) => p.length)), [phrases]);
  const [chars, setChars] = useState<string[]>(() => slotted(target, width).split(""));
  const raf = useRef<number>(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const charsRef = useRef<string[]>(chars);
  charsRef.current = chars;

  // Reduced motion, cycle mode: crossfade the phrases, no per-character churn.
  useEffect(() => {
    if (!reduced || mode !== "cycle" || !active || phrases.length < 2) return;
    const id = setInterval(() => setIdx((i) => (i + 1) % phrases.length), holdMs + swapMs);
    return () => clearInterval(id);
  }, [reduced, mode, phrases.length, holdMs, swapMs, active]);

  useEffect(() => {
    if (reduced || !active) {
      setChars(slotted(target, width).split(""));
      return;
    }

    const from = charsRef.current.slice();
    const to = slotted(target, width).split("");

    /* Each slot gets its own randomised start and end frame -- this is what
       produces the reference's out-of-order dissolve rather than a fade. */
    const plan = to.map(() => {
      const start = Math.random() * 0.45;
      const dur = 0.3 + Math.random() * 0.35;
      return { start, end: Math.min(1, start + dur) };
    });

    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / swapMs);
      setChars(
        to.map((ch, i) => {
          const step = plan[i];
          if (!step) return ch;
          if (p < step.start) return from[i] ?? " ";
          if (p >= step.end) return ch;
          return ch === " " ? " " : rand(POOL);
        }),
      );
      if (p < 1) {
        raf.current = requestAnimationFrame(tick);
        return;
      }
      if (mode === "cycle" && phrases.length > 1) {
        timer.current = setTimeout(() => setIdx((i) => (i + 1) % phrases.length), holdMs);
        return;
      }
      if (mode === "unrest") {
        // One glyph, 90ms, forever.  Subtle enough that a viewer notices it on
        // the second look, never enough to read as broken text.
        const loop = () => {
          const trimmed = target.trim();
          if (!trimmed.length) return;
          // Offset past the leading pad, or the disturbed slot would sometimes
          // be one of the blanks and nothing would appear to happen.
          const at =
            slotOffset(target, width) + Math.floor(Math.random() * trimmed.length);
          setChars((current) => {
            const next = current.slice();
            next[at] = rand(POOL);
            return next;
          });
          timer.current = setTimeout(() => {
            setChars(slotted(target, width).split(""));
            timer.current = setTimeout(loop, 1800 + Math.random() * 1400);
          }, 90);
        };
        timer.current = setTimeout(loop, 1200);
      }
    };
    raf.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf.current);
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, reduced, active, mode, target, width, swapMs, holdMs, phrases.length]);

  return (
    <span className={className} aria-label={target} role="text">
      {chars.map((c, i) => (
        <span
          key={i}
          aria-hidden
          /* A space gets a narrower slot. At display size a full 0.62em slot is
             89px of air, which made "SEE THE PROOF" read as three separate
             words rather than one line. Space slots never churn -- the swap
             keeps a space a space -- so narrowing them cannot reflow anything
             mid-transition. */
          className={c === " " ? "sc-ch sc-ch--space" : "sc-ch"}
          style={{ opacity: c === slotted(target, width)[i] ? 1 : 0.55 }}
        >
          {c === " " ? " " : c}
        </span>
      ))}
    </span>
  );
}

/**
 * Four nested arcs per side, breathing slowly.  Sonar = listening for a
 * decision, which is why the same motif flanks the CTA and the empty review
 * queue (ui/05 §5).
 */
export function SonarArcs({
  side = "left",
  count = 4,
  tone = "display",
}: {
  side?: "left" | "right";
  count?: number;
  tone?: "display" | "unverified";
}) {
  const reduced = useReducedMotion();
  const stroke = tone === "unverified" ? "var(--sig-unverified)" : "var(--fg-display)";
  return (
    <svg className={`sonar sonar--${side}`} viewBox="0 0 60 160" fill="none" aria-hidden>
      {Array.from({ length: count }).map((_, i) => {
        const r = 26 + i * 15;
        const x = 58 - i * 14;
        const sweep = side === "left" ? 1 : 0;
        return (
          <path
            key={i}
            d={`M ${x} ${80 - r} A ${r} ${r} 0 0 ${sweep} ${x} ${80 + r}`}
            stroke={stroke}
            strokeWidth="1"
            className={reduced ? undefined : "sonar-arc"}
            style={
              reduced
                ? { opacity: 0.22 }
                : { animationDelay: `${i * 0.18}s` }
            }
          />
        );
      })}
    </svg>
  );
}
