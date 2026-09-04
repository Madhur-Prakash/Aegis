# AEGIS — UI & MOTION DESIGN PACK

Everything a build agent needs to implement the Aegis frontend **without watching the reference
videos**. Derived by frame-analysing four reference recordings (see `07-REFERENCE-FRAMES.md`) and
synthesising them into one system fit for a financial audit product.

## How to use this pack

Hand the agent **both** of these:

```
aegis/AEGIS_BUILD_SPEC.md      ← what to build (product, backend, invariants, screens)
aegis/ui/                      ← how it should look and move
```

Precedence: `AEGIS_BUILD_SPEC.md` wins on *behaviour, data and safety*. This pack wins on
*visual and motion detail*. Where the spec says "polished, fintech-grade, mobile responsive,
animated", these files are the concrete answer. §25 of the spec reserves two files for the visual
identity — this pack fills them:

| Spec requirement | Fulfilled by |
|---|---|
| `frontend/design/tokens.css` | `00-DESIGN-SYSTEM.md` (copy the block verbatim) |
| `frontend/design/motion.ts` | `01-MOTION-SYSTEM.md` (copy the block verbatim) |
| `docs/UI_MOTION.md` | This pack **is** that document; copy it in or symlink it |

## Files

| File | Contents |
|---|---|
| `00-DESIGN-SYSTEM.md` | Palette with semantics, typography, scale, grid, micro-label system, full `tokens.css` |
| `01-MOTION-SYSTEM.md` | Easings, durations, every named variant, reduced-motion, perf rules, full `motion.ts` |
| `02-PRELOADER-AND-HERO.md` | Boot sequence + hero, shot by shot with timings (references A × B) |
| `03-DROP-IN-REVEALS.md` | The element entrance system — what animates, how, and when (A × B) |
| `04-CURSOR-AND-HOVER.md` | Custom cursor dot↔disc, item hover panel wipe, list magic-bar (D + C) |
| `05-SCRAMBLE-CTA.md` | The "Got Project?" component reworked as Aegis's CTA + the UNVERIFIABLE reuse (C) |
| `06-SCREEN-BLUEPRINTS.md` | All six primary screens: layout, components, which motion goes where |
| `07-REFERENCE-FRAMES.md` | What each still in `reference/` shows and which decision it drove |
| `reference/*.png` | 16 curated stills pulled from the four videos |

---

## The design thesis — read this before writing any CSS

The four references were chosen for their *motion*, and their motion is adopted faithfully. Their
**colour strategy is deliberately not adopted**, for one reason:

> **In an audit product, hue is data.**
>
> Aegis exists to tell you whether a clause passed, whether a machine was sure, and whether money
> moved. Those are the only things allowed to be coloured. Spending a hue on branding would make
> the interface lie — a red brand accent next to a red FAIL badge, an amber logo above an amber
> escalation. So the brand is **monochrome**: near-black, bone, white, and a grey ramp. Exactly
> three hues exist in the entire product, and each one means something.

This is what makes the design read as *considered* rather than as a pastiche of four nice websites.
It also has a payoff for the demo: because amber appears nowhere else, the moment the verifier
returns **UNVERIFIABLE** the screen changes colour for the first time — and that is the single most
important beat in the 5-minute video.

## What each reference contributed

| Reference | Adopted | Rejected |
|---|---|---|
| **A** — Ramos (light red/yellow SaaS) | Staged progress preloader, stepped-wipe transition, per-word `rotateX` flip reveal, inline chips inside headlines, two-tone word weighting | Red/yellow palette, light background, rounded playfulness |
| **B** — dark editorial agency | Near-black canvas, vertical slat reveal, blur-up line entrances, pinned hero with scroll occlusion, dense micro-label grid, hairline rules | Photographic hero, brutalist information overload |
| **C** — hobro.digital (monochrome studio) | Per-character glyph scramble, sonar arc rings, capsule cursor with label, sliding highlight bar on list hover, monochrome discipline | Serif-italic flourishes, particle text |
| **D** — OUTFIT (Swiss red/bone commerce) | Dot↔disc cursor with lerp follow, hover panel wipe + media swap, numeric boot counter, tiny paired name/value labels, hairline row rules, tabular numerals | Red/bone palette, product-grid layout |

## Non-negotiables

1. **Tokens only.** No hex literal, raw duration or inline easing in any component. Everything
   comes from `tokens.css` and `motion.ts` (spec §25.1).
2. **Three hues, each semantic.** Mint = pass/released. Amber = unverifiable/escalated/held.
   Red = fail/adverse. Nothing else is coloured, ever.
3. **`prefers-reduced-motion` is honoured globally**, via one hook. Reduced = opacity-only
   crossfades; every state change stays perceivable (spec §25.3).
4. **`transform` and `opacity` only** in anything that runs more than once. 60fps on a mid-range
   phone is the bar.
5. **Mobile-first.** Every screen verified at 375 / 768 / 1440. No horizontal page scroll ever;
   wide tables scroll inside their own container.
6. **Motion carries meaning.** The animation budget goes to the five moments in
   `01-MOTION-SYSTEM.md` § "The five meaning-bearing moments", not to a decorative hero.
7. **Every animated element has a correct static end state.** Disable animation entirely and the
   page must be fully readable and usable.
