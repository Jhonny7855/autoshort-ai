"""Queue, automation control, scheduling, uploads and published library."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import dumps, execute, insert, loads, log_event, query, query_one, utcnow
from ..security import require_user
from ..services import automation, pipeline, youtube

router = APIRouter(prefix="/api", tags=["queue"])

VALID_STATUSES = set(pipeline.QUEUE_ORDER)


class QueueUpdate(BaseModel):
    status: str | None = None
    priority: int | None = None
    position: int | None = None


class ReorderItem(BaseModel):
    queue_id: int
    position: int


class SchedulePayload(BaseModel):
    enabled: bool | None = None
    approval_mode: bool | None = None
    videos_per_day: int | None = None
    publish_times: list[str] | None = None
    timezone: str | None = None
    days_of_week: list[int] | None = None
    min_gap_minutes: int | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    visibility: str | None = None


class UploadPayload(BaseModel):
    visibility: str = "private"
    publish_at: str | None = None


class DailyGeneratePayload(BaseModel):
    enabled: bool | None = None
    at: str | None = None
    per_day: int | None = None


@router.get("/automation/daily")
def get_daily(request: Request) -> dict[str, Any]:
    user = require_user(request)
    from ..services import publish_scheduler

    publish_scheduler.ensure_daily_job(user["id"])
    return publish_scheduler.daily_summary(user["id"])


@router.post("/automation/daily")
def set_daily(payload: DailyGeneratePayload, request: Request) -> dict[str, Any]:
    user = require_user(request)
    from ..services import publish_scheduler

    if payload.at is not None:
        try:
            hh, mm = [int(x) for x in payload.at.split(":")[:2]]
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Time must be HH:MM (24-hour)")
        pipeline.set_setting(user["id"], "daily_generate_at", f"{hh:02d}:{mm:02d}")
    if payload.enabled is not None:
        pipeline.set_setting(user["id"], "daily_generate_enabled", bool(payload.enabled))
    if payload.per_day is not None:
        pipeline.set_setting(user["id"], "daily_generate_count", max(1, min(int(payload.per_day), 12)))
    publish_scheduler.ensure_daily_job(user["id"])
    return publish_scheduler.daily_summary(user["id"])


@router.post("/automation/daily/run")
async def run_daily_now(request: Request, count: int = 1) -> dict[str, Any]:
    user = require_user(request)
    from ..services import publish_scheduler

    results = await publish_scheduler.run_generation(user["id"], count=max(1, min(count, 12)))
    return {"results": results, **publish_scheduler.daily_summary(user["id"])}


@router.get("/queue")
def list_queue(request: Request) -> dict[str, Any]:
    user = require_user(request)
    rows = query(
        """SELECT q.*, i.topic, i.angle, i.kind, i.novelty_score, i.confidence_score,
                  s.title, s.body, p.output_path, p.quality_score, p.status AS project_status
           FROM queue_items q
           JOIN content_ideas i ON i.id=q.idea_id
           LEFT JOIN video_projects p ON p.idea_id=q.idea_id
           LEFT JOIN scripts s ON s.id=p.script_id
           WHERE q.user_id=?
           ORDER BY q.priority DESC, q.position ASC, q.id ASC""",
        (user["id"],),
    )
    for row in rows:
        row["timeline"] = loads(row.get("timeline"), [])
    counts = {status: 0 for status in pipeline.QUEUE_ORDER}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"items": rows, "counts": counts}


@router.post("/queue/{queue_id}/status")
def set_status(queue_id: int, payload: QueueUpdate, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM queue_items WHERE id=? AND user_id=?", (queue_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")
    if payload.status:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        pipeline.set_queue_status(user["id"], queue_id, payload.status, "Manual update")
    patch = {}
    if payload.priority is not None:
        patch["priority"] = payload.priority
    if payload.position is not None:
        patch["position"] = payload.position
    if patch:
        assignments = ", ".join(f"{k}=?" for k in patch)
        execute(f"UPDATE queue_items SET {assignments}, updated_at=? WHERE id=?", (*patch.values(), utcnow(), queue_id))
    return {"item": query_one("SELECT * FROM queue_items WHERE id=?", (queue_id,))}


@router.delete("/queue/{queue_id}")
def remove(queue_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM queue_items WHERE id=? AND user_id=?", (queue_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")
    execute("UPDATE queue_items SET status='CANCELLED', updated_at=? WHERE id=?", (utcnow(), queue_id))
    pipeline.timeline_add(queue_id, "CANCELLED", "Removed by user")
    return {"ok": True}


@router.post("/queue/reorder")
def reorder(payload: ReorderItem, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM queue_items WHERE id=? AND user_id=?", (payload.queue_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")
    execute("UPDATE queue_items SET position=?, updated_at=? WHERE id=?", (payload.position, utcnow(), payload.queue_id))
    return {"ok": True}


@router.post("/queue/{queue_id}/retry")
async def retry(queue_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM queue_items WHERE id=? AND user_id=?", (queue_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")
    execute("UPDATE queue_items SET status='IDEA', attempts=0, last_error=NULL, updated_at=? WHERE id=?", (utcnow(), queue_id))
    pipeline.timeline_add(queue_id, "IDEA", "Retry requested")
    try:
        result = await pipeline.produce_video(user["id"], queue_id, force=True)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"result": result}


@router.post("/queue/{queue_id}/approve")
async def approve(queue_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM queue_items WHERE id=? AND user_id=?", (queue_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")
    script = query_one("SELECT * FROM scripts WHERE idea_id=? AND user_id=?", (row["idea_id"], user["id"]))
    if script:
        execute("UPDATE scripts SET approved=1, updated_at=? WHERE id=?", (utcnow(), script["id"]))
    project = query_one("SELECT * FROM video_projects WHERE idea_id=?", (row["idea_id"],))
    if project and project.get("output_path"):
        execute("UPDATE queue_items SET status='READY_TO_UPLOAD', updated_at=? WHERE id=?", (utcnow(), queue_id))
        pipeline.timeline_add(queue_id, "READY_TO_UPLOAD", "Approved by user")
        return {"ok": True, "status": "READY_TO_UPLOAD"}
    try:
        result = await pipeline.produce_video(user["id"], queue_id, force=False)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "result": result}


@router.get("/automation/status")
def automation_status(request: Request) -> dict[str, Any]:
    user = require_user(request)
    state = automation.ensure_state(user["id"])
    schedule = automation.ensure_schedule(user["id"])
    counts = query(
        "SELECT status, COUNT(*) AS c FROM queue_items WHERE user_id=? GROUP BY status", (user["id"],)
    )
    return {
        "state": state,
        "schedule": schedule,
        "next_publish_at": automation.next_publish_at(schedule),
        "counts": {row["status"]: row["c"] for row in counts},
        "uploads_today": automation.uploads_today(user["id"], schedule),
    }


@router.post("/automation/start")
def start(request: Request) -> dict[str, Any]:
    user = require_user(request)
    automation.ensure_schedule(user["id"])
    automation.set_status(user["id"], "running")
    return {"status": "running"}


@router.post("/automation/pause")
def pause(request: Request) -> dict[str, Any]:
    user = require_user(request)
    automation.set_status(user["id"], "paused", reason="Paused by user")
    return {"status": "paused"}


@router.post("/automation/stop")
def stop(request: Request) -> dict[str, Any]:
    user = require_user(request)
    automation.set_status(user["id"], "stopped", reason="Stopped by user")
    return {"status": "stopped"}


@router.post("/automation/run-now")
async def run_now(request: Request, count: int = 1) -> dict[str, Any]:
    user = require_user(request)
    results = await automation.run_now(user["id"], count=count)
    return {"results": results}


@router.post("/automation/upload-now")
async def upload_now(request: Request) -> dict[str, Any]:
    user = require_user(request)
    result = await automation.publish_ready(user["id"], force_now=True)
    if not result:
        raise HTTPException(status_code=400, detail="No video is ready to upload")
    if result.get("status") == "FAILED":
        raise HTTPException(status_code=502, detail=result.get("error") or "Upload failed")
    return {"result": result}


@router.get("/schedule")
def get_schedule(request: Request) -> dict[str, Any]:
    user = require_user(request)
    schedule = automation.ensure_schedule(user["id"])
    return {"schedule": schedule, "next_publish_at": automation.next_publish_at(schedule)}


@router.post("/schedule")
def update_schedule(payload: SchedulePayload, request: Request) -> dict[str, Any]:
    user = require_user(request)
    automation.ensure_schedule(user["id"])
    patch: dict[str, Any] = {}
    for key, value in payload.model_dump().items():
        if value is None:
            continue
        if key in {"enabled", "approval_mode"}:
            patch[key] = 1 if value else 0
        elif key in {"publish_times", "days_of_week"}:
            patch[key] = dumps(value)
        elif key == "videos_per_day":
            patch[key] = max(1, min(int(value), 12))
        elif key == "visibility" and value not in {"private", "unlisted", "public"}:
            raise HTTPException(status_code=400, detail="visibility must be private|unlisted|public")
        else:
            patch[key] = value
    if patch:
        assignments = ", ".join(f"{k}=?" for k in patch)
        execute(f"UPDATE schedules SET {assignments}, updated_at=? WHERE user_id=?", (*patch.values(), utcnow(), user["id"]))
    schedule = automation.ensure_schedule(user["id"])
    execute("UPDATE automation_state SET next_run_at=? WHERE user_id=?", (automation.next_publish_at(schedule), user["id"]))
    return {"schedule": schedule, "next_publish_at": automation.next_publish_at(schedule)}


@router.get("/uploads")
def uploads(request: Request) -> dict[str, Any]:
    user = require_user(request)
    rows = query(
        """SELECT u.*, s.title AS script_title FROM upload_jobs u
           LEFT JOIN video_projects p ON p.id=u.project_id
           LEFT JOIN scripts s ON s.id=p.script_id
           WHERE u.user_id=? ORDER BY u.id DESC LIMIT 100""",
        (user["id"],),
    )
    return {"uploads": rows}


@router.get("/published")
def published(request: Request) -> dict[str, Any]:
    user = require_user(request)
    rows = query(
        "SELECT * FROM published_videos WHERE user_id=? ORDER BY COALESCE(published_at, created_at) DESC LIMIT 200",
        (user["id"],),
    )
    return {"videos": rows}


@router.post("/published/sync")
async def sync_published(request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        count = await automation.sync_analytics(user["id"])
    except youtube.GoogleAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"synced": count}


@router.get("/analytics")
def analytics(request: Request) -> dict[str, Any]:
    user = require_user(request)
    totals = query_one(
        """SELECT COUNT(*) AS videos, COALESCE(SUM(views),0) AS views,
                  COALESCE(SUM(likes),0) AS likes, COALESCE(SUM(comments),0) AS comments
           FROM published_videos WHERE user_id=?""",
        (user["id"],),
    ) or {}
    series = query(
        """SELECT day, SUM(views) AS views, SUM(likes) AS likes FROM analytics_snapshots
           WHERE user_id=? GROUP BY day ORDER BY day""",
        (user["id"],),
    )
    best = query(
        """SELECT p.title, p.views, p.likes, p.comments, p.youtube_video_id, p.published_at
           FROM published_videos p WHERE p.user_id=? ORDER BY p.views DESC LIMIT 5""",
        (user["id"],),
    )
    per_hour = query(
        """SELECT substr(COALESCE(published_at, created_at), 12, 2) AS hour, COUNT(*) AS videos,
                  COALESCE(AVG(views), 0) AS avg_views
           FROM published_videos WHERE user_id=? GROUP BY hour ORDER BY hour""",
        (user["id"],),
    )
    queue_stats = query(
        "SELECT status, COUNT(*) AS c FROM queue_items WHERE user_id=? GROUP BY status", (user["id"],)
    )
    return {
        "totals": totals,
        "series": series,
        "best": best,
        "per_hour": per_hour,
        "queue_stats": {row["status"]: row["c"] for row in queue_stats},
        "source": "youtube_data_api",
    }
