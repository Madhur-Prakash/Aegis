# ── deps ────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS deps

WORKDIR /app
# `npm ci` from the lockfile only: a build that resolves a floating version is a
# build that cannot be reproduced.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ── builder ─────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Public values are baked at build time because Next inlines NEXT_PUBLIC_*.
# Nothing secret is ever passed here: the payment rail, the AI provider and the
# chain credentials all live server-side.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ARG NEXT_PUBLIC_CHAIN_EXPLORER=https://sepolia.basescan.org
ARG NEXT_PUBLIC_CHAIN_ID=84532
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_CHAIN_EXPLORER=$NEXT_PUBLIC_CHAIN_EXPLORER \
    NEXT_PUBLIC_CHAIN_ID=$NEXT_PUBLIC_CHAIN_ID \
    NEXT_TELEMETRY_DISABLED=1

# The design-system checks run inside the image build, so an image cannot be
# produced from source that violates them (spec 25.1).
RUN node scripts/check-tokens.mjs \
    && node scripts/check-i18n.mjs \
    && npx tsc --noEmit \
    && npm run build

# ── runtime ─────────────────────────────────────────────────────────────────
FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S aegis && adduser -u 10001 -S aegis -G aegis

WORKDIR /app

# `output: "standalone"` ships only the traced dependencies, so the runtime image
# carries no build toolchain and no dev dependency.
COPY --from=builder --chown=aegis:aegis /app/.next/standalone ./
COPY --from=builder --chown=aegis:aegis /app/.next/static ./.next/static
COPY --from=builder --chown=aegis:aegis /app/public ./public

USER aegis
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
  CMD node -e "require('http').get('http://127.0.0.1:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
