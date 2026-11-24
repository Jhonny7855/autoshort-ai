"""Regression test: linking Google to a local session must not fork the account.

Runs the real FastAPI app in-process through an ASGI transport and stubs only
the three Google network calls, so the callback's account-resolution logic is
exercised for real without contacting Google.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import httpx  # noqa: E402

from app.db import execute, query, query_one  # noqa: E402
from app.main import app  # noqa: E402
from app.services import youtube  # noqa: E402

TEST_SUB = "google-sub-upgrade-test"


async def _fake_exchange(code: str):
    return {
        "access_token": "fake-access",
        "refresh_token": "fake-refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile https://www.googleapis.com/auth/youtube",
    }


async def _fake_userinfo(token: str):
    return {"sub": TEST_SUB, "email": "tester@example.com", "name": "Tester", "locale": "en"}


async def _fake_channels(_uid):
    return []


def _cleanup() -> None:
    """Remove the temp Google link, restoring the local owner row if we took it.

    The callback upgrades the *existing local* user in place, so cleanup must
    put the local identity back instead of deleting the row, otherwise later
    suites find no user and hit foreign-key errors.
    """
    import getpass

    local_sub = f"local:{getpass.getuser()}"
    row = query_one("SELECT id, google_sub FROM users WHERE google_sub=?", (TEST_SUB,))
    if not row:
        return
    user_id = row["id"]
    original = query_one("SELECT id FROM users WHERE google_sub=?", (local_sub,))
    if original and original["id"] != user_id:
        execute("DELETE FROM oauth_tokens WHERE user_id=?", (user_id,))
        return
    execute("DELETE FROM oauth_tokens WHERE user_id=?", (user_id,))
    execute("DELETE FROM google_accounts WHERE user_id=?", (user_id,))
    execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    execute(
        "UPDATE users SET google_sub=?, email=NULL, name=?, picture=NULL, last_login_at=NULL WHERE id=?",
        (local_sub, f"{getpass.getuser()} (local)", user_id),
    )


async def main() -> int:
    youtube.exchange_code = _fake_exchange
    youtube.fetch_userinfo = _fake_userinfo
    youtube.list_channels = _fake_channels

    failures: list[str] = []
    _cleanup()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False) as c:
        login = await c.post("/api/auth/local/login")
        if login.status_code != 200:
            print(f"local login failed: {login.status_code} {login.text[:200]}")
            return 1
        local_id = login.json()["user_id"]
        print(f"local user id={local_id}")

        ideas_before = len((await c.get("/api/content/ideas?limit=100")).json()["ideas"])
        print(f"ideas before link: {ideas_before}")

        start = await c.get("/api/auth/google/start", params={"mode": "link"})
        loc = start.headers.get("location", "")
        state = parse_qs(urlparse(loc).query).get("state", [""])[0]
        print(f"consent redirect host: {urlparse(loc).netloc}")
        if not state:
            failures.append("no state in consent URL")

        cb = await c.get("/api/auth/google/callback", params={"code": "fake-code", "state": state})
        target = cb.headers.get("location", "")
        print(f"callback {cb.status_code} -> {target}")
        if cb.status_code not in (302, 307):
            failures.append(f"callback did not redirect ({cb.status_code})")
        if "/onboarding" not in target:
            failures.append(f"callback did not land on /onboarding: {target}")
        if "5273" in target:
            failures.append(f"callback redirected to the dev-only port: {target}")

        status = (await c.get("/api/auth/status")).json()
        if not status.get("authenticated"):
            failures.append("not authenticated after callback")
        if not status.get("google_linked"):
            failures.append("google not linked after callback")
        if status.get("user", {}).get("id") != local_id:
            failures.append(f"account forked: id {local_id} -> {status.get('user', {}).get('id')}")
        if status.get("google_configured") is not True:
            failures.append("google_configured false after link")

        users = query("SELECT id, google_sub FROM users ORDER BY id")
        print(f"users: {[(u['id'], u['google_sub']) for u in users]}")
        if [u for u in users if str(u["google_sub"]).startswith("local:")]:
            failures.append("local placeholder row survived; it should have been upgraded")
        if len([u for u in users if u["google_sub"] == TEST_SUB]) != 1:
            failures.append("expected exactly one google-linked user row")

        tok = query_one(
            "SELECT access_token_enc, refresh_token_enc, revoked FROM oauth_tokens WHERE user_id=?",
            (local_id,),
        )
        if not tok or not tok.get("access_token_enc") or not tok.get("refresh_token_enc"):
            failures.append("tokens not stored on the upgraded user")
        elif tok.get("revoked"):
            failures.append("tokens marked revoked immediately")

        ideas_after = len((await c.get("/api/content/ideas?limit=100")).json()["ideas"])
        if ideas_after < ideas_before:
            failures.append("ideas were lost during the account upgrade")

        # A second sign-in with the same Google subject must reuse the row.
        start2 = await c.get("/api/auth/google/start", params={"mode": "signin"})
        state2 = parse_qs(urlparse(start2.headers.get("location", "")).query).get("state", [""])[0]
        await c.get("/api/auth/google/callback", params={"code": "fake-code", "state": state2})
        status2 = (await c.get("/api/auth/status")).json()
        if status2.get("user", {}).get("id") != local_id:
            failures.append("repeat sign-in created a second account")
        google_rows = query("SELECT id FROM users WHERE google_sub=?", (TEST_SUB,))
        if len(google_rows) != 1:
            failures.append(f"repeat sign-in duplicated the user ({len(google_rows)} rows)")

        # Signing in from the dev server must return the browser there, not to
        # the backend origin, otherwise the UI lands on a dead port.
        exec_start = await c.get(
            "/api/auth/google/start",
            params={"mode": "signin"},
            headers={"referer": "http://127.0.0.1:5273/"},
        )
        state3 = parse_qs(urlparse(exec_start.headers.get("location", "")).query).get("state", [""])[0]
        cb3 = await c.get("/api/auth/google/callback", params={"code": "fake-code", "state": state3})
        dev_target = cb3.headers.get("location", "")
        print(f"dev-origin callback -> {dev_target}")
        if not dev_target.startswith("http://127.0.0.1:5273/"):
            failures.append(f"dev-origin sign-in did not return to the dev server: {dev_target}")

        # A referer from an origin we do not trust must not be used verbatim.
        evil_start = await c.get(
            "/api/auth/google/start",
            params={"mode": "signin"},
            headers={"referer": "http://evil.example.com/"},
        )
        state4 = parse_qs(urlparse(evil_start.headers.get("location", "")).query).get("state", [""])[0]
        cb4 = await c.get("/api/auth/google/callback", params={"code": "fake-code", "state": state4})
        evil_target = cb4.headers.get("location", "")
        print(f"untrusted-origin callback -> {evil_target}")
        if "evil.example.com" in evil_target:
            failures.append(f"untrusted referer was trusted for the redirect: {evil_target}")

        await c.post("/api/auth/logout")

    _cleanup()
    for f in failures:
        print(f"[FAIL] {f}")
    print("\nAll link checks passed." if not failures else f"\n{len(failures)} failure(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
