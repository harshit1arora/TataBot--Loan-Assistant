"""Object storage.

Two backends behind one interface:

* ``LocalObjectStore`` — a directory on disk. Fine for local development and a
  single container with a mounted volume.
* ``S3ObjectStore`` — any S3-compatible bucket (AWS S3, Cloudflare R2, Supabase
  Storage, MinIO). Required anywhere the filesystem is ephemeral, which includes every
  serverless platform: Vercel, Lambda, Cloud Run.

Keys are always generated server-side (``{prefix}{customer_id}/{uuid}{ext}``) and never
derived from the client-supplied filename, so a hostile name cannot escape the root.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Settings
from .errors import ValidationAppError

MAGIC_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
EXTENSION_FOR_TYPE = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    size_bytes: int


def sniff_content_type(head: bytes, declared: str | None) -> str:
    """Trust the bytes, not the declared header or the filename extension."""
    for content_type, signatures in MAGIC_SIGNATURES.items():
        if any(head.startswith(sig) for sig in signatures):
            return content_type
    raise ValidationAppError(
        "Unsupported file type. Upload a PDF, JPEG or PNG.",
        details={"allowed": list(MAGIC_SIGNATURES)},
    )


def build_key(customer_id: str, content_type: str, prefix: str = "") -> str:
    return f"{prefix}{customer_id}/{uuid.uuid4().hex}{EXTENSION_FOR_TYPE[content_type]}"


class ObjectStore(Protocol):
    def save(self, customer_id: str, content_type: str, data: bytes) -> StoredObject: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class _ValidatingStore:
    """Shared validation so both backends enforce the same limits."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes

    def _validate(self, content_type: str, data: bytes) -> str:
        if not data:
            raise ValidationAppError("The uploaded file is empty.")
        if len(data) > self.max_bytes:
            raise ValidationAppError(
                f"File exceeds the {self.max_bytes // (1024 * 1024)} MB limit."
            )
        return sniff_content_type(data[:16], content_type)


class LocalObjectStore(_ValidatingStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.max_upload_bytes)
        self.root = Path(settings.storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, customer_id: str, content_type: str, data: bytes) -> StoredObject:
        content_type = self._validate(content_type, data)
        key = build_key(customer_id, content_type)
        path = self.path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key=key, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    def read(self, key: str) -> bytes:
        return self.path_for_key(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self.path_for_key(key).is_file()

    def path_for_key(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if not str(candidate).startswith(str(self.root) + os.sep):
            raise ValidationAppError("Invalid storage key.")
        return candidate


class S3ObjectStore(_ValidatingStore):
    """S3-compatible object storage.

    Credentials come from boto3's default chain (environment, instance role, or an OIDC
    exchange), never from application config, so no key is ever written into a file.
    """

    def __init__(self, settings: Settings, client=None) -> None:
        super().__init__(settings.max_upload_bytes)
        if not settings.s3_bucket:
            raise ValidationAppError("S3 storage selected but S3_BUCKET is not set.")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix
        if client is not None:  # injected in tests
            self.client = client
        else:
            import boto3

            self.client = boto3.client(
                "s3",
                region_name=settings.s3_region,
                endpoint_url=settings.s3_endpoint_url or None,
            )

    def save(self, customer_id: str, content_type: str, data: bytes) -> StoredObject:
        content_type = self._validate(content_type, data)
        key = build_key(customer_id, content_type, self.prefix)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return StoredObject(key=key, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))

    def read(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001 - a missing object is a normal answer
            return False


def build_store(settings: Settings) -> ObjectStore:
    """Single place that decides which backend is in use."""
    if settings.storage_backend == "s3":
        return S3ObjectStore(settings)
    return LocalObjectStore(settings)
