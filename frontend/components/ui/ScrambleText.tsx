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
const POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/\\|<>—+·";

const rand = (source: string) => source[Math.floor(Math.random() * source.length)] ?? "·";

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
  const [chars, setChars] = useState<string[]>(() => target.padEnd(width).split(""));
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
      setChars(target.padEnd(width).split(""));
      return;
    }

    const from = charsRef.current.slice();
    const to = target.padEnd(width).split("");

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
          const at = Math.floor(Math.random() * trimmed.length);
          setChars((current) => {
            const next = current.slice();
            next[at] = rand(POOL);
            return next;
          });
          timer.current = setTimeout(() => {
            setChars(target.padEnd(width).split(""));
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
          className="sc-ch"
          style={{ opacity: c === target[i] ? 1 : 0.55 }}
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
