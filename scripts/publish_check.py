"""Local publishing verification: no Google credentials anywhere in the path.

Covers package creation from a real render, the dashboard buckets, manual
confirmation, download/thumbnail serving, metadata copy payloads, scheduling and
the daily generation scheduler. Requires a live server and a produced video.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
FAILS: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" :: {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)
    return cond


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=2400.0) as c:
        c.post("/api/auth/local/login")

        health = c.get("/api/system/health").json()
        check("app healthy without Google credentials", health.get("app") == "ok")
        check("google_configured is false", health.get("google_configured") is False, str(health.get("google_configured")))

        auth = c.get("/api/auth/status").json()
        check("authenticated in local mode", auth.get("authenticated") is True)
        check("local_mode reported", auth.get("local_mode") is True)
        check("no google token required", auth.get("google_linked") is False)

        ob = c.get("/api/system/onboarding/check").json()
        check("onboarding ready without a channel", ob.get("ready") is True, f"ready={ob.get('ready')} channel={ob.get('channel')}")
        check("onboarding marks local mode", ob.get("local_mode") is True)

        # ---- daily generation scheduler ----
        daily = c.get("/api/automation/daily").json()
        check("daily schedule exists", "next_run_at" in daily, str(daily.get("next_run_at")))
        check("daily generation enabled by default", daily.get("enabled") is True)

        r = c.post("/api/automation/daily", json={"at": "25:99"})
        check("daily rejects an invalid time", r.status_code == 400, str(r.status_code))
        r = c.post("/api/automation/daily", json={"at": "06:30", "per_day": 2})
        check("daily accepts a valid time", r.status_code == 200, str(r.status_code))
        check("daily persists the time", r.json().get("at") == "06:30", str(r.json().get("at")))
        check("daily persists per_day", r.json().get("per_day") == 2, str(r.json().get("per_day")))
        r = c.post("/api/automation/daily", json={"per_day": 99})
        check("daily clamps per_day", r.json().get("per_day") == 12, str(r.json().get("per_day")))
        c.post("/api/automation/daily", json={"at": "08:00", "per_day": 1, "enabled": True})

        # ---- generate one video locally ----
        # Approval mode is on by default, which stops after the script. Turn it
        # off so the full render path runs and a package is produced.
        c.post("/api/schedule", json={"approval_mode": False})
        print("\n-- generating one video locally (this renders with FFmpeg) --")
        gen = c.post("/api/automation/daily/run?count=1", timeout=2400.0)
        body = gen.json()
        results = body.get("results") or []
        check("daily run produced a result", bool(results), str(body.get("counts")))
        status = results[0].get("status") if results else None
        check(
            "generation reached a terminal state",
            status in {"READY_TO_UPLOAD", "NEEDS_REVIEW", "WAITING_FOR_APPROVAL"},
            str(status),
        )

        # ---- publishing dashboard ----
        pub = c.get("/api/publish").json()
        records = pub.get("records") or []
        check("publish records exist after generation", bool(records), f"{len(records)} records")
        groups = pub.get("groups") or {}
        for bucket in ("ready", "pending_review", "scheduled", "published", "failed"):
            check(f"dashboard bucket present: {bucket}", bucket in groups)
        check("counts match records", sum((pub.get("counts") or {}).values()) == len(records), str(pub.get("counts")))

        if not records:
            print("\nNo publish record to exercise; stopping early.")
            return report()

        rec = records[0]
        rid = rec["id"]
        check("record has a download url", bool(rec.get("download_url")), str(rec.get("download_url")))
        check("record is not published yet", rec["status"] != "published", rec["status"])

        # ---- package metadata / copy payload ----
        pkg = c.get(f"/api/publish/{rid}/package").json()
        check("package exposes a title", bool(pkg.get("title")), str(pkg.get("title"))[:40])
        check("package exposes copy fields", all(k in (pkg.get("copy") or {}) for k in ("title", "description", "hashtags")))
        check("package points at YouTube Studio", pkg.get("studio_url") == "https://studio.youtube.com", str(pkg.get("studio_url")))
        check("package includes a hashtag line", isinstance(pkg.get("hashtag_line"), str))

        # ---- download ----
        dl = c.get(f"/api/publish/{rid}/download")
        check("download returns the MP4", dl.status_code == 200 and dl.headers.get("content-type", "").startswith("video/"), f"{dl.status_code} {dl.headers.get('content-type')}")
        check("downloaded file is not empty", len(dl.content) > 10000, f"{len(dl.content)} bytes")
        check("download sets a filename", "attachment" in dl.headers.get("content-disposition", ""), dl.headers.get("content-disposition", "")[:60])

        thumb = c.get(f"/api/publish/{rid}/thumbnail")
        check("thumbnail endpoint responds", thumb.status_code in (200, 404), str(thumb.status_code))

        # ---- scheduling ----
        sched = c.post(f"/api/publish/{rid}/schedule", json={"scheduled_at": "2026-12-01 09:00"})
        check("schedule accepted", sched.status_code == 200, str(sched.status_code))
        check("status becomes scheduled", sched.json()["record"]["status"] == "scheduled", sched.json()["record"]["status"])
        cleared = c.post(f"/api/publish/{rid}/schedule", json={"scheduled_at": None})
        check("schedule can be cleared", cleared.json()["record"]["status"] in ("ready", "pending_review"), cleared.json()["record"]["status"])

        # ---- manual confirmation is the only way to publish ----
        bad = c.post(f"/api/publish/{rid}/confirm", json={"youtube_url": "not-a-url"})
        check("confirmation rejects a non-YouTube url", bad.status_code == 400, str(bad.status_code))
        empty = c.post(f"/api/publish/{rid}/confirm", json={"youtube_url": "   "})
        check("confirmation rejects an empty url", empty.status_code == 400, str(empty.status_code))
        still = c.get(f"/api/publish/{rid}").json()["record"]
        check("nothing was published by the rejected attempts", still["status"] != "published", still["status"])

        confirm = c.post(
            f"/api/publish/{rid}/confirm",
            json={"youtube_url": "https://www.youtube.com/shorts/dQw4w9WgXcQ"},
        )
        check("confirmation accepted a real URL", confirm.status_code == 200, str(confirm.status_code))
        confirmed = confirm.json()["record"]
        check("status becomes published", confirmed["status"] == "published", confirmed["status"])
        check("youtube url stored", confirmed["youtube_url"].endswith("dQw4w9WgXcQ"), str(confirmed["youtube_url"]))
        check("video id parsed", confirmed["youtube_video_id"] == "dQw4w9WgXcQ", str(confirmed["youtube_video_id"]))
        check("published_at recorded", bool(confirmed["published_at"]))

        pub2 = c.get("/api/publish").json()
        check("published bucket now populated", len(pub2["groups"]["published"]) >= 1, str(pub2["counts"]))

        # ---- metadata editing is locked after publication ----
        locked = c.patch(f"/api/publish/{rid}", json={"title": "changed"})
        check("published metadata is immutable", locked.status_code == 400, str(locked.status_code))

        # ---- analytics must not claim YouTube data without a token ----
        an = c.get("/api/analytics").json()
        check("analytics totals are zero without YouTube", (an.get("totals") or {}).get("views", 0) == 0, str(an.get("totals")))
        check("no fabricated analytics series", (an.get("series") or []) == [], str(len(an.get("series") or [])))

    return report()


def report() -> int:
    print("\n=== SUMMARY ===")
    if FAILS:
        print(f"{len(FAILS)} failing check(s):")
        for f in FAILS:
            print("  -", f)
        return 1
    print("All publishing checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
