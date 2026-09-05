"use client";

/**
 * The pointer inverts the type it passes over.
 *
 * A disc follows the pointer; inside it the canvas and the letters swap places.
 * Outside it nothing changes. It is the effect from the reference frames where a
 * filled circle crosses a wordmark and the glyphs flip to the background colour
 * inside the circle.
 *
 * Mechanically it is *not* a blend mode. `mix-blend-mode` on a coloured disc
 * over white type gives a muddy third colour rather than a clean swap, which is
 * why the tiny cursor uses `difference` (it claims no hue) and this does not.
 * Instead the children are rendered twice: once normally, and once in the
 * inverted palette clipped to a circle at the pointer. Both layers are the same
 * markup, so the type cannot drift out of register.
 *
 * The second copy is also *magnified* about the pointer. That is what makes it
 * a lens rather than a recolour: the point under the cursor maps to itself and
 * everything around it spreads outward, so the letters inside the disc are
 * larger than the same letters beside it. The clip is applied in the layer's
 * own coordinates, before its transform, so its radius is divided by the
 * magnification to keep the visible disc at the intended size.
 *
 * `clip-path: circle()` and a transform are all that animate, so it composites
 * on the GPU. The overlay is `aria-hidden` and `pointer-events: none` -- it is a
 * duplicate of text a screen reader has already been given.
 */

import { motion, useMotionValue, useSpring, useTransform } from "motion/react";
import type { ReactNode } from "react";
import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { SPRING } from "@/design/motion";
import { useCanHover } from "@/hooks/useCanHover";
import { DuplicateProvider } from "@/hooks/useDuplicate";
import { PeerHoverProvider } from "@/hooks/usePeerHover";
import { useReducedMotion } from "@/hooks/useReducedMotion";

export function InvertOnHover({
  children,
  scale = 0.8,
  bleedY = 20,
  magnify = 1.4,
  minRadius = 56,
  className = "",
}: {
  children: ReactNode;
  /**
   * Disc radius as a multiple of the type it sits on.
   *
   * It was a fixed pixel number, and a fixed number cannot be right twice: the
   * display scale runs 52 -> 84 -> 113 -> 141 -> 144px across the breakpoints,
   * so 150px was a lens at 1440 and a shape larger than the headline at 768.
   * The radius is now measured from the largest type inside the host, so the
   * disc keeps the same proportion to the letters at every width.
   */
  scale?: number;
  /**
   * How far the disc may reach above and below the type, in px.
   *
   * It must not exceed the whitespace that is actually there.  The disc paints
   * a ground, and the duplicate layer only contains the headline -- so wherever
   * the ground reaches past the headline it covers whatever is underneath with
   * nothing drawn in its place.  A full-radius vertical bleed erased the hero
   * lede, which is how this number came to be measured rather than chosen: the
   * gap above and below every headline on the page is 24-32px.
   *
   * Sideways there is nothing to cover -- a headline spans the whole measure --
   * so the horizontal bleed is the full radius and the disc stays round at the
   * start and end of a line.  `.shell` clips it so the page cannot scroll.
   */
  bleedY?: number;
  /** How much larger the type inside the disc is than the type beside it. */
  magnify?: number;
  /**
   * The lens floor, in px. The radius follows the type it sits on, which is
   * right for a headline and useless for a lede: 0.8 of 18px is a 14px disc.
   * Small type gets a lens big enough to read a word or two through.
   */
  minRadius?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const canHover = useCanHover();
  const live = canHover && !reduced;

  const host = useRef<HTMLDivElement>(null);
  const [inside, setInside] = useState(false);

  // The largest font size inside the host, in px.  Measured rather than read
  // from `--fs-display-1`: `getPropertyValue` hands back the unresolved
  // `clamp(...)` string for an unregistered custom property, so the only way to
  // learn the actual size is to ask an element that uses it.
  const [type, setType] = useState(0);
  useLayoutEffect(() => {
    const measure = () => {
      const node = host.current;
      if (!node) return;
      let largest = 0;
      for (const element of node.querySelectorAll("*")) {
        largest = Math.max(largest, Number.parseFloat(getComputedStyle(element).fontSize) || 0);
      }
      setType(largest);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
    // `live` is a dependency because the host only exists once it is true: the
    // first render is the no-pointer branch, which has no ref to measure, and
    // without this the radius stayed 0 and the disc never appeared on every
    // headline below the hero.
  }, [live]);

  // Until the measurement lands the disc has no size, so it cannot flash at the
  // wrong scale; `grow` only ever gets a measured radius.
  const radius = type ? Math.max(minRadius, Math.round(type * scale)) : 0;

  // Springs, so the disc trails the pointer slightly instead of snapping to it.
  const rawX = useMotionValue(-9999);
  const rawY = useMotionValue(-9999);
  const x = useSpring(rawX, SPRING.cursor);
  const y = useSpring(rawY, SPRING.cursor);
  // Grows from nothing on entry, which is what stops it appearing mid-word.
  const grow = useMotionValue(0);
  const r = useSpring(grow, SPRING.cursor);

  // The host grows into the whitespace around the type by `bleedY` vertically
  // and a full radius horizontally, using padding cancelled by an equal
  // negative margin -- so the box the disc lives in is bigger than the type
  // while the layout is untouched. The pointer is measured against that grown
  // box, and the overlay spans exactly it, so the clip needs no offset of its
  // own.
  // Magnification is a spring from 1 to `magnify` while the pointer is inside,
  // not a constant. At rest the duplicate must sit at scale 1, exactly over the
  // type it copies: scaled about the parked pointer position (-9999, -9999) it
  // was thrown thousands of pixels down and right -- invisible under a
  // zero-radius clip, but a transform still counts toward the document's
  // scrollable overflow, so every lens on the page was adding to a blank tail.
  const zoom = useMotionValue(1);
  const mag = useSpring(zoom, SPRING.cursor);
  const clip = useTransform([x, y, r, mag], (values: number[]) => {
    const [cx = 0, cy = 0, cr = 0, m = 1] = values;
    return `circle(${cr / m}px at ${cx}px ${cy}px)`;
  });

  // The magnification is about the pointer, so the transform origin follows it.
  const originX = useTransform(x, (value) => `${value}px`);
  const originY = useTransform(y, (value) => `${value}px`);

  // A hairline at the lens rim, following the same springs.
  //
  // The disc is always the bright ground, so wherever the surface underneath is
  // already that colour the shape does not read at all -- measured, the footer
  // in the light theme is white and so is the disc, so only the ink changed and
  // the circle was invisible. The rim gives the lens an edge on any ground; on
  // the dark canvas it sits between white and near-black, where it disappears
  // into the page, which is the right amount of nothing.
  const rim = useTransform(r, (cr) => cr * 2);
  const rimLeft = useTransform([x, r], (values: number[]) => {
    const [cx = 0, cr = 0] = values;
    return cx - cr;
  });
  const rimTop = useTransform([y, r], (values: number[]) => {
    const [cy = 0, cr = 0] = values;
    return cy - cr;
  });
  // A 0x0 box with a 1px border still paints: at rest the rim left a ~2px dot
  // sitting at whatever spot the pointer last visited. It fades over the first
  // few pixels of growth instead, which also gives the shrink somewhere to go.
  const rimOpacity = useTransform(r, [0, 8], [0, 1]);

  const track = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const box = host.current?.getBoundingClientRect();
      if (!box) return;
      rawX.set(event.clientX - box.left);
      rawY.set(event.clientY - box.top);
    },
    [rawX, rawY],
  );

  const enter = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const box = host.current?.getBoundingClientRect();
      if (!box) return;
      // Place the disc before it grows, or it sweeps in from its last position.
      rawX.jump(event.clientX - box.left);
      rawY.jump(event.clientY - box.top);
      setInside(true);
      grow.set(radius);
      zoom.set(magnify);
    },
    [rawX, rawY, grow, zoom, radius, magnify],
  );

  const leave = useCallback(() => {
    grow.set(0);
    zoom.set(1);
    setInside(false);
  }, [grow, zoom]);

  // One tree in both states. `live` starts false and flips after mount, and an
  // early return to a bare <div> made the flip a *different element structure*
  // -- so React remounted the children: every wrapped block replayed its
  // entrance, the hero headline flapped in twice, and cue timers inside wrapped
  // blocks restarted while their unwrapped siblings did not. Measured as a
  // 500ms stall between the rule landing and the stats starting. The layer and
  // rim are simply added inside the same host when the pointer can hover.
  return (
    /* Both copies are one peer group. Without this the duplicate keeps its own
       hover state -- it never receives pointer events, so it stays at rest --
       and any peer-hover growth inside the disc is a frame out of register with
       the type beneath it. */
    <PeerHoverProvider>
      <div
        ref={host}
        className={`invert-host ${className}`}
        onPointerEnter={live ? enter : undefined}
        onPointerMove={live ? track : undefined}
        onPointerLeave={live ? leave : undefined}
        data-inside={live ? inside : undefined}
        style={
          live
            ? {
                padding: `${bleedY}px ${radius}px`,
                margin: `${-bleedY}px ${-radius}px`,
              }
            : undefined
        }
      >
        {children}
        {live ? (
          <>
            {/* `inset: 0` resolves against the host's padding box -- the grown
                one -- and the same padding puts this copy back in register with
                the one above. */}
            <motion.div
              className="invert-layer"
              style={{
                clipPath: clip,
                scale: mag,
                originX,
                originY,
                inset: 0,
                padding: `${bleedY}px ${radius}px`,
              }}
              aria-hidden
            >
              {/* Everything in here is already-arrived scenery. Chrome's
                  IntersectionObserver honours this layer's `clip-path`, so a
                  `whileInView` entrance inside it would never fire and the disc
                  would paint its ground over nothing. */}
              <DuplicateProvider>{children}</DuplicateProvider>
            </motion.div>
            <motion.div
              className="invert-rim"
              style={{ width: rim, height: rim, left: rimLeft, top: rimTop, opacity: rimOpacity }}
              aria-hidden
            />
          </>
        ) : null}
      </div>
    </PeerHoverProvider>
  );
}
