"""Local publishing API: queue, manual confirmation, downloads, metadata copy."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..db import query_one
from ..security import require_user
from ..services import publishing
from ..services.publish_scheduler import daily_summary

router = APIRouter(prefix="/api/publish", tags=["publish"])


class PublishConfirm(BaseModel):
    youtube_url: str
    published_at: str | None = None


class ScheduleRequest(BaseModel):
    scheduled_at: str | None = None


class RejectRequest(BaseModel):
    note: str | None = None


class MetadataPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None


@router.get("")
def list_publish(request: Request) -> dict[str, Any]:
    user = require_user(request)
    publishing.sync_all(user["id"])
    return publishing.list_records(user["id"])


@router.get("/summary")
def summary(request: Request) -> dict[str, Any]:
    user = require_user(request)
    return daily_summary(user["id"])


@router.post("/sync")
def sync(request: Request) -> dict[str, Any]:
    user = require_user(request)
    created = publishing.sync_all(user["id"])
    return {"created": created, **publishing.list_records(user["id"])}


@router.get("/{record_id}")
def get_one(record_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = publishing.get_record(user["id"], record_id)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"record": publishing._public(row)}


@router.post("/{record_id}/confirm")
def confirm(record_id: int, payload: PublishConfirm, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = publishing.mark_published(user["id"], record_id, payload.youtube_url, published_at=payload.published_at)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"record": publishing._public(row)}


@router.post("/{record_id}/schedule")
def set_schedule(record_id: int, payload: ScheduleRequest, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = publishing.schedule(user["id"], record_id, payload.scheduled_at)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"record": publishing._public(row)}


@router.post("/{record_id}/approve")
def approve(record_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = publishing.approve(user["id"], record_id)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"record": publishing._public(row)}


@router.post("/{record_id}/reject")
def reject(record_id: int, payload: RejectRequest, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = publishing.reject(user["id"], record_id, payload.note)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"record": publishing._public(row)}


@router.patch("/{record_id}")
def patch_metadata(record_id: int, payload: MetadataPatch, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        row = publishing.get_record(user["id"], record_id)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if row["status"] == publishing.STATUS_PUBLISHED:
        raise HTTPException(status_code=400, detail="Published records keep their original metadata")
    from ..db import dumps, execute, utcnow

    patch: dict[str, Any] = {}
    if payload.title is not None:
        patch["title"] = payload.title.strip()[:100]
    if payload.description is not None:
        patch["description"] = payload.description.strip()[:5000]
    if payload.hashtags is not None:
        tags = [t if t.startswith("#") else f"#{t}" for t in (x.strip() for x in payload.hashtags) if t]
        patch["hashtags"] = dumps(tags[:30])
    if patch:
        assignments = ", ".join(f"{k}=?" for k in patch)
        execute(f"UPDATE publish_records SET {assignments}, updated_at=? WHERE id=?", (*patch.values(), utcnow(), record_id))
        try:
            publishing.rebuild_package(user["id"], record_id)
        except publishing.PublishError:
            pass
    return {"record": publishing._public(publishing.get_record(user["id"], record_id))}


@router.post("/{record_id}/rebuild")
def rebuild(record_id: int, request: Request) -> dict[str, Any]:
    user = require_user(request)
    try:
        publishing.rebuild_package(user["id"], record_id)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


def _file_for(user_id: int, record_id: int, column: str, filename: str) -> FileResponse:
    try:
        row = publishing.get_record(user_id, record_id)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raw = row.get(column)
    if not raw:
        raise HTTPException(status_code=404, detail="File not available")
    path = Path(raw)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File is missing on disk")
    return FileResponse(path, filename=filename)


@router.get("/{record_id}/download")
def download(record_id: int, request: Request) -> FileResponse:
    user = require_user(request)
    row = query_one("SELECT title FROM publish_records WHERE id=? AND user_id=?", (record_id, user["id"]))
    stem = publishing._slug((row or {}).get("title") or "short")
    return _file_for(user["id"], record_id, "video_path", f"{stem}.mp4")


@router.get("/{record_id}/thumbnail")
def thumbnail(record_id: int, request: Request) -> FileResponse:
    user = require_user(request)
    row = query_one("SELECT title FROM publish_records WHERE id=? AND user_id=?", (record_id, user["id"]))
    stem = publishing._slug((row or {}).get("title") or "thumbnail")
    return _file_for(user["id"], record_id, "thumb_path", f"{stem}.jpg")


@router.get("/{record_id}/package")
def package_manifest(record_id: int, request: Request) -> dict[str, Any]:
    """Metadata ready to paste into YouTube Studio, plus one-click copy strings."""
    user = require_user(request)
    try:
        row = publishing.get_record(user["id"], record_id)
    except publishing.PublishError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    from ..db import loads

    tags = loads(row.get("hashtags"), []) or []
    title = row.get("title") or ""
    description = row.get("description") or ""
    hashtag_line = " ".join(tags)
    full_description = f"{description}\n\n{hashtag_line}".strip()
    return {
        "title": title,
        "description": description,
        "hashtags": tags,
        "hashtag_line": hashtag_line,
        "copy": {
            "title": title,
            "description": full_description,
            "hashtags": hashtag_line,
        },
        "studio_url": "https://studio.youtube.com",
        "download_url": f"/api/publish/{record_id}/download",
        "thumbnail_url": f"/api/publish/{record_id}/thumbnail" if row.get("thumb_path") else None,
        "package": quote(str(row.get("package_dir") or "")),
    }
