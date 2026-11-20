from core_service.storage import S3ObjectStore
from core_service.config import get_settings
import pytest

class Pager:
    def paginate(self, **kwargs):
        yield {"Versions": [{"Key": "cust/doc", "VersionId": "v1"}, {"Key": "cust/doc-other", "VersionId": "v2"}], "DeleteMarkers": [{"Key": "cust/doc", "VersionId": "m1"}]}

class Client:
    def __init__(self, fail=False):
        self.deleted = []
        self.fail = fail
    def get_paginator(self, name):
        return Pager()
    def delete_objects(self, **kwargs):
        self.deleted.extend(kwargs["Delete"]["Objects"])
        return {"Errors": [{"Code": "AccessDenied"}]} if self.fail else {}
    def delete_object(self, **kwargs):
        self.deleted.append(kwargs["Key"])

def test_s3_deletes_only_matching_versions(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_bucket", "example")
    client = Client()
    S3ObjectStore(settings, client=client).delete("cust/doc")
    assert client.deleted == [{"Key": "cust/doc", "VersionId": "v1"}, {"Key": "cust/doc", "VersionId": "m1"}, "cust/doc"]

def test_s3_version_failure_is_reported(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "s3_bucket", "example")
    with pytest.raises(RuntimeError):
        S3ObjectStore(settings, client=Client(True)).delete("cust/doc")
