"use client";

/**
 * The landing page (ui/02 §3-§6, reference frames A4 / B2 / B3 / B4 / C1 / D4).
 *
 * Six numbered compositions, not six website sections. Every one opens with the
 * same fixed gesture -- rule draws, index labels rise, headline words flip in,
 * paragraph blurs up, content drops in -- which is what makes the page read as
 * composed rather than assembled (ui/02 §6).
 *
 * The earlier version of this file had a hero and two card grids. Cards are the
 * one structure none of the four references contains: they are all built from
 * hairline rules, columns of micro-labels, and display type large enough to run
 * off the edge of the frame. That is what this is now.
 *
 * Every figure below is fetched. `FALSE RELEASES 0` reads from
 * `/health/eval-summary`, which serves the JSON `make eval` wrote; if that file
 * is absent the stat is omitted rather than filled in.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { motion, useScroll, useTransform } from "motion/react";

import { Boot, hasBooted } from "@/components/domain/Boot";
import { useSession } from "@/components/domain/AppProviders";
import { Shell } from "@/components/domain/Shell";
import {
  HeadlineChip,
  MicroGrid,
  ProofStrip,
  ScrollType,
  SectionOpener,
  type MicroRow,
} from "@/components/ui/editorial";
import { InvertOnHover } from "@/components/ui/InvertOnHover";
import { BlurLines, FlipHeadline, Lattice, Reveal, SlatBackdrop } from "@/components/ui/Reveal";
import { ScrambleText } from "@/components/ui/ScrambleText";
import { Button, Capsule, CountUp } from "@/components/ui/primitives";
import { chipPop, D, E, pick, stagger, ST } from "@/design/motion";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { dateOnly, inr, num, pct } from "@/lib/format";
import { usePeerHover } from "@/hooks/usePeerHover";
import { useI18n } from "@/lib/i18n";

export default function LandingPage() {
  const { t, list, locale } = useI18n();
  const { status } = useSession();
  const reduced = useReducedMotion();
  const [booting, setBooting] = useState<boolean | null>(null);
  // The closing section is its own peer group: the scrambling line and the two
  // lines of metadata around it.  The line cannot carry the inverting disc --
  // `InvertOnHover` renders its children twice, and a second `ScrambleText`
  // would be scrambling to its own clock, so the glyphs inside the disc would
  // not match the ones under it.
  const ctaPeers = usePeerHover();

  const hero = useRef<HTMLElement>(null);
  // ui/02 §5: the hero stays pinned while the next section slides over it, and
  // its content fades and settles back as it is occluded. Framer's useScroll is
  // a passive observer, which is the one scroll-linked mechanism the pack
  // permits. `offset` is measured against the hero's own height, so 0.6 is 60vh
  // of a 100svh hero regardless of the viewport.
  const { scrollYProgress } = useScroll({
    target: hero,
    offset: ["start start", "end start"],
  });
  const heroOpacity = useTransform(scrollYProgress, [0, 0.6], [1, 0.35]);
  const heroScale = useTransform(scrollYProgress, [0, 0.6], [1, 0.97]);
  // Each layer leaves at its own rate. One block dimming reads as a fade; three
  // layers separating reads as depth, which is the whole point of the pin.
  const titleY = useTransform(scrollYProgress, [0, 1], ["0%", "-18%"]);
  const titleTrack = useTransform(scrollYProgress, [0, 1], ["-0.03em", "-0.055em"]);
  const ledeY = useTransform(scrollYProgress, [0, 1], ["0%", "-46%"]);
  const ledeOpacity = useTransform(scrollYProgress, [0, 0.45], [1, 0]);
  const statsY = useTransform(scrollYProgress, [0, 1], ["0%", "-8%"]);
  const backdropY = useTransform(scrollYProgress, [0, 1], ["0%", "12%"]);
  const backdropScale = useTransform(scrollYProgress, [0, 1], [1, 1.08]);

  useEffect(() => {
    setBooting(!hasBooted());
  }, []);

  const evals = useAsync(() => api.evalSummary(), []);
  const demo = useAsync(
    () => (status === "signed-in" ? api.demoDeal() : Promise.resolve(null)),
    [status],
  );

  const headline = evals.status === "ready" && evals.data.available ? evals.data.headline : null;
  const money = demo.status === "ready" && demo.data ? demo.data.money : null;

  if (booting) return <Boot onDone={() => setBooting(false)} />;

  // ── 01 / 06 · the thesis ─────────────────────────────────────────────────
  const heroLines = [
    [
      { text: t("hero.line1a"), tone: "solid" as const },
      { text: t("hero.line1b"), tone: "muted" as const },
    ],
    [
      { text: t("hero.line2a"), tone: "solid" as const },
      { text: t("hero.line2b"), tone: "solid" as const },
    ],
  ];

  // The labels are always rendered and the values fill in when the fetch
  // resolves, so the row reserves its space and the hero never jumps
  // (ui/03 §7: layout must not shift between loading, empty and ready).
  const pending = <span className="stat-v stat-v--pending">&mdash;</span>;
  const stats: { key: string; label: string; value: React.ReactNode }[] = money
    ? [
        {
          key: "held",
          label: t("hero.held"),
          value: <CountUp value={money.held_paise} format={inr} className="stat-v" />,
        },
        {
          key: "released",
          label: t("hero.released"),
          value: <CountUp value={money.released_paise} format={inr} className="stat-v" />,
        },
      ]
    : [
        {
          key: "bundles",
          label: t("hero.labelledBundles"),
          value: headline ? (
            <CountUp value={headline.labelled_bundles} format={num} className="stat-v" />
          ) : (
            pending
          ),
        },
        {
          key: "escalation",
          label: t("hero.escalationRate"),
          value: headline ? (
            <span className="stat-v">{pct(headline.escalation_rate, 0)}</span>
          ) : (
            pending
          ),
        },
      ];
  stats.push({
    key: "false",
    label: t("hero.falseReleases"),
    value: headline ? (
      <span className="stat-v" style={{ color: "var(--sig-pass)" }}>
        {num(headline.false_releases)}
      </span>
    ) : (
      pending
    ),
  });

  // ── 04 / 06 · the invariants, as reference B4's dense grid ───────────────
  const invariants: MicroRow[] = (
    [
      ["I1", "ATTESTATION", "no rupee moves without one", "pass"],
      ["I2", "IMPORT LINT", "agents cannot reach settlement", "pass"],
      ["I3", "THRESHOLDS", "0.85 release · 0.35 reject · no bypass", "pass"],
      ["I4", "CONSERVATION", "held + released + refunded = funded", "pass"],
      ["I5", "HASH CHAIN", "append-only, enforced by trigger", "pass"],
      ["I6", "IDEMPOTENCY", "20 attempts · 1 payout · 1 rail call", "pass"],
      ["I7", "ON-CHAIN DATA", "hashes, ids, integers, enums only", "pass"],
      ["I8", "ADVISORY ARBITER", "settlement blocked until a human decides", "unverified"],
      ["I9", "TYPED ERRORS", "never a bare 500", "pass"],
      ["I10", "STATE MACHINES", "unknown pair raises", "pass"],
      ["I11", "NO SECRETS", "scanned in CI, masked in logs", "pass"],
      ["I12", "TENANT ISOLATION", "404, never 403", "pass"],
      ["I13", "NO DUAL-WRITE", "transactional outbox + relay", "pass"],
    ] as const
  ).map(([name, kind, detail, tone]) => ({
    name,
    kind,
    detail,
    tone: tone as MicroRow["tone"],
  }));

  // ── 03 / 06 · what the chain does and does not hold ──────────────────────
  const chainRows: MicroRow[] = (
    [
      ["TERMS HASH", "ON CHAIN", "so neither side can edit the rulebook", "pass"],
      ["ATTESTATION HASH", "ON CHAIN", "so a decision can be re-checked", "pass"],
      ["MILESTONE SEQ", "ON CHAIN", "an integer, nothing more", "pass"],
      ["RUPEES", "NEVER", "they move on Razorpay, start to finish", "fail"],
      ["INVOICES", "NEVER", "bytes stay in tenant-scoped storage", "fail"],
      ["NAMES · EMAILS", "NEVER", "no personal data leaves the database", "fail"],
      ["CHAT MESSAGES", "NEVER", "deal-scoped, and never evidence", "fail"],
      ["A TOKEN", "DOES NOT EXIST", "no coin, no staking, nothing to buy", "fail"],
    ] as const
  ).map(([name, kind, detail, tone]) => ({
    name,
    kind,
    detail,
    tone: tone as MicroRow["tone"],
  }));

  return (
    <Shell>
      {/* ── 01 / 06 ─────────────────────────────────────────────────────── */}
      <section className="hero" ref={hero}>
        <SlatBackdrop columns={12} />
        <motion.div
          className="hero-backdrop"
          style={reduced ? undefined : { y: backdropY, scale: backdropScale }}
        >
          <Lattice />
        </motion.div>

        <motion.div
          className="hero-body"
          style={reduced ? undefined : { opacity: heroOpacity, scale: heroScale }}
        >
          <Reveal variant="blurUp">
            <div className="corner-meta">
              <span className="nano">01 / 06</span>
              <span className="nano">{t("hero.chainLabel")}</span>
            </div>
          </Reveal>

          <motion.div
            style={reduced ? undefined : { y: titleY, letterSpacing: titleTrack }}
          >
            {/* The pointer carries a disc that inverts the type it crosses. */}
            <InvertOnHover>
              <FlipHeadline lines={heroLines} interactive />
            </InvertOnHover>
          </motion.div>

          <motion.div style={reduced ? undefined : { y: ledeY, opacity: ledeOpacity }}>
            <BlurLines>{t("hero.sub")}</BlurLines>
          </motion.div>

          <div className="row hero-cta">
            {[
              {
                href: status === "signed-in" ? "/deals" : "/login",
                label: t("hero.openDeal"),
                primary: true,
              },
              { href: "#why-chain", label: t("hero.seeProof"), primary: false },
            ].map((cta, index) => (
              <motion.span
                key={cta.href}
                custom={index}
                variants={pick(chipPop, reduced)}
                initial="hidden"
                animate="show"
              >
                <Link href={cta.href} data-cursor="">
                  <Button variant={cta.primary ? "primary" : "ghost"} cursorLabel={cta.label}>
                    {cta.label}
                  </Button>
                </Link>
              </motion.span>
            ))}
            {evals.status === "ready" && evals.data.available && evals.data.all_green ? (
              <motion.span
                custom={2}
                variants={pick(chipPop, reduced)}
                initial="hidden"
                animate="show"
              >
                <Capsule dotTone="pass">{t("hero.evalGreen")}</Capsule>
              </motion.span>
            ) : null}
          </div>

          {/* A rule that fades looks like a mistake; it draws. Then the stats
              drop in, then each figure counts up (ui/02 §4, t=900ms). */}
          <motion.hr
            className="rule hero-rule"
            initial={reduced ? { opacity: 0 } : { scaleX: 0 }}
            animate={reduced ? { opacity: 1 } : { scaleX: 1 }}
            transition={
              reduced
                ? { duration: D.fast }
                : {
                    duration: D.slow,
                    ease: E.expo as [number, number, number, number],
                    delay: reduced ? 0 : 0.9,
                  }
            }
            style={{ transformOrigin: "0% 50%" }}
          />

          <motion.dl className="hero-stats" style={reduced ? undefined : { y: statsY }}>
            {stats.map((stat, index) => (
              <motion.div
                key={stat.key}
                initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: reduced ? D.fast : D.base,
                  ease: E.enter as [number, number, number, number],
                  delay: reduced ? 0 : 1 + stagger(index, ST.base),
                }}
              >
                <dt className="stat-k micro">{stat.label}</dt>
                <dd>{stat.value}</dd>
              </motion.div>
            ))}
          </motion.dl>

          {evals.status === "ready" && evals.data.available ? (
            <span className="nano hero-measured">
              {t("hero.measuredOn", {
                date: dateOnly(evals.data.generated_at ?? new Date().toISOString(), locale),
              })}
              {evals.data.provider && !evals.data.provider.is_live_model
                ? ` · ${t("hero.fixtureProvider")}`
                : ""}
            </span>
          ) : (
            <span className="nano hero-measured">{t("hero.noEvalYet")}</span>
          )}
        </motion.div>
      </section>

      {/* ── 02 / 06 · the one thing the product is about ─────────────────── */}
      <section className="section next-section" id="unverifiable">
        <SectionOpener
          index={2}
          label={t("section.verifier")}
          lines={[
            [
              { text: t("section.v1a"), tone: "solid" },
              { text: t("section.v1b"), tone: "muted" },
              { text: t("section.v1c"), tone: "muted" },
            ],
            [{ text: t("section.v2"), tone: "solid" }],
          ]}
          lede={t("section.verifierLede")}
        />

        {/* Full width of the frame, moving with the scroll rather than on a
            loop, and readable whole at every scroll position. The travel and
            the type size are solved together in `ScrollType`, so the size is
            not overridden here. */}
        <ScrollType tone="outline">UNVERIFIABLE</ScrollType>

        <Reveal>
          <blockquote className="pullquote">
            <span className="nano">{t("section.quoteLabel")}</span>
            <p>{t("section.quote")}</p>
            <span className="nano">{t("section.quoteAttr")}</span>
          </blockquote>
        </Reveal>
      </section>

      {/* ── 03 / 06 · why a chain at all ─────────────────────────────────── */}
      <section className="section next-section" id="why-chain">
        <SectionOpener
          index={3}
          label={t("hero.whyChainLabel")}
          lines={[
            [
              { text: t("section.c1a"), tone: "muted" },
              { text: t("section.c1b"), tone: "solid" },
            ],
            [
              { text: t("section.c2a"), tone: "muted" },
              { text: t("section.c2b"), tone: "solid" },
            ],
          ]}
          lede={t("hero.whyChain")}
        />
        <MicroGrid
          rows={chainRows}
          columns={[t("section.colWhat"), t("section.colWhere"), t("section.colWhy")]}
        />
      </section>

      {/* ── 04 / 06 · the invariants ─────────────────────────────────────── */}
      <section className="section next-section" id="invariants">
        <SectionOpener
          index={4}
          label={t("section.invariantsLabel")}
          lines={[
            [
              { text: t("section.i1a"), tone: "solid" },
              { text: t("section.i1b"), tone: "muted" },
            ],
            [
              { text: t("section.i2a"), tone: "muted" },
              { text: t("section.i2b"), tone: "solid" },
            ],
          ]}
          lede={t("section.invariantsLede")}
        />
        <MicroGrid
          rows={invariants}
          columns={[t("section.colId"), t("section.colInvariant"), t("section.colProof")]}
        />
      </section>

      {/* ── 05 / 06 · the measured result ───────────────────────────────── */}
      <section className="section next-section" id="evidence">
        <SectionOpener
          index={5}
          label={t("section.measuredLabel")}
          lines={[
            [
              { text: t("section.m1a"), tone: "solid" },
              { text: t("section.m1b"), tone: "solid" },
            ],
          ]}
          lede={t("section.measuredLede")}
          chip={
            headline ? (
              <HeadlineChip
                value={`${num(headline.labelled_bundles)} ${t("section.chipBundles")}`}
                tone="pass"
                label={t("section.chipLabel")}
              />
            ) : undefined
          }
        />

        {headline ? (
          <ProofStrip
            cells={[
              { key: "accuracy", label: t("section.accuracy"), text: pct(headline.accuracy, 0) },
              {
                key: "brier",
                label: t("section.brier"),
                text: headline.brier_score.toFixed(4),
              },
              {
                key: "prechecks",
                label: t("section.prechecks"),
                text: pct(headline.resolved_by_prechecks_pct, 1),
              },
              {
                key: "adversarial",
                label: t("section.adversarial"),
                text: num(headline.adversarial_bundles),
              },
              {
                key: "auc",
                label: t("section.auc"),
                text: headline.risk_test_auc.toFixed(4),
              },
              {
                key: "cost",
                label: t("section.cost"),
                text: `₹${headline.cost_inr_per_verification_projected.toFixed(2)}`,
              },
            ]}
          />
        ) : null}

        <Reveal index={1}>
          <p className="prose proof-note">{t("section.measuredNote")}</p>
        </Reveal>
      </section>

      {/* ── 06 / 06 · the closing scramble (reference C1) ────────────────── */}
      <section className="section next-section cta" id="start" {...ctaPeers.group}>
        <div className="corner-meta cta-corner">
          <span className="nano">06 / 06</span>
          <span className="nano">{t("cta.label")}</span>
        </div>

        <p className="micro cta-meta" {...ctaPeers.peer("label")}>
          {t("cta.label")}
        </p>
        <div className="cta-line" {...ctaPeers.peer("line")}>
          <ScrambleText phrases={list("cta.phrases")} />
        </div>
        <Link href={status === "signed-in" ? "/deals" : "/register"} data-cursor="">
          <Button cursorLabel={t("cta.start")}>{t("cta.start")}</Button>
        </Link>
        <span className="nano cta-meta" {...ctaPeers.peer("footnote")}>
          {t("cta.footnote")}
        </span>
      </section>
    </Shell>
  );
}
