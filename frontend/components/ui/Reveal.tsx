"use client";

/**
 * The entrance system (ui/03).
 *
 * One default (`dropIn`) and five specialists, each applied only where the pack
 * says.  Every entrance is `once: true`; nothing replays on scroll-up.
 */

import { motion } from "motion/react";
import type { ReactNode } from "react";

import {
  blurUp,
  chipPop,
  dropIn,
  flipWord,
  inView,
  pick,
  slatUp,
  SLAT_COLUMNS,
  D,
  E,
} from "@/design/motion";
import { useState } from "react";

import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useIsDuplicate } from "@/hooks/useDuplicate";
import { usePeerHover } from "@/hooks/usePeerHover";

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
      viewport={duplicate ? undefined : inView}
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
                  custom={index}
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
}: {
  children: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const duplicate = useIsDuplicate();
  const v = pick(blurUp, reduced);
  const lines = children.split(" / ");
  return (
    <p className={className}>
      {lines.map((line, i) => (
        <motion.span
          key={i}
          custom={i}
          variants={v}
          initial={duplicate ? "show" : "hidden"}
          whileInView={duplicate ? undefined : "show"}
          viewport={duplicate ? undefined : inView}
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

/**
 * The column-mask backdrop (ui/02 §4).
 *
 * The slats are *masks*: they rise to reveal what is behind them and then they
 * must go away.  Left mounted they are simply opaque bars sitting on the hero -
 * and because `--ink-800` is `#FFFFFF` in the light theme, that read as a solid
 * white panel with a hard edge where the container ended.  They now unmount
 * when the last column finishes, which is what the docstring always claimed.
 */
export function SlatBackdrop({ columns }: { columns?: number }) {
  const reduced = useReducedMotion();
  const [done, setDone] = useState(false);
  const count = columns ?? SLAT_COLUMNS;

  if (reduced || done) return null;
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
          // The final column owns the unmount, so it fires once rather than
          // `count` times.
          onAnimationComplete={i === count - 1 ? () => setDone(true) : undefined}
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
