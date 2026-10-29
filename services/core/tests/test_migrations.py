"""The additive schema patch must upgrade an older database without losing rows."""
from __future__ import annotations

from core_service.migrations import apply_additive_migrations
from sqlalchemy import create_engine, inspect, text


def test_missing_columns_are_added_and_rows_survive(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db", future=True)
    with engine.begin() as connection:
        # The shape of the table before provenance columns existed.
        connection.execute(
            text(
                """
                CREATE TABLE customers (
                    id VARCHAR(32) PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    age INTEGER NOT NULL,
                    city VARCHAR(80) NOT NULL,
                    phone VARCHAR(15) NOT NULL,
                    email VARCHAR(160) NOT NULL,
                    pre_approved_limit_paise INTEGER NOT NULL,
                    declared_salary_paise INTEGER NOT NULL,
                    credit_score INTEGER NOT NULL,
                    phone_verified BOOLEAN NOT NULL DEFAULT 0,
                    address_verified BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO customers (id, name, age, city, phone, email, "
                "pre_approved_limit_paise, declared_salary_paise, credit_score) VALUES "
                "('CUST001','Asha Verma',32,'Pune','9810000001','a@b.com',30000000,6000000,745)"
            )
        )

    applied = apply_additive_migrations(engine)
    assert set(applied) == {"customers.source", "customers.score_source", "customers.limit_source"}

    columns = {col["name"] for col in inspect(engine).get_columns("customers")}
    assert {"source", "score_source", "limit_source"} <= columns

    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT name, source, score_source, limit_source FROM customers")
        ).one()
    assert row == ("Asha Verma", "seeded", "demo_seed", "offered"), "existing rows keep sane defaults"

    # Running it twice is a no-op.
    assert apply_additive_migrations(engine) == []
