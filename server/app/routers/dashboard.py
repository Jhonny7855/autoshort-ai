"""Dashboard aggregate snapshot for the overview page."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request

from ..db import query, query_one
from ..security import require_user
from ..services import automation, youtube

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    user = require_user(request)
    uid = user["id"]
    channel = youtube.selected_channel(uid)
    state = automation.ensure_state(uid)
    schedule = automation.ensure_schedule(uid)

    published_total = query_one("SELECT COUNT(*) AS c FROM published_videos WHERE user_id=?", (uid,)) or {"c": 0}
    views_total = query_one("SELECT COALESCE(SUM(views),0) AS v FROM published_videos WHERE user_id=?", (uid,)) or {"v": 0}
    queue_count = query_one(
        "SELECT COUNT(*) AS c FROM queue_items WHERE user_id=? AND status NOT IN ('PUBLISHED','CANCELLED')",
        (uid,),
    ) or {"c": 0}
    generating = query_one(
        """SELECT COUNT(*) AS c FROM queue_items WHERE user_id=? AND status IN
           ('RESEARCHING','GENERATING_AUDIO','GENERATING_VISUALS','RENDERING','QUALITY_CHECK')""",
        (uid,),
    ) or {"c": 0}
    failed = query_one("SELECT COUNT(*) AS c FROM queue_items WHERE user_id=? AND status='FAILED'", (uid,)) or {"c": 0}

    recent = query(
        """SELECT q.id, q.status, q.updated_at, i.topic, p.quality_score
           FROM queue_items q JOIN content_ideas i ON i.id=q.idea_id
           LEFT JOIN video_projects p ON p.idea_id=q.idea_id
           WHERE q.user_id=? ORDER BY q.updated_at DESC LIMIT 8""",
        (uid,),
    )
    latest_videos = query(
        "SELECT * FROM published_videos WHERE user_id=? ORDER BY COALESCE(published_at, created_at) DESC LIMIT 6",
        (uid,),
    )
    upcoming = query(
        """SELECT q.id, i.topic, q.status, q.position
           FROM queue_items q JOIN content_ideas i ON i.id=q.idea_id
           WHERE q.user_id=? AND q.status IN ('READY_TO_UPLOAD','SCHEDULED','WAITING_FOR_APPROVAL')
           ORDER BY q.position LIMIT 6""",
        (uid,),
    )
    logs = query("SELECT level, scope, message, created_at FROM logs WHERE user_id=? ORDER BY id DESC LIMIT 12", (uid,))
    niche = query_one("SELECT * FROM niches WHERE user_id=? AND active=1", (uid,))

    return {
        "user": {"name": user.get("name"), "email": user.get("email"), "picture": user.get("picture")},
        "channel": channel,
        "niche": niche,
        "automation": {
            "state": state,
            "schedule": schedule,
            "next_publish_at": automation.next_publish_at(schedule),
            "uploads_today": automation.uploads_today(uid, schedule),
        },
        "metrics": {
            "published": published_total["c"],
            "queue": queue_count["c"],
            "generating": generating["c"],
            "failed": failed["c"],
            "views": views_total["v"],
        },
        "recent": recent,
        "latest_videos": latest_videos,
        "upcoming": upcoming,
        "logs": logs,
    }


@router.get("/calendar")
def calendar(request: Request) -> dict[str, Any]:
    user = require_user(request)
    uid = user["id"]
    schedule = automation.ensure_schedule(uid)
    slots = automation.slots_today(schedule)
    tz_name = schedule.get("timezone") or "UTC"
    tz = automation._tz(tz_name)
    now = datetime.now(tz)

    days = []
    for offset in range(0, 14):
        day = now + timedelta(days=offset)
        if day.isoweekday() not in set(schedule.get("days_of_week") or [1, 2, 3, 4, 5, 6, 7]):
            continue
        for slot in slots:
            planned = slot.replace(year=day.year, month=day.month, day=day.day)
            if planned < now - timedelta(minutes=1):
                continue
            days.append(
                {
                    "date": planned.date().isoformat(),
                    "time": planned.strftime("%H:%M"),
                    "iso": planned.isoformat(),
                }
            )
            break
    scheduled = query(
        """SELECT id, title, scheduled_at, status, youtube_video_id FROM published_videos
           WHERE user_id=? AND (status='scheduled' OR scheduled_at IS NOT NULL)
           ORDER BY scheduled_at LIMIT 30""",
        (uid,),
    )
    ready = query(
        """SELECT q.id, i.topic FROM queue_items q JOIN content_ideas i ON i.id=q.idea_id
           WHERE q.user_id=? AND q.status='READY_TO_UPLOAD' ORDER BY q.position LIMIT 20""",
        (uid,),
    )
    return {"planned_slots": days[:20], "scheduled_videos": scheduled, "ready_to_upload": ready, "timezone": tz_name}
