"""Autonomous automation engine.

Runs as a background asyncio loop inside the FastAPI process (independent of
whether the dashboard is open). Responsibilities:
  * keep the content queue topped up from the active niche
  * advance queue items through the production pipeline
  * publish / schedule uploads according to the user's schedule
  * record real errors and retry with backoff
  * sync YouTube analytics
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import settings
from ..db import dumps, execute, insert, loads, log_event, query, query_one, utcnow
from . import pipeline, youtube
from .hub import emit

DEFAULT_SCHEDULE = {
    "enabled": 0,
    "approval_mode": 1,
    "videos_per_day": 1,
    "publish_times": ["19:00"],
    "timezone": "UTC",
    "days_of_week": [1, 2, 3, 4, 5, 6, 7],
    "min_gap_minutes": 90,
    "quiet_start": None,
    "quiet_end": None,
    "visibility": "private",
}


def ensure_state(user_id: int) -> dict[str, Any]:
    state = query_one("SELECT * FROM automation_state WHERE user_id=?", (user_id,))
    if not state:
        insert(
            "automation_state",
            {
                "user_id": user_id,
                "status": "idle",
                "current_progress": 0,
                "updated_at": utcnow(),
            },
        )
        state = query_one("SELECT * FROM automation_state WHERE user_id=?", (user_id,))
    return state or {}


def ensure_schedule(user_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM schedules WHERE user_id=?", (user_id,))
    if not row:
        insert(
            "schedules",
            {
                "user_id": user_id,
                **{k: (json.dumps(v) if isinstance(v, list) else v) for k, v in DEFAULT_SCHEDULE.items()},
                "created_at": utcnow(),
                "updated_at": utcnow(),
            },
        )
        row = query_one("SELECT * FROM schedules WHERE user_id=?", (user_id,))
    if row:
        row["publish_times"] = loads(row.get("publish_times"), ["19:00"])
        row["days_of_week"] = loads(row.get("days_of_week"), [1, 2, 3, 4, 5, 6, 7])
    return row or {}


def set_status(user_id: int, status: str, *, reason: str | None = None) -> None:
    ensure_state(user_id)
    execute(
        "UPDATE automation_state SET status=?, paused_reason=?, updated_at=? WHERE user_id=?",
        (status, reason, utcnow(), user_id),
    )
    emit(user_id, "automation_status", {"status": status, "reason": reason})


def status_of(user_id: int) -> dict[str, Any]:
    state = ensure_state(user_id)
    schedule = ensure_schedule(user_id)
    return {"state": state, "schedule": schedule}


def _tz(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return timezone.utc


def now_local(tz_name: str) -> datetime:
    return datetime.now(_tz(tz_name))


def slots_today(schedule: dict[str, Any]) -> list[datetime]:
    tz = _tz(schedule.get("timezone") or "UTC")
    today = datetime.now(tz).date()
    out = []
    for hhmm in schedule.get("publish_times") or ["19:00"]:
        try:
            h, m = [int(x) for x in str(hhmm).split(":")[:2]]
        except (ValueError, TypeError):
            continue
        out.append(datetime(today.year, today.month, today.day, h, m, tzinfo=tz))
    return sorted(out)


def next_publish_at(schedule: dict[str, Any]) -> str | None:
    if not schedule.get("enabled"):
        return None
    tz = _tz(schedule.get("timezone") or "UTC")
    days = set(schedule.get("days_of_week") or [1, 2, 3, 4, 5, 6, 7])
    now = datetime.now(tz)
    for day_offset in range(0, 8):
        day = (now + timedelta(days=day_offset))
        if day.isoweekday() not in days:
            continue
        for slot in slots_today(schedule):
            candidate = slot.replace(year=day.year, month=day.month, day=day.day)
            if candidate > now:
                return candidate.astimezone(timezone.utc).isoformat(timespec="seconds")
    return None


def uploads_today(user_id: int, schedule: dict[str, Any]) -> int:
    tz = _tz(schedule.get("timezone") or "UTC")
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    row = query_one(
        """SELECT COUNT(*) AS c FROM upload_jobs
           WHERE user_id=? AND status IN ('uploaded','scheduled') AND created_at >= ?""",
        (user_id, start.isoformat(timespec="seconds")),
    )
    return int(row["c"]) if row else 0


def _parse_hhmm(value: str | None) -> int | None:
    """Minutes past midnight for 'HH:MM', or None when unparseable."""
    if not value:
        return None
    try:
        hh, mm = [int(x) for x in str(value).split(":")[:2]]
    except (ValueError, TypeError):
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def in_quiet_hours(schedule: dict[str, Any], at: datetime | None = None) -> bool:
    """True when `at` falls inside the schedule's quiet window.

    Windows may wrap midnight (22:00 -> 07:00), which is the common case.
    """
    start = _parse_hhmm(schedule.get("quiet_start"))
    end = _parse_hhmm(schedule.get("quiet_end"))
    if start is None or end is None or start == end:
        return False
    tz = _tz(schedule.get("timezone") or "UTC")
    moment = at or datetime.now(tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    minute = moment.astimezone(tz).hour * 60 + moment.astimezone(tz).minute
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def last_upload_at(user_id: int) -> datetime | None:
    row = query_one(
        """SELECT created_at FROM upload_jobs
           WHERE user_id=? AND status IN ('uploaded','scheduled')
           ORDER BY created_at DESC LIMIT 1""",
        (user_id,),
    )
    if not row or not row.get("created_at"):
        return None
    try:
        moment = datetime.fromisoformat(str(row["created_at"]))
    except (ValueError, TypeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def min_gap_satisfied(schedule: dict[str, Any], user_id: int) -> bool:
    """Respect the minimum gap between uploads so a slot burst cannot double-post."""
    gap = int(schedule.get("min_gap_minutes") or 0)
    if gap <= 0:
        return True
    last = last_upload_at(user_id)
    if not last:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(minutes=gap)


async def fill_queue(user_id: int, target: int = 3) -> int:
    pending = query_one(
        """SELECT COUNT(*) AS c FROM queue_items
           WHERE user_id=? AND status NOT IN ('PUBLISHED','CANCELLED','FAILED','WAITING_FOR_APPROVAL')""",
        (user_id,),
    )
    current = int(pending["c"]) if pending else 0
    added = 0
    niche = query_one("SELECT * FROM niches WHERE user_id=? AND active=1", (user_id,))
    channel = youtube.selected_channel(user_id)
    while current + added < target:
        idea = await pipeline.create_idea(
            user_id, niche=niche, channel_row_id=channel["id"] if channel else None
        )
        if not idea:
            break
        await pipeline.enqueue_idea(user_id, idea["id"])
        added += 1
        if added > 6:
            break
    if added:
        emit(user_id, "queue_update", {"added": added})
    return added


async def process_next(user_id: int) -> dict[str, Any] | None:
    item = pipeline.next_queue_item(user_id)
    if not item:
        return None
    ensure_state(user_id)
    execute(
        "UPDATE automation_state SET status='running', current_queue_id=?, current_step=?, current_progress=0, last_run_at=?, updated_at=? WHERE user_id=?",
        (item["id"], "starting", utcnow(), utcnow(), user_id),
    )
    emit(user_id, "automation_status", {"status": "running", "queue_id": item["id"]})
    try:
        result = await pipeline.produce_video(user_id, item["id"])
        execute("UPDATE queue_items SET attempts=attempts+1, last_error=NULL WHERE id=?", (item["id"],))
        emit(user_id, "pipeline_done", {"queue_id": item["id"], "result": result.get("status")})
        return result
    except pipeline.ItemBusyError:
        # Another worker is already producing this item; leave it alone.
        return {"status": "BUSY", "queue_id": item["id"]}
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:900]
        log_event(
            "Pipeline failed",
            level="error",
            scope="pipeline",
            user_id=user_id,
            context={"queue_id": item["id"], "error": message},
        )
        execute(
            "UPDATE queue_items SET status='FAILED', last_error=?, attempts=attempts+1, updated_at=? WHERE id=?",
            (message, utcnow(), item["id"]),
        )
        pipeline.timeline_add(item["id"], "FAILED", message)
        execute(
            "UPDATE automation_state SET last_error=?, updated_at=? WHERE user_id=?",
            (message, utcnow(), user_id),
        )
        emit(user_id, "pipeline_error", {"queue_id": item["id"], "error": message})
        return {"status": "FAILED", "error": message}
    finally:
        execute(
            "UPDATE automation_state SET status=?, current_progress=?, updated_at=? WHERE user_id=?",
            ("idle", 100, utcnow(), user_id),
        )


async def publish_ready(user_id: int, *, force_now: bool = False) -> dict[str, Any] | None:
    schedule = ensure_schedule(user_id)
    channel = youtube.selected_channel(user_id)
    ready = query_one(
        """SELECT q.*, p.id AS video_project_id, p.output_path, s.title, s.description, s.hashtags, p.quality_score
           FROM queue_items q
           JOIN video_projects p ON p.idea_id = q.idea_id
           JOIN scripts s ON s.id = p.script_id
           WHERE q.user_id=? AND q.status='READY_TO_UPLOAD' AND p.output_path IS NOT NULL
           ORDER BY q.priority DESC, q.position ASC LIMIT 1""",
        (user_id,),
    )
    if not ready:
        return None
    if not force_now:
        if not schedule.get("enabled"):
            return None
        if in_quiet_hours(schedule):
            return None
        if uploads_today(user_id, schedule) >= int(schedule.get("videos_per_day") or 1):
            return None
        if not min_gap_satisfied(schedule, user_id):
            return None
        slot = next_publish_at(schedule)
        now_utc = datetime.now(timezone.utc)
        if slot:
            slot_dt = datetime.fromisoformat(slot)
            if slot_dt - now_utc > timedelta(minutes=10):
                return None

    if not schedule.get("approval_mode") == 0 and not force_now:
        execute("UPDATE queue_items SET status='WAITING_FOR_APPROVAL', updated_at=? WHERE id=?", (utcnow(), ready["id"]))
        pipeline.timeline_add(ready["id"], "WAITING_FOR_APPROVAL", "Approval mode enabled")
        emit(user_id, "queue_update", {"queue_id": ready["id"], "status": "WAITING_FOR_APPROVAL"})
        return {"status": "WAITING_FOR_APPROVAL"}

    # Without a linked channel there is nowhere to push to over the API. The
    # render still becomes a local publish package the user can upload by hand.
    if not channel:
        return await publish_locally(user_id, ready)

    visibility = schedule.get("visibility") or "private"
    publish_at = None
    if schedule.get("enabled") and not force_now:
        slot = next_publish_at(schedule)
        if slot:
            publish_at = slot
            visibility = "private"
    return await do_upload(user_id, ready, visibility=visibility, publish_at=publish_at)


async def publish_locally(user_id: int, ready: dict[str, Any]) -> dict[str, Any]:
    """Register a finished render as a ready-to-publish local package."""
    from . import publishing

    record = publishing.upsert_from_project(
        user_id,
        queue_id=ready["id"],
        project_id=ready["video_project_id"],
        queue_status="READY_TO_UPLOAD",
        force=True,
    )
    if not record:
        return {"status": "FAILED", "error": "Rendered file is missing on disk"}
    emit(user_id, "publish_ready", {"queue_id": ready["id"], "record_id": record["id"]})
    return {
        "status": "READY",
        "record_id": record["id"],
        "local": True,
        "download_url": f"/api/publish/{record['id']}/download",
    }


async def do_upload(
    user_id: int,
    ready: dict[str, Any],
    *,
    visibility: str = "private",
    publish_at: str | None = None,
) -> dict[str, Any]:
    project_id = ready["video_project_id"]
    output = ready["output_path"]
    channel = youtube.selected_channel(user_id)
    tags = loads(ready.get("hashtags"), []) or []
    upload_id = insert(
        "upload_jobs",
        {
            "user_id": user_id,
            "project_id": project_id,
            "channel_id": channel["id"] if channel else None,
            "status": "uploading",
            "visibility": visibility,
            "publish_at": publish_at,
            "title": ready.get("title"),
            "description": ready.get("description"),
            "tags": dumps(tags),
            "progress": 5,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    execute("UPDATE queue_items SET status='UPLOADING', updated_at=? WHERE id=?", (utcnow(), ready["id"]))
    pipeline.timeline_add(ready["id"], "UPLOADING", "Uploading to YouTube")
    emit(user_id, "upload_started", {"upload_id": upload_id, "queue_id": ready["id"]})

    try:
        result = await youtube.upload_video(
            user_id,
            file_path=output,
            title=ready.get("title") or "Short",
            description=ready.get("description") or "",
            tags=[t.lstrip("#") for t in tags],
            visibility=visibility,
            publish_at=publish_at,
        )
        video_id = result.get("video_id")
        if not video_id:
            raise RuntimeError("YouTube did not return a video id")
        execute(
            "UPDATE upload_jobs SET status=?, youtube_video_id=?, progress=100, updated_at=? WHERE id=?",
            ("scheduled" if publish_at else "uploaded", video_id, utcnow(), upload_id),
        )
        existing = query_one(
            "SELECT id FROM published_videos WHERE channel_id=? AND youtube_video_id=?",
            (channel["id"] if channel else None, video_id),
        )
        if existing:
            execute(
                "UPDATE published_videos SET title=?, visibility=?, scheduled_at=?, status=? WHERE id=?",
                (ready.get("title"), visibility, publish_at, "scheduled" if publish_at else "published", existing["id"]),
            )
        else:
            insert(
                "published_videos",
                {
                    "user_id": user_id,
                    "channel_id": channel["id"] if channel else None,
                    "project_id": project_id,
                    "youtube_video_id": video_id,
                    "title": ready.get("title"),
                    "description": ready.get("description"),
                    "visibility": visibility,
                    "published_at": None if publish_at else utcnow(),
                    "scheduled_at": publish_at,
                    "status": "scheduled" if publish_at else "published",
                    "created_at": utcnow(),
                },
            )
        new_status = "SCHEDULED" if publish_at else "PUBLISHED"
        execute("UPDATE queue_items SET status=?, updated_at=? WHERE id=?", (new_status, utcnow(), ready["id"]))
        pipeline.timeline_add(ready["id"], new_status, f"YouTube video {video_id}")
        emit(user_id, "upload_done", {"queue_id": ready["id"], "video_id": video_id, "status": new_status})
        return {"status": new_status, "video_id": video_id}
    except Exception as exc:  # noqa: BLE001
        message = str(exc)[:900]
        execute(
            "UPDATE upload_jobs SET status='failed', error=?, attempts=attempts+1, updated_at=? WHERE id=?",
            (message, utcnow(), upload_id),
        )
        execute("UPDATE queue_items SET status='FAILED', last_error=?, updated_at=? WHERE id=?", (message, utcnow(), ready["id"]))
        pipeline.timeline_add(ready["id"], "FAILED", message)
        log_event("Upload failed", level="error", scope="upload", user_id=user_id, context={"error": message})
        emit(user_id, "upload_error", {"queue_id": ready["id"], "error": message})
        return {"status": "FAILED", "error": message}


async def sync_analytics(user_id: int) -> int:
    channel = youtube.selected_channel(user_id)
    if not channel:
        return 0
    videos = await youtube.fetch_my_videos(user_id, max_results=50)
    updated = 0
    for video in videos:
        existing = query_one(
            "SELECT * FROM published_videos WHERE channel_id=? AND youtube_video_id=?",
            (channel["id"], video["youtube_video_id"]),
        )
        payload = {
            "title": video.get("title"),
            "description": video.get("description"),
            "thumbnail": video.get("thumbnail"),
            "visibility": video.get("visibility"),
            "published_at": video.get("published_at"),
            "views": video.get("views") or 0,
            "likes": video.get("likes") or 0,
            "comments": video.get("comments") or 0,
            "last_synced_at": utcnow(),
        }
        if existing:
            assignments = ", ".join(f"{k}=?" for k in payload)
            execute(f"UPDATE published_videos SET {assignments} WHERE id=?", (*payload.values(), existing["id"]))
            pv_id = existing["id"]
        else:
            pv_id = insert(
                "published_videos",
                {
                    "user_id": user_id,
                    "channel_id": channel["id"],
                    "youtube_video_id": video["youtube_video_id"],
                    "status": "published",
                    "created_at": utcnow(),
                    **payload,
                },
            )
        day = datetime.now(timezone.utc).date().isoformat()
        snap = query_one("SELECT id FROM analytics_snapshots WHERE published_video_id=? AND day=? AND source='youtube_data_api'", (pv_id, day))
        if snap:
            execute(
                "UPDATE analytics_snapshots SET views=?, likes=?, comments=? WHERE id=?",
                (video.get("views") or 0, video.get("likes") or 0, video.get("comments") or 0, snap["id"]),
            )
        else:
            insert(
                "analytics_snapshots",
                {
                    "user_id": user_id,
                    "published_video_id": pv_id,
                    "day": day,
                    "views": video.get("views") or 0,
                    "likes": video.get("likes") or 0,
                    "comments": video.get("comments") or 0,
                    "source": "youtube_data_api",
                    "created_at": utcnow(),
                },
            )
        updated += 1
    return updated


async def retry_failed(user_id: int, max_attempts: int = 3) -> int:
    rows = query(
        "SELECT * FROM queue_items WHERE user_id=? AND status='FAILED' AND attempts<? ORDER BY id",
        (user_id, max_attempts),
    )
    for row in rows:
        execute("UPDATE queue_items SET status='IDEA', updated_at=? WHERE id=?", (utcnow(), row["id"]))
        pipeline.timeline_add(row["id"], "IDEA", "Retry scheduled")
    return len(rows)


class AutomationEngine:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._tick = 0

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="automation-engine")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001
                log_event("Automation tick crashed", level="error", scope="automation", context={"error": str(exc)})
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass

    async def tick(self) -> None:
        self._tick += 1
        users = query("SELECT id FROM users")
        for user in users:
            user_id = user["id"]
            state = ensure_state(user_id)
            schedule = ensure_schedule(user_id)
            execute(
                "UPDATE automation_state SET next_run_at=? WHERE user_id=?",
                (next_publish_at(schedule), user_id),
            )
            if state.get("status") in ("stopped", "paused"):
                continue
            try:
                # The local daily generation job does not depend on a channel or
                # on OAuth: it only needs the machine this app runs on.
                from . import publish_scheduler

                await publish_scheduler.run_due_jobs()
            except Exception as exc:  # noqa: BLE001
                log_event("Daily job runner failed", level="error", scope="schedule", user_id=user_id, context={"error": str(exc)})
            if not schedule.get("enabled") and state.get("status") != "running":
                continue
            try:
                if state.get("status") == "running":
                    await fill_queue(user_id, target=3)
                    await process_next(user_id)
                if schedule.get("enabled"):
                    await fill_queue(user_id, target=int(schedule.get("videos_per_day") or 1) + 1)
                    await publish_ready(user_id)
            except Exception as exc:  # noqa: BLE001
                log_event("Automation user tick failed", level="error", scope="automation", user_id=user_id, context={"error": str(exc)})
        if self._tick % 15 == 0:
            for user in users:
                try:
                    await retry_failed(user["id"])
                except Exception:
                    pass
        if self._tick % 30 == 0:
            for user in users:
                if query_one("SELECT id FROM youtube_channels WHERE user_id=? AND is_selected=1", (user["id"],)):
                    try:
                        await sync_analytics(user["id"])
                    except Exception:
                        pass


engine = AutomationEngine()


async def run_now(user_id: int, count: int = 1) -> list[dict[str, Any]]:
    results = []
    for _ in range(max(1, min(count, 3))):
        await fill_queue(user_id, target=1)
        result = await process_next(user_id)
        if not result:
            break
        results.append(result)
        if result.get("status") in ("FAILED", "WAITING_FOR_APPROVAL", "NEEDS_REVIEW"):
            break
    return results
