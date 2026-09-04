"use client";

/**
 * The sliding highlight bar (ui/04 §3).
 *
 * `layoutId` makes the bar *slide* between rows instead of fading, and that
 * slide is the whole point: without it this is an ordinary hover.  The row text
 * inverts fully; a subtle tint would lose the effect.
 *
 * Under reduced motion there is no bar and the row takes a raised background
 * instead, so the state is still perceivable.
 */

import { motion } from "motion/react";
import type { ReactNode } from "react";
import { useState } from "react";

import { SPRING } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

export type MagicRow = {
  id: string;
  label: ReactNode;
  meta?: ReactNode;
  trailing?: ReactNode;
};

export function MagicList({
  items,
  selectedId,
  onSelect,
  cursorLabel = "OPEN",
  layoutId = "magic-bar",
  emptyLabel,
}: {
  items: MagicRow[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  cursorLabel?: string;
  layoutId?: string;
  emptyLabel?: ReactNode;
}) {
  const [active, setActive] = useState<string | null>(null);
  const reduced = useReducedMotion();

  if (!items.length && emptyLabel) {
    return <div className="mlist-empty">{emptyLabel}</div>;
  }

  return (
    <ul className="mlist" onPointerLeave={() => setActive(null)}>
      {items.map((item) => {
        const highlighted = active === item.id || (active === null && selectedId === item.id);
        return (
          <li
            key={item.id}
            className={`mrow ${selectedId === item.id ? "is-selected" : ""} ${
              reduced && highlighted ? "is-raised" : ""
            }`}
            data-cursor={`label:${cursorLabel}`}
            tabIndex={0}
            role={onSelect ? "button" : undefined}
            aria-current={selectedId === item.id ? "true" : undefined}
            onPointerEnter={() => setActive(item.id)}
            onFocus={() => setActive(item.id)}
            onClick={() => onSelect?.(item.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect?.(item.id);
              }
            }}
          >
            {highlighted && !reduced ? (
              <motion.span
                layoutId={layoutId}
                className="mbar"
                transition={SPRING.layout}
                aria-hidden
              />
            ) : null}
            <span className={`mrow-label ${highlighted && !reduced ? "is-on" : ""}`}>
              {item.label}
            </span>
            {item.meta ? (
              <span className={`micro ${highlighted && !reduced ? "is-on" : ""}`}>
                {item.meta}
              </span>
            ) : null}
            {item.trailing}
          </li>
        );
      })}
    </ul>
  );
}
