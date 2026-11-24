"""Google OAuth 2.0 (authorization-code + PKCE-less web flow) and YouTube Data API.

Only official endpoints are used. No password handling, no scraping, no
CAPTCHA bypass. Tokens are stored encrypted and never sent to the frontend.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings
from ..crypto import decrypt, encrypt
from ..db import execute, insert, log_event, query_one, utcnow

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

_pending_states: dict[str, dict[str, Any]] = {}


class GoogleAuthError(RuntimeError):
    pass


def redirect_uri() -> str:
    return settings.base_url + settings.GOOGLE_REDIRECT_PATH


def configured() -> bool:
    return settings.google_configured


def build_consent_url(*, mode: str = "signin", user_id: int | None = None, origin: str | None = None) -> str:
    if not configured():
        raise GoogleAuthError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env."
        )
    state = secrets.token_urlsafe(24)
    _pending_states[state] = {
        "created": time.time(),
        "mode": mode,
        "user_id": user_id,
        "origin": origin,
    }
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(settings.GOOGLE_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return f"{GOOGLE_AUTH}?{query}"


def consume_state(state: str) -> dict[str, Any] | None:
    now = time.time()
    for key in [k for k, v in _pending_states.items() if now - v["created"] > 900]:
        _pending_states.pop(key, None)
    return _pending_states.pop(state, None)


async def exchange_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise GoogleAuthError(f"Token exchange failed ({r.status_code}): {r.text[:300]}")
    return r.json()


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code != 200:
        raise GoogleAuthError(f"Userinfo failed ({r.status_code})")
    return r.json()


def store_tokens(user_id: int, token_data: dict[str, Any]) -> None:
    expires_at = None
    if token_data.get("expires_in"):
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(token_data["expires_in"]) - 30)
        ).isoformat(timespec="seconds")
    existing = query_one("SELECT id, refresh_token_enc FROM oauth_tokens WHERE user_id=? AND provider='google'", (user_id,))
    refresh_enc = encrypt(token_data["refresh_token"]) if token_data.get("refresh_token") else (existing or {}).get("refresh_token_enc")
    payload = {
        "access_token_enc": encrypt(token_data.get("access_token", "")),
        "refresh_token_enc": refresh_enc,
        "token_type": token_data.get("token_type", "Bearer"),
        "scope": token_data.get("scope"),
        "expires_at": expires_at,
        "updated_at": utcnow(),
        "revoked": 0,
    }
    if existing:
        assignments = ", ".join(f"{k}=?" for k in payload)
        execute(f"UPDATE oauth_tokens SET {assignments} WHERE id=?", (*payload.values(), existing["id"]))
    else:
        insert("oauth_tokens", {"user_id": user_id, "provider": "google", **payload})


async def _refresh(user_id: int, refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            GOOGLE_TOKEN,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        raise GoogleAuthError(
            f"Token refresh failed ({r.status_code}). The user may need to reconnect Google. {r.text[:200]}"
        )
    data = r.json()
    store_tokens(user_id, {**data, "refresh_token": refresh_token})
    return data["access_token"]


async def access_token_for(user_id: int) -> str | None:
    row = query_one("SELECT * FROM oauth_tokens WHERE user_id=? AND provider='google' AND revoked=0", (user_id,))
    if not row:
        return None
    expires = row.get("expires_at") or ""
    access = decrypt(row.get("access_token_enc") or "")
    try:
        expired = datetime.fromisoformat(expires) <= datetime.now(timezone.utc)
    except ValueError:
        expired = True
    if access and not expired:
        return access
    refresh = decrypt(row.get("refresh_token_enc") or "")
    if not refresh:
        return access or None
    if not configured():
        return access or None
    try:
        return await _refresh(user_id, refresh)
    except GoogleAuthError as exc:
        log_event(str(exc), level="error", scope="youtube", user_id=user_id)
        return access or None


async def revoke(user_id: int) -> None:
    row = query_one("SELECT * FROM oauth_tokens WHERE user_id=? AND provider='google'", (user_id,))
    if not row:
        return
    token = decrypt(row.get("refresh_token_enc") or "") or decrypt(row.get("access_token_enc") or "")
    if token and configured():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(GOOGLE_REVOKE, data={"token": token})
        except Exception:
            pass
    execute("UPDATE oauth_tokens SET revoked=1, access_token_enc=NULL, refresh_token_enc=NULL WHERE id=?", (row["id"],))


async def list_channels(user_id: int) -> list[dict[str, Any]]:
    token = await access_token_for(user_id)
    if not token:
        raise GoogleAuthError("No Google token available. Connect your Google account first.")
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(
            f"{YOUTUBE_API}/channels",
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 401:
        raise GoogleAuthError("YouTube authorization expired. Reconnect your Google account.")
    if r.status_code != 200:
        raise GoogleAuthError(f"YouTube API error {r.status_code}: {r.text[:300]}")
    items = r.json().get("items", [])
    channels = []
    for item in items:
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        thumbs = snippet.get("thumbnails", {})
        channels.append(
            {
                "channel_id": item.get("id"),
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "custom_url": snippet.get("customUrl"),
                "thumbnail": (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url"),
                "country": snippet.get("country"),
                "subscriber_count": int(stats["subscriberCount"]) if stats.get("subscriberCount") else None,
                "video_count": int(stats["videoCount"]) if stats.get("videoCount") else None,
                "view_count": int(stats["viewCount"]) if stats.get("viewCount") else None,
            }
        )
    return channels


def sync_channels(user_id: int, channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ch in channels:
        existing = query_one(
            "SELECT id FROM youtube_channels WHERE user_id=? AND channel_id=?", (user_id, ch["channel_id"])
        )
        payload = {
            "title": ch.get("title"),
            "description": ch.get("description"),
            "custom_url": ch.get("custom_url"),
            "thumbnail": ch.get("thumbnail"),
            "country": ch.get("country"),
            "subscriber_count": ch.get("subscriber_count"),
            "video_count": ch.get("video_count"),
            "view_count": ch.get("view_count"),
            "updated_at": utcnow(),
        }
        if existing:
            assignments = ", ".join(f"{k}=?" for k in payload)
            execute(f"UPDATE youtube_channels SET {assignments} WHERE id=?", (*payload.values(), existing["id"]))
            rows.append(query_one("SELECT * FROM youtube_channels WHERE id=?", (existing["id"],)))
        else:
            new_id = insert(
                "youtube_channels",
                {"user_id": user_id, "channel_id": ch["channel_id"], "created_at": utcnow(), **payload},
            )
            rows.append(query_one("SELECT * FROM youtube_channels WHERE id=?", (new_id,)))
    return [r for r in rows if r]


def selected_channel(user_id: int) -> dict[str, Any] | None:
    return query_one(
        "SELECT * FROM youtube_channels WHERE user_id=? AND is_selected=1", (user_id,)
    ) or query_one("SELECT * FROM youtube_channels WHERE user_id=? ORDER BY id LIMIT 1", (user_id,))


def select_channel(user_id: int, channel_row_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM youtube_channels WHERE id=? AND user_id=?", (channel_row_id, user_id))
    if not row:
        raise GoogleAuthError("Channel not found for this account")
    execute("UPDATE youtube_channels SET is_selected=0 WHERE user_id=?", (user_id,))
    execute("UPDATE youtube_channels SET is_selected=1 WHERE id=?", (channel_row_id,))
    return {**row, "is_selected": 1}


async def upload_video(
    user_id: int,
    *,
    file_path: str,
    title: str,
    description: str,
    tags: list[str],
    visibility: str,
    publish_at: str | None = None,
) -> dict[str, Any]:
    """Resumable upload via the official YouTube Data API v3."""
    token = await access_token_for(user_id)
    if not token:
        raise GoogleAuthError("No valid Google token. Reconnect your YouTube account.")

    import json as _json
    import os

    size = os.path.getsize(file_path)
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [t for t in tags if t][:30],
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": visibility if not publish_at else "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        metadata["status"]["publishAt"] = publish_at

    async with httpx.AsyncClient(timeout=None) as client:
        init = await client.post(
            f"{YOUTUBE_API}/videos",
            params={"part": "snippet,status", "uploadType": "resumable"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/mp4",
            },
            content=_json.dumps(metadata).encode("utf-8"),
        )
        if init.status_code not in (200, 201):
            raise GoogleAuthError(f"Upload session failed ({init.status_code}): {init.text[:300]}")
        session_url = init.headers.get("location")
        if not session_url:
            raise GoogleAuthError("YouTube did not return an upload session URL")

        with open(file_path, "rb") as fh:
            body = fh.read()
        put = await client.put(
            session_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
            content=body,
        )
    if put.status_code not in (200, 201):
        raise GoogleAuthError(f"Upload failed ({put.status_code}): {put.text[:400]}")
    data = put.json()
    return {"video_id": data.get("id"), "raw": data}


async def fetch_my_videos(user_id: int, max_results: int = 25) -> list[dict[str, Any]]:
    token = await access_token_for(user_id)
    if not token:
        return []
    channel = selected_channel(user_id)
    if not channel:
        return []
    uploads = "UU" + channel["channel_id"][2:] if channel["channel_id"].startswith("UC") else None
    if not uploads:
        return []
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(
            f"{YOUTUBE_API}/playlistItems",
            params={"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": min(max_results, 50)},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        ids = [i["contentDetails"]["videoId"] for i in items if i.get("contentDetails", {}).get("videoId")]
        if not ids:
            return []
        v = await client.get(
            f"{YOUTUBE_API}/videos",
            params={"part": "snippet,statistics,status", "id": ",".join(ids[:50])},
            headers={"Authorization": f"Bearer {token}"},
        )
    if v.status_code != 200:
        return []
    out = []
    for item in v.json().get("items", []):
        stats = item.get("statistics", {})
        out.append(
            {
                "youtube_video_id": item.get("id"),
                "title": item.get("snippet", {}).get("title"),
                "description": item.get("snippet", {}).get("description"),
                "published_at": item.get("snippet", {}).get("publishedAt"),
                "thumbnail": (
                    item.get("snippet", {}).get("thumbnails", {}).get("medium", {}) or {}
                ).get("url"),
                "visibility": item.get("status", {}).get("privacyStatus"),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "channel_id": item.get("snippet", {}).get("channelId"),
            }
        )
    return out
