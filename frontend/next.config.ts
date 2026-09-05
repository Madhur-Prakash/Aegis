import type { NextConfig } from "next";

// The dev bundler builds its modules with `eval` and talks to a websocket for
// HMR; neither exists in a production build, so neither is allowed there.
const isDev = process.env.NODE_ENV !== "production";

/**
 * The app has no CDN, no analytics, no embedded frame and no external font: every
 * byte it loads is same-origin, so the policy can be closed rather than merely
 * narrowed.
 *
 * `'unsafe-inline'` on scripts is the one concession.  Next inlines its own
 * bootstrap payload and `app/layout.tsx` inlines the before-paint theme script;
 * replacing that with a nonce needs a middleware, which this app deliberately
 * does not have.  The directives that actually close attack paths on a
 * money-moving UI are still enforced: `frame-ancestors 'none'` (clickjacking a
 * release button), `form-action 'self'` (a posted form exfiltrating a session),
 * `base-uri 'self'` (a planted <base> repointing every relative URL) and
 * `object-src 'none'`.
 */
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  // The design system sets computed values through `style={{...}}` props.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  // `/api/*` and the SSE stream are same-origin; dev adds the HMR socket.
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-src 'none'",
  "frame-ancestors 'none'",
  "worker-src 'self' blob:",
  "manifest-src 'self'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  // `frame-ancestors` covers this for a current browser; the older header is
  // still what an old one obeys, and this UI authorises payments.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
  },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  eslint: { ignoreDuringBuilds: false },
  typescript: { ignoreBuildErrors: false },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  // There is deliberately no `rewrites()` here.  Next resolves rewrite
  // destinations at BUILD time and bakes them into routes-manifest.json, so a
  // standalone image built without API_INTERNAL_BASE proxies to
  // http://localhost:8000 forever -- which, inside a container, is the frontend
  // itself.  The proxy lives in app/api/[...path]/route.ts instead and reads the
  // backend address per request.
};

export default nextConfig;
