"use client";

/**
 * The entrance system (ui/03).
 *
 * One default (`dropIn`) and five specialists, each applied only where the pack
 * says.  Every entrance is `once: true`; nothing replays on scroll-up.
 */

import { motion } from "motion/react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import {
  blurUp,
  chipPop,
  dropIn,
  flipWord,
  inView,
  pick,
  D,
  E,
} from "@/design/motion";

import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useIsDuplicate } from "@/hooks/useDuplicate";
import { usePeerHover } from "@/hooks/usePeerHover";

type Variant = "dropIn" | "blurUp" | "chipPop";

const VARIANTS = { dropIn, blurUp, chipPop } as const;

/**
 * `inView` asks for a quarter of the element to be visible before it reveals.
 * That is right for a row or a cell, and it is a trap for a headline: a
 * multi-line display block can be taller than a short viewport, and if the
 * observer's first callback lands before layout has settled the ratio may never
 * cross the threshold again -- `once: true` then leaves the content hidden for
 * good. Measured at 215x400 the hero headline came up 0/4 words revealed while
 * a plain observer on the same element reported a ratio of 0.702.
 *
 * Display type therefore reveals on any intersection at all. It is on screen;
 * that is the whole condition. `inView` itself is untouched because
 * `design/motion.ts` is copied verbatim from the pack.
 *
 * Content that can never appear is the worst failure this page has, so the
 * looser threshold is the correct trade against revealing a few pixels early.
 */
const enterDisplay = { ...inView, amount: "some" } as const;

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
  const duplicate = useIsDuplicate();
  const Component = motion[as];
  return (
    <Component
      custom={index}
      variants={pick(VARIANTS[variant], reduced)}
      // A decorative duplicate is already there; only the real one arrives.
      initial={duplicate ? "show" : "hidden"}
      whileInView={duplicate ? undefined : "show"}
      viewport={duplicate ? undefined : inView}
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
  trailing,
  interactive = false,
  as = "h1",
  pace = 1,
}: {
  lines: { text: string; tone: "solid" | "muted" }[][];
  className?: string;
  perspective?: number;
  /** Rendered inside the final line, in the text flow -- this is where an
   *  inline headline chip goes (ui/00 §2.4). Never more than one. */
  trailing?: ReactNode;
  /**
   * Per-word hover: the word under the pointer grows and takes the canvas's
   * maximum-contrast colour while its neighbours recede.
   *
   * Contrast is `--fg-display` -- white on the dark canvas, near-black on the
   * light one -- so "contrasting with the background" holds in both themes
   * without naming a colour.
   */
  interactive?: boolean;
  as?: "h1" | "h2";
  /**
   * Spreads the per-word stagger: the index handed to `flipWord` is multiplied
   * by this. The variants live in the verbatim `motion.ts`, so the step itself
   * cannot change, and `stagger()` caps at 0.4s -- a pace of 2.4 puts four
   * words at 0 / 0.13 / 0.26 / 0.40 instead of 0 / .055 / .11 / .165.
   */
  pace?: number;
}) {
  const reduced = useReducedMotion();
  const duplicate = useIsDuplicate();
  // One mechanism for every hover on the page: the word under the pointer grows
  // and takes full contrast, its neighbours shrink a hair and recede.  See
  // `usePeerHover`.
  const peers = usePeerHover();
  const live = interactive && peers.live;
  const v = pick(flipWord, reduced);
  let i = 0; // continuous index across all lines: restarting per line breaks the rhythm

  // The reveal is driven from the headline, not from each word.
  //
  // Each word used to carry its own `whileInView`, and every section headline
  // stayed invisible because of it: `flipWord`'s hidden state is
  // `rotateX: -92deg`, which collapses the word's transformed box to roughly
  // zero area, and IntersectionObserver divides intersection area by that box
  // -- so the ratio could never reach `amount: 0.25` and the observer never
  // fired. The headline itself is untransformed, so observing it works, and the
  // variant label propagates down to the words, each still resolving its own
  // stagger from `custom`. It is also four observers fewer per headline.
  const Tag = as === "h2" ? motion.h2 : motion.h1;

  return (
    <Tag
      className={className}
      style={{ perspective }}
      initial={duplicate ? "show" : "hidden"}
      whileInView={duplicate ? undefined : "show"}
      viewport={duplicate ? undefined : enterDisplay}
      {...(live ? peers.group : {})}
    >
      {lines.map((line, li) => (
        <span
          key={li}
          style={{ display: "block", overflow: "hidden", paddingBottom: ".06em" }}
        >
          {line.map((word) => {
            const index = i++;
            return (
              /* Two elements on purpose: the inner one is the reveal (a Framer
                 variant animating transform), the outer one is the hover (a CSS
                 transition on transform and colour). One element cannot own two
                 competing transforms. */
              <span
                key={index}
                className={`hword ${word.tone === "solid" ? "w-solid" : "w-muted"}`}
                {...(live ? peers.peer(String(index)) : {})}
              >
                <motion.span
                  custom={index * pace}
                  variants={v}
                  style={{
                    display: "inline-block",
                    transformOrigin: "50% 100%",
                    willChange: "transform",
                  }}
                >
                  {word.text}
                </motion.span>
              </span>
            );
          })}
          {trailing && li === lines.length - 1 ? trailing : null}
        </span>
      ))}
    </Tag>
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
  pace = 1,
  cue,
}: {
  children: string;
  className?: string;
  /** Spreads the per-line stagger; see `FlipHeadline`. */
  pace?: number;
  /**
   * Seconds after mount before the lines start. A cue replaces the viewport
   * trigger: the hero lede is on screen the moment the page is, and what it
   * needs is not "when visible" but "after the headline". Scroll sections do
   * not pass one and keep `whileInView`.
   */
  cue?: number;
}) {
  const reduced = useReducedMotion();
  const duplicate = useIsDuplicate();
  const v = pick(blurUp, reduced);
  const lines = children.split(" / ");
  const gated = cue !== undefined;
  const [cued, setCued] = useState(!gated);
  useEffect(() => {
    if (!gated) return;
    const id = setTimeout(() => setCued(true), reduced ? 0 : cue * 1000);
    return () => clearTimeout(id);
  }, [gated, cue, reduced]);
  return (
    <p className={className}>
      {lines.map((line, i) => (
        <motion.span
          key={i}
          custom={i * pace}
          variants={v}
          initial={duplicate ? "show" : "hidden"}
          animate={gated ? (cued || duplicate ? "show" : "hidden") : undefined}
          whileInView={gated || duplicate ? undefined : "show"}
          viewport={gated || duplicate ? undefined : enterDisplay}
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
  const duplicate = useIsDuplicate();
  if (reduced || duplicate) return <hr className={`rule ${className}`} />;
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
