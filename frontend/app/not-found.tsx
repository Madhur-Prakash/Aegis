"use client";

/**
 * 404 (ui/06 §7): the CTA component, reused.
 *
 * The display line cycles `NOT FOUND` / `NO SUCH DEAL` through the same
 * per-character dissolve as the closing CTA, flanked by the same arcs. Reusing
 * one motif for a second meaning is what makes a design system feel authored
 * rather than assembled -- and here the second meaning is exact: the machine is
 * looking for something and not finding it.
 *
 * Tenant isolation returns 404 rather than 403 for a resource that belongs to
 * someone else (I12), so this page is also what a cross-tenant probe sees. It
 * deliberately says nothing about whether the thing exists: both phrases are
 * true of a deal that is real but not yours.
 */

import Link from "next/link";

import { Lattice } from "@/components/ui/Reveal";
import { ScrambleText, SonarArcs } from "@/components/ui/ScrambleText";
import { useI18n } from "@/lib/i18n";

export default function NotFound() {
  const { t, list } = useI18n();

  return (
    <div className="auth-screen">
      <Lattice opacity={0.04} />
      <section className="notfound">
        <span className="nano">404</span>

        <div className="cta-stage">
          <SonarArcs side="left" />
          <h1 className="cta-line notfound-line">
            <ScrambleText phrases={list("common.notFoundPhrases")} />
          </h1>
          <SonarArcs side="right" />
        </div>

        <p className="state-body notfound-body">{t("common.notFoundBody")}</p>

        <Link href="/" className="link" data-cursor="">
          {t("common.home")}
        </Link>
      </section>
    </div>
  );
}
