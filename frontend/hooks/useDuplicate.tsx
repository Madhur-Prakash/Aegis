"use client";

/**
 * "You are the decorative copy, not the real one."
 *
 * `InvertOnHover` renders its children twice: once normally, and once in the
 * disc's palette clipped to a circle. The second copy is `aria-hidden`
 * scenery -- but it is also a full React subtree, so every entrance animation
 * inside it runs again, independently.
 *
 * That was a bug, and a measured one. Chrome's IntersectionObserver takes an
 * ancestor's `clip-path` into account, and the overlay is clipped to
 * `circle(0px)` until the pointer arrives -- so the duplicate's `whileInView`
 * observer never fired, its words stayed in `flipWord`'s hidden state
 * (`opacity: 0`, `rotateX(-92deg)`, a 4px-tall box), and the disc painted its
 * ground with no type on it at all. On the light canvas that read as a black
 * hole punched through the headline. Deleting the clip in the inspector made
 * the type appear, which is what identified the cause.
 *
 * An entrance is a *reveal*: it belongs to the copy the reader is meant to
 * notice arriving. The duplicate should simply already be there. Anything
 * rendered inside this provider therefore starts in its final state and skips
 * `whileInView` entirely -- which also removes one observer per animated node
 * from the page.
 */

import type { ReactNode } from "react";
import { createContext, useContext } from "react";

const DuplicateContext = createContext(false);

export function DuplicateProvider({ children }: { children: ReactNode }) {
  return <DuplicateContext.Provider value={true}>{children}</DuplicateContext.Provider>;
}

/** True when this component is inside a decorative duplicate. */
export function useIsDuplicate(): boolean {
  return useContext(DuplicateContext);
}
