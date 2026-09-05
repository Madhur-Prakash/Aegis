"use client";

/**
 * Infinite scroll: append the next pass when a sentinel near the foot of the
 * page comes into view.
 *
 * An `IntersectionObserver` rather than a scroll listener. A scroll handler
 * fires on every frame of every scroll and then has to measure the document,
 * which forces layout; the observer is told once what to watch and reports only
 * when the answer changes.
 *
 * `rootMargin` starts the load before the sentinel is actually on screen, so the
 * next pass is in the DOM by the time the reader arrives at it and the page
 * never visibly stalls at the bottom.
 *
 * Two things this hook refuses to do:
 *
 *   - fire twice for one arrival. The observer reports on every intersection
 *     change, and appending content moves the sentinel, which reports again
 *     before React has re-rendered. A ref guards the window between the callback
 *     and the state actually landing.
 *
 *   - grow without limit. "Infinite" in a browser is a promise you cannot keep:
 *     every pass here is a full composition with its own scroll-linked motion
 *     and reveal observers, and enough of them will make the tab crawl and then
 *     hang. `max` is the point at which it stops honestly rather than degrading.
 */

import { useCallback, useEffect, useRef, useState } from "react";

type Options = {
  /** How many passes may be appended before it stops. */
  max: number;
  /** Distance below the viewport at which to start loading. */
  rootMargin?: string;
  /** Off under reduced motion, or before the page is ready to grow. */
  enabled?: boolean;
};

export function useInfiniteScroll({ max, rootMargin = "600px", enabled = true }: Options) {
  const [passes, setPasses] = useState(0);
  const sentinel = useRef<HTMLDivElement | null>(null);
  // Mirrors `passes` for the observer callback, which closes over the value at
  // subscribe time and would otherwise keep appending from a stale count.
  const busy = useRef(false);

  const exhausted = passes >= max;

  const append = useCallback(() => {
    if (busy.current) return;
    busy.current = true;
    setPasses((current) => (current >= max ? current : current + 1));
  }, [max]);

  // Released only once the render has committed, so the sentinel has had a
  // chance to move out of view before another intersection can be honoured.
  useEffect(() => {
    busy.current = false;
  }, [passes]);

  useEffect(() => {
    const node = sentinel.current;
    if (!node || !enabled || exhausted) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) append();
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [append, enabled, exhausted, rootMargin, passes]);

  return { passes, sentinel, exhausted };
}
