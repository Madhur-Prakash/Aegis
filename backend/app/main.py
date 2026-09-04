"""FastAPI application: routers, middleware, lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import (
    auth_router,
    deal_router,
    dev_router,
    dispute_router,
    evidence_router,
    misc_router,
    org_router,
    provenance_router,
)
from app.common.errors import AegisError, NotFound, ValidationFailed, error_response
from app.common.ids import request_id as new_request_id
from app.common.logging import configure_logging, flush, get_logger, shutdown
from app.common.redis_client import close_redis
from app.config.settings import settings
from app.db.session import dispose_engine
from app.events.bus import ensure_topics, get_producer

configure_logging(settings)
log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "api starting",
        extra={
            "demo_mode": settings.DEMO_MODE,
            "rail": settings.PAYMENT_RAIL,
            "ai_provider": settings.ai_effective_provider,
            "kafka_enabled": settings.KAFKA_ENABLED,
        },
    )
    if settings.KAFKA_ENABLED:
        await ensure_topics()
        try:
            await get_producer().start()
        except Exception as exc:  # a broker that is not up must not stop the API
            log.warning("kafka producer unavailable", extra={"error": type(exc).__name__})
    try:
        yield
    finally:
        await get_producer().stop()
        await close_redis()
        await dispose_engine()
        log.info("api stopped")
        flush(5.0)
        shutdown()


app = FastAPI(
    title="Aegis",
    version="1.0.0",
    description=(
        "Programmable escrow for agentic commerce. The LLM never moves money: it writes a "
        "signed attestation, and a deterministic settlement engine reads it."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    rid = request.headers.get("x-request-id") or new_request_id()
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


@app.exception_handler(AegisError)
async def aegis_error_handler(request: Request, exc: AegisError) -> JSONResponse:
    if exc.http_status >= 500:
        log.error(
            "unhandled domain error",
            extra={"code": exc.code, "path": request.url.path, "details": exc.details},
        )
    else:
        log.info(
            "typed error",
            extra={"code": exc.code, "status": exc.http_status, "path": request.url.path},
        )
    return error_response(exc, request)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        ValidationFailed(details={"errors": exc.errors()[:10]}),
        request,
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(NotFound(), request)
    return error_response(
        AegisError(
            message=str(exc.detail),
            code="HTTP_ERROR",
            http_status=exc.status_code,
        ),
        request,
    )


@app.exception_handler(Exception)
async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "unexpected error",
        extra={"path": request.url.path, "error_type": type(exc).__name__},
    )
    return error_response(AegisError(), request)


V1 = "/api/v1"
app.include_router(auth_router.router, prefix=V1)
app.include_router(org_router.router, prefix=V1)
app.include_router(deal_router.router, prefix=V1)
app.include_router(evidence_router.router, prefix=V1)
app.include_router(provenance_router.router, prefix=V1)
app.include_router(dispute_router.router, prefix=V1)
app.include_router(misc_router.router, prefix=V1)

# The demo affordance exists only when DEMO_MODE=true.  This is a registration-time
# decision, not a runtime flag check inside a handler (spec 14).
if settings.DEMO_MODE:
    app.include_router(dev_router.router, prefix=V1)
    log.info("dev router registered", extra={"reason": "DEMO_MODE=true"})


@app.get("/", tags=["platform"])
async def root() -> dict[str, str]:
    return {
        "service": "aegis",
        "docs": "/docs",
        "health": f"{V1}/health/ready",
        "thesis": "Every rupee has a provable reason.",
    }
