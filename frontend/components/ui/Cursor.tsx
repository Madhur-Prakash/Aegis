"use client";

/**
 * The dot-to-disc cursor (ui/04 §1).
 *
 * Reference D's cursor is red.  That is deliberately not copied: red is
 * `--sig-fail` here, and a red disc floating over a passing clause row would be
 * a lie.  This one uses `mix-blend-mode: difference` with a white fill, so it
 * inverts whatever is beneath it -- always visible in both themes, over amber
 * chips, over anything, and claiming no semantic hue.
 *
 * `cursor: none` is applied via `body[data-cursor="on"]` only, so a JS failure
 * can never leave the page with no cursor at all.
 */

import { motion, useMotionValue, useSpring } from "motion/react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { SPRING } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

type Mode = "rest" | "hover" | "label" | "press" | "text";

const GEOMETRY: Record<Mode, { w: number | "auto"; h: number; r: number }> = {
  rest: { w: 8, h: 8, r: 999 },
  hover: { w: 48, h: 48, r: 999 },
  label: { w: "auto", h: 32, r: 999 },
  press: { w: 36, h: 36, r: 999 },
  text: { w: 2, h: 22, r: 1 },
};

export function Cursor() {
  const reduced = useReducedMotion();
  const [enabled, setEnabled] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [mode, setMode] = useState<Mode>("rest");
  const [label, setLabel] = useState("");

  const x = useMotionValue(-100);
  const y = useMotionValue(-100);
  // The lerp/trail from reference D.  Lower stiffness = more trail.
  const sx = useSpring(x, SPRING.cursor);
  const sy = useSpring(y, SPRING.cursor);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!mounted || reduced) return;
    // Pointer devices only.  A custom cursor must never ship to a phone.
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (!fine) return;
    setEnabled(true);
    document.body.dataset.cursor = "on";

    const move = (e: PointerEvent) => {
      x.set(e.clientX);
      y.set(e.clientY);
    };
    const over = (e: PointerEvent) => {
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>("[data-cursor]");
      if (!el) {
        setMode("rest");
        setLabel("");
        return;
      }
      const value = el.dataset.cursor ?? "hover";
      if (value.startsWith("label:")) {
        setLabel(value.slice(6));
        setMode("label");
      } else if (value === "text") {
        setMode("text");
        setLabel("");
      } else {
        setMode("hover");
        setLabel("");
      }
    };
    const down = () => setMode((m) => (m === "rest" ? "press" : m));
    const up = () => setMode((m) => (m === "press" ? "rest" : m));
    const leave = () => {
      x.set(-100);
      y.set(-100);
    };

    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerover", over, { passive: true });
    window.addEventListener("pointerdown", down, { passive: true });
    window.addEventListener("pointerup", up, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerover", over);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      document.removeEventListener("pointerleave", leave);
      delete document.body.dataset.cursor;
      setEnabled(false);
    };
  }, [mounted, reduced, x, y]);

  // Reduced motion returns the native cursor: a trailing spring is exactly the
  // kind of motion that triggers discomfort.
  if (!mounted || !enabled || reduced) return null;

  const geo = GEOMETRY[mode];
  return createPortal(
    <motion.div
      className="cursor"
      style={{ x: sx, y: sy, translateX: "-50%", translateY: "-50%" }}
      animate={{ width: geo.w, height: geo.h, borderRadius: geo.r }}
      transition={SPRING.chip}
      aria-hidden
    >
      {mode === "label" ? <span className="cursor-label">{label}</span> : null}
    </motion.div>,
    document.body,
  );
}
