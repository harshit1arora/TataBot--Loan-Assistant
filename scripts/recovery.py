"""Offline pilot backup and restore. Stop all writers first. Always create a fresh destination."""

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

DATABASES = ("core.db", "conversation.db")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root):
    for filename in DATABASES:
        with closing(sqlite3.connect((root / filename).as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Database integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Invalid foreign key in backup")
            if filename == "core.db":
                for key, checksum in db.execute("SELECT storage_key, sha256 FROM documents"):
                    path = (root / "storage" / key).resolve()
                    if not path.is_relative_to(root / "storage") or not path.is_file():
                        raise ValueError("Referenced evidence missing")
                    if digest(path) != checksum:
                        raise ValueError("Evidence checksum differs from its document record")


def hashes(root):
    return {
        p.relative_to(root).as_posix(): digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p != root / "manifest.json"
    }


def transfer(operation, source, destination):
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Choose a new destination outside the source")
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        staged = Path(tmp) / "snapshot"
        staged.mkdir()
        if operation == "restore":
            manifest = json.loads((source / "manifest.json").read_text())
            if manifest["format"] != 1 or hashes(source) != manifest["sha256"]:
                raise ValueError("Backup checksum mismatch")
        for filename in DATABASES:
            with closing(
                sqlite3.connect((source / filename).as_uri() + "?mode=ro", uri=True)
            ) as src:
                with closing(sqlite3.connect(staged / filename)) as dst:
                    src.backup(dst)
                    dst.execute("PRAGMA journal_mode=DELETE")
        shutil.copytree(source / "storage", staged / "storage")
        verify(staged)
        if operation == "backup":
            (staged / "manifest.json").write_text(
                json.dumps({"format": 1, "sha256": hashes(staged)})
            )
        staged.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    transfer(args.operation, args.source, args.destination)
