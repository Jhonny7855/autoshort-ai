"""AI engine status, model management, settings, niches."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import execute, insert, query, query_one, utcnow
from ..security import require_user
from ..services import ai, niches, pipeline

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ModelPull(BaseModel):
    name: str


class NicheActivate(BaseModel):
    niche_id: int


class SettingUpdate(BaseModel):
    key: str
    value: Any


@router.get("/status")
async def ai_status() -> dict[str, Any]:
    info = await ai.health()
    models = info.get("models") or []
    recommendation = "llama3.2:3b"
    total_gb = 0.0
    try:
        from ..services.system import snapshot

        total_gb = snapshot()["memory"].get("total_gb") or 0.0
    except Exception:
        pass
    if total_gb >= 14:
        recommendation = "llama3.1:8b"
    elif total_gb >= 8:
        recommendation = "llama3.2:3b"
    else:
        recommendation = "qwen2.5:1.5b"
    return {
        **info,
        "recommended_model": recommendation,
        "install_hint": "Install Ollama from https://ollama.com/download then run: ollama pull " + recommendation,
        "usable": bool(models),
    }


@router.post("/models/pull")
async def pull_model(payload: ModelPull, request: Request) -> StreamingResponse:
    require_user(request)
    name = payload.name.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=400, detail="Invalid model name")

    async def stream():
        try:
            async for chunk in ai.pull_model(name):
                status = chunk.get("status", "")
                total = chunk.get("total")
                completed = chunk.get("completed")
                pct = round(completed / total * 100, 1) if total and completed else None
                yield f'data: {{"status": "{status}", "percent": {pct if pct is not None else "null"}}}\n\n'
        except Exception as exc:  # noqa: BLE001
            yield f'data: {{"error": "{str(exc)[:200]}"}}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/models/select")
def select_model(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    user = require_user(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Model name required")
    pipeline.set_setting(user["id"], "ai_model", name)
    return {"ok": True, "model": name}


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    user = require_user(request)
    return {"settings": pipeline.effective_settings(user["id"])}


@router.post("/settings")
def update_settings(payload: SettingUpdate, request: Request) -> dict[str, Any]:
    user = require_user(request)
    pipeline.set_setting(user["id"], payload.key, payload.value)
    return {"settings": pipeline.effective_settings(user["id"])}


@router.get("/niches")
def list_niches(request: Request) -> dict[str, Any]:
    user = require_user(request)
    niches.ensure_presets(user["id"])
    rows = query("SELECT * FROM niches WHERE user_id=? ORDER BY total_score DESC", (user["id"],))
    return {"niches": rows, "active": niches.active_niche(user["id"])}


@router.post("/niches/score")
async def score_niches(request: Request) -> dict[str, Any]:
    user = require_user(request)
    rows = await niches.score_niches(user["id"])
    return {"niches": rows}


@router.post("/niches/activate")
def activate_niche(payload: NicheActivate, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = niches.set_active(user["id"], payload.niche_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"niche": row}


@router.post("/test")
async def test_ai(request: Request) -> dict[str, Any]:
    require_user(request)
    try:
        text = await ai.generate("Reply with exactly: AUTOSHORT AI local model online.", temperature=0.2, num_predict=40)
        return {"ok": True, "response": text[:300]}
    except ai.AIError as exc:
        return {"ok": False, "error": str(exc)}
