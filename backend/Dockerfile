# ── builder ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Cache-mount uv so rebuilds are fast.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 netcat-openbsd curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 aegis

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=aegis:aegis alembic.ini ./
COPY --chown=aegis:aegis migrations ./migrations
COPY --chown=aegis:aegis app ./app
COPY --chown=aegis:aegis scripts ./scripts
COPY --chown=aegis:aegis evals ./evals
COPY --chown=aegis:aegis tests ./tests
COPY --chown=aegis:aegis entrypoint.sh ./entrypoint.sh

# `/app/logs` is created here because the process runs as a non-root user and
# logifyx's file handler is unconditional: without a writable directory the
# library raises at import time and the container never starts.
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data/evidence /data/generated /data/fixtures /app/evals/out /app/logs \
    && chown -R aegis:aegis /data /app/evals /app/logs

USER aegis
EXPOSE 8000
ENTRYPOINT []
CMD ["/app/entrypoint.sh", "api"]
