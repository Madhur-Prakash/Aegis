import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  eslint: { ignoreDuringBuilds: false },
  typescript: { ignoreBuildErrors: false },
  // There is deliberately no `rewrites()` here.  Next resolves rewrite
  // destinations at BUILD time and bakes them into routes-manifest.json, so a
  // standalone image built without API_INTERNAL_BASE proxies to
  // http://localhost:8000 forever -- which, inside a container, is the frontend
  // itself.  The proxy lives in app/api/[...path]/route.ts instead and reads the
  // backend address per request.
};

export default nextConfig;
