"""The one and only module that imports logifyx (spec §6).

The whole logging stack is swappable here because everything else in the codebase
calls `get_logger()`.

**Adapted to the installed logifyx 1.1.3 surface.**  The spec sketched
`setup_logify(service=..., level=..., json=..., mask_fields=[...], kafka={...})`.
The real 1.1.3 API is:

* ``setup_logify()``            -- no arguments; installs ``Logifyx`` as the logger class.
* ``get_logify_logger(name, json_mode=, mask=<bool>, color=, level=, log_dir=,
  kafka_servers=, kafka_topic=)`` -- configuration is per-logger keyword arguments.
* ``mask`` is a **boolean**, not a field list, and logifyx's own ``MaskFilter`` only
  rewrites a handful of ``key=value`` patterns in the message string.  It does not
  touch structured ``extra`` fields.

I11 requires that a fixed list of fields never reaches an emitted record, including
structured extras.  So the wrapper enables logifyx masking *and* installs
``AegisMaskFilter``, which redacts ``_MASK_FIELDS`` from both the extras and the
rendered message.  Call sites are unchanged.  See docs/DECISIONS.md (ADR-002).
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import queue
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from logifyx import (
    ContextLoggerAdapter,
    flush,
    get_logify_logger,
    setup_logify,
    shutdown,
)

__all__ = [
    "MASK_FIELDS",
    "audit_sink_dropped",
    "configure_logging",
    "flush",
    "get_logger",
    "shutdown",
]

# The mechanical half of I11.  Verified by tests/security/test_log_masking.py.
_MASK_FIELDS: tuple[str, ...] = (
    "password",
    "password_hash",
    "new_password",
    "token",
    "access_token",
    "refresh_token",
    "token_hash",
    "authorization",
    "api_key",
    "ai_api_key",
    "secret",
    "jwt_secret",
    "private_key",
    "operator_private_key",
    "verifier_private_key",
    "razorpay_key_secret",
    "webhook_secret",
    "email",
    "email_normalized",
    "phone",
    "address",
    "artifact_bytes",
    "raw_evidence",
    "otp",
)
MASK_FIELDS = _MASK_FIELDS

_REDACTED = "***"

# `key=value`, `key: value`, `"key": "value"` forms inside a rendered message.
# ORDER MATTERS.  The scheme-prefixed patterns run first: a `key: value` rule
# applied to `authorization: Bearer eyJhbGci...` stops at the first space and
# redacts only the word "Bearer", leaving the token in the log.
_MESSAGE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # A PEM block.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    # A credential preceded by its scheme.
    re.compile(r"(?i)\b(bearer|basic|token|apikey|api-key)(\s+)([A-Za-z0-9._\-+/=]{8,})"),
    # A 32-byte hex value, with or without the 0x prefix: a private key, and
    # nothing else in this system is written as bare 64-hex in prose (hashes are
    # logged as named fields, which the extras path masks or keeps by name).
    re.compile(r"\b(0x)?([0-9a-fA-F]{64})\b"),
    # `key=value`, `key: value`, `"key": "value"` inside a rendered message.
    *(
        re.compile(rf'(?i)(["\']?\b{re.escape(f)}\b["\']?\s*[:=]\s*)("?[^"\s,;}}\)]+"?)')
        for f in _MASK_FIELDS
    ),
)

_STANDARD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def _redact_value(value: Any, depth: int = 0) -> Any:
    """Recursively redact masked keys inside nested containers."""
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: (_REDACTED if str(k).lower() in _MASK_FIELDS else _redact_value(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(v, depth + 1) for v in value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes>"
    return value


def _replace_credential(match: re.Match[str]) -> str:
    """Keep every group except the last, which is the value.

    Retaining the label matters: a masked log line still has to say *what* was
    redacted, or the audit trail loses the shape of the event.
    """
    groups = match.groups()
    if not groups:
        return _REDACTED
    prefix = "".join(g for g in groups[:-1] if g)
    return f"{prefix}{_REDACTED}" if prefix else _REDACTED


class AegisMaskFilter(logging.Filter):
    """Enforces I11 over structured extras and the rendered message."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if key.lower() in _MASK_FIELDS:
                record.__dict__[key] = _REDACTED
            else:
                record.__dict__[key] = _redact_value(record.__dict__[key])

        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            rendered = str(record.msg)
        for pattern in _MESSAGE_PATTERNS:
            rendered = pattern.sub(_replace_credential, rendered)
        record.msg = rendered
        record.args = None
        return True


class _KafkaAuditSink(logging.Handler):
    """A non-blocking bridge to logifyx's Kafka handler.

    logifyx 1.1.3's ``KafkaHandler.emit`` calls
    ``loop.run_until_complete(self._send_async(record))`` on the *calling* thread.
    In a synchronous caller that is a blocking round trip per log line, and in
    Python 3.12 the fallback ``asyncio.run`` creates a fresh event loop each time
    while the producer stays cached against the first one -- so after the first
    line every send hangs.  A frozen request path is not an acceptable price for
    an audit stream.

    So the wrapper owns the concurrency instead: records go onto a bounded queue,
    and one daemon thread with one persistent event loop drives logifyx's handler
    (its Avro record building and schema handling included).  A broker that is
    down costs dropped audit lines and a counter, never a stalled process.

    See docs/DECISIONS.md (ADR-002).
    """

    def __init__(self, bootstrap_servers: str, topic: str, maxsize: int = 4096) -> None:
        super().__init__()
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.dropped = 0
        self._queue: queue.Queue[logging.LogRecord | None] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._run, name="aegis-kafka-audit", daemon=True)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        self.start()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        import asyncio

        from logifyx.kafka import KafkaHandler

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        handler = KafkaHandler(bootstrap_servers=self.bootstrap_servers, topic=self.topic)
        try:
            while True:
                record = self._queue.get()
                if record is None:
                    break
                try:
                    loop.run_until_complete(handler._send_async(record))
                except Exception:
                    self.dropped += 1
        finally:
            with contextlib.suppress(Exception):
                loop.run_until_complete(handler.close_async())
            loop.close()

    def close(self) -> None:
        if self._started:
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(None)
            self._thread.join(timeout=3.0)
        super().close()


_configured = False
_context_defaults: dict[str, Any] = {}
_logger_kwargs: dict[str, Any] = {}
_audit_sink: _KafkaAuditSink | None = None


def _writable_log_dir(preferred: str) -> Path:
    """The first of `preferred` and a temp directory that can actually be written."""
    for candidate in (Path(preferred), Path(tempfile.gettempdir()) / "aegis-logs"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".writable"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    # Both failed: hand back the temp path anyway and let logifyx surface it.
    return Path(tempfile.gettempdir()) / "aegis-logs"


def configure_logging(settings: Any) -> None:
    """Call once, from the FastAPI lifespan and from every worker entrypoint."""
    global _configured, _context_defaults, _logger_kwargs
    if _configured:
        return

    setup_logify()

    kwargs: dict[str, Any] = {
        "json_mode": True,  # structured everywhere, including local
        "mask": True,
        "color": False,
    }

    # logifyx's file handler is unconditional and it raises if it cannot create
    # its log directory -- which would take the whole process down for a reason
    # that is never worth a crash.  The path is declared, probed for writability,
    # and falls back to the OS temp directory.  Console output is unaffected
    # either way, and the container runtime collects that.
    kwargs["log_dir"] = str(_writable_log_dir(getattr(settings, "LOG_DIR", "logs")))

    _logger_kwargs = kwargs
    root = _build("aegis", settings.LOG_LEVEL)
    root.propagate = False

    # The Kafka audit stream (spec 6) is attached to the root aegis logger only,
    # through the non-blocking bridge above.  Child loggers created by _build
    # propagate to it, so every line reaches aegis.audit exactly once.
    global _audit_sink
    if getattr(settings, "LOG_TO_KAFKA", False) and getattr(settings, "KAFKA_ENABLED", False):
        _audit_sink = _KafkaAuditSink(settings.KAFKA_BOOTSTRAP_SERVERS, "aegis.audit")
        _audit_sink.addFilter(AegisMaskFilter())
        root.addHandler(_audit_sink)

    _context_defaults = {"service": settings.SERVICE_NAME, "env": settings.ENVIRONMENT}
    _configured = True

    # The Kafka sink runs its own producer.  Without an explicit flush+shutdown a
    # short-lived process (a script, an eval run) blocks at exit waiting on it,
    # and the last log lines -- the ones needed after a crash -- are lost.  Every
    # entrypoint also calls these explicitly; this is the backstop for scripts.
    atexit.register(_drain)


def _drain() -> None:
    if _audit_sink is not None:
        with contextlib.suppress(Exception):  # pragma: no cover
            _audit_sink.close()
    with contextlib.suppress(Exception):  # pragma: no cover
        flush(2.0)
    with contextlib.suppress(Exception):  # pragma: no cover
        shutdown()


def audit_sink_dropped() -> int:
    """How many audit lines the bridge had to drop.  Surfaced on /health/metrics."""
    return _audit_sink.dropped if _audit_sink is not None else 0


def _build(name: str, level: str) -> Any:
    """Create/return a logifyx logger with the project's single configuration.

    logifyx configures per logger name, and a child created through
    ``logging.getLogger`` would build its own default (coloured, non-JSON)
    handlers.  Every logger in the project is therefore constructed here with the
    same kwargs, and every one carries the I11 mask filter on the logger and on
    each handler.

    ``setup_logify()`` installs ``Logifyx`` as the process-wide logger class,
    which means *every* library's ``logging.getLogger`` call would also build a
    self-configured logger -- SQLAlchemy's pool and engine loggers then print at
    INFO and drown the output.  So the class is installed only for the moment an
    Aegis logger is constructed, and restored immediately afterwards; third-party
    loggers stay plain and inherit the root level.
    """
    previous = logging.getLoggerClass()
    setup_logify()
    try:
        logger = get_logify_logger(name, **_logger_kwargs)
    finally:
        logging.setLoggerClass(previous if previous is not logging.Logger else logging.Logger)
        logging.setLoggerClass(logging.Logger)
    logger.setLevel(level)
    if name != "aegis":
        # logifyx builds a handler per logger.  Leaving those in place emits every
        # line twice -- once from the child's own handler and once from the root's
        # -- so children carry no handlers and propagate to the single root
        # handler pair (stdout JSON + the Kafka audit sink).  They stay Logifyx
        # instances because ContextLoggerAdapter reads `logger.config` to decide
        # whether to merge context into `extra` or prefix it onto the message.
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.propagate = True
    if not any(isinstance(f, AegisMaskFilter) for f in logger.filters):
        logger.addFilter(AegisMaskFilter())
    for handler in logger.handlers:
        if not any(isinstance(f, AegisMaskFilter) for f in handler.filters):
            handler.addFilter(AegisMaskFilter())
    return logger


def get_logger(name: str, **context: Any) -> ContextLoggerAdapter:
    """Returns a context-bound logger.  Always bind the ids you have."""
    if not _configured:  # a worker that forgot to configure still gets masking
        from app.config.settings import settings as _s

        configure_logging(_s)
    from app.config.settings import settings as _s

    full = name if name.startswith("aegis") else f"aegis.{name}"
    logger = _build(full, _s.LOG_LEVEL)
    return ContextLoggerAdapter(logger, {**_context_defaults, **context})
