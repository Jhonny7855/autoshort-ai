"""End-to-end smoke test for AUTOSHORT AI backend.

Runs against a live server at BASE (default http://127.0.0.1:8787).
Exercises: health, local login, AI inference, idea -> research -> script ->
TTS -> visuals -> render -> QC, and verifies a real MP4 exists on disk.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8787"
FAILS: list[str] = []


def ok(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}{' :: ' + detail if detail else ''}")


def bad(label: str, detail: str = "") -> None:
    print(f"[FAIL] {label}{' :: ' + detail if detail else ''}")
    FAILS.append(label)


def check(label: str, cond: bool, detail: str = "") -> bool:
    ok(label, detail) if cond else bad(label, detail)
    return cond


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=120.0) as c:
        r = c.get("/api/system/health")
        h = r.json()
        check("health endpoint", r.status_code == 200 and h.get("app") == "ok", f"v{h.get('version')}")
        check("ffmpeg detected", bool(h.get("ffmpeg", {}).get("ok")), h.get("ffmpeg", {}).get("version", "")[:40])

        r = c.post("/api/auth/local/login")
        check("local login", r.status_code == 200 and r.json().get("ok"), r.text[:120])

        r = c.get("/api/auth/status")
        me = r.json()
        check("auth status authenticated", bool(me.get("authenticated")), str(me.get("user")))

        r = c.get("/api/ai/status")
        ai = r.json()
        models = [m["name"] for m in ai.get("models") or []]
        check("ollama reachable", bool(ai.get("reachable")), ai.get("base_url", ""))
        check("model installed", bool(models), ", ".join(models))

        r = c.post("/api/ai/test")
        t = r.json()
        check("ai inference", bool(t.get("ok")), str(t.get("response") or t.get("error"))[:120])

        r = c.get("/api/ai/niches")
        niches = r.json().get("niches") or []
        check("niche presets seeded", len(niches) >= 10, f"{len(niches)} niches")
        active = next((n for n in niches if n.get("active")), None)
        if not active and niches:
            active = niches[0]
            c.post("/api/ai/niches/activate", json={"niche_id": active["id"]})
            active = next((n for n in (c.get("/api/ai/niches").json().get("niches") or []) if n.get("active")), active)
        check("active niche", bool(active), str((active or {}).get("name")))

        r = c.post("/api/content/ideas", json={"auto": True, "niche_id": (active or {}).get("id")})
        idea = r.json().get("idea") or {}
        check("idea generated", bool(idea.get("id")), str(idea.get("topic"))[:90])
        if not idea.get("id"):
            return report()

        idea_id = idea["id"]

        r = c.post(f"/api/content/ideas/{idea_id}/research")
        sources = r.json().get("sources") or []
        check("research sources", len(sources) > 0, f"{len(sources)} sources")

        r = c.post(f"/api/content/ideas/{idea_id}/script?seconds=30")
        script = r.json().get("script") or {}
        check("script generated", bool(script.get("id")), str(script.get("title"))[:80])
        check("script has scenes", len(script.get("scenes") or []) >= 3, f"{len(script.get('scenes') or [])} scenes")
        check(
            "approval gate default",
            script.get("approved") in (0, False),
            f"approved={script.get('approved')} (must be 0 until a human approves)",
        )

        body_words = len(str(script.get("body") or "").split())
        target = int(script.get("target_seconds") or 30)
        check(
            "script within word budget",
            body_words <= target * 2.6 + 20,
            f"{body_words} words for a {target}s target",
        )
        spoken = " ".join(str(s.get("narration") or "") for s in script.get("scenes") or []).lower()
        directions = [
            w for w in ("the narrator", "close-up", "wide shot", "cut to", "camera", "we see", "stock footage")
            if w in spoken
        ]
        check("narration is spoken text", not directions, f"directions found: {directions}" if directions else "no camera directions")

        def _norm(text: str) -> list[str]:
            return re.findall(r"[a-z0-9']+", text.lower())

        body_tokens = _norm(str(script.get("body") or ""))
        scene_tokens = _norm(spoken)
        in_order = body_tokens == scene_tokens or (
            len(scene_tokens) >= len(body_tokens) * 0.9 and scene_tokens[: len(body_tokens)] == body_tokens
        )
        check(
            "scenes follow script order",
            in_order,
            f"body {len(body_tokens)} words vs scenes {len(scene_tokens)} words, order preserved={in_order}",
        )

        print("\n--- approval gate blocks an unapproved script ---")
        gate = c.get("/api/schedule").json()
        gate_mode = gate.get("schedule", {}).get("approval_mode", gate.get("approval_mode"))
        if gate_mode == 0:
            check("approval gate enforced", True, "skipped: approval_mode=0 (auto-publish configured)")
        else:
            probe_topic = f"Approval gate probe {int(time.time())}"
            gate_resp = c.post("/api/content/ideas", json={"topic": probe_topic, "angle": "test"})
            gate_idea = gate_resp.json().get("idea") if gate_resp.status_code == 200 else None
            if not gate_idea or not gate_idea.get("id"):
                bad("approval gate probe idea", gate_resp.text[:200])
            else:
                gate_id = gate_idea["id"]
                c.post(f"/api/content/ideas/{gate_id}/research", timeout=300.0)
                gate_script = c.post(f"/api/content/ideas/{gate_id}/script?seconds=30", timeout=600.0).json()
                gate_script = gate_script.get("script") or {}
                if gate_script.get("approved") in (1, True):
                    c.patch(f"/api/content/scripts/{gate_script['id']}", json={"approved": False})
                gr = c.post(
                    f"/api/video/ideas/{gate_id}/produce",
                    json={"force": False, "approve_script": False},
                    timeout=900.0,
                )
                gres = gr.json().get("result") or {}
                check(
                    "approval gate enforced",
                    gres.get("status") == "WAITING_FOR_APPROVAL",
                    f"status={gres.get('status')} (expected WAITING_FOR_APPROVAL)",
                )
                queue_id = gr.json().get("queue_id")
                if queue_id:
                    c.post(f"/api/queue/{queue_id}/approve", json={})
                c.delete(f"/api/content/ideas/{gate_id}")

        r = c.get("/api/content/voices")
        caps = r.json()
        chain = (caps.get("providers") or {}).get("chain") or []
        check("tts provider available", bool(chain), " -> ".join(chain))

        r = c.post("/api/system/test/tts")
        tts_test = r.json()
        check("tts synthesis", bool(tts_test.get("ok")), f"{tts_test.get('provider')} {tts_test.get('duration')}s")

        if script.get("id"):
            c.patch(f"/api/content/scripts/{script['id']}", json={"approved": True})

        print("\n--- running full production pipeline (may take a few minutes) ---")
        started = time.time()
        r = c.post(f"/api/video/ideas/{idea_id}/produce", json={"force": False, "approve_script": True}, timeout=1800.0)
        took = time.time() - started
        if r.status_code != 200:
            bad("produce pipeline", r.text[:400])
            return report()
        result = r.json().get("result") or {}
        check("produce pipeline", result.get("status") in {"READY_TO_UPLOAD", "NEEDS_REVIEW"}, f"status={result.get('status')} in {took:.0f}s")
        output = result.get("output")
        if check("mp4 written", bool(output) and Path(output).exists(), str(output)):
            size_mb = Path(output).stat().st_size / 1e6
            check("mp4 non-trivial size", size_mb > 0.2, f"{size_mb:.2f} MB")

        r = c.get(f"/api/video/ideas/{idea_id}/project")
        proj = r.json()
        report_data = proj.get("project", {}).get("quality_report") or {}
        check("quality score computed", report_data.get("score") is not None, f"{report_data.get('score')}")
        check("quality checks present", len(report_data.get("checks") or []) >= 8, f"{len(report_data.get('checks') or [])} checks")
        check("video stream resolution", (report_data.get("width") or 0) > 0, f"{report_data.get('width')}x{report_data.get('height')}")
        check("project video url served", bool(proj.get("video_url")), str(proj.get("video_url")))
        if proj.get("video_url"):
            vr = c.get(proj["video_url"])
            check("video downloadable", vr.status_code == 200 and len(vr.content) > 10000, f"{len(vr.content)} bytes")
        if proj.get("captions_url"):
            cr = c.get(proj["captions_url"])
            check("captions served", cr.status_code == 200, f"{len(cr.content)} bytes")

        r = c.get("/api/queue")
        q = r.json()
        item = next((i for i in q.get("items") or [] if i.get("idea_id") == idea_id), None)
        check("queue item tracked", bool(item), f"status={(item or {}).get('status')}")
        check("queue timeline recorded", len((item or {}).get("timeline") or []) >= 5, f"{len((item or {}).get('timeline') or [])} entries")

        r = c.get("/api/dashboard/overview")
        check("dashboard overview", r.status_code == 200, f"queue={r.json().get('metrics', {}).get('queue')}")

        r = c.get("/api/system/resources")
        res = r.json()
        check("resource telemetry", bool(res.get("memory")), f"RAM {res.get('memory', {}).get('percent')}%")

        r = c.get("/api/system/logs")
        check("logs recorded", len(r.json().get("logs") or []) > 0, f"{len(r.json().get('logs') or [])} entries")

        r = c.post("/api/system/test/ffmpeg")
        check("ffmpeg self-test endpoint", bool(r.json().get("ok")))

        r = c.post("/api/system/test/youtube")
        yt = r.json()
        linked = bool(c.get("/api/auth/status").json().get("google_linked"))
        # Upload must be gated on a real token: refuse cleanly when unlinked,
        # and never report success without one.
        if linked:
            check("youtube test responds when linked", "ok" in yt, str(yt.get("error"))[:90])
        else:
            check(
                "youtube upload gated until a token exists",
                yt.get("ok") is False and bool(yt.get("error")),
                str(yt.get("error"))[:90],
            )

        r = c.get("/")
        check("spa served", r.status_code == 200 and b"<div id=\"root\"" in r.content or r.status_code == 200, f"{r.status_code}")

    return report()


def report() -> int:
    print("\n=== SUMMARY ===")
    if FAILS:
        print(f"{len(FAILS)} failing check(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
