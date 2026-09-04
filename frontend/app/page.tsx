"use client";

/**
 * The landing page (ui/02).
 *
 * Boot -> hero -> why-chain -> closing CTA.  Three sections, no more: the pitch
 * is one claim, one honest caveat about what the chain is for, and one door.
 *
 * Every figure in the hero is fetched.  `FALSE RELEASES` reads from
 * `/health/eval-summary`, which serves the JSON written by `make eval`; if that
 * file does not exist the stat is omitted rather than filled in with a number
 * nobody measured.  `HELD` and `RELEASED` come from the seeded deal's actual
 * balances once there is a session to read them with.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Boot, hasBooted } from "@/components/domain/Boot";
import { useSession } from "@/components/domain/AppProviders";
import { Shell } from "@/components/domain/Shell";
import { BlurLines, FlipHeadline, Lattice, Reveal, Rule, SlatBackdrop } from "@/components/ui/Reveal";
import { ScrambleText } from "@/components/ui/ScrambleText";
import { Button, CountUp, Capsule } from "@/components/ui/primitives";
import { CornerMeta } from "@/components/ui/StateChip";
import { useAsync } from "@/hooks/useAsync";
import { api } from "@/lib/api";
import { dateOnly, inr, num, pct } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export default function LandingPage() {
  const { t, list, locale } = useI18n();
  const { status } = useSession();
  const [booting, setBooting] = useState<boolean | null>(null);

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

  if (booting) {
    return <Boot onDone={() => setBooting(false)} />;
  }

  return (
    <Shell>
      <section className="hero">
        <SlatBackdrop columns={12} />
        <Lattice />
        <div className="hero-body">
          <CornerMeta left={`${t("brand")} · ${t("tagline")}`} right="01 / 03" />
          <FlipHeadline lines={heroLines} />
          <BlurLines>{t("hero.sub")}</BlurLines>

          <div className="row">
            <Link href={status === "signed-in" ? "/deals" : "/login"} data-cursor="">
              <Button cursorLabel={t("hero.openDeal")}>{t("hero.openDeal")}</Button>
            </Link>
            <Link href="#why-chain" data-cursor="">
              <Button variant="ghost">{t("hero.seeProof")}</Button>
            </Link>
            {evals.status === "ready" && evals.data.available && evals.data.all_green ? (
              <Capsule dotTone="pass">{t("hero.evalGreen")}</Capsule>
            ) : null}
          </div>

          <dl className="hero-stats">
            {money ? (
              <>
                <div>
                  <dt className="stat-k micro">{t("hero.held")}</dt>
                  <dd className="stat-v">
                    <CountUp value={money.held_paise} format={inr} />
                  </dd>
                </div>
                <div>
                  <dt className="stat-k micro">{t("hero.released")}</dt>
                  <dd className="stat-v">
                    <CountUp value={money.released_paise} format={inr} />
                  </dd>
                </div>
              </>
            ) : headline ? (
              <>
                <div>
                  <dt className="stat-k micro">{t("hero.labelledBundles")}</dt>
                  <dd className="stat-v">
                    <CountUp value={headline.labelled_bundles} format={(value) => num(value)} />
                  </dd>
                </div>
                <div>
                  <dt className="stat-k micro">{t("hero.escalationRate")}</dt>
                  <dd className="stat-v">{pct(headline.escalation_rate, 0)}</dd>
                </div>
              </>
            ) : null}

            {headline ? (
              <div>
                <dt className="stat-k micro">{t("hero.falseReleases")}</dt>
                <dd className="stat-v" style={{ color: "var(--sig-pass)" }}>
                  {num(headline.false_releases)}
                </dd>
              </div>
            ) : null}
          </dl>

          {evals.status === "ready" && evals.data.available ? (
            <span className="nano">
              {t("hero.measuredOn", {
                date: dateOnly(evals.data.generated_at ?? new Date().toISOString(), locale),
              })}
              {evals.data.provider && !evals.data.provider.is_live_model
                ? ` · ${t("hero.fixtureProvider")}`
                : ""}
            </span>
          ) : (
            <span className="nano">{t("hero.noEvalYet")}</span>
          )}
        </div>
      </section>

      <section className="section next-section" id="why-chain">
        <CornerMeta left={t("hero.whyChainLabel")} right="02 / 03" />
        <Reveal>
          <h2 className="headline-2">{t("hero.whyChainTitle")}</h2>
        </Reveal>
        <Rule />
        <Reveal index={1}>
          <p className="prose" style={{ paddingTop: "var(--sp-4)" }}>
            {t("hero.whyChain")}
          </p>
        </Reveal>

        <div className="grid-cards" style={{ paddingTop: "var(--sp-6)" }}>
          {list("hero.pillars").map((pillar, index) => (
            <Reveal key={pillar} index={index + 2}>
              <article className="card">
                <span className="nano">{String(index + 1).padStart(2, "0")}</span>
                <p style={{ margin: 0, paddingTop: "var(--sp-2)" }}>{pillar}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="section next-section cta">
        <CornerMeta left={t("cta.label")} right="03 / 03" />
        <p className="micro">{t("cta.label")}</p>
        <div className="cta-line">
          <ScrambleText phrases={list("cta.phrases")} />
        </div>
        <Link href={status === "signed-in" ? "/deals" : "/register"} data-cursor="">
          <Button cursorLabel={t("cta.start")}>{t("cta.start")}</Button>
        </Link>
        <span className="nano">{t("cta.footnote")}</span>
      </section>
    </Shell>
  );
}
