"""ObjectStore: LocalStore (a Docker volume) and S3Store (boto3, MinIO or S3).

Artifact bytes are never logged and never sent on-chain (I7, I11).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.common.errors import ArtifactRejected, NotFound
from app.common.logging import get_logger
from app.config.settings import settings

log = get_logger("storage")

ALLOWED_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "text/plain",
}

# Real content sniffing -- not just the extension.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
)


@dataclass(slots=True)
class StoredRef:
    key: str
    size_bytes: int
    sha256: str
    content_type: str


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> StoredRef: ...
    def get(self, key: str) -> bytes: ...
    def presign_get(self, key: str, ttl_s: int) -> str: ...
    def delete(self, key: str) -> None: ...


def sniff_content_type(data: bytes, declared: str, filename: str) -> str:
    """Returns the *sniffed* type, and rejects a mismatch against the declaration."""
    head = data[:16]
    sniffed: str | None = None
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            sniffed = mime
            break
    if sniffed is None:
        guessed, _ = mimetypes.guess_type(filename)
        looks_like_text = data[:1024].isascii() and (
            guessed in (None, "text/plain") or declared == "text/plain"
        )
        if looks_like_text:
            sniffed = "text/plain"
    if sniffed is None:
        raise ArtifactRejected(
            code="UNRECOGNISED_CONTENT",
            message="The file content does not match any accepted type.",
            details={"declared": declared, "filename": filename},
        )
    if sniffed not in ALLOWED_MIME:
        raise ArtifactRejected(
            code="MIME_NOT_ALLOWED",
            message="That file type is not accepted.",
            details={"sniffed": sniffed, "allowed": sorted(ALLOWED_MIME)},
        )
    # jpeg is sometimes declared image/jpg by browsers; that one alias is accepted.
    jpeg_alias = declared == "image/jpg" and sniffed == "image/jpeg"
    if declared and declared not in (sniffed, "application/octet-stream") and not jpeg_alias:
        raise ArtifactRejected(
            code="MIME_MISMATCH",
            message="The declared file type does not match its contents.",
            details={"declared": declared, "sniffed": sniffed},
        )
    return sniffed


def enforce_size(size: int) -> None:
    if size <= 0:
        raise ArtifactRejected(code="EMPTY_FILE", message="The file is empty.")
    if size > settings.MAX_ARTIFACT_BYTES:
        raise ArtifactRejected(
            code="FILE_TOO_LARGE",
            message="The file exceeds the maximum size.",
            details={"size_bytes": size, "max_bytes": settings.MAX_ARTIFACT_BYTES},
        )


@dataclass
class LocalStore:
    root: Path = Path(settings.LOCAL_STORE_PATH)

    def _path(self, key: str) -> Path:
        safe = key.replace("..", "_").lstrip("/")
        return self.root / safe

    def put(self, key: str, data: bytes, content_type: str) -> StoredRef:
        digest = hashlib.sha256()
        digest.update(data)  # hash is computed here, never trusted from the client
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        ref = StoredRef(key, len(data), digest.hexdigest(), content_type)
        log.info(
            "artifact stored",
            extra={"storage_key": key, "size_bytes": ref.size_bytes, "sha256": ref.sha256},
        )
        return ref

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise NotFound(details={"type": "Artifact", "key": key})
        return path.read_bytes()

    def presign_get(self, key: str, ttl_s: int) -> str:
        """A short-lived HMAC URL served by the API -- never a public path."""
        expires = int(time.time()) + ttl_s
        sig = hmac.new(
            settings.JWT_SECRET.encode(), f"{key}:{expires}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        token = base64.urlsafe_b64encode(f"{key}|{expires}|{sig}".encode()).decode().rstrip("=")
        return f"/api/v1/evidence/download/{token}"

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()


def verify_presigned(token: str) -> str:
    padded = token + "=" * (-len(token) % 4)
    try:
        key, expires_s, sig = base64.urlsafe_b64decode(padded).decode().split("|")
    except Exception as exc:
        raise NotFound() from exc
    expected = hmac.new(
        settings.JWT_SECRET.encode(), f"{key}:{expires_s}".encode(), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected) or int(expires_s) < int(time.time()):
        raise NotFound()
    return key


@dataclass
class S3Store:
    bucket: str = settings.S3_BUCKET
    endpoint: str = settings.S3_ENDPOINT

    def __post_init__(self) -> None:
        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint or None,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
        )

    def put(self, key: str, data: bytes, content_type: str) -> StoredRef:
        digest = hashlib.sha256(data).hexdigest()
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return StoredRef(key, len(data), digest, content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise NotFound(details={"type": "Artifact", "key": key}) from exc

    def presign_get(self, key: str, ttl_s: int) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl_s
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        if settings.OBJECT_STORE == "s3" and settings.S3_BUCKET:
            _store = S3Store()
        else:
            root = Path(settings.LOCAL_STORE_PATH)
            root.mkdir(parents=True, exist_ok=True)
            _store = LocalStore(root)
    return _store


def store_ready() -> bool:
    try:
        store = get_store()
        if isinstance(store, LocalStore):
            return os.access(store.root, os.W_OK)
        store.presign_get("healthcheck", 30)
        return True
    except Exception:
        return False
