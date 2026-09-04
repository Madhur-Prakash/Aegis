# UI and motion

The design system as **implemented**, with the file that owns each rule. `design/tokens.css` and
`design/motion.ts` are copied verbatim from the design pack; everything else here describes how they
are consumed and what enforces that.

---

## 1. Hue is data

The product is monochrome. There are exactly **three** semantic hues and each one means one thing:

| token | meaning |
|---|---|
| `--sig-pass` (mint) | `PASS`, `RELEASE`, released money, a verified signature, an intact chain |
| `--sig-unverified` (amber) | `UNVERIFIABLE`, `ESCALATE`, held money, under human review, a queued anchor |
| `--sig-fail` (red) | `FAIL`, `REJECT`, refunded/adverse, a broken hash, a failed payout |

Each has a `-tint` (12–14% mix) for a fill and an `-edge` (40–45%) for a border, so a chip never
needs a second colour.

**Red is reserved.** It appears when something is *wrong* — a `FAIL` verdict, a digest mismatch, a
broken ledger index, an unbalanced money bar. It is never used for emphasis, for a destructive button
that is merely irreversible, or for decoration. This is why the custom cursor is
`mix-blend-mode: difference` and carries no hue at all, departing from the reference it is based on.

**State becomes a hue in exactly one place**: `lib/format.ts`, in `milestoneTone`, `verdictTone`,
`decisionTone`, `dealTone` and `riskTone`. A component receives a `Tone`, never a colour, and no
component decides what amber means.

**Colour is never the only channel.** Every chip carries its word (`PASS`, `UNVERIFIABLE`, `FAIL`),
clause rows carry a glyph as well as a hue, the money sum line carries `✓`/`✕` plus a
visually-hidden sentence, and `RailTag` prints `SIMULATED` or `REAL TEST MODE` as text.

## 2. Copy that must not be softened

`PASS` · `UNVERIFIABLE` · `FAIL`. Never "unclear", "pending", "needs review" or "inconclusive". The
whole argument of the product rests on a machine saying plainly that it **could not verify**
something, and every softer word gives that back.

Likewise `SIMULATED`, and the sum line `released + held + refunded = funded` written out rather than
implied.

## 3. Type

`display-1` / `display-2` (900 weight) for the hero and one figure per screen; `display-3` (500) for
page titles; body at `--fs-body`; `micro` and `nano` in mono, uppercase, tracked, for labels.

* **A micro-label never wraps.** `white-space: nowrap` is in the token definition.
* **Numerals are tabular** everywhere via `.num`, so a column of rupee figures does not shimmer as it
  counts up.
* **Money always goes through `inr()`** with the `en-IN` locale. This is not a preference: the
  grouping differs, and a judge from Bangalore reading `₹420,000` instead of `₹4,20,000` would be
  right to notice.
* **Confidence is always three decimals.** `0.510` and `0.51` must not look different.
* **Hashes truncate in the middle**, never at the end — both ends of a hash carry signal — and the
  full value is in `title` and copyable.

### Devanagari

`[lang="hi"]` opens the display line-heights (a शिरोरेखा collides with tight leading), reduces
negative letter-spacing, and scopes tracking to Latin only, because spacing Devanagari breaks its
conjuncts. The Hindi hero is a **shorter headline**, not a literal translation: Devanagari words are
longer, and translating the English line literally turns a two-line hero into four.

## 4. Motion

Every duration and easing lives in `design/motion.ts`. No component contains a number or a curve.

| name | value | used for |
|---|---|---|
| `D.instant` | 0.09s | glyph swaps, opacity nudges |
| `D.fast` | 0.18s | hover, focus, chips |
| `D.base` | 0.26s | panels, drawers |
| `D.slow` | 0.42s | wipes, shakes |
| `D.reveal` | 0.52s | the default entrance |
| `D.hero` | 0.90s | the slat backdrop |
| `D.wipe` | 0.76s | the boot staircase |

Easings: `E.enter` `[0.16, 1, 0.30, 1]`, `E.exit` `[0.55, 0, 0.85, 0.25]`, `E.expo`
`[0.19, 1, 0.22, 1]`, `E.back` `[0.34, 1.56, 0.64, 1]`. Springs for the cursor, chips and layout.

### Entrances

One default — `dropIn` (opacity, `y: 28`, `rotateX: -10`, an 8px blur clearing) — and five
specialists, each used only where the pack specifies: `flipWord` for the hero, `blurUp` for lede
lines, `slatUp` for the column mask, `chipPop` for chips, `panelWipe`/`mediaSwap` for the hover card.

**Every scroll reveal is `once: true`.** Nothing replays on scroll-up. A page that re-animates as you
scroll back is a page that feels unfinished.

### The nine motion moments

| # | where | what |
|---|---|---|
| 1 | boot → app | a six-step staircase clip-path sweeps bottom-left to top-right |
| 2 | hero | per-word `rotateX` flap, continuous index across both lines so the rhythm does not restart |
| 3 | nav | one `layoutId` bar **slides** between links rather than fading |
| 4 | milestone card | a state-tinted backdrop panel wipes out from behind the card; nothing lifts, nothing gains a shadow |
| 5 | money bar | segments animate `flexGrow` under `layout`, so total width is conserved and I4 is visible |
| 6 | verdict chips | `PASS` and `FAIL` snap; `UNVERIFIABLE` never settles |
| 7 | attestation seal | a circle draws clockwise, the sigil scales with an overshoot, the tx hash types in. One-shot |
| 8 | tamper check | one 6px shake and a red underline on the mismatched digest |
| 9 | closing CTA | per-character scramble cycling three phrases |

### The one thing that never comes to rest

`UNVERIFIABLE` resolves and then **keeps disturbing one random character, forever** — one slot, a
random glyph for 90ms, restored, repeating after 1800 + random(1400)ms.

A `PASS` chip's label locks. An amber badge that sits still says "warning". A label that cannot hold
still says *the machine is still not sure*, which is the literal truth of the state, and it is the
only element in the product that should never look settled.

The scramble runs on fixed-width character slots (`.sc-ch`, `width: 0.62em`) so the line never
reflows while glyphs churn, and it pauses when off-screen so a forty-row table does not run forty
timers.

## 5. Reduced motion

One hook, `useReducedMotion`, honoured globally — plus a CSS backstop for anything that slips past
it. It reads the OS preference **and** an in-product override, so Settings → Animation → Off reaches
every component through the same channel as the system setting and the two cannot diverge.

Under reduced motion:

* every entrance collapses to a 0.18s crossfade (`pick()` swaps the variant set);
* the `UNVERIFIABLE` jitter **stops entirely** and the chip keeps a static `?` and a dashed border —
  same message, no motion;
* `CountUp` renders the final value immediately;
* the money bar stops animating `layout` but still shows the correct proportions;
* the slat backdrop does not mount at all;
* the boot sequence skips its wipe.

Nothing is *only* communicated by motion, which is what makes turning it off safe.

## 6. Loading, empty, error

Three states, designed rather than defaulted.

* **Skeletons, not spinners**, matching the final layout so nothing jumps.
* **Empty** is a `micro` label, one line of explanation, and the single action that resolves it.
  Never an illustration.
* **Error** appears **instantly**, with no entrance animation, and carries the typed `code` from the
  API envelope above the message — mirroring I9 in the interface.

## 7. Enforcement

```bash
npm run check:tokens     # no hex, no rgb()/hsl(), no raw duration, no inline cubic-bezier
npm run check:i18n       # no key a component asks for that a dictionary lacks
```

`check-tokens` scans `app/`, `components/`, `hooks/` and `lib/`, skipping only `design/`, and
additionally asserts the CSS duration scale in `globals.css` **equals** `D` in `motion.ts`
numerically — otherwise a CSS transition and its Framer counterpart could drift and the same
interaction would take two different times depending on which layer animated it.

A line may be exempted with a `tokens-allow:` comment stating the reason, which puts the exemption in
the diff rather than in a config file. There is exactly one: the `prefers-reduced-motion` `0.01ms`
kill switch, which is not a design duration.

Both checks run **inside the Docker build**, so an image cannot be produced from violating source.
CI additionally plants a hex colour and a divergent duration and requires the check to fail on each.

## 8. Accessibility

* Focus is visible everywhere: a 2px `--focus` outline with a 3px offset, defined on
  `:where(a, button, [tabindex]):focus-visible`.
* Toggles are real `<button>`s with `aria-pressed`, not styled divs.
* Hit targets are ≥44px on touch.
* The hover card mirrors its hover state on `whileFocus`, so nothing is reachable by pointer alone.
* The money bar is `role="img"` with a full sentence in `aria-label`.
* The agent console is `role="log"` with `aria-live="polite"` and `aria-relevant="additions"`.
* The lifecycle strip uses `aria-current="step"`.
* Every icon-only control has an `aria-label`, and every decorative glyph is `aria-hidden`.

## 9. Responsive

Breakpoints and what changes at each. (The manual pass at 375 / 768 / 1440 in both themes, both
languages, and with animation on and off is a release-checklist item, recorded in the build status
rather than asserted here.)

* **The page never scrolls sideways.** `overflow-x: hidden` on `body`, and wide content scrolls
  inside its own `.scroll-x` container.
* **Below 768px the clause table becomes cards.** That is the screen a judge will open on a phone.
* `.two-col` and `.cockpit` collapse to one column below 1024px.
* `.meta` rows stack their key above their value below 768px.
* The nav collapses to a sheet; the flanking sonar arcs are hidden.
* The custom cursor exists only on `(hover: hover) and (pointer: fine)`, and the native cursor is
  hidden only there.
