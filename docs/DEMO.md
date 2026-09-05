<div align="center">

# The demo

**Six minutes, one deal, every branch that matters.**

Every number below is from the recorded `make demo` run and is reproduced in
[`backend/evals/out/demo.json`](../backend/evals/out/demo.json).

<p>
<img alt="Runtime" src="https://img.shields.io/badge/runtime-6_MINUTES-4FD1A5?style=for-the-badge&labelColor=0D0D10">
<img alt="Escrow" src="https://img.shields.io/badge/escrow-INR_420,000.00-C6C0B4?style=for-the-badge&labelColor=0D0D10">
<img alt="Ledger" src="https://img.shields.io/badge/ledger-37_EVENTS_%C2%B7_VERIFY_OK-4FD1A5?style=for-the-badge&labelColor=0D0D10">
</p>

<p>
<img alt="Milestone 1" src="https://img.shields.io/badge/M01-RELEASE_@_0.879-4FD1A5?style=flat-square&labelColor=0D0D10">
<img alt="Milestone 2" src="https://img.shields.io/badge/M02-ESCALATE_@_0.197-FFC24B?style=flat-square&labelColor=0D0D10">
<img alt="Milestone 3" src="https://img.shields.io/badge/M03-RELEASE_@_0.865,_then_DISPUTED-FF4A4A?style=flat-square&labelColor=0D0D10">
<img alt="Rail" src="https://img.shields.io/badge/rail-SIMULATED-FFC24B?style=flat-square&labelColor=0D0D10">
<img alt="Chain" src="https://img.shields.io/badge/anchors-10_QUEUED_%C2%B7_0_CONFIRMED-FFC24B?style=flat-square&labelColor=0D0D10">
</p>

<p>
  <a href="../README.md">Overview</a>
  &nbsp;·&nbsp; <a href="README.md">Docs</a>
  &nbsp;·&nbsp; <a href="ARCHITECTURE.md">Architecture</a>
  &nbsp;·&nbsp; <a href="API.md">API</a>
  &nbsp;·&nbsp; <a href="DATA.md">Data</a>
  &nbsp;·&nbsp; <a href="SECURITY.md">Security</a>
  &nbsp;·&nbsp; <a href="OPERATIONS.md">Operations</a>
  &nbsp;·&nbsp; <b>Demo</b>
  &nbsp;·&nbsp; <a href="UI_MOTION.md">UI &amp; Motion</a>
  &nbsp;·&nbsp; <a href="DECISIONS.md">Decisions</a>
  &nbsp;·&nbsp; <a href="LIMITATIONS.md">Limitations</a>
</p>

</div>

<samp>

[Minute 0 — landing](#minute-0--the-landing-page) &nbsp;·&nbsp;
[Minute 1 — cockpit](#minute-1--the-cockpit) &nbsp;·&nbsp;
[Minute 2 — release](#minute-2--milestone-01-releases-automatically) &nbsp;·&nbsp;
[**Minute 3 — escalate**](#minute-3--milestone-02-escalates-and-this-is-the-whole-product) &nbsp;·&nbsp;
[Minute 4 — dispute](#minute-4--milestone-03-a-dispute-and-an-advisory-arbiter) &nbsp;·&nbsp;
[Minute 5 — break it](#minute-5--it-reconciles-and-you-can-break-it) &nbsp;·&nbsp;
[One more minute](#if-you-have-one-more-minute)

</samp>

```bash
make up && make seed && make demo       # or `make demo-reset` to start the deal over
```

Then open <http://localhost:3000> and sign in with **Continue as the demo buyer**.

> [!IMPORTANT]
> The login screen's demo buttons post to `POST /api/v1/dev/assume`, which runs the seeded user's
> real email and password through the ordinary login path and sets the same httpOnly cookies. There
> is no `?as=` parameter anywhere, and with `DEMO_MODE=false` the route is **not registered at all**.
>
> Say this out loud when you demo it — it is the difference between a demo affordance and a back
> door.

---

## The deal

**Meridian Apparel** (Bengaluru) is buying 2,500 cotton twill shirts, code `CT-240-IVY`, from
**Tirupur Knitworks** (Tiruppur). Neither has traded with the other before. **INR 420,000.00** in
three milestones.

| # | milestone | amount | outcome in the recorded run |
|:--|:--|--:|:--|
| `01` | Fabric procured | INR 126,000.00 | <img alt="" src="https://img.shields.io/badge/RELEASE-4FD1A5?style=flat-square&labelColor=0D0D10"> auto, at confidence 0.879 |
| `02` | Production complete | INR 168,000.00 | <img alt="" src="https://img.shields.io/badge/ESCALATE-FFC24B?style=flat-square&labelColor=0D0D10"> then approved by a human |
| `03` | Delivered &amp; accepted | INR 126,000.00 | <img alt="" src="https://img.shields.io/badge/DISPUTED-FF4A4A?style=flat-square&labelColor=0D0D10"> then settled as a split |

---

## Minute 0 — the landing page

<http://localhost:3000>

The boot sequence is not a vanity loader: each of its four nodes is a real dependency from
`GET /api/v1/health/ready`. It fills as each becomes ready, turns amber on a degraded optional
dependency, and **halts red on Postgres** rather than booting into a broken app. It runs once per
session.

The hero's `FALSE RELEASES 0` is read from `GET /api/v1/health/eval-summary`, which serves the JSON
`make eval` wrote.

> [!NOTE]
> **If that file does not exist, the stat is omitted** rather than filled in. A landing page that
> invents its own headline number is the exact failure this product is arguing against.

Scroll once: *"The money never touches the chain."* That is the honest caveat, placed second rather
than buried.

---

## Minute 1 — the cockpit

`/deals/{id}`

**Point at the money bar first.** Three flex segments in one fixed-width track. On settlement the
segments animate `flexGrow` through Framer's `layout`, so the total width never changes and
`released + held + refunded = funded` is *visibly* conserved.

> [!TIP]
> The tick is computed client-side from the actual numbers; if it were ever false the line would turn
> red and show a cross. **That should be impossible — showing it anyway is how I4 is meant
> seriously.**

Also on this screen:

* **risk 0.0083 → `TIER_1`**, 0.8% fee, 0 hold days, 30% buyer prefund. Click through to
  `/deals/{id}/risk` for the three factors that moved it, in plain language:

  | factor | reason |
  |--:|:--|
  | `-1.183` | on-time rate 91% across their deals |
  | `-0.963` | 92% of clauses are machine-checkable |
  | `-0.647` | counterparty of 1.5 years standing |

* the **agent console** — a monospace log fed by the deal's hash-chained ledger and the live SSE
  stream. Every line corresponds to a row in `ledger_events`; **nothing is invented client-side**.
* **messages**, with the footnote *"Deal-scoped. Never used as evidence."* — which is literally true:
  chat is not hashed into any bundle.

**Further reading** &nbsp;
[Where the tiers come from — Data §4](DATA.md#4-counterparties) &nbsp;·&nbsp;
[The money invariant on the wire — API §1](API.md#1-conventions)

---

## Minute 2 — milestone 01 releases automatically

`/deals/{id}/milestones/{id}/evidence` → **Run verification**

Measured: pre-checks **8/8**, **3 model calls**, decision **RELEASE @ confidence 0.879**.

Open the verification screen and stay on it. Three things to point at:

1. **The clause table is in source order**, not sorted by severity. The machine's honesty is the
   point, not a tidy list.
2. **The confidence breakdown**, which is not optional. Four bars and the arithmetic:

   ```
   0.45·verifiable_fraction + 0.45·llm_component + 0.10·extraction_quality
        − 0.50·(unverifiable_required / total_required)
   ```

   then calibrated. **We do not use the model's self-reported confidence for anything.**
3. **The seal** — a circle draws clockwise, the sigil scales with an overshoot, and the truncated
   transaction hash types in beneath. One-shot; it never replays on re-render.

Then the money: **INR 126,000.00** released, rail reference `sim_rel_a21033dd5d2554eb6936`, labelled
`SIMULATED` because no Razorpay key is configured. Held drops to INR 294,000.00, the bar re-flows,
and the sum line still ticks.

**Further reading** &nbsp;
[Why confidence is computed, not asked for — ADR-003](DECISIONS.md#adr-003--confidence-is-computed-in-python-then-calibrated-on-a-separate-corpus) &nbsp;·&nbsp;
[The full request path — Architecture §2](ARCHITECTURE.md#2-request-path-end-to-end)

---

## Minute 3 — milestone 02 escalates, and this is the whole product

<img alt="" src="https://img.shields.io/badge/this_is_the_minute-THAT_MATTERS-FFC24B?style=flat-square&labelColor=0D0D10">

The seller submits **four photographs** as evidence of 500 completed units.

Measured: **ESCALATE @ confidence 0.197.** Clause `c2` came back `UNVERIFIABLE` with this note:

> *4 photograph(s) cannot establish a count of 500; nothing in the pixels evidences a total, and
> nothing contradicts it either.*

**No money moved.** Held stays at INR 294,000.00.

Look at the `UNVERIFIABLE` chip. It resolves — and then keeps disturbing one random character,
forever. It is the only element in the product that never comes to rest, and it is the only one that
should not:

> [!IMPORTANT]
> A static amber badge says *"warning"*. A label that cannot hold still says *the machine is still
> not sure*, which is the literal truth of the state. Under reduced motion the jitter stops entirely
> and the chip keeps a static `?` and a dashed border — same message, no motion.

Then `/review`. The queue leads with **WHAT THE AGENT COULD NOT VERIFY**, because that is the only
reason the row is there, and a reviewer who has to hunt for it starts rubber-stamping. The reason
field is mandatory and the button says **signs as you**.

Measured: the reviewer **APPROVED** with a written reason → **INR 168,000.00** released. Held drops
to INR 126,000.00.

**Further reading** &nbsp;
[Why it escalates and never rejects — ADR-004](DECISIONS.md#adr-004--a-required-unverifiable-clause-escalates-it-never-rejects) &nbsp;·&nbsp;
[The chip that never settles — UI &amp; Motion §4](UI_MOTION.md#the-one-thing-that-never-comes-to-rest) &nbsp;·&nbsp;
[The category this bundle belongs to — Data §3](DATA.md#3-the-150-evaluation-bundles)

---

## Minute 4 — milestone 03, a dispute, and an advisory arbiter

Milestone 03 verified **RELEASE @ 0.865**. Before the payout ran, the buyer **raised a dispute** over
60 units.

Measured, from the transcript: the settlement worker **refused the pending authorization** with
reason `MILESTONE_DISPUTED`. Held stays at INR 126,000.00.

> [!NOTE]
> This is **I8 doing its job at runtime** — the authorization existed and was still not consumed. A
> guarantee that only holds when nothing is in flight is not a guarantee.

The arbiter then produced an **advisory** recommendation: `PARTIAL` @ 0.74 — release INR 115,920.00,
refund INR 10,080.00 — with its arithmetic shown:

> The tolerance clause allows a 20% deduction per affected unit at a unit price of 84,000 paise:
> 60 × 84,000 × 20% = 1,008,000 paise.

and **two open questions it could not answer**:

> * Was an independent count or inspection sheet issued for the affected units?
> * Do the photographs on record cover the units the buyer identifies?

The open questions get as much room as the reasoning. An arbiter that admits what it does not know is
more useful than one that does not, and hiding that list behind a disclosure would be a way of
quietly not showing it.

The human approved the split. Measured `override_delta 0` — the reviewer agreed, and **the delta is
recorded either way**.

---

## Minute 5 — it reconciles, and you can break it

Final money, measured:

```
funded    INR 420,000.00
released  INR 409,920.00
refunded  INR  10,080.00
held      INR       0.00
balanced  true
```

Deal state `COMPLETED`. Ledger: **37 events**, `verify ok`, head `f0988563d52c71de…`.

> [!NOTE]
> This head changed from the figure quoted before the security pass. The Merkle leaf and node
> hashes are now domain-separated ([Architecture §4](ARCHITECTURE.md#4-evidence-and-provenance)),
> which changes every evidence root, and therefore every attestation hash the ledger chains over.
> **Every other figure in this document is unchanged** — the confidences, the decisions, the rail
> references, the money and the event count are all independent of that formula, and all of them
> still match `demo.json` exactly.

### The provenance screen — `/provenance/{attestationId}`

**"For this rupee."** One page that answers the audit question end to end: which model decided, on
which prompt hash, over which evidence Merkle root, signed by which key, approved by which human,
paid on which rail reference, anchored in which transaction.

`signature verifies` is rendered from `signature_verified`, which the backend computes by
**recovering the signer address from the canonical hash** — not by comparing a stored string.

> [!CAUTION]
> **Now break it.** Press **Tamper one byte**. The browser downloads the artifact through its
> short-lived presigned link, flips exactly one bit of one byte **in its own copy**, hashes it
> locally, and asks `POST /api/v1/provenance/tamper-check` to hash the same bytes. The digests
> differ, the row shakes once, and the mismatched digest is underlined in red — the only place in the
> product where red means *stop*.
>
> **Nothing on the server changed.** Press **Check the bytes** to see it pass again.

Then scroll to the ledger panel and press **Verify ledger**: the chain re-links, and the balances
below it are **replayed from the events alone**, not read from the deal row. A chain that links but
replays to a different total is still a broken ledger.

### The chain

Measured: **10 anchors queued, 0 confirmed**, reason
`CONTRACT_ADDRESS / OPERATOR_PRIVATE_KEY not configured`.

Say this plainly. No transaction hash is shown, because none exists. Suite C check 5 verifies that
every queued anchor payload carries exactly the local attestation's canonical hash, so the moment a
contract address is configured the anchors published are the right ones.
[`make deploy-contract`](OPERATIONS.md#the-contract) and re-run to verify the on-chain half.

**Further reading** &nbsp;
[The Merkle tree and the ledger — Architecture §4](ARCHITECTURE.md#4-evidence-and-provenance) &nbsp;·&nbsp;
[Why no contract is deployed — Limitations §3](LIMITATIONS.md#3-no-contract-is-deployed)

---

## If you have one more minute

| show | why it lands |
|:--|:--|
| `/ledger` | `OUTBOX BACKLOG 0` and `DLQ DEPTH 0`. Two numbers that say the transactional outbox is keeping up (I13), on a screen rather than in a terminal. |
| `/entities/{id}` | The counterparty passport, and the pricing tier with the three facts that produced it. **A tier without an explanation is a fee dressed up as a policy.** |
| Language toggle → **हि** | Not a machine translation. The Hindi hero is a *shorter* headline, because Devanagari words are longer and a literal translation turns a two-line hero into four. Display line-heights open up and letter-spacing is scoped to Latin only. |
| Settings → **Animation: Off** | Every entrance collapses to a crossfade, the `UNVERIFIABLE` jitter stops, the money bar stops animating and shows the final figures immediately. It writes through the same hook as the OS preference, so **the two cannot diverge**. |
| Resize to 375px | The verification screen becomes cards. It is the screen a judge will open on a phone, and it must not scroll sideways. |

**Further reading** &nbsp;
[The whole design and motion system](UI_MOTION.md) &nbsp;·&nbsp;
[The three numbers on `/ledger` — Operations §4](OPERATIONS.md#4-observability)

---

## Reproducing the transcript

```bash
cd backend && uv run python -m scripts.demo --json > /tmp/demo.json
```

Every figure quoted above appears in that file. `make demo-reset` returns the deal to `DRAFT` and
runs it again from the beginning.

---

<div align="center">

<sub><b>Aegis</b> · programmable escrow for agentic commerce</sub>

<p>
  <a href="OPERATIONS.md">&larr; Operations</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="README.md">Docs index</a>
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <a href="UI_MOTION.md">UI &amp; Motion &rarr;</a>
</p>

<sub>
<a href="../README.md">Overview</a> ·
<a href="ARCHITECTURE.md">Architecture</a> ·
<a href="API.md">API</a> ·
<a href="DATA.md">Data</a> ·
<a href="SECURITY.md">Security</a> ·
<a href="OPERATIONS.md">Operations</a> ·
<a href="UI_MOTION.md">UI &amp; Motion</a> ·
<a href="DECISIONS.md">Decisions</a> ·
<a href="LIMITATIONS.md">Limitations</a>
</sub>

</div>
