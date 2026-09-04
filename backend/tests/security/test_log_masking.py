"""I11 -- masked fields never appear in emitted output."""

from __future__ import annotations

import io
import json
import logging

import pytest

from app.common.logging import MASK_FIELDS, AegisMaskFilter, configure_logging, get_logger
from app.config.settings import settings

# A deliberately fake value: the test asserts it never reaches a log sink.
SECRET = "SUPER-SECRET-VALUE-9f3a1c"  # secret-scan-allow: fixture for the masking test


class _JsonFormatter(logging.Formatter):
    """Serialises the message AND the extras, so the assertions below see what a
    real structured sink would see."""

    _STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
        "message",
        "asctime",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {"message": record.getMessage()}
        for key, value in record.__dict__.items():
            if key not in self._STANDARD and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


@pytest.fixture
def captured() -> tuple[logging.Logger, io.StringIO]:
    """A logger wired exactly like the project's, capturing to a buffer."""
    configure_logging(settings)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(AegisMaskFilter())
    logger = logging.getLogger("aegis.test.masking")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addFilter(AegisMaskFilter())
    return logger, buffer


def test_every_masked_field_is_redacted_in_extras(captured):
    logger, buffer = captured
    for field in MASK_FIELDS:
        logger.info("payload", extra={field: SECRET})
    output = buffer.getvalue()
    assert SECRET not in output, output


def test_masked_fields_are_redacted_when_nested(captured):
    logger, buffer = captured
    logger.info(
        "nested payload",
        extra={
            "request": {
                "headers": {"authorization": SECRET},
                "body": {"user": {"password": SECRET, "name": "safe"}},
                "items": [{"api_key": SECRET}, {"safe": "visible"}],
            }
        },
    )
    output = buffer.getvalue()
    assert SECRET not in output
    assert "safe" in output
    assert "visible" in output


def test_masked_fields_are_redacted_in_the_message_text(captured):
    logger, buffer = captured
    logger.info("login failed password=%s token=%s", SECRET, SECRET)
    logger.info(f'{{"api_key": "{SECRET}"}}')
    logger.info(f"authorization: Bearer {SECRET}")
    assert SECRET not in buffer.getvalue()


def test_artifact_bytes_are_never_logged(captured):
    logger, buffer = captured
    logger.info("uploaded", extra={"artifact_bytes": b"%PDF-1.7 secret contents"})
    output = buffer.getvalue()
    assert "PDF" not in output
    assert "secret contents" not in output


def test_raw_bytes_anywhere_are_summarised_not_dumped(captured):
    logger, buffer = captured
    logger.info("blob", extra={"payload": b"\x89PNG\r\n\x1a\n secret pixels"})
    output = buffer.getvalue()
    assert "secret pixels" not in output
    assert "bytes>" in output


def test_safe_fields_still_appear(captured):
    logger, buffer = captured
    logger.info(
        "settlement",
        extra={
            "deal_id": "D-4812",
            "milestone_id": "m-2",
            "amount_paise": 12_600_000,
            "rail_ref": "sim_rel_abc",
        },
    )
    output = buffer.getvalue()
    assert "D-4812" in output
    assert "12600000" in output
    assert "sim_rel_abc" in output


def test_the_mask_list_covers_the_spec_fields():
    required = {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "secret",
        "private_key",
        "operator_private_key",
        "verifier_private_key",
        "razorpay_key_secret",
        "webhook_secret",
        "email",
        "phone",
        "address",
        "artifact_bytes",
        "raw_evidence",
        "otp",
    }
    assert required.issubset(set(MASK_FIELDS))


def test_bearer_tokens_in_free_text_are_masked(captured):
    logger, buffer = captured
    logger.info(f"authorization: Bearer {SECRET}0000")
    logger.info(f"sent header Basic {SECRET}0000")
    logger.info(f"X-Api-Key {SECRET}0000 rejected")
    output = buffer.getvalue()
    assert SECRET not in output, output
    # The label survives, so the audit line still says what happened.
    assert "authorization" in output
    assert "rejected" in output


def test_a_hex_private_key_in_free_text_is_masked(captured):
    logger, buffer = captured
    key = "0x" + "ab" * 32
    logger.info(f"loaded operator private key {key} from the environment")
    assert "ab" * 32 not in buffer.getvalue()


def test_the_real_project_logger_masks_too():
    """Not the test harness: the logger every module actually uses.

    A capture handler is attached to the real ``aegis`` root logger, so the
    record travels through the production filter chain -- the adapter, the
    logger's filter and the handler's filter -- before it is asserted on.
    """
    configure_logging(settings)
    buffer = io.StringIO()
    probe = logging.StreamHandler(buffer)
    probe.setFormatter(_JsonFormatter())
    root = logging.getLogger("aegis")
    root.addHandler(probe)
    try:
        get_logger("masking-probe", request_id="req_1").info(
            "auth attempt",
            extra={"password": SECRET, "email": "person@example.com", "deal_id": "D-4812"},
        )
    finally:
        root.removeHandler(probe)

    output = buffer.getvalue()
    assert SECRET not in output, output
    assert "person@example.com" not in output
    line = next(line for line in output.splitlines() if "auth attempt" in line)
    payload = json.loads(line)
    assert payload["request_id"] == "req_1"
    assert payload["password"] == "***"
    assert payload["email"] == "***"
    assert payload["deal_id"] == "D-4812"  # the traceable ids survive


def test_no_module_imports_logifyx_directly():
    """logifyx goes behind exactly one wrapper (spec 6).

    The check walks the AST rather than searching the text, so a *comment* or a
    docstring that names the library -- explaining why it is wrapped, which is
    worth writing -- is not mistaken for an import.  Only an actual `import`
    statement counts.
    """
    import ast
    from pathlib import Path

    app = Path(__file__).resolve().parents[2] / "app"
    offenders = []
    for path in sorted(app.rglob("*.py")):
        if path.name == "logging.py" and path.parent.name == "common":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "logifyx" or name.startswith("logifyx.") for name in names):
                offenders.append(str(path.relative_to(app.parent)))
                break
    assert offenders == [], f"these modules import logifyx directly: {offenders}"


def _imported_modules(source: str) -> list[str]:
    """Every module name reached by an `import` statement in `source`."""
    import ast

    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_the_logifyx_boundary_check_catches_an_import_and_ignores_a_comment():
    """The check above is only worth having if it fails on a genuine violation.

    It replaced a substring search, which flagged a *comment* naming the library
    in `app/config/settings.py` -- a false positive that would have been "fixed"
    by deleting a useful comment.  These two cases pin the distinction.
    """
    offending = "# names logifyx in a comment AND imports it\nfrom logifyx import setup_logify\n"
    assert "logifyx" in _imported_modules(offending)

    innocent = (
        '"""Explains that logifyx sits behind exactly one wrapper."""\n'
        "# logifyx is deliberately not imported here\n"
        "VALUE = 1\n"
    )
    assert "logifyx" in innocent
    assert _imported_modules(innocent) == []
