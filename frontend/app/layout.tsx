import type { Metadata, Viewport } from "next";

import { AppProviders } from "@/components/domain/AppProviders";
import { BRAND_THEME_COLOR } from "@/design/brand";
// Plain constants, not the client modules that re-export them: a Server
// Component importing a client export gets a throwing stub, which then gets
// interpolated into the script below as invalid JavaScript.
import { LOCALE_KEY, THEME_KEY } from "@/lib/storage-keys";

import "./globals.css";

export const metadata: Metadata = {
  title: "Aegis - every rupee has a provable reason",
  description:
    "Programmable escrow for agentic commerce. An AI verifies the evidence, a deterministic engine moves the money, and every decision is signed and anchored.",
  applicationName: "Aegis",
  icons: { icon: "/icon.svg" },
  // A demo deployment holding real deal data behind authentication: nothing
  // here should be indexed, and `public/robots.txt` says the same.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Dark is the default and the demo; light is complete and toggled.  The
  // literals live in `design/brand.ts` beside the tokens, because a
  // `<meta name="theme-color">` is read before any stylesheet exists and so
  // cannot be a `var()`.
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: BRAND_THEME_COLOR.dark },
    { media: "(prefers-color-scheme: light)", color: BRAND_THEME_COLOR.light },
  ],
};

/**
 * Applied before first paint, so a user on the light theme never sees a dark
 * flash.  It reads only two keys and cannot throw into the render path.
 */
const NO_FLASH = `
(function () {
  try {
    var theme = localStorage.getItem("${THEME_KEY}");
    if (theme === "light" || theme === "dark") {
      document.documentElement.setAttribute("data-theme", theme);
    }
    var locale = localStorage.getItem("${LOCALE_KEY}");
    if (locale === "en" || locale === "hi") document.documentElement.lang = locale;
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
      </head>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
