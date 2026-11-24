"""Ideas, research, scripts and scene editing."""
from __future__ import annotations

from typing import Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..db import dumps, execute, insert, loads, query, query_one, utcnow
from ..security import ensure_owned, require_user
from ..services import pipeline, research, scripts, tts
from ..services.hub import emit

router = APIRouter(prefix="/api/content", tags=["content"])


class IdeaCreate(BaseModel):
    topic: str | None = None
    angle: str | None = None
    niche_id: int | None = None
    auto: bool = False


class ScriptPatch(BaseModel):
    hook: str | None = None
    body: str | None = None
    cta: str | None = None
    title: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None
    keywords: list[str] | None = None
    alt_hooks: list[str] | None = None
    pinned_comment: str | None = None
    voice_direction: str | None = None
    target_seconds: int | None = None
    approved: bool | None = None


class ScenePatch(BaseModel):
    narration: str | None = None
    visual_prompt: str | None = None
    overlay_text: str | None = None
    motion: str | None = None
    transition: str | None = None
    duration: float | None = None


@router.get("/ideas")
def list_ideas(request: Request, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    user = require_user(request)
    sql = "SELECT * FROM content_ideas WHERE user_id=?"
    params: list[Any] = [user["id"]]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 200))
    rows = query(sql, tuple(params))
    return {"ideas": rows}


@router.post("/ideas")
async def create_idea(payload: IdeaCreate, request: Request) -> dict[str, Any]:
    user = require_user(request)
    niche = None
    if payload.niche_id:
        niche = query_one("SELECT * FROM niches WHERE id=? AND user_id=?", (payload.niche_id, user["id"]))
    if payload.auto and not payload.topic:
        idea = await pipeline.create_idea(user["id"], niche=niche)
    else:
        if not payload.topic:
            raise HTTPException(status_code=400, detail="topic or auto=true required")
        idea = await pipeline.create_idea(user["id"], niche=niche, topic=payload.topic, angle=payload.angle)
    return {"idea": idea}


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    idea = ensure_owned("content_ideas", idea_id, user["id"])
    sources = query("SELECT * FROM research_sources WHERE idea_id=? ORDER BY id", (idea_id,))
    script = scripts.get_script(user["id"], idea_id)
    project = query_one("SELECT * FROM video_projects WHERE idea_id=?", (idea_id,))
    if project and project.get("quality_report"):
        project["quality_report"] = loads(project["quality_report"])
    return {"idea": idea, "sources": sources, "script": script, "project": project}


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    ensure_owned("content_ideas", idea_id, user["id"])
    execute("DELETE FROM queue_items WHERE idea_id=? AND user_id=?", (idea_id, user["id"]))
    execute("DELETE FROM content_ideas WHERE id=?", (idea_id,))
    return {"ok": True}


@router.post("/ideas/{idea_id}/research")
async def research_idea(idea_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    idea = ensure_owned("content_ideas", idea_id, user["id"])
    sources = await pipeline.run_research(user["id"], idea)
    return {"sources": sources, "idea": query_one("SELECT * FROM content_ideas WHERE id=?", (idea_id,))}


@router.post("/ideas/{idea_id}/script")
async def generate_script(idea_id: int, request: Request, seconds: int | None = None) -> dict[str, Any]:
    user = require_user(request)
    idea = ensure_owned("content_ideas", idea_id, user["id"])
    sources = query("SELECT * FROM research_sources WHERE idea_id=?", (idea_id,))
    if not sources:
        sources = await pipeline.run_research(user["id"], idea)
    script = await pipeline.run_script(user["id"], idea, sources, seconds=seconds)
    emit(user["id"], "script_ready", {"idea_id": idea_id, "script_id": script.get("id")})
    return {"script": script}


@router.get("/ideas/{idea_id}/script")
def get_script(idea_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    ensure_owned("content_ideas", idea_id, user["id"])
    script = scripts.get_script(user["id"], idea_id)
    if not script:
        raise HTTPException(status_code=404, detail="No script yet")
    return {"script": script}


@router.patch("/scripts/{script_id}")
def patch_script(script_id: int, payload: ScriptPatch, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM scripts WHERE id=? AND user_id=?", (script_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Script not found")
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    script = scripts.update_script(user["id"], script_id, patch)
    return {"script": script}


@router.post("/scripts/{script_id}/scenes/regenerate")
def regenerate_scenes(script_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    row = query_one("SELECT * FROM scripts WHERE id=? AND user_id=?", (script_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Script not found")
    scenes = scripts.regenerate_scenes(script_id, int(row.get("target_seconds") or 45))
    return {"scenes": scenes}


@router.patch("/scenes/{scene_id}")
def patch_scene(scene_id: int, payload: ScenePatch, request: Request) -> dict[str, Any]:
    user = require_user(request)
    scene = query_one(
        """SELECT sc.* FROM scenes sc JOIN scripts s ON s.id=sc.script_id
           WHERE sc.id=? AND s.user_id=?""",
        (scene_id, user["id"]),
    )
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if patch:
        assignments = ", ".join(f"{k}=?" for k in patch)
        execute(f"UPDATE scenes SET {assignments} WHERE id=?", (*patch.values(), scene_id))
    return {"scene": query_one("SELECT * FROM scenes WHERE id=?", (scene_id,))}


@router.get("/voices")
def voices() -> dict[str, Any]:
    return tts.available_voices()


@router.post("/voices/preview")
async def preview_voice(request: Request, voice: str | None = None, provider: str | None = None, text: str = "This is how your narration will sound.") -> dict[str, Any]:
    user = require_user(request)
    out_dir = settings.dirs()["tmp"] / f"preview_{user['id']}"
    try:
        result = await tts.synthesize(text[:200], out_dir, voice=voice, provider=provider or "auto")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rel = Path(result.path).relative_to(settings.media_dir)
    return {"url": "/media/" + str(rel).replace("\\", "/"), "provider": result.provider, "duration": result.duration}
