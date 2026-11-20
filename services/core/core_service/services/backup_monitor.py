"""Monitor Cloud SQL PostgreSQL automated backups and PITR using read-only APIs."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import google.auth
from google.auth.transport.requests import AuthorizedSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import BackupMonitor
from .notifications import enqueue

SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def targets() -> list[str]:
    return [
        part.strip()
        for part in os.getenv("CLOUD_SQL_MONITOR_TARGETS", "").split(",")
        if part.strip()
    ]


def inspect_target(target: str, session=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    result: dict = {"status": "unknown", "checked_at": now.isoformat(), "issues": []}
    parts = target.split(":")
    if len(parts) != 2 or not all(re.fullmatch(r"[a-zA-Z0-9_.-]+", value) for value in parts):
        result["issues"] = ["invalid_target"]
        return result
    try:
        if session is None:
            credentials, _ = google.auth.default(scopes=[SCOPE])
            session = AuthorizedSession(credentials)
        url = (
            "https://sqladmin.googleapis.com/v1/projects/"
            + quote(parts[0], safe="")
            + "/instances/"
            + quote(parts[1], safe="")
        )
        instance_response = session.get(url, timeout=8)
        instance_response.raise_for_status()
        instance = instance_response.json()
        response = session.get(url + "/backupRuns", params={"maxResults": 100}, timeout=8)
        response.raise_for_status()
        data = response.json()
        config = instance.get("settings", {}).get("backupConfiguration", {})
        enabled = config.get("enabled")
        pitr = config.get("pointInTimeRecoveryEnabled")
        runs = [run for run in data.get("items", []) if run.get("type") == "AUTOMATED"]
        latest = runs[0] if runs else None
        completed = next(
            (r for r in runs if r.get("status") == "SUCCESSFUL" and r.get("endTime")), None
        )
        completed_at = (
            datetime.fromisoformat(completed["endTime"].replace("Z", "+00:00"))
            if completed
            else None
        )
        max_age = int(os.getenv("BACKUP_MAX_AGE_HOURS", "36"))
        issues = []
        if enabled is not True:
            issues.append(
                "automated_backups_disabled" if enabled is False else "backup_config_unknown"
            )
        if pitr is not True:
            issues.append("pitr_disabled" if pitr is False else "pitr_config_unknown")
        if latest and latest.get("status") in ("FAILED", "OVERDUE"):
            issues.append("latest_scheduled_backup_" + latest["status"].lower())
        if not completed_at:
            issues.append("no_successful_backup_in_recent_results")
        elif completed_at > now + timedelta(minutes=5) or now - completed_at > timedelta(
            hours=max_age
        ):
            issues.append("successful_backup_stale_or_invalid")
        result.update(
            status="degraded" if issues else "healthy",
            issues=issues,
            automated_backups_enabled=enabled,
            pitr_enabled=pitr,
            latest_scheduled_status=latest.get("status") if latest else None,
            latest_successful_backup_at=completed_at.isoformat() if completed_at else None,
            backup_start_time=config.get("startTime"),
            transaction_log_retention_days=config.get("transactionLogRetentionDays"),
            results_truncated=bool(data.get("nextPageToken")),
        )
    except Exception as exc:  # provider/auth failures are reported as unknown, never healthy
        result["issues"] = ["cloud_api_unavailable"]
        result["error_type"] = type(exc).__name__
    return result


def poll(db: Session) -> None:
    for target in targets():
        result = inspect_target(target)
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        now = datetime.now(UTC)
        db.execute(
            insert(BackupMonitor)
            .values(target=target, checked_at=now, result=result)
            .on_conflict_do_update(
                index_elements=["target"], set_={"checked_at": now, "result": result}
            )
        )
        if result["status"] != "healthy":
            recipient = os.getenv("ESCALATION_EMAIL", "").strip()
            if recipient:
                # One alert per target per UTC day, with a different key when status changes.
                import hashlib

                digest = hashlib.sha256(target.encode()).hexdigest()[:16]
                key = f"backup:{digest}:{now.date()}:{result['status']}"
                enqueue(
                    db,
                    key,
                    "backup",
                    recipient,
                    "TataBot backup monitor needs attention",
                    "Cloud SQL backup or point-in-time recovery monitoring needs attention. Check the operations page.",
                )
