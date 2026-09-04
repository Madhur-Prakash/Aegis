# 06 - SCREEN BLUEPRINTS

The six primary screens from `AEGIS_BUILD_SPEC.md` §24, with layout, components and the motion
assigned to each. Plus the supporting flows.

Shared shell first, then each screen at desktop and mobile.

---

## 0. Shell

```
┌────────────────────────────────────────────────────────────────────────┐
│ ◈ AEGIS   Deals  Review (2)  Ledger        ORG ▾   ⌘K   ☾  EN  ●     │ ← 56px, sticky
├────────────────────────────────────────────────────────────────────────┤
│  nano: 02 / 06                                    nano: BASE SEPOLIA   │ ← corner metadata
│                                                                        │
│  [screen content]                                                      │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

- Nav: 56px, `position: sticky`, `background: color-mix(in oklab, var(--bg) 82%, transparent)`,
  `backdrop-filter: blur(12px)`, `border-bottom: var(--hairline)`. Items use `magicBar` (04 §3).
- `Review (2)` badge is amber when the count is non-zero. It is the only amber in the chrome, and
  it should draw the eye - that's the point.
- Right cluster: org switcher, `⌘K` command hint, theme toggle, language toggle, avatar.
- **Degraded banner** (spec §27): if `/health` reports chain RPC or Kafka down, a 32px amber strip
  sits under the nav: `CHAIN RPC UNAVAILABLE - ANCHORING QUEUED (14)`. Never hide a degraded
  dependency.
- Mobile: nav collapses to logo + `Review` badge + hamburger. Bottom-sheet menu, not a drawer.

---

## 1. Deal cockpit - the primary screen

```
┌────────────────────────────────────────────────────────────────────────┐
│ nano: DEAL D-4812                              nano: IN_PROGRESS       │
│                                                                        │
│ Meridian Label  →  Tirupur Exports                    ₹4,20,000       │ ← display-3 + num
│ 500 custom kurtas · 3 milestones · opened 4 Sep 2026                   │ ← micro
│ ──────────────────────────────────────────────────────────────────────  │
│                                                                        │
│ ┌── MONEY ────────────────────────────────────────────────────────────┐ │
│ │ ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ │
│ │ RELEASED ₹1,26,000     HELD ₹2,94,000        REFUNDED ₹0           │ │
│ │ released + held + refunded = funded ₹4,20,000                  ✓   │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│ ┌── STATE ───────────────────────────────────────────────────────────┐ │
│ │ DRAFT ─ TERMS_SIGNED ─ FUNDED ─ ●IN_PROGRESS ─ COMPLETED           │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│ MILESTONES                                                             │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                    │
│ │ 01 ✓ SETTLED │ │ 02 ? UNVERIF │ │ 03   PENDING │                    │ ← HoverPanelCard
│ │ ₹1,26,000    │ │ ₹1,68,000    │ │ ₹1,26,000    │                    │
│ │ Fabric       │ │ Production   │ │ Delivery     │                    │
│ └──────────────┘ └──────────────┘ └──────────────┘                    │
│                                                                        │
│ ┌── AGENT CONSOLE ───────────┐  ┌── MESSAGES ──────────────────────┐  │
│ │ 14:22:07 Verifier RELEASE  │  │ Tirupur: photos uploaded          │  │
│ │ 14:22:07 Settlement AUTH   │  │ Meridian: checking count          │  │
│ │ 14:22:08 Kafka published   │  │ ┌──────────────────────────────┐  │  │
│ │ 14:22:09 Razorpay OK       │  │ │ message…                  →  │  │  │
│ │ 14:22:10 Chain anchored ↗  │  └──────────────────────────────────┘  │
│ └────────────────────────────┘                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### The money bar - the most important component in the app

Three flex segments in one fixed-width track. The invariant `held + released + refunded = funded`
is **visible on screen at all times** (spec §I4), and the `✓` next to the sum line is computed
client-side from the actual numbers - not hardcoded.

```tsx
<div className="money" role="img"
     aria-label={`Released ${inr(released)}, held ${inr(held)}, refunded ${inr(refunded)}, of ${inr(funded)} funded`}>
  <div className="money-track">
    <motion.span layout transition={SPRING.layout}
      className="money-seg" style={{ flexGrow: released, background: "var(--money-released)" }} />
    <motion.span layout transition={SPRING.layout}
      className="money-seg" style={{ flexGrow: held, background: "var(--money-held)" }} />
    <motion.span layout transition={SPRING.layout}
      className="money-seg" style={{ flexGrow: refunded, background: "var(--money-refunded)" }} />
  </div>
  <div className="money-legend">…</div>
  <div className="money-sum micro">
    released + held + refunded = funded {inr(funded)} {balanced ? "✓" : "✕"}
  </div>
</div>
```

- Track: `height: 10px`, `border-radius: var(--r-full)`, `overflow: hidden`, `gap: 2px`.
- **Motion (moment 3.1):** on settlement the segments animate `flexGrow` via Framer `layout`, the
  newly released portion crossfades amber → mint, and each figure `countUp`s. Total width never
  changes, so conservation is visible.
- If `balanced` is false the sum line turns `--sig-fail` and shows `✕`. That should be impossible;
  showing it anyway is how you prove you meant the invariant.
- Mobile: track full width, legend stacks to three rows of `key - value`.

### Milestone cards
`HoverPanelCard` (04 §2), `tone` from milestone state. Grid `repeat(auto-fit, minmax(240px, 1fr))`
→ single column below 768px. Cursor label `VIEW PROOF`.

### Agent console
Monospace log, `--fs-micro`, newest at the bottom, auto-scrolled. Each line:
`time · actor · event`, actor colour-coded only by role weight (not hue). New lines arrive via SSE
with `y +8 → 0` + `opacity`, `--d-fast`. Cap at 200 lines in the DOM.
Chain lines carry a `↗` link to Basescan.

### Motion summary
Header `blurUp` → rule `scaleX` → money bar `dropIn` then `countUp` → state machine `dropIn` →
milestone cards `dropIn` `--st-loose` → console and chat `dropIn` together.

---

## 2. Evidence submission

```
nano: MILESTONE 02 / 03                                  nano: EVIDENCE
Submit evidence                                          ← display-3
Production complete · ₹1,68,000                          ← micro

┌── REQUIRED ─────────────────────────────────────────────────────┐
│ PHOTO SET          ○ not provided                               │
│ SPEC REFERENCE     ● provided                                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│            Drop files, or browse                                │  ← dashed --line-2
│            PDF · PNG · JPG · max 20 MB                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

ARTIFACTS
┌──────────────────────────────────────────────────────────────────┐
│ ▣ invoice-ct240.pdf   INVOICE   1.2 MB   sha256 7f3a…e91   ✓    │
│   vendor: Sri Textiles · date: 2026-08-28 · qty: 540 m           │  ← extracted preview
├──────────────────────────────────────────────────────────────────┤
│ ▣ line-01.jpg         PHOTO     3.4 MB   sha256 c081…44b   ✓    │
└──────────────────────────────────────────────────────────────────┘

MERKLE ROOT  9c1f…a730                          [ SUBMIT BUNDLE ]
```

- Drop zone: `2px dashed var(--line-2)`, `--r-lg`. On drag-over: border → `--bone-100`,
  background → `--ink-800`, `scale 1.005`. No bounce.
- Upload progress: a `2px` determinate bar at the row's bottom edge, `linear`. The **sha256
  appears as it is computed client-side** and is a genuinely reassuring detail - show it.
- Extracted fields appear under each row with `blurUp` once extraction returns. Fields the model
  could not read render as `-` in `--fg-micro`, never as an empty string.
- Merkle root renders once every artifact is hashed, with `sealDraw` on a small 16px seal glyph.
- Mobile: artifact rows become stacked blocks; the hash truncates to 8 chars with tap-to-copy.

---

## 3. Verification result - the best screenshot in the submission

```
nano: ATTESTATION A-9917                        nano: MODEL claude-opus-5

┌─────────────────────────────────────────────────────────────────────┐
│  DECISION                                                            │
│  ESCALATE                                          ((( 0.51 )))     │ ← display-2 amber
│  confidence 0.51 · threshold 0.85 · escalated to human review        │
└─────────────────────────────────────────────────────────────────────┘

CONFIDENCE BREAKDOWN
verifiable fraction   0.50  ▓▓▓▓▓░░░░░
llm component         0.78  ▓▓▓▓▓▓▓▓░░
extraction quality    0.71  ▓▓▓▓▓▓▓░░░
unverifiable penalty −0.25  ░░░░░░░░░░
─────────────────────────────────────────
computed              0.51           calibration v3

CLAUSES
┌────────────────────────────────────────────────────────────────────┐
│ c1  Photo set present                    ✓ PASS          invoice…  │
│ c2  500 finished units evidenced         ? UNVERIFIABLE  line-01…  │ ← scrambleUnrest
│     "Four photographs cannot establish a count of 500."            │
│ c3  Matches approved spec CT-240-IVY     ✓ PASS          spec…     │
└────────────────────────────────────────────────────────────────────┘

[ SEND TO HUMAN REVIEW ]   [ VIEW PROVENANCE ]
```

- **Decision block:** the word is `display-2` in the semantic hue. For `ESCALATE`, the confidence
  value is flanked by small `SonarArcs` in amber - reused motif, and it reads as *listening*.
- **Confidence breakdown is mandatory.** Four bars plus the arithmetic. This single panel is what
  makes the claim "we do not trust the model's self-reported confidence" legible rather than
  asserted. Bars animate `scaleX 0→value`, `--st-base` stagger, after the decision lands.
- **Clause table motion (moment 3.2):** rows `dropIn` at `--st-base`. `PASS` / `FAIL` chips snap
  with `chipPop`. `UNVERIFIABLE` uses `ScrambleText mode="unrest"` (05 §4) - it resolves and then
  never fully settles.
- The clause note for an `UNVERIFIABLE` verdict is rendered in full, in `--fs-sm` italic, directly
  beneath the row. Do not truncate it. It is the product's thesis in one sentence.
- Evidence refs are links that scroll-and-highlight the artifact.
- `aria-live="polite"` on the decision block; announce `"Decision: escalate, confidence 0.51"`.
- Mobile: the clause table becomes stacked cards (clause / verdict / note / refs). It must not
  scroll sideways - this is the screen a judge will open on a phone.

---

## 4. Human review queue

```
nano: QUEUE                                            nano: 2 AWAITING

┌────────────────────────────────────────────────────────────────────┐
│ D-4812 · M02   Production complete    ₹1,68,000   0.51   2h ago   │ ← MagicList row
│ D-4790 · M01   Fabric procured        ₹90,000     0.62   6h ago   │
└────────────────────────────────────────────────────────────────────┘

── SELECTED ─────────────────────────────────────────────────────────
WHAT THE AGENT COULD NOT VERIFY
  ? 500 finished units evidenced
    "Four photographs cannot establish a count of 500."

EVIDENCE            [thumbnails, click to enlarge]
ARBITER OPEN QUESTIONS  (disputes only)
  · Was a third-party count sheet issued?

DECISION
( ) APPROVE RELEASE  ₹1,68,000
( ) REJECT
( ) OVERRIDE - editable split   [ ₹1,15,920 ] [ ₹10,080 ]
REASON (required)  ┌──────────────────────────────────────────────┐
                   └──────────────────────────────────────────────┘
                                     [ CONFIRM · signs as you ]
```

- Rows use `MagicList` (04 §3) - the sliding bar. Empty queue shows the amber sonar empty state
  (05 §5).
- **"What the agent could not verify" is the first thing on the panel**, above the evidence. The
  reviewer's job is that sentence.
- The reason field is `required`; the confirm button is disabled until it has ≥12 characters, and
  the button label says `signs as you` so the reviewer understands they are on the record.
- Override split inputs validate live that the two values sum to the milestone amount; on mismatch
  the sum line turns `--sig-fail` and confirm disables. Mirror of the backend's balance check
  (spec §19) - never let the UI submit something the engine will reject.
- On confirm: `sealDraw` on a small approval seal, then the row leaves the queue with
  `y -12 / opacity 0`, `--d-base`, `exit` easing, and the nav badge counts down.

---

## 5. Provenance explorer

```
nano: PROVENANCE                          nano: ANCHORED 0x7f3a…e91d ↗

For this rupee                                       ← display-3
₹1,26,000 released 4 Sep 2026 14:22:09 IST

┌─ ATTESTATION ────────────────────────────────────────────────┐
│ MODEL              claude-opus-5                              │
│ MODEL VERSION      2026-05-01                                 │
│ PROMPT HASH        sha256 4a91…07cc                     copy  │  ← .meta rows
│ EVIDENCE ROOT      9c1f…a730                            copy  │
│ DECISION           RELEASE                                    │
│ CONFIDENCE         0.94   (threshold 0.85, calibration v3)    │
│ SIGNER             verifier-key-01  0x91aa…4d2                │
│ ANCHORED           block 18,442,901 · Base Sepolia       ↗    │
│ HUMAN APPROVER     -                                          │
└──────────────────────────────────────────────────────────────┘

┌─ TAMPER CHECK ───────────────────────────────────────────────┐
│ artifact  invoice-ct240.pdf                                   │
│ leaf      sha256 7f3a…e910                                    │
│ path      ├─ 2b81…  ├─ ee04…  └─ 9c1f…a730                    │
│ result    ✓ PROOF VALID                                       │
│                                     [ TAMPER ONE BYTE ]       │
└──────────────────────────────────────────────────────────────┘

LEDGER  seq 1…14   ✓ CHAIN INTACT      [ VERIFY LEDGER ]
```

- Left column of `.meta` rows (00 §3) - this screen is the purest expression of the micro-label
  system. Every hash is monospace, truncated middle (`7f3a…e910`), with copy-on-click and the full
  value in `title`.
- The attestation seal (moment 3.4) draws once on first view, then stays static.
- **`TAMPER ONE BYTE` is a real button**, and it must be in the demo. It flips a byte in a local
  copy, re-runs verification, and the row fails with the shake treatment (moment 3.5). Then a
  `RESTORE` button appears. This is the single most persuasive interaction in the product.
- `VERIFY LEDGER` calls `GET /deals/{id}/ledger/verify` and renders either `✓ CHAIN INTACT` or
  `✕ BROKEN AT INDEX 7` with the expected/found hashes side by side.
- Mobile: `.meta` rows stack key-above-value; the Merkle path becomes a vertical list.

---

## 6. Reputation view

```
nano: COUNTERPARTY                              nano: RISK 0.14 · TIER 2

Tirupur Exports                                  ← display-3
Tiruppur, Tamil Nadu · counterparty since Mar 2025

DEALS COMPLETED   11        GMV        ₹31,40,000
DISPUTES           1        ON TIME     91%
LARGEST DEAL      ₹6,20,000

RISK 0.14                                        ← display-2, mint
TOP FACTORS
  + 11 completed deals with no adverse outcome            −0.09
  + on-time rate 91% across 11 deals                      −0.05
  − this deal is 1.4× their largest to date               +0.07

PRICING
  escrow fee 1.5%  ·  hold 3 days  ·  buyer prefund 50%
```

- Risk value is `display-2` in the semantic hue for its band (mint <0.10–0.25, amber 0.25–0.50,
  red >0.50). **Never a bare number** (spec §22): the three factors, with signed contributions,
  are mandatory and render in plain language.
- Factor rows use `dropIn` at `--st-base`; contribution values `countUp`.
- Stats grid: `.meta` pairs, two columns desktop, one mobile.

---

## 7. Supporting flows

| Flow | Notes |
|---|---|
| **Auth** (register / verify / login / forgot / reset) | Single centred column, `max-width: 380px`, on `--ink-900` with the hairline lattice at 4% behind. `dropIn` on the card. Inputs: `--ink-800` fill, `1px --line-1`, focus → `--bone-100` border. Errors inline beneath the field with the typed `code` in mono. No hero, no illustration. |
| **Email verification gate** | Full-page state, amber sonar arcs, `VERIFY YOUR EMAIL` scramble headline, resend button with a 60s cooldown shown as a countdown. |
| **Organizations / members** | `MagicList` of members; role as a chip; invite is a modal with email + role. Last-owner protection surfaces as a disabled control with a tooltip explaining why. |
| **Notification centre** | Right-docked panel, `translateX` in at `--d-base`. Unread rows carry a 4px amber left border. Grouped by day with `micro` day headers. |
| **Settings** | Theme (system / light / dark), language (EN / हिंदी), notification preferences as a `.meta` grid of toggles. |
| **Command palette (⌘K)** | Optional but cheap and it makes the demo look fast: jump to deal, milestone, review queue, provenance. `scale .98→1` + `opacity`, `--d-fast`. |
| **404 / error boundary** | `display-1` scramble cycling `NOT FOUND` / `NO SUCH DEAL`, one link home. Reuse the CTA component. |

---

## 8. Responsive matrix

| Screen | <768px | 768–1023 | ≥1024 |
|---|---|---|---|
| Cockpit | Single column; money bar full-width; cards stacked; console + chat become tabs | 2-col cards | 3-col cards, console/chat side by side |
| Evidence | Stacked artifact blocks | 2-col artifacts | Table rows |
| Verification | Clause **cards**, never a table | Table, horizontal scroll in wrapper | Full table |
| Review queue | Queue list → tap opens full-screen detail | List left, detail below | List left 380px, detail right |
| Provenance | `.meta` stacked; Merkle path vertical | 2-col | 2-col + sticky seal |
| Reputation | 1-col stats | 2-col | 2-col + factors right |

Verify every screen at **375 / 768 / 1440**, in **both themes**, in **English and Hindi**, with
**animations on and off**. That is 24 combinations per screen; spot-check the cockpit and the
verification result exhaustively and the rest at 375 dark EN.
