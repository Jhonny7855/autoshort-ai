"""System telemetry, logs, storage and settings pages."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..db import dumps, execute, insert, query, query_one, utcnow
from ..security import require_user
from ..services import ai, pipeline, system, youtube

router = APIRouter(prefix="/api/system", tags=["system"])


class SettingPayload(BaseModel):
    key: str
    value: Any


@router.get("/health")
def health() -> dict[str, Any]:
    from ..services.renderer import check_ffmpeg

    return {
        "app": "ok",
        "version": settings.APP_VERSION,
        "ffmpeg": check_ffmpeg(),
        "google_configured": settings.google_configured,
        "data_dir": str(settings.DATA_DIR),
        "serve_web": settings.WEB_DEV_URL,
    }


@router.get("/resources")
def resources(request: Request) -> dict[str, Any]:
    require_user(request)
    snap = system.snapshot()
    models = query("SELECT * FROM ai_models ORDER BY id DESC LIMIT 20")
    return {**snap, "models": models}


@router.post("/resources/cleanup")
def cleanup(request: Request) -> dict[str, Any]:
    require_user(request)
    return system.cleanup_temp()


@router.get("/logs")
def logs(request: Request, level: str | None = None, limit: int = 100) -> dict[str, Any]:
    user = require_user(request)
    sql = "SELECT * FROM logs WHERE (user_id=? OR user_id IS NULL)"
    params: list[Any] = [user["id"]]
    if level:
        sql += " AND level=?"
        params.append(level)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 500))
    rows = query(sql, tuple(params))
    return {"logs": rows}


@router.delete("/logs")
def clear_logs(request: Request) -> dict[str, Any]:
    user = require_user(request)
    execute("DELETE FROM logs WHERE user_id=?", (user["id"],))
    return {"ok": True}


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    user = require_user(request)
    cfg = pipeline.effective_settings(user["id"])
    channel = youtube.selected_channel(user["id"])
    token = query_one("SELECT scope, expires_at, revoked FROM oauth_tokens WHERE user_id=?", (user["id"],))
    return {
        "settings": cfg,
        "channel": channel,
        "google": {
            "configured": settings.google_configured,
            "linked": bool(token and not token.get("revoked")),
            "scope": (token or {}).get("scope"),
            "expires_at": (token or {}).get("expires_at"),
        },
        "paths": {k: str(v) for k, v in settings.dirs().items()},
    }


@router.post("/settings")
def save_settings(payload: SettingPayload, request: Request) -> dict[str, Any]:
    user = require_user(request)
    pipeline.set_setting(user["id"], payload.key, payload.value)
    return {"settings": pipeline.effective_settings(user["id"])}


@router.post("/test/ffmpeg")
def test_ffmpeg(request: Request) -> dict[str, Any]:
    require_user(request)
    from ..services.renderer import check_ffmpeg

    return check_ffmpeg()


@router.post("/test/tts")
async def test_tts(request: Request) -> dict[str, Any]:
    require_user(request)
    from ..services import tts

    cfg = pipeline.effective_settings(request.state.user["id"]) if hasattr(request.state, "user") else {}
    try:
        out_dir = settings.dirs()["tmp"] / "tts_test"
        result = await tts.synthesize("Audio check complete.", out_dir, provider=cfg.get("tts_provider") or "auto")
        return {"ok": True, "provider": result.provider, "duration": result.duration}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.post("/test/youtube")
async def test_youtube(request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        channels = await youtube.list_channels(user["id"])
    except youtube.GoogleAuthError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "channels": len(channels)}


@router.get("/onboarding/check")
async def onboarding_check(request: Request) -> dict[str, Any]:
    user = require_user(request)
    ai_info = await ai.health()
    channel = youtube.selected_channel(user["id"])
    niche = query_one("SELECT * FROM niches WHERE user_id=? AND active=1", (user["id"],))
    from ..services import tts
    from ..services.renderer import check_ffmpeg

    ffmpeg_ok = check_ffmpeg()["ok"]
    # A channel is optional: local mode produces finished Shorts and packages
    # them for manual upload, so setup must not block on Google.
    return {
        "google": settings.google_configured,
        "ai": {"reachable": ai_info["reachable"], "models": len(ai_info.get("models") or [])},
        "tts": tts.capabilities()["chain"],
        "ffmpeg": ffmpeg_ok,
        "channel": channel,
        "niche": niche,
        "local_mode": True,
        "ready": bool(ai_info.get("models") and niche and ffmpeg_ok),
    }
