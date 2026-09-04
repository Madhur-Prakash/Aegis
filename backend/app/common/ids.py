"""Deterministic and sortable identifiers."""

from __future__ import annotations

import secrets
import time
import uuid

# Stable namespace for every seeded row (spec §8.1).  Never change this value:
# it is what makes `make seed` idempotent across machines.
AEGIS_SEED_NS = uuid.UUID("6f1f8e2c-2f4e-5a7b-9c3d-0e1a2b3c4d5e")

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def seed_id(natural_key: str) -> uuid.UUID:
    """UUIDv5 from a natural key, e.g. ``seed_id("user:buyer@meridian.demo")``."""
    return uuid.uuid5(AEGIS_SEED_NS, natural_key)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def request_id() -> str:
    """A ULID-ish, lexicographically sortable request id."""
    ms = int(time.time() * 1000)
    ts = "".join(_B32[(ms >> shift) & 31] for shift in range(45, -5, -5))
    rand = "".join(secrets.choice(_B32) for _ in range(16))
    return f"req_{ts}{rand}"


def url_token(nbytes: int = 32) -> str:
    """A cryptographically random, URL-safe token (verification, reset, invites)."""
    return secrets.token_urlsafe(nbytes)
