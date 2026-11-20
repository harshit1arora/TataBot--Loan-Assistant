"""Quiesced PostgreSQL pilot archive using standard libpq environment credentials."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg

from recovery import digest, hashes


def validate(core, storage):
    with psycopg.connect(dbname=core) as db:
        for key, checksum in db.execute("SELECT storage_key,sha256 FROM documents"):
            path = (storage / key).resolve()
            if not path.is_relative_to(storage.resolve()) or digest(path) != checksum:
                raise ValueError("Document checksum mismatch")


def backup(core, conversation, storage, archive):
    if archive.exists() or archive.resolve().is_relative_to(storage.resolve()):
        raise ValueError("Choose a fresh archive directory outside document storage")
    with tempfile.TemporaryDirectory(dir=archive.parent) as tmp:
        stage = Path(tmp) / "archive"
        stage.mkdir()
        for role, name in (("core", core), ("conversation", conversation)):
            subprocess.run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--file",
                    str(stage / (role + ".dump")),
                    "--dbname",
                    name,
                ],
                check=True,
            )
        shutil.copytree(storage, stage / "storage")
        validate(core, stage / "storage")
        (stage / "manifest.json").write_text(json.dumps({"version": 1, "sha256": hashes(stage)}))
        stage.rename(archive)


def restore(core, conversation, storage, archive):
    manifest = json.loads((archive / "manifest.json").read_text())
    if manifest["version"] != 1 or manifest["sha256"] != hashes(archive):
        raise ValueError("Damaged archive")
    if storage.exists() or core == conversation:
        raise ValueError("Restore requires fresh databases and a new storage directory")
    # createdb refuses to replace existing databases, including on concurrent invocations.
    created = []
    try:
        for role, name in (("core", core), ("conversation", conversation)):
            subprocess.run(["createdb", "--", name], check=True)
            created.append(name)
            subprocess.run(
                [
                    "pg_restore",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    name,
                    str(archive / (role + ".dump")),
                ],
                check=True,
            )
        validate(core, archive / "storage")
        with tempfile.TemporaryDirectory(dir=storage.parent) as tmp:
            staged = Path(tmp) / "storage"
            shutil.copytree(archive / "storage", staged)
            staged.rename(storage)
    except Exception:
        for name in reversed(created):
            subprocess.run(["dropdb", "--", name], check=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("core")
    parser.add_argument("conversation")
    parser.add_argument("storage", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    (backup if args.operation == "backup" else restore)(
        args.core, args.conversation, args.storage, args.archive
    )
