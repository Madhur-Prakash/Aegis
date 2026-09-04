# 00 - DESIGN SYSTEM

Dark-first, monochrome brand, three semantic hues. Synthesised from reference **B** (near-black
editorial canvas, dense micro-labels, hairline rules) and reference **D** (tiny paired labels,
tabular numerals, hairline row rules), with reference **C**'s monochrome discipline.

---

## 1. Colour

### 1.1 The rule

**Three hues exist. Each means something. Nothing else is coloured.**

| Hue | Token | Value | Means |
|---|---|---|---|
| Mint | `--sig-pass` | `#4FD1A5` | Clause PASS · milestone SETTLED · money RELEASED · attestation valid |
| Amber | `--sig-unverified` | `#FFC24B` | Clause **UNVERIFIABLE** · ESCALATE · UNDER_HUMAN_REVIEW · money HELD |
| Red | `--sig-fail` | `#FF4A4A` | Clause FAIL · REJECTED · payout failed · tamper detected · DLQ |

Amber is the signature. It appears nowhere decorative, so when the verifier escalates, the
interface changes colour for the first time. Protect that.

### 1.2 Neutrals

Near-black canvas from B, bone from D. Bone is the *text* colour, not a background - that
inversion is what keeps it from looking like reference D.

```
--ink-900  #08080A   page canvas (dark)
--ink-800  #0D0D10   raised surface / card
--ink-700  #14141A   raised surface hover
--ink-600  #1D1D24   hairline-adjacent fill
--line-1   #24242C   hairline rule (1px, the workhorse divider)
--line-2   #34343E   hairline emphasis
--grey-500 #6B6B78   micro-label, tertiary
--grey-300 #9A9AA8   secondary text
--bone-100 #F2EFE9   primary text, "white" (warm, never pure #FFF for body)
--white    #FFFFFF   display type only, and the cursor
```

Light theme inverts to a bone canvas with ink text; the three semantic hues **darken slightly**
for AA contrast on bone (values in the token block).

### 1.3 Contrast requirements

- Body text on `--ink-900`: `--bone-100` → 15.8:1. Use it.
- `--grey-300` on `--ink-900` → 7.1:1, fine for secondary. `--grey-500` → 3.9:1, **micro-labels
  only at ≥11px/600 weight**, never body copy.
- Semantic hues are used as **fill on a dark chip with ink text**, or as a 1px border + 8% tint
  fill. Never as light text on a light tint.

---

## 2. Typography

### 2.1 Families

| Role | Family | Source | Why |
|---|---|---|---|
| Display + UI | **Satoshi** (300/500/700/900) | Fontshare, free, self-host via `next/font/local` | Geometric grotesk with a real Black weight - carries A's wide headline voice *and* B's huge condensed-feeling caps |
| Mono / micro | **JetBrains Mono** (400/500/700) | Google Fonts or self-host | Micro-labels, ids, hashes, addresses, timestamps, and every number that must align |

Fallbacks: `Satoshi, "Inter", system-ui, sans-serif` and
`"JetBrains Mono", ui-monospace, "SF Mono", monospace`.
If Satoshi cannot be self-hosted, substitute **General Sans** (also Fontshare) - do **not**
substitute Inter for display; it has no Black weight with this presence.

### 2.2 Scale

Fluid via `clamp()`, mobile-first. Line-height tightens as size grows - that inverse relationship
is what makes B's hero read as a *block* rather than as lines.

| Token | clamp() | LH | Tracking | Use |
|---|---|---|---|---|
| `--fs-display-1` | `clamp(3.25rem, 11vw, 9rem)` | 0.86 | −0.03em | Hero headline, CTA scramble |
| `--fs-display-2` | `clamp(2.5rem, 7vw, 5rem)` | 0.9 | −0.025em | Section openers |
| `--fs-display-3` | `clamp(1.75rem, 4vw, 3rem)` | 0.95 | −0.02em | Screen titles, money figure |
| `--fs-h4` | `clamp(1.125rem, 2vw, 1.5rem)` | 1.15 | −0.01em | Card titles |
| `--fs-body` | `1rem` (16px) | 1.55 | 0 | Body copy |
| `--fs-sm` | `0.875rem` (14px) | 1.5 | 0 | Secondary, table cells |
| `--fs-micro` | `0.6875rem` (11px) | 1.3 | **0.09em** | Micro-labels, UPPERCASE, mono |
| `--fs-nano` | `0.625rem` (10px) | 1.25 | 0.11em | Corner metadata (B/D style) |

Display type is **`--font-display` at weight 900** for hero and CTA; weight 500 for screen titles.
Never use 900 below `--fs-display-3` - it turns to mud.

### 2.3 Two-tone words (from A)

A's headlines alternate solid and muted words to create rhythm. Adopted, monochrome:

```html
<h1 class="display-1">
  <span class="w-solid">Every rupee</span>
  <span class="w-muted">has a</span>
  <span class="w-solid">provable</span>
  <span class="w-muted">reason.</span>
</h1>
```

`.w-solid { color: var(--white) }` · `.w-muted { color: var(--grey-500) }`
Ratio roughly 60/40 solid to muted. Muted words are the connective tissue - articles,
prepositions, auxiliaries - never the nouns that carry meaning.

### 2.4 Inline chips inside headlines (from A)

A embeds small circular icon badges *in the text flow*. Adopted, and given a job: the chip carries
a live value.

```html
<h2>Held <Chip value="₹4,20,000" tone="unverified" /> across three milestones</h2>
```

Chip: `inline-flex`, height `0.72em`, `border-radius: 999px`, `padding: 0 0.5em`,
`font: 500 0.34em/1 var(--font-mono)`, `vertical-align: 0.06em`, background = semantic tint,
border = `1px solid` semantic at 40%. Never more than **one chip per headline**.

### 2.5 Numerals - mandatory

```css
.num, td, .money { font-variant-numeric: tabular-nums; font-family: var(--font-mono); }
```

Every money figure, confidence value, hash, id and timestamp uses tabular mono. A column of
rupee amounts that doesn't align is a bug in this product.

Format money with Indian grouping, always:

```ts
export const inr = (paise: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR",
    maximumFractionDigits: 0 }).format(paise / 100);   // → "₹4,20,000"
```

Never `en-US`. `₹420,000` is wrong for this audience and a judge from Bangalore will notice.

---

## 3. The micro-label system (from B and D)

The signature of both dark references: **tiny uppercase mono labels paired with a value**, set
against generous space, with hairline rules doing all the structural work. This is what makes an
interface look engineered rather than templated.

```html
<div class="meta">
  <span class="meta-k">MILESTONE</span>
  <span class="meta-v">02 / 03</span>
</div>
```

```css
.meta      { display:flex; justify-content:space-between; gap:1rem;
             padding-block:.5rem; border-bottom:1px solid var(--line-1); }
.meta-k    { font:500 var(--fs-micro)/1.3 var(--font-mono);
             letter-spacing:.09em; text-transform:uppercase; color:var(--grey-500); }
.meta-v    { font:500 var(--fs-micro)/1.3 var(--font-mono);
             letter-spacing:.04em; color:var(--bone-100); font-variant-numeric:tabular-nums; }
```

Use for: deal metadata, attestation provenance fields, chain records, counterparty stats, corner
metadata on section headers. **Rule: a micro-label never wraps.** Truncate the value with
`text-overflow: ellipsis` and expose the full string on hover/focus.

Corner metadata (B): each major section carries `--fs-nano` labels at its top-left and top-right -
section index (`03 / 07`), and a state or count. Cheap, and it does most of the work of making the
page feel like a system.

---

## 4. Layout

- **Grid:** 12 columns, `gap: clamp(1rem, 2vw, 1.75rem)`, max container `1440px`,
  gutter `clamp(1.25rem, 5vw, 4.5rem)`.
- **Breakpoints:** `sm 480 · md 768 · lg 1024 · xl 1280 · 2xl 1536`. Design at 375 first.
- **Section rhythm:** `padding-block: clamp(4.5rem, 12vh, 10rem)`. Hero is `100svh` (not `vh` -
  mobile browser chrome).
- **Hairline rules, not cards.** Structure comes from `1px solid var(--line-1)` dividers and
  space. Surfaces (`--ink-800`) are used only where content must be *lifted* - a card in a review
  queue, a modal. No drop shadows on dark; use a `1px` top highlight instead:
  `box-shadow: inset 0 1px 0 rgb(255 255 255 / .04)`.
- **Radius:** `--r-sm 6px` (chips, inputs) · `--r-md 10px` (cards) · `--r-lg 16px` (panels) ·
  `--r-full 999px` (pills, cursor). Restrained - B and C are near-square; A's roundness is not
  adopted.
- **Wide content:** clause tables, ledger lists and provenance records get
  `overflow-x: auto; overscroll-behavior-x: contain` on their own wrapper. The page never scrolls
  sideways.

---

## 5. `frontend/design/tokens.css` - copy verbatim

```css
/* ─────────────────────────────────────────────────────────────────────────
   AEGIS DESIGN TOKENS - the only file in the project that defines a colour,
   a size, or a radius. Components reference tokens; never literals.
   Dark is the default. Light inverts neutrals; semantic hues darken for AA.
   ───────────────────────────────────────────────────────────────────────── */
:root {
  color-scheme: dark;

  /* ── Neutrals (dark, default) ─────────────────────────────── */
  --ink-900:  #08080A;
  --ink-800:  #0D0D10;
  --ink-700:  #14141A;
  --ink-600:  #1D1D24;
  --line-1:   #24242C;
  --line-2:   #34343E;
  --grey-500: #6B6B78;
  --grey-300: #9A9AA8;
  --bone-100: #F2EFE9;
  --white:    #FFFFFF;

  /* ── Semantic hues - the ONLY colour in the product ───────── */
  --sig-pass:        #4FD1A5;
  --sig-unverified:  #FFC24B;
  --sig-fail:        #FF4A4A;
  --sig-pass-tint:        color-mix(in oklab, var(--sig-pass) 12%, transparent);
  --sig-unverified-tint:  color-mix(in oklab, var(--sig-unverified) 14%, transparent);
  --sig-fail-tint:        color-mix(in oklab, var(--sig-fail) 12%, transparent);
  --sig-pass-edge:        color-mix(in oklab, var(--sig-pass) 40%, transparent);
  --sig-unverified-edge:  color-mix(in oklab, var(--sig-unverified) 45%, transparent);
  --sig-fail-edge:        color-mix(in oklab, var(--sig-fail) 40%, transparent);

  /* ── Roles ────────────────────────────────────────────────── */
  --bg:            var(--ink-900);
  --bg-raised:     var(--ink-800);
  --bg-raised-hi:  var(--ink-700);
  --fg:            var(--bone-100);
  --fg-display:    var(--white);
  --fg-secondary:  var(--grey-300);
  --fg-micro:      var(--grey-500);
  --border:        var(--line-1);
  --border-strong: var(--line-2);
  --focus:         var(--bone-100);

  /* money states map onto semantics */
  --money-held:     var(--sig-unverified);
  --money-released: var(--sig-pass);
  --money-refunded: var(--grey-300);

  /* ── Type ─────────────────────────────────────────────────── */
  --font-display: Satoshi, Inter, system-ui, sans-serif;
  --font-mono:    "JetBrains Mono", ui-monospace, "SF Mono", monospace;

  --fs-display-1: clamp(3.25rem, 11vw, 9rem);
  --fs-display-2: clamp(2.5rem, 7vw, 5rem);
  --fs-display-3: clamp(1.75rem, 4vw, 3rem);
  --fs-h4:        clamp(1.125rem, 2vw, 1.5rem);
  --fs-body:      1rem;
  --fs-sm:        0.875rem;
  --fs-micro:     0.6875rem;
  --fs-nano:      0.625rem;

  --lh-display-1: 0.86;  --tr-display-1: -0.03em;
  --lh-display-2: 0.90;  --tr-display-2: -0.025em;
  --lh-display-3: 0.95;  --tr-display-3: -0.02em;
  --lh-body:      1.55;
  --tr-micro:     0.09em;

  /* ── Space & shape ────────────────────────────────────────── */
  --sp-1: .25rem; --sp-2: .5rem;  --sp-3: .75rem; --sp-4: 1rem;
  --sp-5: 1.5rem; --sp-6: 2rem;   --sp-7: 3rem;   --sp-8: 4.5rem;
  --gutter:  clamp(1.25rem, 5vw, 4.5rem);
  --section: clamp(4.5rem, 12vh, 10rem);
  --container: 1440px;
  --grid-gap:  clamp(1rem, 2vw, 1.75rem);

  --r-sm: 6px; --r-md: 10px; --r-lg: 16px; --r-full: 999px;
  --hairline: 1px solid var(--border);
  --lift: inset 0 1px 0 rgb(255 255 255 / .04);

  /* ── Cursor ───────────────────────────────────────────────── */
  --cursor-dot:  8px;
  --cursor-disc: 48px;

  /* ── Z ────────────────────────────────────────────────────── */
  --z-base: 0; --z-sticky: 10; --z-nav: 20; --z-modal: 40;
  --z-toast: 50; --z-cursor: 90; --z-boot: 100;
}

/* System-preference dark: already the default - nothing to redefine. */

/* Explicit light theme */
:root[data-theme="light"] {
  color-scheme: light;
  --ink-900:  #F2EFE9;
  --ink-800:  #FFFFFF;
  --ink-700:  #F7F5F1;
  --ink-600:  #EBE7E0;
  --line-1:   #DCD7CE;
  --line-2:   #C6C0B4;
  --grey-500: #77736A;
  --grey-300: #56534C;
  --bone-100: #0D0D10;
  --white:    #08080A;

  --sig-pass:       #128A63;
  --sig-unverified: #9A6400;
  --sig-fail:       #C42121;

  --fg-display: var(--white);
  --focus:      var(--ink-900);
  --lift:       0 1px 2px rgb(8 8 10 / .06);
}

/* System-preference light, when the user has made no explicit choice */
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]):not([data-theme="light"]) {
    color-scheme: light;
    --ink-900:  #F2EFE9;  --ink-800:  #FFFFFF;  --ink-700: #F7F5F1;
    --ink-600:  #EBE7E0;  --line-1:   #DCD7CE;  --line-2:  #C6C0B4;
    --grey-500: #77736A;  --grey-300: #56534C;
    --bone-100: #0D0D10;  --white:    #08080A;
    --sig-pass: #128A63;  --sig-unverified: #9A6400; --sig-fail: #C42121;
    --fg-display: var(--white);
    --focus: var(--ink-900);
    --lift: 0 1px 2px rgb(8 8 10 / .06);
  }
}

/* ── Base ───────────────────────────────────────────────────── */
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 400 var(--fs-body)/var(--lh-body) var(--font-display);
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;              /* the page never scrolls sideways */
}
*, *::before, *::after { box-sizing: border-box; }
img, video, svg { max-width: 100%; display: block; }

:where(a, button, [tabindex]):focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 3px;
  border-radius: var(--r-sm);
}

.display-1 { font: 900 var(--fs-display-1)/var(--lh-display-1) var(--font-display);
             letter-spacing: var(--tr-display-1); color: var(--fg-display);
             text-wrap: balance; margin: 0; }
.display-2 { font: 900 var(--fs-display-2)/var(--lh-display-2) var(--font-display);
             letter-spacing: var(--tr-display-2); color: var(--fg-display);
             text-wrap: balance; margin: 0; }
.display-3 { font: 500 var(--fs-display-3)/var(--lh-display-3) var(--font-display);
             letter-spacing: var(--tr-display-3); color: var(--fg-display); margin: 0; }

.w-solid { color: var(--fg-display); }
.w-muted { color: var(--fg-micro); }

.micro { font: 500 var(--fs-micro)/1.3 var(--font-mono);
         letter-spacing: var(--tr-micro); text-transform: uppercase;
         color: var(--fg-micro); white-space: nowrap; }
.nano  { font: 500 var(--fs-nano)/1.25 var(--font-mono);
         letter-spacing: .11em; text-transform: uppercase; color: var(--fg-micro); }
.num   { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

.rule    { border: 0; border-top: var(--hairline); margin: 0; }
.scroll-x { overflow-x: auto; overscroll-behavior-x: contain; }

/* Hide the native cursor only where the custom one is active (pointer devices) */
@media (hover: hover) and (pointer: fine) {
  body[data-cursor="on"], body[data-cursor="on"] * { cursor: none; }
}
```

---

## 6. State chip - the most-used component

```tsx
const TONE = {
  pass:       ["--sig-pass",       "--sig-pass-tint",       "--sig-pass-edge"],
  unverified: ["--sig-unverified", "--sig-unverified-tint", "--sig-unverified-edge"],
  fail:       ["--sig-fail",       "--sig-fail-tint",       "--sig-fail-edge"],
  neutral:    ["--fg-micro",       "transparent",           "--border"],
} as const;

export function StateChip({ tone, children }:
  { tone: keyof typeof TONE; children: React.ReactNode }) {
  const [fg, bg, edge] = TONE[tone];
  return (
    <span className="chip" style={{
      color: `var(${fg})`, background: `var(${bg})`, borderColor: `var(${edge})` }}>
      {children}
    </span>
  );
}
```

```css
.chip {
  display:inline-flex; align-items:center; gap:.4em;
  padding:.28em .6em; border:1px solid; border-radius:var(--r-sm);
  font:600 var(--fs-micro)/1 var(--font-mono);
  letter-spacing:.07em; text-transform:uppercase; white-space:nowrap;
}
```

Copy for the three verdicts is fixed and must not be softened: `PASS` · `UNVERIFIABLE` · `FAIL`.
Never "unclear", "pending" or "review" - the product's whole argument rests on the machine saying
plainly that it could not verify something.

---

## 7. Accessibility checklist

- [ ] AA contrast for all text in both themes (verify `--grey-500` usage is micro-only).
- [ ] Semantic state is never conveyed by colour alone - every chip carries its word, and clause
      rows carry an icon (`✓` / `?` / `✕`) as well as a hue.
- [ ] Focus visible on every interactive element, in both themes, and **not** removed when the
      custom cursor is active.
- [ ] The custom cursor is disabled on touch and on `pointer: coarse`; native cursor restored.
- [ ] `aria-live="polite"` on the verification result region; the decision is announced.
- [ ] Dialogs trap focus, close on `Esc`, and restore focus on close.
- [ ] The scramble CTA exposes its resolved text to assistive tech (`aria-label`), never the
      scrambling characters.
- [ ] Theme and language toggles are real buttons with `aria-pressed` / `aria-current`.
