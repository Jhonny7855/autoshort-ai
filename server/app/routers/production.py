"""Video production, rendering previews, quality reports and asset serving."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..db import dumps, execute, insert, loads, query, query_one, utcnow
from ..security import ensure_owned, require_user
from ..services import pipeline, renderer, scripts, subtitles
from ..services.hub import emit

router = APIRouter(prefix="/api/video", tags=["video"])


class ProduceRequest(BaseModel):
    force: bool = False
    approve_script: bool = False


class RenderRequest(BaseModel):
    preset: str = "balanced"
    subtitle_style: str | None = None
    music_enabled: bool | None = None


class ThumbPatch(BaseModel):
    overlay_text: str | None = None


def _project(user_id: int, idea_id: int) -> dict[str, Any]:
    project = query_one("SELECT * FROM video_projects WHERE idea_id=? AND user_id=?", (idea_id, user_id))
    if not project:
        raise HTTPException(status_code=404, detail="No project for this idea yet")
    return project


@router.post("/ideas/{idea_id}/produce")
async def produce(idea_id: int, payload: ProduceRequest, request: Request) -> dict[str, Any]:
    user = require_user(request)
    ensure_owned("content_ideas", idea_id, user["id"])
    queue = query_one("SELECT * FROM queue_items WHERE idea_id=?", (idea_id,))
    if not queue:
        queue = await pipeline.enqueue_idea(user["id"], idea_id)
    if payload.approve_script:
        script = scripts.get_script(user["id"], idea_id)
        if script:
            scripts.update_script(user["id"], script["id"], {"approved": 1})
    try:
        result = await pipeline.produce_video(user["id"], queue["id"], force=payload.force)
    except pipeline.PipelineError as exc:
        execute("UPDATE queue_items SET status='FAILED', last_error=?, updated_at=? WHERE id=?", (str(exc), utcnow(), queue["id"]))
        pipeline.timeline_add(queue["id"], "FAILED", str(exc))
        emit(user["id"], "pipeline_error", {"queue_id": queue["id"], "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    emit(user["id"], "pipeline_done", {"queue_id": queue["id"], "result": result.get("status")})
    return {"result": result, "queue_id": queue["id"]}


@router.get("/ideas/{idea_id}/project")
def get_project(idea_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    # An idea that has not been produced yet is a normal state, not an error:
    # return an empty project payload so the studio can offer "Produce" instead
    # of logging a failed request in the browser console.
    project = query_one("SELECT * FROM video_projects WHERE idea_id=? AND user_id=?", (idea_id, user["id"]))
    if not project:
        return {"project": None, "scenes": [], "render_jobs": [], "video_url": None, "music_url": None, "captions_url": None}
    if project.get("quality_report"):
        project["quality_report"] = loads(project["quality_report"])
    scenes = []
    if project.get("script_id"):
        scenes = scripts.scenes_for(project["script_id"])
        for scene in scenes:
            if scene.get("asset_id"):
                asset = query_one("SELECT url FROM assets WHERE id=?", (scene["asset_id"],))
                scene["asset_url"] = asset.get("url") if asset else None
            if scene.get("audio_id"):
                audio = query_one("SELECT path FROM audio_files WHERE id=?", (scene["audio_id"],))
                scene["audio_url"] = _media_url(audio.get("path")) if audio else None
    jobs = query("SELECT * FROM render_jobs WHERE project_id=? ORDER BY id DESC LIMIT 10", (project["id"],))
    return {
        "project": project,
        "scenes": scenes,
        "render_jobs": jobs,
        "video_url": _media_url(project.get("output_path")),
        "music_url": _media_url(project.get("music_path")),
        "captions_url": _media_url(project.get("subtitle_path")),
    }


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(settings.media_dir.resolve())
    except ValueError:
        return None
    return "/media/" + str(rel).replace("\\", "/")


@router.post("/ideas/{idea_id}/rerender")
async def rerender(idea_id: int, payload: RenderRequest, request: Request) -> dict[str, Any]:
    user = require_user(request)
    project = _project(user["id"], idea_id)
    if not project.get("script_id"):
        raise HTTPException(status_code=400, detail="Project has no script")
    scenes = scripts.scenes_for(project["script_id"])
    if not scenes:
        raise HTTPException(status_code=400, detail="Project has no scenes")
    cfg = pipeline.effective_settings(user["id"])

    scene_payload = []
    for scene in scenes:
        asset = query_one("SELECT path FROM assets WHERE id=?", (scene["asset_id"],)) if scene.get("asset_id") else None
        audio = query_one("SELECT path FROM audio_files WHERE id=?", (scene["audio_id"],)) if scene.get("audio_id") else None
        if not asset or not Path(asset["path"]).exists():
            raise HTTPException(status_code=400, detail=f"Scene {scene['scene_no']} missing visual")
        if not audio or not Path(audio["path"]).exists():
            raise HTTPException(status_code=400, detail=f"Scene {scene['scene_no']} missing narration")
        scene_payload.append({**scene, "asset_path": asset["path"], "audio_path": audio["path"]})

    if payload.subtitle_style:
        pipeline.set_setting(user["id"], "subtitle_style", payload.subtitle_style)
    if payload.music_enabled is not None:
        pipeline.set_setting(user["id"], "music_enabled", payload.music_enabled)

    cfg = pipeline.effective_settings(user["id"])
    subs = pipeline.build_subtitles(
        user["id"],
        query_one("SELECT * FROM scripts WHERE id=?", (project["script_id"],)) or {},
        scenes,
        total_override=sum(float(s.get("duration") or 3) for s in scenes),
    )
    music_path = None
    if cfg.get("music_enabled", True):
        bed = settings.dirs()["music"] / f"auto_{idea_id}.wav"
        from ..services import visuals

        total = sum(float(s.get("duration") or 3) for s in scenes) + 1
        gen = visuals.music_bed(total, bed, mood="uplifting")
        music_path = str(gen) if gen else None

    job_id = insert(
        "render_jobs",
        {
            "project_id": project["id"],
            "preset": payload.preset,
            "status": "running",
            "progress": 0,
            "step": "starting",
            "started_at": utcnow(),
            "created_at": utcnow(),
        },
    )
    try:
        result = await __import__("asyncio").to_thread(
            renderer.render_project,
            project,
            scene_payload,
            voice_path=project.get("voice_path"),
            music_path=music_path,
            subtitle_file=subs.get("path"),
            preset_key=payload.preset,
            music_volume=float(cfg.get("music_volume") or 0.18),
            job_id=job_id,
        )
    except renderer.RenderError as exc:
        execute("UPDATE render_jobs SET status='failed', error=?, finished_at=? WHERE id=?", (str(exc), utcnow(), job_id))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"output": _media_url(result.output_path), "duration": result.duration, "log": _media_url(result.log_path)}


@router.post("/ideas/{idea_id}/quality")
def recheck_quality(idea_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    project = _project(user["id"], idea_id)
    if not project.get("output_path"):
        raise HTTPException(status_code=400, detail="Render the video first")
    idea = query_one("SELECT * FROM content_ideas WHERE id=?", (idea_id,))
    script = query_one("SELECT * FROM scripts WHERE id=?", (project["script_id"],))
    scenes = scripts.scenes_for(project["script_id"])
    subs = {"word_count": sum(len((s.get("narration") or "").split()) for s in scenes)}
    report = pipeline.quality_report(user["id"], idea, script or {}, scenes, project["output_path"], subs)
    return {"report": report}


@router.get("/render/presets")
def presets() -> dict[str, Any]:
    return {"presets": [{"key": k, **v} for k, v in renderer.PRESETS.items()], "ffmpeg": renderer.check_ffmpeg()}


@router.get("/subtitle-styles")
def subtitle_styles() -> dict[str, Any]:
    return {"styles": [{"key": k, **{kk: vv for kk, vv in v.items()}} for k, v in subtitles.STYLES.items()]}


@router.get("/thumbnails")
def thumbnails(request: Request) -> dict[str, Any]:
    user = require_user(request)
    rows = query(
        """SELECT p.id, p.idea_id, p.output_path, p.duration, p.quality_score, p.status, s.title
           FROM video_projects p LEFT JOIN scripts s ON s.id=p.script_id
           WHERE p.user_id=? ORDER BY p.id DESC LIMIT 40""",
        (user["id"],),
    )
    out = []
    for row in rows:
        if row.get("output_path"):
            stem = Path(row["output_path"]).stem
            thumb = settings.dirs()["thumbs"] / f"{stem}.jpg"
            row["thumb_url"] = _media_url(str(thumb))
        out.append(row)
    return {"projects": out}
