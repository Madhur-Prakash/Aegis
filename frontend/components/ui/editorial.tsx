"use client";

/**
 * The editorial composition primitives (ui/00 §2.3-2.4, ui/02 §6, reference B4).
 *
 * These four exist because the landing page was assembled out of generic cards
 * when the references are built out of hairline rules, micro-label columns and
 * oversized type that runs off the edge of the frame.  A card grid is the one
 * thing none of the four references contains.
 */

import { motion, useScroll, useTransform } from "motion/react";
import type { ReactNode } from "react";
import { useRef } from "react";

import { InvertOnHover } from "@/components/ui/InvertOnHover";
import { FlipHeadline, BlurLines, Reveal } from "@/components/ui/Reveal";
import { D, E, ST, SPRING, inView, pick, dropIn } from "@/design/motion";
import { useIsDuplicate } from "@/hooks/useDuplicate";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { usePeerHover } from "@/hooks/usePeerHover";
import type { Tone } from "@/lib/format";

// ── Inline headline chip (ui/00 §2.4) ───────────────────────────────────────
/**
 * Reference A embeds small circular badges *inside* the headline text flow.
 * Adopted, and given a job: the chip carries a live value, so the headline
 * states a fact instead of decorating one.
 *
 * Never more than one per headline -- the pack is explicit, and two of them
 * turn a statement into a dashboard.
 */
export function HeadlineChip({
  value,
  tone = "unverified",
  label,
}: {
  value: string;
  tone?: Tone;
  label?: string;
}) {
  const reduced = useReducedMotion();
  const duplicate = useIsDuplicate();
  const colour = tone === "neutral" ? "--fg-micro" : `--sig-${tone}`;
  return (
    <motion.span
      className="headline-chip num"
      style={{
        color: `var(${colour})`,
        background: tone === "neutral" ? "transparent" : `var(--sig-${tone}-tint)`,
        borderColor: tone === "neutral" ? "var(--border)" : `var(--sig-${tone}-edge)`,
      }}
      aria-label={label}
      // The chip rides inside the headline, so it is duplicated with it.
      initial={duplicate ? { opacity: 1, scale: 1 } : reduced ? { opacity: 0 } : { opacity: 0, scale: 0.7 }}
      whileInView={duplicate ? undefined : { opacity: 1, scale: 1 }}
      viewport={duplicate ? undefined : inView}
      transition={
        reduced
          ? { duration: D.fast }
          : { duration: D.base, ease: E.back as [number, number, number, number] }
      }
    >
      {value}
    </motion.span>
  );
}

// ── Section opener (ui/02 §6) ───────────────────────────────────────────────
/**
 * One pattern, every section, in a fixed order:
 *
 *   rule (draws from the left) -> index labels -> flipWord headline -> paragraph
 *
 * The order is what makes the page read as composed rather than assembled, and
 * it is why the section numbers are real: `03 / 06` in the corner matches the
 * third opener on the page.
 */
export function SectionOpener({
  index,
  total = 6,
  label,
  lines,
  lede,
  chip,
  id,
  interactive = true,
}: {
  index: number;
  total?: number;
  label: string;
  /** Per-word two-tone content; `flipWord` runs one continuous index across lines. */
  lines: { text: string; tone: "solid" | "muted" }[][];
  lede?: string;
  chip?: ReactNode;
  id?: string;
  /**
   * The opener headline gets the same two pointer gestures as the hero: the
   * inverting disc, and per-word growth with full contrast.  On by default --
   * a page where only the first headline answers the pointer reads as an
   * unfinished one, which is exactly how it read before.
   */
  interactive?: boolean;
}) {
  const reduced = useReducedMotion();
  const pad = (n: number) => String(n).padStart(2, "0");

  const title = (
    <FlipHeadline
      lines={lines}
      className="display-2 opener-title"
      trailing={chip}
      interactive={interactive}
      as="h2"
    />
  );
  // `display-2` is smaller than the hero, so the disc is smaller too: it is
  // scaled to the type, not to the viewport.  Not wrapped at all when the
  // opener is static, so a non-interactive headline carries no extra layer.
  const headline = interactive ? <InvertOnHover>{title}</InvertOnHover> : title;

  return (
    <header className="opener" id={id}>
      {/* A rule that fades looks like a mistake; it should draw. */}
      <motion.hr
        className="rule opener-rule"
        initial={reduced ? { opacity: 0 } : { scaleX: 0 }}
        whileInView={reduced ? { opacity: 1 } : { scaleX: 1 }}
        viewport={inView}
        transition={
          reduced
            ? { duration: D.fast }
            : { duration: D.slow, ease: E.expo as [number, number, number, number] }
        }
        style={{ transformOrigin: "0% 50%" }}
      />

      <Reveal variant="blurUp">
        <div className="opener-meta">
          <span className="nano">
            {pad(index)} / {pad(total)}
          </span>
          <span className="nano">{label}</span>
        </div>
      </Reveal>

      {headline}

      {/* The lede takes the lens too, so the whole opener answers the pointer
          the same way. */}
      {lede ? (
        interactive ? (
          <InvertOnHover>
            <BlurLines>{lede}</BlurLines>
          </InvertOnHover>
        ) : (
          <BlurLines>{lede}</BlurLines>
        )
      ) : null}
    </header>
  );
}

// ── Dense micro-grid (reference B4) ─────────────────────────────────────────
export type MicroRow = {
  /** Left column: the subject, uppercase mono. */
  name: string;
  /** Middle column: what it is. */
  kind: string;
  /** Right column: the consequence, right-aligned. */
  detail: string;
  tone?: Tone;
};

/**
 * Reference B4's dense grid: dozens of tiny rows read as one *texture* rather
 * than as dozens of events.  Columns of `micro` labels on hairline rows with
 * `(a.)` index markers -- no cards, no borders except hairlines.
 *
 * The stagger is capped by `stagger()` in motion.ts, so row 8 onwards lands
 * together. That is correct: the texture should appear, not tick in.
 */
export function MicroGrid({
  rows,
  columns,
  layoutId = "microbar",
}: {
  rows: MicroRow[];
  columns: [string, string, string];
  /** Unique per grid, so two grids on one page do not share the bar. */
  layoutId?: string;
}) {
  // The same gesture the headline words use, keyed by row name rather than by
  // index so re-ordering the rows cannot leave the highlight on the wrong one.
  const peers = usePeerHover();
  // Inside the lens copy the bar must not carry the `layoutId`: two elements
  // sharing one id would have Framer animate *between* the copies.
  const duplicate = useIsDuplicate();
  const letter = (i: number) => String.fromCharCode(97 + (i % 26));

  return (
    <div className="microgrid" style={{ perspective: 800 }} {...peers.group}>
      <div className="microgrid-head">
        <span className="nano">{columns[0]}</span>
        <span className="nano">{columns[1]}</span>
        <span className="nano" />
        <span className="nano microgrid-right">{columns[2]}</span>
      </div>
      {rows.map((row, i) => {
        const on = peers.on(row.name);
        return (
          <Reveal as="div" key={row.name} index={i} className="microgrid-row">
            {/* The pointer bindings sit on this span rather than on the row.
                The row is Framer-animated, so it carries an inline `transform`
                and `opacity` for the reveal -- and an inline style beats any
                stylesheet, so a hover declared in CSS would silently do
                nothing there.  Same reason the headline words are two
                elements. */}
            <span className="microgrid-cells" {...peers.peer(row.name)}>
              {/* Reference C4: a filled bar *slides* between rows rather than
                  fading in, and the row it lands on inverts. The slide is the
                  whole effect -- without `layoutId` this is an ordinary hover.

                  It lives *inside* the scaled box, not beside it. As a sibling
                  on the row it kept the row's original width while the cells
                  grew, so 18px of text hung off each end -- and the inverted
                  text is the same near-black as the page, so those letters
                  simply disappeared. Inside, the bar grows with the type it is
                  inverting and cannot fall out of register with it. */}
              {on ? (
                duplicate ? (
                  <span className="microgrid-bar" aria-hidden />
                ) : (
                  <motion.span
                    layoutId={layoutId}
                    className="microgrid-bar"
                    transition={SPRING.layout}
                    aria-hidden
                  />
                )
              ) : null}
              <span className="micro microgrid-name">{row.name}</span>
              <span className="micro microgrid-kind">{row.kind}</span>
              <span className="nano microgrid-index">({letter(i)}.)</span>
              <span
                className="micro microgrid-detail"
                style={
                  row.tone && row.tone !== "neutral" && !on
                    ? { color: `var(--sig-${row.tone})` }
                    : undefined
                }
              >
                {row.detail}
              </span>
            </span>
          </Reveal>
        );
      })}
    </div>
  );
}

// ── The measured-proof strip ─────────────────────────────────────
/**
 * Six figures from `make eval`, drifting independently, each answering the
 * pointer.
 *
 * It lives here rather than inline on the page because the peer-hover state has
 * to be owned by the strip: the cell under the pointer can only grow *relative
 * to its peers* if one component knows about all of them.
 */
export function ProofStrip({
  cells,
}: {
  cells: { key: string; label: string; text: string }[];
}) {
  const peers = usePeerHover();
  return (
    <div className="proofstrip" {...peers.group}>
      {cells.map((cell, index) => (
        <FloatCluster key={cell.key} seed={index}>
          <Reveal index={index}>
            {/* Inner, for the same reason as the grid rows above: the element
                Framer animates cannot also be the element CSS hovers. */}
            <span className="proofcell" {...peers.peer(cell.key)}>
              <span className="nano">{cell.label}</span>
              <span className="proofcell-v num">{cell.text}</span>
            </span>
          </Reveal>
        </FloatCluster>
      ))}
    </div>
  );
}

// ── Scroll-linked display type ──────────────────────────────────────────────
/**
 * Oversized type that moves horizontally with scroll and is *meant* to be
 * clipped by the viewport.
 *
 * Tied to scroll progress rather than an infinite CSS marquee: a marquee moves
 * whether or not the reader is going anywhere, which is decoration. This moves
 * because they are moving, which is composition. Reduced motion parks it at the
 * midpoint, where the line is fully legible.
 */
export function ScrollType({
  children,
  from = -1,
  to = 1,
  tone = "muted",
}: {
  children: string;
  /**
   * Start offset as a percentage of the *frame's* width -- the line is a block,
   * so a Framer `x` percentage resolves against the frame, not against the
   * glyphs.
   *
   * It was +/-6, which together with the type size meant the word could never
   * be read whole. The travel and the size are solved together, and every
   * percent given to travel is a percent the type cannot have: at 1% the
   * letters reach 14.3vw and fill 96% of the frame, which is within a few
   * percent of the hard ceiling for a twelve-character word on one line.
   */
  from?: number;
  to?: number;
  tone?: "solid" | "muted" | "outline";
}) {
  const reduced = useReducedMotion();
  // Per-letter, so the one under the pointer can grow on its own.
  const peers = usePeerHover();
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const x = useTransform(scrollYProgress, [0, 1], [`${from}%`, `${to}%`]);
  const letters = [...children];

  return (
    <div className="scrolltype" ref={ref} aria-label={children}>
      <motion.span
        className={`scrolltype-line scrolltype-line--${tone}`}
        style={reduced ? undefined : { x }}
        aria-hidden
        {...peers.group}
      >
        {letters.map((letter, index) => (
          /* Each letter is its own inline-block so it can scale without
             reflowing its neighbours: a transform does not affect layout, so
             the word stays put and the letter grows over it. */
          <span
            key={index}
            className="scrolltype-char"
            {...peers.peer(String(index))}
          >
            {letter}
          </span>
        ))}
      </motion.span>
    </div>
  );
}

// ── Floating card cluster ───────────────────────────────────────────────────
/**
 * Cards that drift independently, so the composition reads as arranged rather
 * than as a row. Each gets its own duration and amplitude -- identical motion on
 * every card is the tell that it was a loop rather than a layout.
 *
 * `sine.inOut`-equivalent easing, 3-6s, and nothing moves at all under reduced
 * motion.
 */
export function FloatCluster({
  children,
  seed = 0,
}: {
  children: ReactNode;
  seed?: number;
}) {
  const reduced = useReducedMotion();
  // Deterministic per-card variation: no randomness, so SSR and client agree.
  const amplitude = [-12, 8, -6, 10, -9][seed % 5] ?? -8;
  const period = [4.2, 5.6, 3.4, 6.1, 4.8][seed % 5] ?? 5;
  const tilt = [0, -0.6, 0.5, 0, 0.35][seed % 5] ?? 0;

  if (reduced) return <div className="float">{children}</div>;
  return (
    <motion.div
      className="float"
      animate={{ y: [0, amplitude, 0], rotate: [0, tilt, 0] }}
      transition={{ duration: period, repeat: Infinity, ease: "easeInOut" }}
      variants={pick(dropIn, false)}
      style={{ willChange: "transform" }}
    >
      {children}
    </motion.div>
  );
}

export { ST };
