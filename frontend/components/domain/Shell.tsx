"use client";

/**
 * The shared shell (ui/06 §0): 56px sticky nav with a magic-bar indicator, the
 * degraded banner, the notification panel, and the theme/language toggles.
 *
 * `Review (n)` is the only amber in the chrome, and it should draw the eye --
 * that is the point.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, useMotionValueEvent, useScroll } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { SPRING } from "@/design/motion";
import { useSession } from "@/components/domain/AppProviders";
import { Footer } from "@/components/domain/Footer";
import { NotificationPanel } from "@/components/domain/NotificationPanel";
import { usePeerHover } from "@/hooks/usePeerHover";
import { api } from "@/lib/api";
import { relative } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

type NavLink = { href: string; key: string; badge?: boolean };

const LINKS: NavLink[] = [
  { href: "/deals", key: "nav.deals" },
  // The only amber in the chrome, and it should draw the eye.
  { href: "/review", key: "nav.review", badge: true },
  { href: "/ledger", key: "nav.ledger" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  // The bar is transparent until the page has moved. `useMotionValueEvent` on
  // Framer's passive scroll observer, so there is still no scroll listener.
  const [scrolled, setScrolled] = useState(false);
  const { t, locale, setLocale } = useI18n();
  const { me, status, health, rail, theme, setTheme, signOut } = useSession();
  const pathname = usePathname();
  // The bar uses the same peer hover as the rest of the page, with one
  // difference declared in CSS: nav items do not grow, they only take or give
  // up contrast.  A 56px bar that resizes its own contents is the opposite of
  // subtle.
  const peers = usePeerHover();
  const [queue, setQueue] = useState(0);
  const [unread, setUnread] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  const loadCounts = useCallback(async () => {
    if (status !== "signed-in") return;
    const [reviewResult, notificationResult] = await Promise.allSettled([
      api.reviewQueue(),
      api.notifications(),
    ]);
    if (reviewResult.status === "fulfilled") setQueue(reviewResult.value.length);
    if (notificationResult.status === "fulfilled") setUnread(notificationResult.value.unread);
  }, [status]);

  useEffect(() => {
    void loadCounts();
  }, [loadCounts, pathname]);

  const { scrollY } = useScroll();
  useMotionValueEvent(scrollY, "change", (value) => {
    // One threshold with hysteresis-free comparison: the state only flips when
    // it actually changes, so this does not re-render on every frame.
    const next = value > 8;
    setScrolled((current) => (current === next ? current : next));
  });

  const degraded = (health?.degraded ?? []).filter((name) => name !== "payment_rail");
  const banner = degraded.includes("chain_rpc")
    ? t("boot.degradedChain")
    : degraded.includes("kafka")
      ? t("boot.degradedKafka")
      : null;

  return (
    <div className="shell">
      <nav className="nav" data-scrolled={scrolled} {...peers.group}>
        <Link href="/" className="nav-brand" data-cursor="">
          <svg width="16" height="16" viewBox="0 0 28 28" aria-hidden>
            <circle cx="14" cy="14" r="12" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="M8 14 l4 5 l8 -9"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          {t("brand")}
        </Link>

        {status === "signed-in" ? (
          <ul className="nav-links">
            {LINKS.map((link) => {
              const active = pathname.startsWith(link.href);
              // At rest the bar marks the current page; under the pointer it
              // slides to whatever is being considered.
              const on = peers.active === null ? active : peers.active === link.href;
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="nav-link"
                    aria-current={active ? "page" : undefined}
                    data-cursor=""
                    {...peers.peer(link.href)}
                  >
                    {on ? (
                      <motion.span
                        layoutId="nav-bar"
                        className="nav-bar"
                        transition={SPRING.layout}
                        aria-hidden
                      />
                    ) : null}
                    {t(link.key)}
                    {link.badge && queue > 0 ? (
                      <span className="nav-badge num">{queue}</span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : null}

        <div className="nav-right">
          {rail ? (
            <span className="nano nav-meta" title={`${t("common.railMode")} ${rail.mode}`}>
              {t("common.railMode")} {rail.mode}
            </span>
          ) : null}
          {health ? (
            <span className="nano nav-meta" title={`${t("common.aiProvider")} ${health.ai_provider}`}>
              {t("common.aiProvider")} {health.ai_provider.toUpperCase()}
            </span>
          ) : null}

          {status === "signed-in" ? (
            <>
              <button
                className="icon-btn"
                onClick={() => setPanelOpen((open) => !open)}
                aria-label={t("notifications.title")}
                aria-expanded={panelOpen}
                data-cursor=""
              >
                <span aria-hidden>◔</span>
                {unread > 0 ? <span className="nav-badge num">{unread}</span> : null}
              </button>
              <Link
                href="/settings"
                className="nav-link"
                data-cursor=""
                {...peers.peer("/settings")}
              >
                {t("nav.settings")}
              </Link>
            </>
          ) : null}

          <button
            className="icon-btn"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={t("settings.theme")}
            aria-pressed={theme === "dark"}
            data-cursor=""
          >
            <span aria-hidden>{theme === "dark" ? "☾" : "☀"}</span>
          </button>
          <button
            className="icon-btn"
            onClick={() => setLocale(locale === "en" ? "hi" : "en")}
            aria-label={t("settings.language")}
            data-cursor=""
          >
            <span className="nano">{locale === "en" ? "EN" : "हि"}</span>
          </button>

          {status === "signed-in" ? (
            <button className="icon-btn nav-auth" onClick={() => void signOut()} data-cursor="">
              <span className="nano">{t("nav.signOut")}</span>
            </button>
          ) : (
            <Link
              href="/login"
              className="nav-link nav-auth"
              data-cursor=""
              {...peers.peer("/login")}
            >
              {t("auth.signIn")}
            </Link>
          )}

          <button
            className="icon-btn nav-mobile-toggle"
            onClick={() => setSheetOpen((open) => !open)}
            aria-label={t("nav.menu")}
            aria-expanded={sheetOpen}
            data-cursor=""
          >
            <span aria-hidden>≡</span>
          </button>
        </div>
      </nav>

      {banner ? (
        <div className="degraded" role="status">
          <span aria-hidden>▲</span>
          {banner}
        </div>
      ) : null}

      {me && !me.email_verified ? (
        <div className="degraded" role="status">
          <span aria-hidden>▲</span>
          {t("auth.verifyTitle")} - <Link href="/verify-email" className="link">{t("auth.resend")}</Link>
        </div>
      ) : null}

      {sheetOpen ? (
        <div className="sheet">
          <ul className="sheet-links">
            {LINKS.map((link) => (
              <li key={link.href}>
                <Link href={link.href} onClick={() => setSheetOpen(false)}>
                  {t(link.key)}
                  {link.badge && queue > 0 ? ` (${queue})` : ""}
                </Link>
              </li>
            ))}
            <li>
              <Link href="/settings" onClick={() => setSheetOpen(false)}>
                {t("nav.settings")}
              </Link>
            </li>
            {/* Hidden from the bar below 768px, so it lives here instead. */}
            <li>
              {status === "signed-in" ? (
                <button
                  className="sheet-action"
                  onClick={() => {
                    setSheetOpen(false);
                    void signOut();
                  }}
                >
                  {t("nav.signOut")}
                </button>
              ) : (
                <Link href="/login" onClick={() => setSheetOpen(false)}>
                  {t("auth.signIn")}
                </Link>
              )}
            </li>
          </ul>
        </div>
      ) : null}

      {panelOpen ? (
        <NotificationPanel
          onClose={() => {
            setPanelOpen(false);
            void loadCounts();
          }}
        />
      ) : null}

      <main className="container" style={{ flex: 1, paddingBottom: "var(--sp-8)" }}>
        {children}
      </main>

      <Footer />
    </div>
  );
}

export { relative };
