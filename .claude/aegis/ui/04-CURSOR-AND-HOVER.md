# 04 — CURSOR & HOVER STATES

Both taken from **reference D** (OUTFIT), with the list-hover bar from **reference C** (hobro).

Measured from D at 12fps: the cursor is a **tiny dot at rest** (~8px) that **scales to a large disc**
(~48px) on interactive hover, **trails the pointer** by a few frames, and can **carry a micro
label**. On item hover, a **panel wipes out from behind the media** and the **media swaps** to an
alternate frame.

---

## 1. The cursor

### 1.1 Behaviour

| State | Size | Fill | Label | Trigger |
|---|---|---|---|---|
| `rest` | 8px | solid | — | default |
| `hover` | 48px | solid | optional | `[data-cursor]` element |
| `label` | auto × 32px pill | solid | required | `[data-cursor="label:VIEW PROOF"]` |
| `press` | 36px | solid | inherited | `pointerdown` |
| `text` | 2px × 22px bar | solid | — | inputs, `[contenteditable]` |
| `hidden` | 0 | — | — | pointer leaves window |

### 1.2 The colour decision

Reference D's cursor is red. **Do not copy that.** Red is `--sig-fail` in this product, and a red
disc floating over a passing clause row is a lie.

Instead the cursor uses `mix-blend-mode: difference` with a white fill. It inverts whatever is
beneath it, so it is always visible on both themes, over photos, over amber chips, and it claims no
semantic hue. This is strictly better than picking a brand colour, and it costs nothing.

```css
.cursor {
  position: fixed; top: 0; left: 0; z-index: var(--z-cursor);
  pointer-events: none; border-radius: var(--r-full);
  background: #fff; mix-blend-mode: difference;
  will-change: transform;
}
```

One caveat to verify: `mix-blend-mode` on a fixed element can be neutralised by an ancestor that
creates a stacking context with its own `isolation`. Mount the cursor as a **direct child of
`<body>`** via a portal, and ensure no ancestor sets `isolation: isolate`.

### 1.3 Implementation

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, useMotionValue, useSpring } from "motion/react";
import { SPRING } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";

type Mode = "rest" | "hover" | "label" | "press" | "text";

export function Cursor() {
  const reduced = useReducedMotion();
  const [enabled, setEnabled] = useState(false);
  const [mode, setMode] = useState<Mode>("rest");
  const [label, setLabel] = useState("");

  const x = useMotionValue(-100);
  const y = useMotionValue(-100);
  // The lerp/trail from reference D. Lower stiffness = more trail.
  const sx = useSpring(x, SPRING.cursor);
  const sy = useSpring(y, SPRING.cursor);

  useEffect(() => {
    // Pointer devices only — never on touch (spec: mobile must use native affordances).
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (!fine) return;
    setEnabled(true);
    document.body.dataset.cursor = "on";

    const move = (e: PointerEvent) => { x.set(e.clientX); y.set(e.clientY); };

    const over = (e: PointerEvent) => {
      const el = (e.target as HTMLElement)?.closest<HTMLElement>("[data-cursor]");
      if (!el) { setMode("rest"); setLabel(""); return; }
      const v = el.dataset.cursor ?? "hover";
      if (v.startsWith("label:")) { setLabel(v.slice(6)); setMode("label"); }
      else if (v === "text")      { setMode("text");  setLabel(""); }
      else                        { setMode("hover"); setLabel(""); }
    };

    const down  = () => setMode((m) => (m === "rest" ? "press" : m));
    const up    = () => setMode((m) => (m === "press" ? "rest" : m));
    const leave = () => { x.set(-100); y.set(-100); };

    window.addEventListener("pointermove", move,  { passive: true });
    window.addEventListener("pointerover", over,  { passive: true });
    window.addEventListener("pointerdown", down,  { passive: true });
    window.addEventListener("pointerup",   up,    { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerover", over);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      document.removeEventListener("pointerleave", leave);
      delete document.body.dataset.cursor;
    };
  }, [x, y]);

  if (!enabled || reduced) return null;         // reduced motion → native cursor

  const geo: Record<Mode, { w: number; h: number; r: number }> = {
    rest:  { w: 8,  h: 8,  r: 999 },
    hover: { w: 48, h: 48, r: 999 },
    label: { w: 0,  h: 32, r: 999 },            // width from content
    press: { w: 36, h: 36, r: 999 },
    text:  { w: 2,  h: 22, r: 1 },
  };
  const g = geo[mode];

  return createPortal(
    <motion.div
      className="cursor"
      style={{ x: sx, y: sy, translateX: "-50%", translateY: "-50%" }}
      animate={{ width: mode === "label" ? "auto" : g.w, height: g.h, borderRadius: g.r }}
      transition={SPRING.chip}
      aria-hidden
    >
      {mode === "label" && <span className="cursor-label">{label}</span>}
    </motion.div>,
    document.body,
  );
}
```

```css
.cursor-label {
  display:block; padding:0 .75rem; line-height:32px;
  font:600 var(--fs-micro)/32px var(--font-mono);
  letter-spacing:.08em; text-transform:uppercase; color:#000;
  white-space:nowrap;
}
```

`width: "auto"` inside a Framer `animate` will not tween smoothly — for the `label` mode, let the
pill size itself from content and animate only `opacity` and `scale` on the label span. Accept the
instant width change; reference D does the same and it reads as a snap, which is correct.

### 1.4 Declaring cursor targets

Add `data-cursor` in markup. No JS registration, no context.

```html
<button data-cursor>…</button>
<a data-cursor="label:OPEN DEAL" href="…">…</a>
<article data-cursor="label:VIEW PROOF">…</article>
<input data-cursor="text" />
```

Label copy is always **two words maximum**, uppercase, verb-first: `VIEW PROOF`, `OPEN DEAL`,
`SUBMIT`, `APPROVE`, `EXPAND`, `VERIFY`, `DOWNLOAD`.

### 1.5 Hard requirements

- [ ] `pointer: coarse` / touch → component returns `null`, native cursor and native tap
      behaviour restored. Never ship a custom cursor to a phone.
- [ ] `prefers-reduced-motion` → component returns `null`. The trailing spring is exactly the kind
      of motion that triggers discomfort.
- [ ] `:focus-visible` outlines still render while the custom cursor is active. Keyboard users are
      not served by a cursor.
- [ ] `cursor: none` is applied via `body[data-cursor="on"]` only, so if the component fails to
      mount the native cursor is never lost. **This matters** — a JS error that hides the cursor
      with no replacement makes the app unusable.
- [ ] Never gate an interaction on the custom cursor. It is decoration over real affordances.

---

## 2. Item hover — the panel wipe (reference D)

Measured: on hover-enter a **panel wipes horizontally out from behind the media** (~420ms), the
**media crossfades to an alternate frame** (~260ms) with a slight scale-down from 1.04, and the
cursor becomes a labelled disc. Nothing translates; nothing gains a shadow.

Aegis translation — the hovered thing is a **milestone card** or an **evidence artifact**, and the
panel is not decorative: **it is tinted with the item's semantic state.** So hovering a milestone
tells you its state through the wipe colour itself.

```tsx
export function HoverPanelCard({
  tone, primary, alternate, title, meta, cursorLabel = "VIEW PROOF", children,
}: {
  tone: "pass" | "unverified" | "fail" | "neutral";
  primary: string; alternate?: string;
  title: string; meta: string; cursorLabel?: string; children?: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.article
      className="hcard" data-cursor={`label:${cursorLabel}`}
      initial="rest" whileHover={reduced ? "rest" : "hover"} whileFocus="hover" tabIndex={0}
    >
      {/* the wipe panel — sits behind the media, anchored to its left edge */}
      <motion.span
        className="hcard-panel" variants={panelWipe}
        style={{ background: `var(--sig-${tone}-tint)`,
                 borderColor: `var(--sig-${tone}-edge)`, transformOrigin: "0% 50%" }}
        aria-hidden
      />
      <div className="hcard-media">
        <img src={primary} alt="" className="hcard-img" />
        {alternate && (
          <motion.img src={alternate} alt="" className="hcard-img hcard-img--alt"
            variants={mediaSwap} aria-hidden />
        )}
      </div>
      <div className="hcard-foot">
        <span className="hcard-title">{title}</span>
        <span className="micro">{meta}</span>
      </div>
      {children}
    </motion.article>
  );
}
```

```css
.hcard         { position:relative; isolation:auto; background:none; border:0; padding:0; }
.hcard-panel   { position:absolute; inset:-6px -10px; border:1px solid;
                 border-radius:var(--r-md); z-index:0; }
.hcard-media   { position:relative; z-index:1; overflow:hidden;
                 border-radius:var(--r-sm); aspect-ratio:4/5; background:var(--ink-800); }
.hcard-img     { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.hcard-img--alt{ opacity:0; }
.hcard-foot    { position:relative; z-index:1; display:flex; justify-content:space-between;
                 gap:var(--sp-3); padding-top:var(--sp-2); }
.hcard-title   { font:500 var(--fs-sm)/1.3 var(--font-display); color:var(--fg); }
```

Rules:
- The panel is **inset negatively** (`-6px -10px`) so it reads as a backdrop growing out from
  behind the item — reference D's exact effect. Never a border-radius glow or a shadow.
- `transform-origin: 0% 50%` gives the left-to-right wipe. Mirror to `100% 50%` for right-aligned
  grid items so the wipe always travels *outward* from the page centre.
- `whileFocus="hover"` — the keyboard gets the same state. Do not leave focus users with a dead
  card.
- No `translateY` on hover. Reference D lifts nothing, and the restraint is what makes it feel
  expensive.

---

## 3. List hover — the magic bar (reference C)

Reference C's service list slides a filled bar between rows and inverts the row's text. Perfect for
Aegis's clause table, review queue and nav. Uses Framer's shared layout so the bar interpolates
rather than fading.

```tsx
export function MagicList({ items }: { items: { id: string; label: string; meta: string }[] }) {
  const [active, setActive] = useState<string | null>(null);
  const reduced = useReducedMotion();
  return (
    <ul className="mlist" onPointerLeave={() => setActive(null)}>
      {items.map((it) => {
        const on = active === it.id;
        return (
          <li key={it.id} className="mrow" data-cursor="label:OPEN"
              onPointerEnter={() => setActive(it.id)} tabIndex={0}
              onFocus={() => setActive(it.id)}>
            {on && !reduced && (
              <motion.span layoutId="magic-bar" className="mbar"
                transition={SPRING.layout} aria-hidden />
            )}
            <span className={`mrow-label ${on ? "is-on" : ""}`}>{it.label}</span>
            <span className={`micro ${on ? "is-on" : ""}`}>{it.meta}</span>
          </li>
        );
      })}
    </ul>
  );
}
```

```css
.mlist      { list-style:none; margin:0; padding:0; }
.mrow       { position:relative; display:flex; align-items:center;
              justify-content:space-between; gap:var(--sp-4);
              padding:var(--sp-4) var(--sp-4); border-top:var(--hairline); }
.mrow:last-child { border-bottom:var(--hairline); }
.mbar       { position:absolute; inset:0; background:var(--bone-100);
              border-radius:var(--r-sm); z-index:0; }
.mrow-label { position:relative; z-index:1; font:500 var(--fs-h4)/1.2 var(--font-display);
              color:var(--fg); transition:color var(--d-fast) ease; }
.mrow-label.is-on, .micro.is-on { color:var(--ink-900); }
.micro      { position:relative; z-index:1; transition:color var(--d-fast) ease; }
```

- The bar is `--bone-100` and the row text inverts to `--ink-900`. Full inversion, exactly as in
  reference C — a subtle tint would lose the effect.
- `layoutId` makes the bar **slide** between rows instead of fading. That slide is the whole
  point; without it this is an ordinary hover.
- Reduced motion → no bar; the row gets `background: var(--ink-700)` instead.
- Reset `active` on `pointerleave` of the list, or the bar sticks on the last row.

---

## 4. Standard hover states for everything else

Restraint elsewhere so the two effects above stay special.

| Element | Hover |
|---|---|
| Button (primary) | `background: --bone-100 → #fff`, `--d-fast`. No scale, no shadow. |
| Button (ghost) | `border-color: --line-1 → --line-2`, `color: --fg-secondary → --fg` |
| Link (inline) | `text-decoration-color: transparent → currentColor`, `--d-fast` |
| Table row | `background: transparent → --ink-800` |
| Chip | `border-color` → +15% opacity. Never change the hue. |
| Icon button | `background: transparent → --ink-700`, `--r-sm` |
| Nav item | `magicBar` (§3) |
| Disabled | `opacity: .45`, `cursor: not-allowed`, no hover response, `data-cursor` omitted |

Every hover has a `:focus-visible` equivalent. Every hover transition is `--d-fast` — hover
feedback slower than 200ms feels laggy.

---

## 5. Touch

On `pointer: coarse`:

- Custom cursor off; `panelWipe` and `mediaSwap` are bound to **`:active`** instead of hover, so a
  tap still shows the state tint.
- The magic bar binds to the pressed row on `:active`.
- Minimum touch target **44 × 44px**; increase `.mrow` padding to `--sp-5` below `768px`.
- Nothing may be reachable only via hover. Every hover-revealed action also exists as a visible
  control or inside a tap-opened sheet — a hover-only "view proof" affordance is inaccessible on a
  phone, and the spec requires the full flow to work at 375px.
