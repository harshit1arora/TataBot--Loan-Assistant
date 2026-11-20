"""Immutable database revisions, applied in one serialized transaction."""

import json
from pathlib import Path

from sqlalchemy import inspect
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
        execute("CREATE TABLE IF NOT EXISTS tatabot_core_revision (revision INTEGER PRIMARY KEY)")
        existing = [
            row[0]
            for row in execute("SELECT revision FROM tatabot_core_revision ORDER BY revision")
        ]
        if existing not in (
            [],
            [1],
            [1, 2],
            [1, 2, 3],
            [1, 2, 3, 4],
            [1, 2, 3, 4, 5],
            [1, 2, 3, 4, 5, 6],
            [1, 2, 3, 4, 5, 6, 7],
        ):
            raise RuntimeError(f"Unknown database revisions {existing}")
        if not existing:
            inspector = inspect(connection)
            if inspector.has_table("customers"):
                columns = {c["name"] for c in inspector.get_columns("customers")}
                for name, default in (
                    ("source", "seeded"),
                    ("score_source", "demo_seed"),
                    ("limit_source", "offered"),
                ):
                    if name not in columns:
                        execute(
                            f"ALTER TABLE customers ADD COLUMN {name} VARCHAR(20) NOT NULL DEFAULT '{default}'"
                        )
            for statement in json.loads((DIRECTORY / f"001_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (1)")
        if 2 not in existing:
            for statement in (DIRECTORY / "002.sql").read_text().splitlines():
                if statement.strip():
                    execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (2)")

        if 3 not in existing:
            for statement in json.loads((DIRECTORY / f"003_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (3)")

        if 4 not in existing:
            for statement in json.loads((DIRECTORY / f"004_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (4)")

        if 5 not in existing:
            for statement in json.loads((DIRECTORY / f"005_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (5)")

        if 6 not in existing:
            for statement in json.loads((DIRECTORY / f"006_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (6)")

        if 7 not in existing:
            for statement in json.loads((DIRECTORY / f"007_{dialect}.json").read_text()):
                execute(statement)
            execute("INSERT INTO tatabot_core_revision VALUES (7)")
