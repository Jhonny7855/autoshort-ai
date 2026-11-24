"""Daily content-generation scheduler.

This replaces the "must have a YouTube channel and Google token" publishing loop
with a local daily job:

  * top up the content queue
  * produce (render) the next queued item
  * register the finished render as a local publish package

It never contacts YouTube, never needs OAuth and never marks anything published.
Publishing is always a human action confirmed with a real URL.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from ..config import settings
from ..db import execute, insert, loads, log_event, query, query_one, utcnow
from . import automation, pipeline, publishing
from .hub import emit

JOB_KIND = "daily_generate"


def _setting(user_id: int, key: str, default: Any = None) -> Any:
    row = query_one("SELECT value FROM app_settings WHERE user_id=? AND key=?", (user_id, key))
    if not row:
        return default
    return loads(row["value"], default)


def ensure_daily_job(user_id: int) -> dict[str, Any]:
    """Create or refresh the recurring generation job for this user."""
    schedule = automation.ensure_schedule(user_id)
    enabled = bool(_setting(user_id, "daily_generate_enabled", True))
    per_day = int(_setting(user_id, "daily_generate_count", 1) or 1)
    at = str(_setting(user_id, "daily_generate_at", "08:00") or "08:00")

    run_at = _next_run(schedule.get("timezone") or "UTC", at)
    dedupe = f"{JOB_KIND}:{user_id}"
    existing = query_one("SELECT * FROM jobs WHERE dedupe_key=?", (dedupe,))
    payload = {"count": max(1, min(per_day, 12)), "at": at}
    from ..db import dumps

    if existing:
        execute(
            "UPDATE jobs SET payload=?, status=?, run_at=?, updated_at=? WHERE id=?",
            (
                dumps(payload),
                "pending" if enabled else "disabled",
                run_at,
                utcnow(),
                existing["id"],
            ),
        )
        return query_one("SELECT * FROM jobs WHERE id=?", (existing["id"],)) or {}
    job_id = insert(
        "jobs",
        {
            "user_id": user_id,
            "kind": JOB_KIND,
            "payload": dumps(payload),
            "status": "pending" if enabled else "disabled",
            "priority": 0,
            "run_at": run_at,
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "dedupe_key": dedupe,
        },
    )
    return query_one("SELECT * FROM jobs WHERE id=?", (job_id,)) or {}


def _next_run(tz_name: str, at: str) -> str:
    tz = automation._tz(tz_name)
    now = datetime.now(tz)
    try:
        hh, mm = [int(x) for x in at.split(":")[:2]]
    except (ValueError, TypeError):
        hh, mm = 8, 0
    target = datetime.combine(now.date(), time(hour=hh, minute=mm), tzinfo=tz)
    if target <= now:
        target = target + timedelta(days=1)
    return target.astimezone(timezone.utc).isoformat(timespec="seconds")


async def run_due_jobs() -> int:
    """Execute daily generation jobs whose time has arrived."""
    due = query(
        "SELECT * FROM jobs WHERE kind=? AND status='pending' AND run_at <= ?",
        (JOB_KIND, utcnow()),
    )
    ran = 0
    for job in due:
        user_id = job.get("user_id")
        if not user_id:
            continue
        payload = loads(job.get("payload"), {}) or {}
        try:
            await run_generation(user_id, count=int(payload.get("count") or 1))
            execute("UPDATE jobs SET status='done', updated_at=? WHERE id=?", (utcnow(), job["id"]))
            ran += 1
        except Exception as exc:  # noqa: BLE001
            attempts = int(job.get("attempts") or 0) + 1
            message = str(exc)[:900]
            execute(
                "UPDATE jobs SET attempts=?, last_error=?, status=?, updated_at=? WHERE id=?",
                (attempts, message, "pending" if attempts < int(job.get("max_attempts") or 3) else "failed", utcnow(), job["id"]),
            )
            log_event("Daily generation failed", level="error", scope="schedule", user_id=user_id, context={"error": message})
        finally:
            schedule = automation.ensure_schedule(user_id)
            ensure_daily_job(user_id)
            execute(
                "UPDATE automation_state SET next_run_at=?, updated_at=? WHERE user_id=?",
                (_next_run(schedule.get("timezone") or "UTC", str(payload.get("at") or "08:00")), utcnow(), user_id),
            )
    return ran


async def run_generation(user_id: int, count: int = 1) -> list[dict[str, Any]]:
    """Generate `count` videos locally and register them for manual publishing."""
    automation.ensure_state(user_id)
    automation.ensure_schedule(user_id)
    results: list[dict[str, Any]] = []
    for _ in range(max(1, min(count, 12))):
        await automation.fill_queue(user_id, target=1)
        result = await automation.process_next(user_id)
        if not result:
            break
        results.append(result)
        if result.get("status") in ("FAILED", "BUSY"):
            break
        project_id = result.get("project_id")
        if project_id:
            publishing.upsert_from_project(
                user_id,
                queue_id=result.get("queue_id"),
                project_id=project_id,
                queue_status=result.get("status") or "READY_TO_UPLOAD",
            )
        if result.get("status") in ("WAITING_FOR_APPROVAL", "NEEDS_REVIEW"):
            break
    emit(user_id, "schedule_run", {"generated": len(results)})
    return results


def daily_summary(user_id: int) -> dict[str, Any]:
    """What the publishing dashboard needs to show about the daily job."""
    job = query_one("SELECT * FROM jobs WHERE dedupe_key=?", (f"{JOB_KIND}:{user_id}",))
    enabled = bool(_setting(user_id, "daily_generate_enabled", True))
    counts = query(
        "SELECT status, COUNT(*) AS c FROM publish_records WHERE user_id=? GROUP BY status", (user_id,)
    )
    record_counts = {row["status"]: row["c"] for row in counts}
    return {
        "enabled": enabled,
        "job": job,
        "per_day": int(_setting(user_id, "daily_generate_count", 1) or 1),
        "at": str(_setting(user_id, "daily_generate_at", "08:00") or "08:00"),
        "next_run_at": (job or {}).get("run_at"),
        "counts": {
            "ready": record_counts.get(publishing.STATUS_READY, 0),
            "pending_review": record_counts.get(publishing.STATUS_PENDING_REVIEW, 0),
            "scheduled": record_counts.get(publishing.STATUS_SCHEDULED, 0),
            "published": record_counts.get(publishing.STATUS_PUBLISHED, 0),
            "failed": record_counts.get(publishing.STATUS_FAILED, 0),
        },
        "youtube_configured": settings.google_configured,
    }
