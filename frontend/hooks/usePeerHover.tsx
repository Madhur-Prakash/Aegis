"use client";

/**
 * Peer hover: one gesture, used everywhere a list or a row of items appears.
 *
 * The item under the pointer grows and takes the canvas's maximum-contrast
 * colour; its peers shrink very slightly and recede. It is the treatment the
 * reference list-hover uses, and the reason it is a hook rather than a
 * component is that the same three lines have to sit on a headline word, a grid
 * row, a metric cell, a footer link and a nav item without any of them sharing
 * markup.
 *
 * Two things it deliberately does *not* do:
 *
 * - It does not fire on touch. `pointerenter` arrives on tap and then never
 *   leaves, so a "hovered" item would stay enlarged with no way to undo it.
 * - It does not fire under reduced motion. The scale is the effect; a colour
 *   change alone is not worth the re-render, and growth is exactly the kind of
 *   motion the preference is asking us to drop.
 *
 * The state is a *key*, not an index, so re-ordering a list cannot leave the
 * highlight on the wrong item.
 */

import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { useCanHover } from "@/hooks/useCanHover";
import { useReducedMotion } from "@/hooks/useReducedMotion";

/** What CSS sees on each peer. `rest` means the pointer is outside the group. */
export type PeerState = "rest" | "on" | "off";

export type PeerHover = {
  /** True when the gesture is actually running on this device. */
  live: boolean;
  /** The key under the pointer, or `null`. */
  active: string | null;
  /** Spread on the container: it is what clears the highlight. */
  group: { onPointerLeave?: () => void };
  /** Spread on each peer. */
  peer: (key: string) => {
    onPointerEnter?: () => void;
    onFocus?: () => void;
    "data-peer"?: PeerState;
  };
  /** True for the peer under the pointer -- for a `layoutId` bar, say. */
  on: (key: string) => boolean;
};

const PeerHoverContext = createContext<PeerHover | null>(null);

/**
 * A peer group shared by more than one copy of the same markup.
 *
 * `InvertOnHover` renders its children *twice* -- once normally and once in the
 * inverted palette, clipped to the disc.  Two renders of one React element are
 * two independent component instances, so each copy of the headline was keeping
 * its own hover state, and only the copy that receives pointer events (the
 * lower one; the overlay is `pointer-events: none`) ever left the rest state.
 * The measured result: the word under the pointer was at `scale(1.06)` in the
 * base layer and `scale(1)` inside the disc, so the two layers fell out of
 * register exactly when the reader was looking closest at them.
 *
 * With the state above both copies there is only one of it, and the duplicate
 * cannot disagree with the original.  Only wrap markup that is one peer group:
 * two groups under one provider would share a highlight.
 */
export function PeerHoverProvider({ children }: { children: ReactNode }) {
  const group = useOwnPeerHover();
  return <PeerHoverContext.Provider value={group}>{children}</PeerHoverContext.Provider>;
}

/**
 * The group state, from the nearest `PeerHoverProvider` if there is one and
 * otherwise this component's own.
 */
export function usePeerHover(): PeerHover {
  const shared = useContext(PeerHoverContext);
  const own = useOwnPeerHover();
  return shared ?? own;
}

function useOwnPeerHover(): PeerHover {
  const canHover = useCanHover();
  const reduced = useReducedMotion();
  const live = canHover && !reduced;
  const [active, setActive] = useState<string | null>(null);

  const clear = useCallback(() => setActive(null), []);

  return useMemo(() => {
    if (!live) {
      return {
        live: false,
        active: null,
        group: {},
        peer: () => ({}),
        on: () => false,
      };
    }
    return {
      live: true,
      active,
      group: { onPointerLeave: clear },
      peer: (key: string) => ({
        onPointerEnter: () => setActive(key),
        // Keyboard users get the same emphasis; without this the highlight is
        // pointer-only and the focused item is the one thing not called out.
        onFocus: () => setActive(key),
        "data-peer": (active === null ? "rest" : active === key ? "on" : "off") as PeerState,
      }),
      on: (key: string) => active === key,
    };
  }, [live, active, clear]);
}
