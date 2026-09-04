"use client";

/**
 * Whether this device has a real pointer that can hover.
 *
 * Hover-only enhancements must not fire on touch, where `pointerenter` arrives
 * on tap and then never leaves -- so a "hovered" word would stay enlarged with
 * no way to undo it. Checked with the same media query the custom cursor uses,
 * so the two can never disagree.
 */
import { useEffect, useState } from "react";

export const HOVER_QUERY = "(hover: hover) and (pointer: fine)";

export function useCanHover(): boolean {
  // Starts false so the server render and the first client render agree; a
  // pointer device flips it on mount.
  const [canHover, setCanHover] = useState(false);

  useEffect(() => {
    const query = window.matchMedia(HOVER_QUERY);
    const sync = () => setCanHover(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return canHover;
}
