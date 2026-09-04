"use client";

/**
 * The footer as a final composition (reference D4, ui/07).
 *
 * D4's rhythm: a large statement in display type, an oversized mark opposite it,
 * thin rules top and bottom, then micro link columns and a metadata line. What
 * was adopted is that *rhythm* -- the palette is not: D4 is red-on-bone, and in
 * this product red means `FAIL`.
 *
 * It replaced a single `nano` strip, which was the least composed thing on the
 * page and sat directly beneath the most composed.
 */

import Link from "next/link";

import { InvertOnHover } from "@/components/ui/InvertOnHover";
import { Reveal, Rule } from "@/components/ui/Reveal";
import { useSession } from "@/components/domain/AppProviders";
import { usePeerHover } from "@/hooks/usePeerHover";
import { useI18n } from "@/lib/i18n";

const COLUMNS: { key: string; links: { href: string; key: string }[] }[] = [
  {
    key: "footer.product",
    links: [
      { href: "/deals", key: "nav.deals" },
      { href: "/review", key: "nav.review" },
      { href: "/ledger", key: "nav.ledger" },
    ],
  },
  {
    key: "footer.proof",
    links: [
      { href: "/#why-chain", key: "footer.whyChain" },
      { href: "/#invariants", key: "footer.invariants" },
      { href: "/#evidence", key: "footer.evidence" },
    ],
  },
  {
    key: "footer.account",
    links: [
      { href: "/settings", key: "nav.settings" },
      { href: "/login", key: "auth.signIn" },
      { href: "/register", key: "auth.signUp" },
    ],
  },
];

export function Footer() {
  const { t } = useI18n();
  const { health, rail } = useSession();
  const year = new Date().getUTCFullYear();
  // One group across all three columns, not one per column: nine links that
  // respond together read as a single index, which is what the footer is.
  const peers = usePeerHover();

  return (
    <footer className="foot">
      <div className="container">
        <Rule />

        <div className="foot-statement">
          {/* The statement takes the disc but not the per-word growth: these
              two spans each hold several words, and the growth needs
              `inline-block`, which would stop the statement wrapping inside its
              26ch measure. */}
          <InvertOnHover>
            <Reveal variant="blurUp">
              <p className="foot-line">
                <span className="w-solid">{t("footer.statement1")}</span>{" "}
                <span className="w-muted">{t("footer.statement2")}</span>
              </p>
            </Reveal>
          </InvertOnHover>

          {/* The oversized mark, opposite the statement. D4 puts a ©26 here; the
              equivalent fact for this product is the year and the ® of the mark. */}
          <Reveal index={1}>
            <span className="foot-mark" aria-hidden>
              <span className="foot-mark-reg">®</span>
              <span className="foot-mark-year num">{String(year).slice(2)}</span>
            </span>
          </Reveal>
        </div>

        <Rule />

        <div className="foot-columns" {...peers.group}>
          <Reveal className="foot-brand">
            <span className="foot-brand-name">{t("brand")}</span>
            <span className="nano">{t("tagline")}</span>
            <span className="nano">{t("footer.rights", { year })}</span>
          </Reveal>

          {COLUMNS.map((column, index) => (
            <Reveal key={column.key} index={index + 1} className="foot-col">
              <span className="nano">{t(column.key)}</span>
              <ul>
                {column.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="foot-link"
                      data-cursor=""
                      {...peers.peer(link.href)}
                    >
                      {t(link.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </Reveal>
          ))}
        </div>

        <Rule />

        {/* The metadata line is the honest one: what is real right now. */}
        <div className="foot-meta">
          <span className="nano">
            {t("common.railMode")} {rail?.mode ?? "—"}
          </span>
          <span className="nano">
            {t("common.aiProvider")} {(health?.ai_provider ?? "—").toUpperCase()}
          </span>
          {health ? (
            <span className="nano foot-meta-checks">
              {Object.entries(health.checks)
                .map(([name, check]) => `${name.toUpperCase()} ${check.ready ? "OK" : "DEGRADED"}`)
                .join(" · ")}
            </span>
          ) : null}
        </div>
      </div>
    </footer>
  );
}
