"""Canonical JSON - written once, used everywhere (spec §18).

A hash that depends on dict ordering is worthless.  Rules:

* keys sorted, recursively;
* no insignificant whitespace;
* integers stay integers; floats are rendered with a fixed repr so 0.94 and
  0.9400000000000001 can never both appear;
* ``datetime`` becomes UTC ISO-8601 with a ``Z`` suffix and millisecond precision;
* ``None`` is explicit ``null``; ``Decimal``/``UUID`` become strings;
* ``bytes`` become lowercase hex.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any


def _norm(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # A fixed 12-significant-digit repr: stable across platforms.
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite float cannot be canonicalised")
        return float(f"{value:.12g}")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dt.datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=dt.UTC)
        return aware.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if hasattr(value, "model_dump"):  # pydantic v2
        return _norm(value.model_dump())
    raise TypeError(f"{type(value).__name__} is not canonicalisable")


def canonical_json(payload: Any) -> str:
    return json.dumps(
        _norm(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(payload: Any) -> bytes:
    return canonical_json(payload).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def payload_hash(payload: Any) -> str:
    """``sha256(canonical_json(payload))`` - the project's one content hash."""
    return sha256_hex(canonical_bytes(payload))
