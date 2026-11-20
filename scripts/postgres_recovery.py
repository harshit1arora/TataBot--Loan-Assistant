"""Quiesced PostgreSQL pilot archive using standard libpq environment credentials."""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg

from recovery import digest, hashes


def major_version(database, executable):
    with psycopg.connect(dbname=database) as db:
        major = db.info.server_version // 10000
    output = subprocess.check_output([executable, "--version"], text=True)
    match = re.search(r"PostgreSQL\) (\d+)", output)
    if not match or int(match[1]) != major:
        raise ValueError(f"Use {executable} major {major} for this PostgreSQL server")
    return major


def databases(core, conversation):
    return (
        [("core", core)]
        if core == conversation
        else [("core", core), ("conversation", conversation)]
    )


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
        major = major_version(core, "pg_dump")
        for role, name in databases(core, conversation):
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
        (stage / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "postgres_major": major,
                    "shared_database": core == conversation,
                    "sha256": hashes(stage),
                }
            )
        )
        stage.rename(archive)


def restore(core, conversation, storage, archive):
    manifest = json.loads((archive / "manifest.json").read_text())
    if manifest["version"] != 1 or manifest["sha256"] != hashes(archive):
        raise ValueError("Damaged archive")
    if major_version("postgres", "pg_restore") != manifest["postgres_major"]:
        raise ValueError("Choose a restore target matching the archived PostgreSQL major")
    if storage.exists() or (core == conversation) != manifest["shared_database"]:
        raise ValueError("Restore requires fresh databases and a new storage directory")
    # createdb refuses to replace existing databases, including on concurrent invocations.
    created = []
    try:
        for role, name in databases(core, conversation):
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
