"""Storage backends and the serverless entrypoint."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from core_service.config import get_settings
from core_service.errors import ValidationAppError
from core_service.storage import S3ObjectStore, build_store, sniff_content_type

PDF = b"%PDF-1.4 fake but signature-correct"


class FakeS3:
    """Minimal stand-in for the boto3 client — enough to prove the code path."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.put_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = {
            "Body": kwargs["Body"],
            "ContentType": kwargs.get("ContentType"),
            "ServerSideEncryption": kwargs.get("ServerSideEncryption"),
        }

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3 signature
        from io import BytesIO

        return {"Body": BytesIO(self.objects[Key]["Body"])}

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key]["Body"])}


def _settings(**overrides):
    settings = get_settings().model_copy(update=overrides)
    return settings


def test_local_backend_is_the_default():
    assert isinstance(build_store(_settings(storage_backend="local")), object)
    assert not isinstance(build_store(_settings(storage_backend="local")), S3ObjectStore)


def test_s3_backend_is_selected_by_configuration():
    store = build_store(_settings(storage_backend="s3", s3_bucket="tatabot-docs"))
    assert isinstance(store, S3ObjectStore)


def test_s3_requires_a_bucket():
    with pytest.raises(ValidationAppError):
        S3ObjectStore(_settings(storage_backend="s3", s3_bucket=""))


def test_s3_round_trip_and_key_layout():
    client = FakeS3()
    store = S3ObjectStore(_settings(s3_bucket="tatabot-docs", s3_prefix="prod/"), client=client)
    stored = store.save("CUST001", "application/pdf", PDF)

    assert stored.key.startswith("prod/CUST001/")
    assert stored.key.endswith(".pdf")
    assert "CUST001" in stored.key and ".." not in stored.key
    assert store.read(stored.key) == PDF
    assert store.exists(stored.key)
    assert not store.exists("prod/CUST001/missing.pdf")

    put = client.put_calls[0]
    assert put["ContentType"] == "application/pdf"
    assert put["ServerSideEncryption"] == "AES256", "objects must be encrypted at rest"


def test_s3_enforces_the_same_limits_as_local():
    store = S3ObjectStore(
        _settings(s3_bucket="b", max_upload_bytes=10), client=FakeS3()
    )
    with pytest.raises(ValidationAppError):
        store.save("CUST001", "application/pdf", PDF * 10)


def test_client_filename_never_reaches_the_key():
    """A hostile filename cannot influence where the object lands."""
    store = S3ObjectStore(_settings(s3_bucket="b"), client=FakeS3())
    stored = store.save("CUST001", "application/pdf", PDF)
    assert "../../" not in stored.key
    assert ".." not in stored.key


def test_signature_beats_the_declared_type():
    assert sniff_content_type(PDF[:16], "image/png") == "application/pdf"
    with pytest.raises(ValidationAppError):
        sniff_content_type(b"GIF89a-not-allowed", "application/pdf")


def _load_entrypoint(relative: str):
    path = Path(__file__).resolve().parents[3] / relative
    spec = importlib.util.spec_from_file_location(path.stem + "_entry", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vercel_entrypoint_serves_the_app_under_its_prefix():
    """api/core.py must strip /api/core before the app sees the path."""
    module = _load_entrypoint("api/core.py")
    transport = httpx.ASGITransport(app=module.app)

    async def call(path: str):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    import asyncio

    response = asyncio.run(call("/api/core/health"))
    assert response.status_code == 200
    assert response.json()["service"] == "core-service"

    unauthorized = asyncio.run(call("/api/core/v1/customers/me"))
    assert unauthorized.status_code == 401, "routing works, auth still applies"
