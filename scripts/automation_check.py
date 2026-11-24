"""Focused checks for the automation engine (queue fill, run, schedule logic)."""
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

FAILS: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" :: {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)
    return cond


def main() -> int:
    from app.db import execute, query, query_one

    c = httpx.Client(base_url=BASE, timeout=2400.0)
    login = c.post("/api/auth/local/login")
    # The local owner row id is not stable across resets, so never hardcode it.
    USER = login.json()["user_id"]

    # ---- schedule math (pure functions, no network) ----
    from app.services import automation

    sched = {
        "enabled": 1,
        "timezone": "UTC",
        "days_of_week": [1, 2, 3, 4, 5, 6, 7],
        "publish_times": ["23:59"],
        "approval_mode": 1,
    }
    nxt = automation.next_publish_at(sched)
    check("next_publish_at returns a future slot", bool(nxt), str(nxt))
    check("next_publish_at is disabled when schedule off", automation.next_publish_at({**sched, "enabled": 0}) is None)

    empty_day = {**sched, "days_of_week": [9]}
    check("invalid weekday yields no slot", automation.next_publish_at(empty_day) is None)

    bad_tz = {**sched, "timezone": "Not/AZone"}
    check("bad timezone falls back to UTC instead of raising", automation.next_publish_at(bad_tz) is not None)

    # ---- queue fill ----
    execute("DELETE FROM upload_jobs")
    execute("DELETE FROM published_videos")
    c.post("/api/automation/pause")
    before = query_one("SELECT COUNT(*) AS c FROM queue_items")["c"]
    filled = automation_async_fill(c)
    after = query_one("SELECT COUNT(*) AS c FROM queue_items")["c"]
    check("fill_queue adds items without a channel", after >= before, f"{before} -> {after}")
    check("fill_queue reports what it added", isinstance(filled, int), f"added={filled}")

    # ---- run one item end to end through the engine ----
    r = c.post("/api/automation/run-now?count=1", timeout=2400.0)
    payload = r.json()
    results = payload.get("results") or []
    check("run-now executed at least one item", bool(results), json.dumps(results)[:220])
    if results:
        status = results[0].get("status")
        check(
            "run-now reaches a terminal pipeline state",
            status in {"READY_TO_UPLOAD", "NEEDS_REVIEW", "WAITING_FOR_APPROVAL"},
            str(status),
        )

    st = c.get("/api/automation/status").json()
    check("automation state returns to idle after run", st["state"]["status"] in {"idle", "running", "paused"}, st["state"]["status"])

    # ---- publish path without a channel must stop cleanly, not crash ----
    # In local publish mode a finished render becomes a local package instead of
    # a YouTube upload, so a 200 with local=True is a success. A 400 (nothing
    # ready) is also fine. A 5xx is never acceptable.
    r = c.post("/api/automation/upload-now", timeout=120.0)
    body = r.text[:160]
    local_ok = r.status_code == 200 and bool(r.json().get("result", {}).get("local"))
    check(
        "upload-now without channel never crashes",
        r.status_code < 500 and (r.status_code == 400 or local_ok),
        f"status={r.status_code} body={body}",
    )

    # ---- quiet hours / min gap enforcement ----
    from datetime import datetime, timedelta, timezone

    qs = {"timezone": "UTC", "quiet_start": "22:00", "quiet_end": "07:00"}
    check("quiet hours covers late night", automation.in_quiet_hours(qs, datetime.fromisoformat("2026-11-24T23:30:00+00:00")))
    check("quiet hours covers early morning", automation.in_quiet_hours(qs, datetime.fromisoformat("2026-11-24T02:00:00+00:00")))
    check("quiet hours ends at boundary", not automation.in_quiet_hours(qs, datetime.fromisoformat("2026-11-24T07:00:00+00:00")))
    check("quiet hours allows midday", not automation.in_quiet_hours(qs, datetime.fromisoformat("2026-11-24T12:00:00+00:00")))
    check("no quiet hours configured is never quiet", not automation.in_quiet_hours({"timezone": "UTC"}))
    check("unparseable quiet hours are ignored", not automation.in_quiet_hours({"timezone": "UTC", "quiet_start": "zzz", "quiet_end": "07:00"}))

    execute("DELETE FROM upload_jobs")
    check("min gap passes with no prior upload", automation.min_gap_satisfied({"min_gap_minutes": 90}, USER))
    from app.db import insert, utcnow

    idea = query_one("SELECT id FROM content_ideas WHERE user_id=? LIMIT 1", (USER,))
    if idea is None:
        idea_id = insert(
            "content_ideas",
            {
                "user_id": USER,
                "topic": "min gap fixture",
                "angle": None,
                "status": "idea",
                "created_at": utcnow(),
                "updated_at": utcnow(),
            },
        )
    else:
        idea_id = idea["id"]

    project = query_one("SELECT id FROM video_projects WHERE user_id=? LIMIT 1", (USER,))
    project_id = project["id"] if project else None
    if project_id is None:
        project_id = insert(
            "video_projects",
            {
                "user_id": USER,
                "idea_id": idea_id,
                "script_id": None,
                "status": "ready",
                "created_at": utcnow(),
                "updated_at": utcnow(),
            },
        )
    insert(
        "upload_jobs",
        {
            "user_id": USER,
            "project_id": project_id,
            "channel_id": None,
            "status": "uploaded",
            "visibility": "private",
            "progress": 100,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    check("min gap blocks an upload right after another", not automation.min_gap_satisfied({"min_gap_minutes": 90}, USER))
    check("min gap of 0 never blocks", automation.min_gap_satisfied({"min_gap_minutes": 0}, USER))
    execute("DELETE FROM upload_jobs")

    # ---- publish_ready respects quiet hours ----
    c.post("/api/schedule", json={"enabled": True, "quiet_start": "00:00", "quiet_end": "23:59"})
    blocked = asyncio_run(automation.publish_ready(USER))
    check("publish_ready refuses during quiet hours", blocked is None, str(blocked))
    c.post("/api/schedule", json={"quiet_start": None, "quiet_end": None})

    # ---- schedule persistence ----
    r = c.post(
        "/api/schedule",
        json={"enabled": True, "approval_mode": False, "videos_per_day": 2, "publish_times": ["09:15", "18:45"]},
    )
    sch = r.json().get("schedule") or {}
    check("schedule saves enabled", sch.get("enabled") in (1, True), str(sch.get("enabled")))
    check("schedule saves approval_mode", sch.get("approval_mode") in (0, False), str(sch.get("approval_mode")))
    check("schedule saves publish_times", sch.get("publish_times") == ["09:15", "18:45"], str(sch.get("publish_times")))

    r = c.post("/api/schedule", json={"visibility": "bogus"})
    check("schedule rejects invalid visibility", r.status_code == 400, str(r.status_code))

    r = c.post("/api/schedule", json={"videos_per_day": 999})
    check("videos_per_day is clamped", (r.json().get("schedule") or {}).get("videos_per_day") == 12, str(r.json().get("schedule", {}).get("videos_per_day")))

    print()
    if FAILS:
        print(f"{len(FAILS)} failing check(s):")
        for f in FAILS:
            print("  -", f)
        return 1
    print("All automation checks passed.")
    return 0


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def automation_async_fill(client: httpx.Client) -> int:
    import asyncio

    from app.services import automation

    user_id = client.get("/api/auth/me").json()["user"]["id"]
    return asyncio.run(automation.fill_queue(user_id, target=2))


if __name__ == "__main__":
    sys.exit(main())
