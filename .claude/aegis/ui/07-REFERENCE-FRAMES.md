# 07 - REFERENCE FRAMES

Sixteen stills in `reference/`, pulled from the four recordings with `ffmpeg`. Each one is here
because it drove a specific decision. A build agent cannot watch the videos; it can read these.

Source recordings (in `aegis/`, not committed to the repo - add `*.mp4` to `.gitignore`):

| Ref | File | Duration | What it is |
|---|---|---|---|
| **A** | `20260904-0840-51.3882079.mp4` | 38.8s | "Ramos" - light red/yellow analytics SaaS |
| **B** | `20260904-0839-33.5386187.mp4` | 25.6s | Dark editorial eCommerce agency |
| **C** | `20260904-0847-46.6891940.mp4` | 67.6s | hobro.digital - monochrome studio |
| **D** | `Screen Recording 2026-09-04 141220.mp4` | 19.3s | "OUTFIT" - Swiss red/bone commerce |

All four are ~1920×950 @30fps.

---

## Frames

### A - Ramos (hero structure, flip reveal, stepped wipe)

| File | t | Shows | Drove |
|---|---|---|---|
| `A1-preloader-progress-nodes.png` | 2.0s | Full-red preloader, huge wordmark bottom-left, horizontal hairline track with circular icon nodes filling left→right | The **readiness track** boot screen - nodes rewired to real `/health` subsystems (`02` §2) |
| `A2-stair-step-wipe.png` | 4.05s | The red panel exiting as a descending **staircase** of 6 discrete steps | `stepWipe` + `stepWipeClip()` - the app's one page transition (`01` §5, `02` §2) |
| `A3-word-flip-midreveal.png` | 5.1s | Headline mid-reveal: the word "that" rendered **upside-down/mirrored** while neighbours are upright | Proof the reveal is a per-word `rotateX` flap, not a slide → `flipWord` (`02` §4) |
| `A4-hero-resolved.png` | 6.6s | Resolved headline with two-tone words and **inline circular chips inside the text flow** | Two-tone word rhythm + inline headline chips (`00` §2.3, §2.4) |

### B - dark editorial agency (canvas, slat reveal, density)

| File | t | Shows | Drove |
|---|---|---|---|
| `B1-preloader-star.png` | 1.5s | Near-black, tiny centred star glyph, `nano` labels in three corners | The minimal boot canvas and the **corner metadata** convention (`00` §3, `02` §2) |
| `B2-vertical-slat-reveal.png` | 3.35s | Hero revealing through ~24 **vertical bars of varying height**, equaliser-like | `slatUp` - the hero backdrop reveal (`01` §4, `02` §4) |
| `B3-hero-blur-up.png` | 4.55s | Three-line display headline **soft/blurred mid-entrance**, resolving to sharp | `blurUp` - line entrances for paragraphs and sub-headlines (`01` §4) |
| `B4-dense-microgrid.png` | 8.5s | Dense dark grid: tiny uppercase labels in columns, hairline rules, a media element pinned on a full-width rule | The **micro-label system** and hairline-not-cards structure (`00` §3, §4) |

### C - hobro.digital (the CTA component, monochrome, list hover)

| File | t | Shows | Drove |
|---|---|---|---|
| `C1-gotproject-resolved.png` | 13.2s | **"Got Project? / LET'S TALK"** fully resolved, flanked by nested sonar arcs, capsule cursor over the type | The whole scramble CTA - this is the frame from your screenshot (`05` §2) |
| `C2-gotproject-midscramble.png` | 12.4s | The same line mid-transition: characters from two phrases on screen at once, out of order, at mixed opacity, slots held | The **per-character randomised dissolve** mechanic and the `opacity .55` intermediate (`05` §1, §3) |
| `C3-wedo-overlap.png` | 20.0s | "WHAT" ghosted behind solid "WE DO", words entering from different directions and overlapping | Rejected as a headline treatment (too loose for financial copy); kept only the idea of a muted word behind a solid one → two-tone (`00` §2.3) |
| `C4-list-hover-slidebar.png` | 52.0s | Vertical service list with a **filled bar behind the hovered row**, row text inverted | `MagicList` / `magicBar` - clause table, review queue, nav (`04` §3) |

### D - OUTFIT (cursor, item hover, numerals)

| File | t | Shows | Drove |
|---|---|---|---|
| `D1-preloader-counter-cards.png` | 1.2s | Black boot screen, wordmark, **three-digit counter** climbing, photo cards fanned behind | The boot counter (`02` §2) |
| `D2-hero-swiss.png` | 6.2s | Bone canvas, enormous red wordmark, hairline rules, tiny paired labels | Hairline rules + tiny name/value label pairs; **palette rejected** (see below) |
| `D3-grid-hover-big-cursor.png` | 12.6s | Product tile hovered: a **panel wiped out behind the media**, alternate photo shown, and a **large filled disc cursor** over the tile | `panelWipe` + `mediaSwap` + the dot↔disc cursor (`04` §1, §2) |
| `D4-footer.png` | 17.0s | Large statement type, oversized mark, thin rules, micro link columns | Footer/CTA composition rhythm |

---

## Contact sheets

Regenerate the full overviews at any time - useful if you want to check something these 16 stills
don't cover:

```bash
cd aegis
ffmpeg -y -i "20260904-0840-51.3882079.mp4"      -vf "fps=1,scale=380:-1,tile=5x8"   A_sheet.png
ffmpeg -y -i "20260904-0839-33.5386187.mp4"      -vf "fps=1,scale=380:-1,tile=5x5"   B_sheet.png
ffmpeg -y -i "20260904-0847-46.6891940.mp4"      -vf "fps=0.5,scale=380:-1,tile=6x6" C_sheet.png
ffmpeg -y -i "Screen Recording 2026-09-04 141220.mp4" -vf "fps=2,scale=380:-1,tile=5x8" D_sheet.png
```

Zoom into a specific moment (this is how the CTA and the cursor were measured):

```bash
# the Got Project? scramble, 6fps across 0:09–0:16
ffmpeg -y -ss 9  -t 7   -i "20260904-0847-46.6891940.mp4" \
  -vf "fps=6,scale=340:-1,tile=7x6"  C_texthover.png

# the cursor + item hover, 12fps across 0:11.5–0:14
ffmpeg -y -ss 11.5 -t 2.5 -i "Screen Recording 2026-09-04 141220.mp4" \
  -vf "fps=12,scale=500:-1,tile=5x6" D_hover_zoom.png
```

Rule of thumb used here: **1fps** to read a site's overall arc, **4–6fps** to read a transition's
mechanic, **12fps** to count frames and derive a duration.

---

## What was deliberately not adopted

Being explicit about this matters - an agent handed four beautiful references will otherwise try to
honour all of them and produce a collage. Copy this section into `docs/DECISIONS.md`.

| Rejected | From | Reason |
|---|---|---|
| Red / yellow / bone palettes | A, D | **Hue is data in this product.** Red is `FAIL`, amber is `UNVERIFIABLE`, mint is `PASS`. A red brand accent beside a red failure badge makes the interface lie. Brand is monochrome; the three semantic hues are the only colour. (`README` § thesis) |
| Red cursor | D | Same reason. The cursor uses `mix-blend-mode: difference` instead - always visible, claims no hue. (`04` §1.2) |
| Per-letter jitter on pinned scrolling type | B | On a financial interface, type that appears to glitch reads as a rendering fault, not as style. The one place a reference is knowingly not followed. (`02` §5) |
| Photographic hero | B, D | Aegis has no lifestyle imagery and inventing some would be dishonest. Replaced with a generated hairline lattice. (`02` §3) |
| Overlapping display words | C | Too loose for copy a reviewer must read precisely. Reduced to the two-tone solid/muted rhythm. |
| Serif-italic display accents | C | One display family only. A second voice would read as decoration in an audit tool. |
| Particle/dot text formation | C | Expensive, and it says nothing about escrow. |
| Rounded, playful card language | A | B and C are near-square and it is why they read as serious. Radius capped at 16px. (`00` §4) |
| Light-first canvas | A, D | Dark-first suits an operations surface people stare at. Light theme exists and is complete, but dark is the default and the demo. |

---

## Provenance note for the submission

The four recordings are **visual references for motion vocabulary only**. No asset, font, copy,
brand mark, layout or code from any of them is reproduced. The palette, typography, information
architecture and every component are original to Aegis, and the colour system deliberately departs
from all four. Say so in `docs/DECISIONS.md` - it is both true and worth stating, since a reviewer
who recognises hobro.digital or a Ramos template should see immediately that you studied motion
rather than cloned a page.
