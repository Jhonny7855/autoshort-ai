"""Google sign-in, session lifecycle, channel linking."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..config import settings
from ..db import execute, insert, log_event, query_one, utcnow
from ..security import (
    clear_session_cookie,
    create_session,
    current_user_optional,
    destroy_session,
    get_session_token,
    require_user,
    set_session_cookie,
)
from ..services import automation, niches, youtube

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ChannelSelect(BaseModel):
    channel_row_id: int


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user.get("email"),
        "name": user.get("name"),
        "picture": user.get("picture"),
        "created_at": user.get("created_at"),
    }


def _ui_base(request: Request, pending: dict[str, Any] | None = None) -> str:
    """Where to send the browser after the Google round-trip.

    The callback is served by the backend, but the UI may be running on the Vite
    dev port or be served by the backend itself. Prefer the origin the sign-in
    started from when it is a known origin, then fall back to the base URL.
    """
    candidates = [
        (pending or {}).get("origin"),
        request.headers.get("origin"),
    ]
    for candidate in candidates:
        if candidate and candidate.rstrip("/") in settings.ALLOWED_ORIGINS:
            return candidate.rstrip("/")
    return settings.base_url


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    user = current_user_optional(request)
    token_row = None
    if user:
        token_row = query_one("SELECT id, scope, expires_at, revoked FROM oauth_tokens WHERE user_id=? AND provider='google'", (user["id"],))
    channel = youtube.selected_channel(user["id"]) if user else None
    return {
        "authenticated": bool(user),
        "user": _public_user(user) if user else None,
        "google_configured": settings.google_configured,
        "google_linked": bool(token_row and not token_row.get("revoked")),
        "channel": channel,
        "local_mode": True,
        # Onboarding is about producing videos locally. Linking a channel only
        # enables optional API upload; it is not required to finish setup.
        "onboarding_complete": bool(
            user and query_one("SELECT id FROM niches WHERE user_id=? AND active=1", (user["id"],))
        ),
    }


@router.get("/google/start")
def google_start(request: Request, mode: str = "signin") -> RedirectResponse:
    user = current_user_optional(request)
    origin = request.headers.get("referer", "")
    if origin:
        parsed = origin.split("/", 3)
        origin = "/".join(parsed[:3]) if len(parsed) >= 3 else ""
    try:
        url = youtube.build_consent_url(
            mode=mode,
            user_id=user["id"] if user else None,
            origin=origin or None,
        )
    except youtube.GoogleAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url)


@router.post("/local/login")
def local_login(request: Request, response: Response) -> dict[str, Any]:
    """Local owner account for a self-hosted install without Google credentials.

    This creates a real local user row. It does NOT create or pretend to have a
    YouTube connection - YouTube features stay locked until Google is linked.
    """
    import getpass

    os_user = getpass.getuser()
    sub = f"local:{os_user}"
    existing = query_one("SELECT * FROM users WHERE google_sub=?", (sub,))
    if existing:
        user_id = existing["id"]
        execute("UPDATE users SET last_login_at=? WHERE id=?", (utcnow(), user_id))
    else:
        user_id = insert(
            "users",
            {
                "google_sub": sub,
                "email": None,
                "name": f"{os_user} (local)",
                "picture": None,
                "locale": "en",
                "created_at": utcnow(),
                "last_login_at": utcnow(),
                "role": "owner",
            },
        )
    niches.ensure_presets(user_id)
    automation.ensure_schedule(user_id)
    automation.ensure_state(user_id)
    token, expires = create_session(user_id, request)
    set_session_cookie(response, token, expires)
    log_event("Local sign-in", scope="auth", user_id=user_id)
    return {"ok": True, "user_id": user_id, "mode": "local"}


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    if error:
        return RedirectResponse(f"{_ui_base(request)}/?auth_error={error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    pending = youtube.consume_state(state)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state. Try signing in again.")

    token_data = await youtube.exchange_code(code)
    info = await youtube.fetch_userinfo(token_data["access_token"])
    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="Google did not return a subject id")

    existing = query_one("SELECT * FROM users WHERE google_sub=?", (sub,))
    if existing:
        user_id = existing["id"]
        execute(
            "UPDATE users SET email=?, name=?, picture=?, locale=?, last_login_at=? WHERE id=?",
            (info.get("email"), info.get("name"), info.get("picture"), info.get("locale"), utcnow(), user_id),
        )
    else:
        # If this browser already holds a local-owner session, upgrade that row
        # instead of creating a second user and orphaning their ideas and queue.
        session_user = current_user_optional(request)
        if session_user and str(session_user.get("google_sub") or "").startswith("local:"):
            user_id = session_user["id"]
            execute(
                "UPDATE users SET google_sub=?, email=?, name=?, picture=?, locale=?, last_login_at=? WHERE id=?",
                (sub, info.get("email"), info.get("name"), info.get("picture"), info.get("locale"), utcnow(), user_id),
            )
            log_event("Local account linked to Google", scope="auth", user_id=user_id)
        else:
            user_id = insert(
                "users",
                {
                    "google_sub": sub,
                    "email": info.get("email"),
                    "name": info.get("name"),
                    "picture": info.get("picture"),
                    "locale": info.get("locale"),
                    "created_at": utcnow(),
                    "last_login_at": utcnow(),
                    "role": "owner",
                },
            )
        insert("google_accounts", {"user_id": user_id, "google_sub": sub, "email": info.get("email"), "scopes": token_data.get("scope"), "created_at": utcnow()})

    youtube.store_tokens(user_id, token_data)
    niches.ensure_presets(user_id)
    automation.ensure_schedule(user_id)
    automation.ensure_state(user_id)
    log_event("Google sign-in", scope="auth", user_id=user_id)

    try:
        channels = await youtube.list_channels(user_id)
        rows = youtube.sync_channels(user_id, channels)
        if rows and not query_one("SELECT id FROM youtube_channels WHERE user_id=? AND is_selected=1", (user_id,)):
            youtube.select_channel(user_id, rows[0]["id"])
    except youtube.GoogleAuthError as exc:
        log_event(f"Channel sync failed: {exc}", level="warn", scope="youtube", user_id=user_id)

    token, expires = create_session(user_id, request)
    response = RedirectResponse(f"{_ui_base(request, pending)}/onboarding")
    set_session_cookie(response, token, expires)
    return response


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    token = get_session_token(request)
    if token:
        destroy_session(token)
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/google/revoke")
def revoke(request: Request) -> dict[str, Any]:
    user = require_user(request)
    execute("UPDATE oauth_tokens SET revoked=1, access_token_enc=NULL, refresh_token_enc=NULL WHERE user_id=?", (user["id"],))
    execute("UPDATE youtube_channels SET is_selected=0 WHERE user_id=?", (user["id"],))
    return {"ok": True}


@router.post("/channels/sync")
async def sync_channels(request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        channels = await youtube.list_channels(user["id"])
    except youtube.GoogleAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = youtube.sync_channels(user["id"], channels)
    return {"channels": rows}


@router.get("/channels")
def list_channels(request: Request) -> dict[str, Any]:
    from ..db import query

    user = require_user(request)
    rows = query("SELECT * FROM youtube_channels WHERE user_id=? ORDER BY id", (user["id"],))
    return {"channels": rows, "selected": youtube.selected_channel(user["id"])}


@router.post("/channels/select")
def select_channel(payload: ChannelSelect, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = youtube.select_channel(user["id"], payload.channel_row_id)
    except youtube.GoogleAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"channel": row}


@router.get("/channel-creation-guide")
def channel_creation_guide() -> dict[str, Any]:
    return {
        "steps": [
            "Open YouTube Studio in a browser and sign in with the same Google account.",
            "Click your profile avatar, then 'Create a channel'.",
            "Choose your channel name and handle, then accept the terms.",
            "Optionally upload an avatar and banner before your first upload.",
            "Return to AUTOSHORT AI and press 'Refresh channels'.",
        ],
        "official_url": "https://www.youtube.com/create_channel",
        "note": (
            "Google does not expose a public API to create channels. AUTOSHORT AI guides you to the "
            "official flow instead of automating account creation."
        ),
    }


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    user = require_user(request)
    return {"user": _public_user(user)}
