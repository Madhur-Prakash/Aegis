<div align="center">

# Aegis documentation

**Every rupee has a provable reason.**

Nine documents. One rule they all obey: if a number appears here, something in this repository
produced it, and the command that produced it is named.

<p>
<a href="../README.md"><img alt="Overview" src="https://img.shields.io/badge/start-Overview-4FD1A5?style=for-the-badge&labelColor=0D0D10"></a>
<img alt="Documents" src="https://img.shields.io/badge/documents-9-C6C0B4?style=for-the-badge&labelColor=0D0D10">
<img alt="Invariants" src="https://img.shields.io/badge/invariants-13-4FD1A5?style=for-the-badge&labelColor=0D0D10">
<img alt="ADRs" src="https://img.shields.io/badge/ADRs-12-C6C0B4?style=for-the-badge&labelColor=0D0D10">
<a href="../backend/evals/out/RESULTS.md"><img alt="Source of numbers" src="https://img.shields.io/badge/numbers_from-make_eval-4FD1A5?style=for-the-badge&labelColor=0D0D10"></a>
</p>

<p>
  <a href="../README.md">Overview</a>
  &nbsp;·&nbsp; <b>Docs</b>
  &nbsp;·&nbsp; <a href="ARCHITECTURE.md">Architecture</a>
  &nbsp;·&nbsp; <a href="API.md">API</a>
  &nbsp;·&nbsp; <a href="DATA.md">Data</a>
  &nbsp;·&nbsp; <a href="SECURITY.md">Security</a>
  &nbsp;·&nbsp; <a href="OPERATIONS.md">Operations</a>
  &nbsp;·&nbsp; <a href="DEMO.md">Demo</a>
  &nbsp;·&nbsp; <a href="UI_MOTION.md">UI &amp; Motion</a>
  &nbsp;·&nbsp; <a href="DECISIONS.md">Decisions</a>
  &nbsp;·&nbsp; <a href="LIMITATIONS.md">Limitations</a>
</p>

</div>

---

## The library

<table>
<thead>
<tr><th align="left">Document</th><th align="left">What it answers</th><th align="left">Signal</th></tr>
</thead>
<tbody>

<tr>
<td valign="top"><a href="ARCHITECTURE.md"><b>Architecture</b></a></td>
<td valign="top">How the pieces fit, where the one boundary that matters is drawn, and what breaks when each dependency fails.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/I2_I5_I12_I13-4FD1A5?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/services-10-C6C0B4?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="API.md"><b>API</b></a></td>
<td valign="top">The envelope, the auth model, the full error taxonomy, the rate-limit buckets, and the conventions a generated schema cannot express.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/paths-75-C6C0B4?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/typed_errors-27-4FD1A5?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="DATA.md"><b>Data</b></a></td>
<td valign="top">Every corpus, every base rate marked <code>[sourced]</code> or <code>[assumed]</code>, and the published generative model behind the labels.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/deals-2000-C6C0B4?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/corpus-SYNTHETIC-FFC24B?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="SECURITY.md"><b>Security</b></a></td>
<td valign="top">Ten adversaries and what stops each one — then a section naming the thirteen things that are <i>not</i> built.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/adversaries-10-C6C0B4?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/named_gaps-13-FF4A4A?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="OPERATIONS.md"><b>Operations</b></a></td>
<td valign="top">Starting it, moving it onto real test credentials, the three numbers to watch, and a runbook for each way it goes wrong.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/start-one_command-4FD1A5?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/runbook-8_faults-C6C0B4?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="DEMO.md"><b>Demo</b></a></td>
<td valign="top">Six minutes, one deal, every branch that matters — with the URL to open and the sentence to say at each step.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/runtime-6_min-C6C0B4?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/ledger_events-37-4FD1A5?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="UI_MOTION.md"><b>UI &amp; Motion</b></a></td>
<td valign="top">Three semantic hues, nine motion moments, and the build steps that fail if a component reintroduces a literal.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/hues-3-C6C0B4?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/gates-2_in_build-4FD1A5?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="DECISIONS.md"><b>Decisions</b></a></td>
<td valign="top">Twelve ADRs, and — first on the page — the table of things deliberately <b>not</b> adopted.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/ADRs-12-C6C0B4?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/rejected-12-FFC24B?style=flat-square&labelColor=0D0D10"></td>
</tr>

<tr>
<td valign="top"><a href="LIMITATIONS.md"><b>Limitations</b></a></td>
<td valign="top">Everything simulated, missing, or not measured — including three defects this build found by running itself.</td>
<td valign="top" nowrap><img alt="" src="https://img.shields.io/badge/rail-SIMULATED-FFC24B?style=flat-square&labelColor=0D0D10"><br><img alt="" src="https://img.shields.io/badge/contract-NOT_DEPLOYED-FFC24B?style=flat-square&labelColor=0D0D10"></td>
</tr>

</tbody>
</table>

> [!TIP]
> Two generated documents sit outside this list and are never hand-edited:
> [`backend/evals/out/RESULTS.md`](../backend/evals/out/RESULTS.md) — every measured number — and
> [`docs/openapi.json`](openapi.json) — 75 paths, 82 operations, regenerated with `make docs`.

---

## Reading paths

Pick the one that matches why you are here.

<table>
<tr>

<td valign="top" width="33%">

<img alt="" src="https://img.shields.io/badge/path-REVIEWER-4FD1A5?style=flat-square&labelColor=0D0D10">

**Judging it in ten minutes**

1. [Overview — the invariants](../README.md#the-invariants)
2. [Overview — which numbers are real](../README.md#which-numbers-are-real)
3. [Demo](DEMO.md) — minute 3 is the product
4. [Limitations](LIMITATIONS.md)

Ends on what is *not* true. That is deliberate.

</td>

<td valign="top" width="33%">

<img alt="" src="https://img.shields.io/badge/path-ENGINEER-C6C0B4?style=flat-square&labelColor=0D0D10">

**Reading the code**

1. [Architecture §1 — the boundary](ARCHITECTURE.md#1-the-one-boundary-that-matters)
2. [Architecture §3 — the outbox](ARCHITECTURE.md#3-money-path-and-the-transactional-outbox-i13)
3. [API §3 — the error envelope](API.md#3-the-error-envelope-i9)
4. [Decisions](DECISIONS.md) — ADR-004, then ADR-005

</td>

<td valign="top" width="33%">

<img alt="" src="https://img.shields.io/badge/path-ADVERSARY-FF4A4A?style=flat-square&labelColor=0D0D10">

**Attacking it**

1. [Security §1 — threat model](SECURITY.md#1-threat-model)
2. [Security §3 — tenant isolation](SECURITY.md#3-authorization-and-tenant-isolation-i12)
3. [Security §8 — not built](SECURITY.md#8-not-built-and-named-as-such)
4. [Limitations §7 — defects found by running](LIMITATIONS.md#7-three-defects-this-build-found-by-running-itself)

</td>

</tr>
</table>

---

## Invariant index

Thirteen invariants, enforced in code **and** proven by a test. The
[Overview](../README.md#the-invariants) carries the full statement and the proof for each; this table
maps an invariant to the document that explains *why* it is shaped that way.

| # | Invariant, in one line | Explained in |
|:--|:--|:--|
| **I1** | No rupee moves without a qualifying attestation | [Architecture §2](ARCHITECTURE.md#2-request-path-end-to-end) |
| **I2** | LLM output never triggers a transfer | [Architecture §1](ARCHITECTURE.md#1-the-one-boundary-that-matters) · [Security §1](SECURITY.md#1-threat-model) |
| **I3** | Fixed thresholds; a required `UNVERIFIABLE` can never auto-release | [Decisions ADR-004](DECISIONS.md#adr-004--a-required-unverifiable-clause-escalates-it-never-rejects) |
| **I4** | `held + released + refunded == funded`, in integer paise | [API §1](API.md#1-conventions) · [Demo minute 1](DEMO.md#minute-1--the-cockpit) |
| **I5** | Every transition appends exactly one hash-chained ledger event | [Architecture §4](ARCHITECTURE.md#4-evidence-and-provenance) |
| **I6** | Every money operation is idempotent | [Decisions ADR-005](DECISIONS.md#adr-005--the-atomic-db-claim-not-the-redis-lock-is-the-idempotency-guarantee) |
| **I7** | On-chain data is hashes and integers only | [Security §6](SECURITY.md#6-signing-and-on-chain-data-i7) |
| **I8** | The arbiter is advisory; a human must decide | [Demo minute 4](DEMO.md#minute-4--milestone-03-a-dispute-and-an-advisory-arbiter) |
| **I9** | Expected failures return typed errors, never a bare 500 | [API §3](API.md#3-the-error-envelope-i9) |
| **I10** | State machines are explicit transition tables | [Architecture §2](ARCHITECTURE.md#2-request-path-end-to-end) |
| **I11** | No secrets committed; logs never carry them | [Security §4](SECURITY.md#4-secrets-and-logging-i11) |
| **I12** | Tenant isolation, enforced in the repository layer | [Security §3](SECURITY.md#3-authorization-and-tenant-isolation-i12) · [ADR-008](DECISIONS.md#adr-008--tenant-isolation-lives-in-the-repository-and-returns-404) |
| **I13** | No dual-write: state and event commit in one transaction | [Architecture §3](ARCHITECTURE.md#3-money-path-and-the-transactional-outbox-i13) |

---

## Where every number comes from

<img alt="" src="https://img.shields.io/badge/policy-NOTHING_TYPED_BY_HAND-4FD1A5?style=flat-square&labelColor=0D0D10">

| source | produces | regenerate with |
|:--|:--|:--|
| [`backend/evals/out/summary.json`](../backend/evals/out/summary.json) | Every headline figure in the Overview | `make eval` |
| [`backend/evals/out/RESULTS.md`](../backend/evals/out/RESULTS.md) | The full generated report | `make eval` |
| [`backend/evals/out/demo.json`](../backend/evals/out/demo.json) | Every figure in [Demo](DEMO.md) | `make demo` |
| [`data/generated/`](../data/generated) | The corpus described in [Data](DATA.md) | `make dataset` |
| [`docs/openapi.json`](openapi.json) | The 75 paths behind [API](API.md) | `make docs` |

> [!IMPORTANT]
> The recorded run used the **deterministic offline adapter** (`AI_PROVIDER=fixture`), because no
> model key was configured, and the **simulated payment rail**, because no Razorpay key was
> configured. Both are labelled per operation everywhere they appear, in the UI as well as in these
> documents. Start at [Limitations](LIMITATIONS.md) if that is the part you care about.

---

<div align="center">

<sub><b>Aegis</b> · programmable escrow for agentic commerce</sub>

<sub>
<a href="../README.md">Overview</a> ·
<a href="ARCHITECTURE.md">Architecture</a> ·
<a href="API.md">API</a> ·
<a href="DATA.md">Data</a> ·
<a href="SECURITY.md">Security</a> ·
<a href="OPERATIONS.md">Operations</a> ·
<a href="DEMO.md">Demo</a> ·
<a href="UI_MOTION.md">UI &amp; Motion</a> ·
<a href="DECISIONS.md">Decisions</a> ·
<a href="LIMITATIONS.md">Limitations</a>
</sub>

</div>
