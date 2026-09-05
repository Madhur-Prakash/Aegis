/**
 * Icon helpers, all Lucide. One place for the sizes, so the tick in a table row
 * and the tick in a chip are the same tick. The glyph characters these replace
 * rendered at whatever size and weight the surrounding font happened to give
 * them, which was never the same twice.
 */

import { Check, X } from "lucide-react";

/** A pass / fail mark, sized to the text it sits in. Decorative: the text
 *  beside it carries the meaning, so it is hidden from assistive tech. */
export function Tick({ ok, size = 14 }: { ok: boolean; size?: number }) {
  const Icon = ok ? Check : X;
  return <Icon className="ico" size={size} strokeWidth={2.25} aria-hidden />;
}
