"""Additive schema patching.

The schema is created from the models (see `db.create_all`), which is fine for a new
database but does not add columns to an existing one. Until Alembic is introduced, this
applies the strictly additive changes that a running instance may be missing.

Rules: only ADD COLUMN, always with a default, never a drop or a type change. Anything
else belongs in a real migration.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .logging_setup import get_logger

logger = get_logger("core.migrations")

# (table, column, DDL type + default)
ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("customers", "source", "VARCHAR(20) NOT NULL DEFAULT 'seeded'"),
    ("customers", "score_source", "VARCHAR(20) NOT NULL DEFAULT 'demo_seed'"),
    ("customers", "limit_source", "VARCHAR(20) NOT NULL DEFAULT 'offered'"),
]


def apply_additive_migrations(engine: Engine) -> list[str]:
    """Returns the columns it had to add, so startup logs show what changed."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    for table, column, ddl in ADDITIVE_COLUMNS:
        if table not in existing_tables:
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if column in columns:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        applied.append(f"{table}.{column}")
        logger.info("added column", extra={"event": "migration", "column": f"{table}.{column}"})

    return applied
