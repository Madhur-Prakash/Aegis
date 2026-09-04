"use client";

/**
 * The entrance system (ui/03).
 *
 * One default (`dropIn`) and five specialists, each applied only where the pack
 * says.  Every entrance is `once: true`; nothing replays on scroll-up.
 */

import { motion } from "motion/react";
import type { ReactNode } from "react";

import { blurUp, chipPop, dropIn, flipWord, inView, pick, slatUp, SLAT_COLUMNS, D, E } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

type Variant = "dropIn" | "blurUp" | "chipPop";

const VARIANTS = { dropIn, blurUp, chipPop } as const;

/** The default entrance for almost everything. */
export function Reveal({
  children,
  index = 0,
  variant = "dropIn",
  as = "div",
  className,
  style,
}: {
  children: ReactNode;
  index?: number;
  variant?: Variant;
  as?: "div" | "li" | "tr" | "section" | "span" | "article";
  className?: string;
  style?: React.CSSProperties;
}) {
  const reduced = useReducedMotion();
  const Component = motion[as];
  return (
    <Component
      custom={index}
      variants={pick(VARIANTS[variant], reduced)}
      initial="hidden"
      whileInView="show"
      viewport={inView}
      className={className}
      style={style}
    >
      {children}
    </Component>
  );
}

/**
 * Per-word `rotateX` flap (ui/02 §4).  Never used below `--fs-h4`: at small
 * sizes the rotation reads as a font-rendering glitch, which is the wrong
 * impression for a product whose whole claim is trustworthiness.
 */
export function FlipHeadline({
  lines,
  className = "display-1",
  perspective = 800,
}: {
  lines: { text: string; tone: "solid" | "muted" }[][];
  className?: string;
  perspective?: number;
}) {
  const reduced = useReducedMotion();
  const v = pick(flipWord, reduced);
  let i = 0; // continuous index across all lines: restarting per line breaks the rhythm
  return (
    <h1 className={className} style={{ perspective }}>
      {lines.map((line, li) => (
        <span
          key={li}
          style={{ display: "block", overflow: "hidden", paddingBottom: ".06em" }}
        >
          {line.map((word) => (
            <motion.span
              key={i}
              custom={i++}
              variants={v}
              initial="hidden"
              whileInView="show"
              viewport={inView}
              className={word.tone === "solid" ? "w-solid" : "w-muted"}
              style={{
                display: "inline-block",
                transformOrigin: "50% 100%",
                marginRight: ".26em",
                willChange: "transform",
              }}
            >
              {word.text}
            </motion.span>
          ))}
        </span>
      ))}
    </h1>
  );
}

/**
 * Per-line soft rise.  Lines are split on a literal " / " at write time, never
 * measured at runtime: runtime splitting breaks on font load, on resize, and on
 * translation into Hindi (ui/03 §5).
 */
export function BlurLines({
  children,
  className = "lede",
}: {
  children: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const v = pick(blurUp, reduced);
  const lines = children.split(" / ");
  return (
    <p className={className}>
      {lines.map((line, i) => (
        <motion.span
          key={i}
          custom={i}
          variants={v}
          initial="hidden"
          whileInView="show"
          viewport={inView}
          style={{ display: "block" }}
        >
          {line}
        </motion.span>
      ))}
    </p>
  );
}

/** A hairline rule draws from the left.  A rule that fades looks like a mistake. */
export function Rule({ className = "" }: { className?: string }) {
  const reduced = useReducedMotion();
  if (reduced) return <hr className={`rule ${className}`} />;
  return (
    <motion.hr
      className={`rule ${className}`}
      initial={{ scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={inView}
      transition={{ duration: D.slow, ease: E.expo as [number, number, number, number] }}
      style={{ transformOrigin: "0% 50%" }}
    />
  );
}

/**
 * The column-mask backdrop (ui/02 §4).  Unmounts its masks on completion, and
 * uses fewer columns on narrow screens.
 */
export function SlatBackdrop({ columns }: { columns?: number }) {
  const reduced = useReducedMotion();
  const count = columns ?? SLAT_COLUMNS;
  if (reduced) return null;
  return (
    <div className="slat-wrap" aria-hidden style={{ ["--slats" as string]: count }}>
      {Array.from({ length: count }).map((_, i) => (
        <motion.span
          key={i}
          custom={i}
          variants={slatUp}
          initial="hidden"
          animate="show"
          className="slat"
        />
      ))}
    </div>
  );
}

/** The generated hairline lattice the slats reveal.  No lifestyle imagery exists. */
export function Lattice({ opacity = 0.06 }: { opacity?: number }) {
  return (
    <div className="lattice" aria-hidden style={{ opacity }}>
      <svg width="100%" height="100%" preserveAspectRatio="none">
        <defs>
          <pattern id="aegis-lattice" width="4.1666%" height="7.1428%" patternUnits="objectBoundingBox">
            <path d="M 0 0 L 0 100 M 0 0 L 100 0" stroke="var(--line-1)" strokeWidth="1" fill="none" />
          </pattern>
          <radialGradient id="aegis-vignette">
            <stop offset="55%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <mask id="aegis-lattice-mask">
            <rect width="100%" height="100%" fill="url(#aegis-vignette)" />
          </mask>
        </defs>
        <rect
          width="100%"
          height="100%"
          fill="url(#aegis-lattice)"
          mask="url(#aegis-lattice-mask)"
        />
      </svg>
    </div>
  );
}
