"""Create the schema and load the demo customers. Safe to run repeatedly."""
from __future__ import annotations

from .db import create_all, session_scope
from .services import customers as customer_service


def main() -> None:
    create_all()
    with session_scope() as db:
        added = customer_service.seed(db)
    print(f"schema ready; {added} demo customers inserted")


if __name__ == "__main__":
    main()
