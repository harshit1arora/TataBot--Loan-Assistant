"""Immutable database revisions, applied in one serialized transaction."""

import json
from pathlib import Path

from sqlalchemy.engine import Engine

DIRECTORY = Path(__file__).parent / "revisions"


def upgrade(engine: Engine) -> None:
    dialect = engine.dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError(f"Unsupported migration dialect {dialect}")
    with engine.begin() as connection:
        execute = connection.exec_driver_sql
        if dialect == "sqlite":
            execute("BEGIN IMMEDIATE")
        else:
            execute("SELECT pg_advisory_xact_lock(hashtext('tatabot_schema_upgrade'))")
        execute(
            "CREATE TABLE IF NOT EXISTS tatabot_conversation_revision (revision INTEGER PRIMARY KEY)"
        )
        existing = [
            row[0]
            for row in execute(
                "SELECT revision FROM tatabot_conversation_revision ORDER BY revision"
            )
        ]
        if existing not in ([], [1], [1, 2]):
            raise RuntimeError(f"Unknown database revisions {existing}")
        if not existing:
            for statement in json.loads((DIRECTORY / f"001_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_conversation_revision VALUES (1)")
        if 2 not in existing:
            for statement in (DIRECTORY / "002.sql").read_text().splitlines():
                if statement.strip():
                    execute(statement)
            execute("INSERT INTO tatabot_conversation_revision VALUES (2)")
