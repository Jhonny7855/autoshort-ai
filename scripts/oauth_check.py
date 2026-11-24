"""Verify Google OAuth plumbing end-to-end with the credentials in .env.

Does NOT perform the Google consent click (that needs a human browser).
Checks config load, consent URL shape, callback error handling, and that
YouTube upload stays gated with a clean message until a token exists.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402

BASE = "http://127.0.0.1:8787"
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def main() -> int:
    with httpx.Client(base_url=BASE, follow_redirects=False, timeout=30) as c:
        health = c.get("/api/system/health").json()
        check(health.get("google_configured") is True, "health reports google_configured", str(health.get("google_configured")))
        check(health.get("ffmpeg", {}).get("ok") is True, "health reports ffmpeg ok")

        status = c.get("/api/auth/status").json()
        check(status.get("google_configured") is True, "auth status google_configured")
        check(status.get("google_linked") is False, "google_linked false before consent")

        start = c.get("/api/auth/google/start", params={"mode": "signin"})
        check(start.status_code in (302, 307), "consent redirect issued", str(start.status_code))
        loc = start.headers.get("location", "")
        q = parse_qs(urlparse(loc).query)
        check(urlparse(loc).netloc == "accounts.google.com", "consent host is accounts.google.com", urlparse(loc).netloc)
        check(q.get("client_id", [""])[0] == settings.GOOGLE_CLIENT_ID, "consent client_id matches .env")
        check(q.get("redirect_uri", [""])[0] == settings.base_url + "/api/auth/google/callback", "consent redirect_uri matches", q.get("redirect_uri", [""])[0])
        check(q.get("access_type", [""])[0] == "offline", "consent asks offline access (refresh token)")
        check(q.get("prompt", [""])[0] == "consent", "consent forces prompt=consent")
        scopes = q.get("scope", [""])[0].split()
        for needed in ("https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/yt-analytics.readonly"):
            check(needed in scopes, f"scope requested: {needed.split('/auth/')[1]}")
        check("state" in q and len(q["state"][0]) >= 16, "consent carries an opaque state")

        rejected = c.get("/api/auth/google/callback", params={"error": "access_denied"})
        check(rejected.status_code in (302, 307), "denied consent redirects instead of 500", str(rejected.status_code))
        check("auth_error=access_denied" in rejected.headers.get("location", ""), "denied consent surfaces auth_error", rejected.headers.get("location", ""))

        missing = c.get("/api/auth/google/callback")
        check(missing.status_code == 400, "callback without code/state is 400", str(missing.status_code))

        bogus = c.get("/api/auth/google/callback", params={"code": "x", "state": "not-a-real-state"})
        check(bogus.status_code == 400, "callback with unknown state is 400", str(bogus.status_code))
        check("state" in bogus.text.lower(), "unknown state message is explanatory", bogus.json().get("detail", "")[:80])

        login = c.post("/api/auth/local/login")
        check(login.status_code == 200 and login.json().get("ok"), "local owner login works")

        yt = c.post("/api/system/test/youtube")
        yt_json = yt.json() if yt.headers.get("content-type", "").startswith("application/json") else {}
        body = json.dumps(yt_json)[:200]
        check(yt.status_code in (200, 400), "youtube test responds", str(yt.status_code))
        check("No Google token" in body or yt_json.get("ok") is False, "youtube test explains missing token", body)

        uploads = c.get("/api/uploads").json()
        check(isinstance(uploads, (dict, list)), "uploads endpoint readable while unlinked")

        revoke = c.post("/api/auth/google/revoke")
        check(revoke.status_code == 200, "revoke works with no token", str(revoke.status_code))

        c.post("/api/auth/logout")

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} OAuth checks passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
