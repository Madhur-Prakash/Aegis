# 03 - ELEMENT DROP-IN / APPEARANCE SYSTEM

The entrance vocabulary, mixed from **reference A** (per-word `rotateX` flip, `chipPop` overshoot,
stepped wipe) and **reference B** (blur-up rise, slat masks, staggered density). One default,
five specialists, and a strict rule about which is used where.

---

## 1. The default: `dropIn`

Reference A rises words with a flip; reference B rises blocks with a blur. `dropIn` is the average
of the two, and it is the entrance for **almost everything**:

```
opacity  0    → 1
y       +28px → 0
rotateX -10°  → 0        ← A's flap, dialled down from -92° to a hint
blur     8px  → 0        ← B's softness
duration 520ms, ease enter, stagger 90ms
```

The `-10°` rotateX is the whole trick. It gives the element a barely-perceptible sense of falling
into the plane rather than sliding up it - A's character at a strength that survives being used
two hundred times. Requires `perspective: 800px` on the container.

```tsx
<motion.div variants={dropIn} custom={i}
  initial="hidden" whileInView="show" viewport={inView}
  style={{ perspective: 800 }}>
```

Set `perspective` once on the section wrapper, not per item.

---

## 2. When to use which

| Element | Variant | Why |
|---|---|---|
| Display headlines (`display-1`, `display-2`) | `flipWord` | A's signature; per word, continuous index across lines |
| Screen titles (`display-3`) | `blurUp` | Too small for a flip to read; blur is calmer |
| Body paragraphs | `blurUp` per line | B's mechanic; wrap lines in `<span>` |
| Cards, panels, list rows | `dropIn` | The default |
| Chips, badges, verdict pills, boot nodes, avatars | `chipPop` | Needs overshoot to feel like it *landed* |
| Images, evidence thumbnails, backdrops | `slatUp` | B's column mask; 8–24 columns by width |
| Hairline rules | `scaleX 0→1` from left, `420ms`, `expo` | A rule that fades looks like a mistake; it should *draw* |
| Numbers (money, confidence, counters) | `countUp` after `dropIn` | The container drops in, then the value counts |
| Tables | Header `dropIn`, rows `dropIn` at `--st-base` capped 400ms | See §4 |
| Page / route change | `stepWipe` | A's staircase; the app's one transition |
| Modals, drawers | `scale 0.97→1` + `opacity`, `--d-base` | No y-travel; it's not arriving from anywhere |
| Toasts | `y +12 → 0` + `opacity`, `--d-fast` | Fast, from the edge it's docked to |

**Never** apply `flipWord` to body copy, table rows, or anything under `--fs-h4`. At small sizes
the rotation reads as a font-rendering glitch - which, in a product whose entire claim is
trustworthiness, is exactly the wrong impression.

---

## 3. Composition rules

1. **One variant per element.** Never nest `dropIn` inside `dropIn`; the child inherits the
   parent's transform and the blur compounds into mush. Animate the parent, or the children -
   not both.
2. **Group order is fixed** (from reference B's section rhythm):
   `rule → corner metadata → headline → paragraph → content`, `--st-loose` between groups.
3. **Stagger index is continuous within a group**, and resets between groups. A 4-card row uses
   `custom={0..3}`; the paragraph above it starts its own count.
4. **Cap the stagger at 400ms.** `stagger()` in `motion.ts` already does this. A 30-row clause
   table must not take 1.6s to appear.
5. **Once only.** Every scroll reveal uses `viewport={inView}` (`once: true`). Scrolling back up
   never replays. This is non-negotiable - replayed entrances are the fastest way to make a
   product feel cheap.
6. **Direction is always up.** Nothing enters from the left, right, or above. Reference A and B
   both move in one direction and it is why they feel calm. The only exceptions are `panelWipe`
   (horizontal, hover-driven) and toasts (from their dock edge).

---

## 4. Lists and tables - the density problem

Reference B's dense micro-grid works because dozens of tiny rows appear as one texture, not as
dozens of events. Match that:

```tsx
{rows.map((r, i) => (
  <motion.tr key={r.id} variants={dropIn} custom={i}
    initial="hidden" whileInView="show" viewport={inView}>
```

- Rows: `--st-base` (55ms), capped at 400ms → rows 8+ all land together. Correct and intentional.
- **Virtualised or paginated lists animate the page, not the rows.** Re-animating rows on every
  page change is nauseating. Animate the container once; subsequent pages crossfade at
  `--d-fast`.
- **Data updating in place never re-runs an entrance.** A value changing uses `countUp` and a
  `140ms` background tint flash (`--sig-pass-tint` for increase, `--sig-fail-tint` for decrease),
  then back to transparent. Never re-drop the row.
- Sticky table headers: `position: sticky; top: 0; background: var(--bg); border-bottom:
  var(--hairline)`. They do not animate on scroll.

---

## 5. The `blurUp` per-line paragraph

Wrap each visual line so it can stagger. Do not split on words.

```tsx
export function BlurLines({ children }: { children: string }) {
  const reduced = useReducedMotion();
  const v = pick(blurUp, reduced);
  // Author-controlled breaks: split the source on " / " at write time.
  const lines = children.split(" / ");
  return (
    <p className="lede">
      {lines.map((l, i) => (
        <motion.span key={i} custom={i} variants={v} initial="hidden"
          whileInView="show" viewport={inView} style={{ display: "block" }}>
          {l}
        </motion.span>
      ))}
    </p>
  );
}
```

Author line breaks explicitly (`"first clause / second clause"`) rather than measuring text at
runtime. Runtime line-splitting breaks on font load, on resize, and on translation into Hindi -
and Hindi is a requirement (spec §24).

---

## 6. Hindi / i18n considerations

Devanagari has taller ascenders and a headline (शिरोरेखा) that makes tight leading collide.

- Add `[lang="hi"] { --lh-display-1: 1.02; --lh-display-2: 1.06; --tr-display-1: -0.01em; }`
- `flipWord` splits on spaces, which is correct for Hindi word boundaries - but Hindi words are
  longer, so **check the two-line hero doesn't become four**. Provide a separate, shorter Hindi
  headline rather than translating the English literally.
- Do not letter-space Devanagari. Scope `--tr-micro` to `[lang="en"]`, or conjuncts break.
- Numerals stay Latin with Indian grouping in both languages (`₹4,20,000`). Do not switch to
  Devanagari digits - Indian financial interfaces use Latin numerals.

---

## 7. Loading, empty and error states

Every view needs all three (spec §24), and each has a defined motion:

| State | Treatment |
|---|---|
| **Loading** | Skeleton blocks at `--ink-800`, with a `1.6s` shimmer sweep (`linear`, `transform` only). Skeletons match the final layout's dimensions so nothing jumps on load. No spinners on the cockpit, verification result or review queue. |
| **Empty** | `dropIn` once. A `micro` label, a one-line explanation, and the single action that resolves it. Never an illustration. |
| **Error** | No entrance animation - errors appear instantly. `--sig-fail-tint` background, `1px` `--sig-fail-edge` border, the typed error `code` in mono, the human message below, and a retry action. Mirrors the API's typed envelope (spec §I9). |

Layout must not shift between the three. Reserve the space.

---

## 8. QA checklist for the entrance system

- [ ] `perspective` set once per section; no compounding transforms.
- [ ] No entrance replays on scroll-up anywhere in the app.
- [ ] Longest list entrance completes within 400ms of the first row.
- [ ] In-place data updates never re-run an entrance.
- [ ] With JS disabled, or animations forced off, every element is visible and correctly placed.
- [ ] `prefers-reduced-motion` collapses all of the above to opacity crossfades.
- [ ] Throttled 6× CPU at 375px: hero entrance holds ≥50fps.
- [ ] Hindi headline does not overflow at 375px.
