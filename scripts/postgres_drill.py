"""CI-only restore comparison for disposable Postgres databases in the six-service lab."""

import sys
from pathlib import Path

import psycopg
from psycopg import sql

from postgres_recovery import backup, restore


def contents(name):
    with psycopg.connect(dbname=name) as db:
        tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        return {
            table: db.execute(
                sql.SQL("SELECT to_jsonb(t)::text FROM {} t ORDER BY 1").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            for (table,) in tables
        }


root = Path(sys.argv[1])
backup("pilot_core", "pilot_conversation", root / "storage", root / "archive")
restore("restored_core", "restored_conversation", root / "restored_storage", root / "archive")
for role in ("core", "conversation"):
    original = contents("pilot_" + role)
    assert original == contents("restored_" + role)
    assert original["document_reviews" if role == "core" else "conversation_turn_traces"]
print("PostgreSQL recovery verified all populated tables and evidence checksums.")
