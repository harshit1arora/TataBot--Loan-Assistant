"""Document extraction worker.

Runs as its own process so a slow PDF never delays an HTTP response:

    python -m app.worker --once     # drain the queue and exit (used by tests/CI)
    python -m app.worker            # poll forever

Swap this loop for Celery/RQ when you need retries across hosts; the job table and the
extractor interface stay the same.
"""
from __future__ import annotations

import argparse
import time

from .config import get_settings
from .db import create_all, session_scope
from .logging_setup import configure_logging, get_logger
from .services import documents as document_service
from .storage import build_store

logger = get_logger("core.worker")


def run_once() -> int:
    settings = get_settings()
    store = build_store(settings)
    processed = 0
    while True:
        with session_scope() as db:
            document_id = document_service.process_next_job(db, settings=settings, store=store)
        if document_id is None:
            return processed
        processed += 1
        logger.info("extraction done", extra={"event": "extraction", "document_id": document_id})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, "core-worker")
    create_all()
    if args.once:
        print(f"processed {run_once()} job(s)")
        return
    while True:
        run_once()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
