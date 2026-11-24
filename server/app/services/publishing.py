"""Local publishing: turn finished renders into downloadable, ready-to-upload packages.

No Google account, no YouTube Data API and no browser automation are involved.
A package is a folder on disk containing the finished Short plus the metadata a
human needs to publish it by hand in YouTube Studio:

    publishing/<slug>/
        short.mp4
        thumbnail.jpg
        title.txt
        description.txt
        hashtags.txt
        metadata.json

A publish record is created only from a real rendered file. Nothing is ever
marked published without an explicit user confirmation carrying the URL they
pasted back from YouTube Studio.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from ..config import settings
from ..db import dumps, execute, insert, loads, log_event, query, query_one, utcnow

# Statuses shown on the publishing dashboard. These are the only values ever
# written to publish_records.status.
STATUS_READY = "ready"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_SCHEDULED = "scheduled"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"

STATUSES = [STATUS_READY, STATUS_PENDING_REVIEW, STATUS_SCHEDULED, STATUS_PUBLISHED, STATUS_FAILED]


class PublishError(RuntimeError):
    pass


def _slug(value: str, fallback: str = "short") -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return (text[:60] or fallback)


def packages_root() -> Path:
    root = settings.DATA_DIR / "publishing"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _package_dir(record_id: int, title: str | None) -> Path:
    return packages_root() / f"{record_id:04d}-{_slug(title or 'short')}"


def _read_media(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    return candidate if candidate.exists() else None


def _thumbnail_for(video_path: str) -> Path | None:
    thumb = settings.dirs()["thumbs"] / f"{Path(video_path).stem}.jpg"
    return thumb if thumb.exists() else None


def _status_for_queue(queue_status: str) -> str:
    if queue_status == "FAILED":
        return STATUS_FAILED
    if queue_status in ("WAITING_FOR_APPROVAL",):
        return STATUS_PENDING_REVIEW
    if queue_status in ("SCHEDULED",):
        return STATUS_SCHEDULED
    if queue_status in ("PUBLISHED",):
        return STATUS_PUBLISHED
    return STATUS_READY


def build_package(
    record_id: int,
    *,
    title: str | None,
    description: str | None,
    hashtags: list[str],
    video_path: str,
    thumb_path: str | None,
) -> Path:
    """Materialise the on-disk package. Safe to re-run; files are overwritten."""
    target = _package_dir(record_id, title)
    target.mkdir(parents=True, exist_ok=True)

    video_src = _read_media(video_path)
    if not video_src:
        raise PublishError(f"Rendered video is missing on disk: {video_path}")
    video_dst = target / "short.mp4"
    if video_src.resolve() != video_dst.resolve():
        shutil.copy2(video_src, video_dst)

    thumb_dst = None
    thumb_src = _read_media(thumb_path) or _thumbnail_for(video_path)
    if thumb_src:
        thumb_dst = target / "thumbnail.jpg"
        if thumb_src.resolve() != thumb_dst.resolve():
            shutil.copy2(thumb_src, thumb_dst)

    (target / "title.txt").write_text((title or "").strip() + "\n", encoding="utf-8")
    (target / "description.txt").write_text((description or "").strip() + "\n", encoding="utf-8")
    (target / "hashtags.txt").write_text(" ".join(hashtags).strip() + "\n", encoding="utf-8")
    (target / "metadata.json").write_text(
        json.dumps(
            {
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "video": "short.mp4",
                "thumbnail": "thumbnail.jpg" if thumb_dst else None,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def upsert_from_project(
    user_id: int,
    *,
    queue_id: int | None,
    project_id: int,
    queue_status: str,
    force: bool = False,
) -> dict[str, Any] | None:
    """Create or refresh a publish record for a finished render.

    Only video projects that actually produced a file qualify, so an unfinished
    or failed render can never appear as publishable.
    """
    project = query_one("SELECT * FROM video_projects WHERE id=? AND user_id=?", (project_id, user_id))
    if not project:
        return None
    video_path = project.get("output_path")
    if not video_path or not Path(video_path).exists():
        return None

    script = query_one("SELECT * FROM scripts WHERE id=?", (project["script_id"],)) if project.get("script_id") else None
    title = (script or {}).get("title") or project.get("title")
    description = (script or {}).get("description")
    hashtags = loads((script or {}).get("hashtags"), []) or []
    status = _status_for_queue(queue_status)

    existing = query_one("SELECT * FROM publish_records WHERE project_id=?", (project_id,))
    if existing and existing["status"] == STATUS_PUBLISHED and not force:
        # Never downgrade a confirmed publication back into the queue.
        return existing

    if existing:
        execute(
            "UPDATE publish_records SET queue_id=?, title=?, description=?, hashtags=?, video_path=?, status=?, updated_at=? WHERE id=?",
            (
                queue_id,
                title,
                description,
                dumps(hashtags),
                video_path,
                status if existing["status"] != STATUS_SCHEDULED else STATUS_SCHEDULED,
                utcnow(),
                existing["id"],
            ),
        )
        record_id = existing["id"]
    else:
        record_id = insert(
            "publish_records",
            {
                "user_id": user_id,
                "queue_id": queue_id,
                "project_id": project_id,
                "title": title,
                "description": description,
                "hashtags": dumps(hashtags),
                "video_path": video_path,
                "status": status,
                "created_at": utcnow(),
                "updated_at": utcnow(),
            },
        )

    try:
        package = build_package(
            record_id,
            title=title,
            description=description,
            hashtags=hashtags,
            video_path=video_path,
            thumb_path=existing.get("thumb_path") if existing else None,
        )
        thumb = package / "thumbnail.jpg"
        execute(
            "UPDATE publish_records SET thumb_path=?, package_dir=?, updated_at=? WHERE id=?",
            (str(thumb) if thumb.exists() else None, str(package), utcnow(), record_id),
        )
    except (PublishError, OSError) as exc:
        log_event("Publish package build failed", level="warn", scope="publish", user_id=user_id, context={"error": str(exc)})

    return query_one("SELECT * FROM publish_records WHERE id=?", (record_id,))


def sync_all(user_id: int) -> int:
    """Backfill records for every finished project that does not have one yet."""
    rows = query(
        """SELECT q.id AS queue_id, q.status AS queue_status, p.id AS project_id
           FROM video_projects p
           LEFT JOIN queue_items q ON q.idea_id = p.idea_id
           WHERE p.user_id=? AND p.output_path IS NOT NULL""",
        (user_id,),
    )
    created = 0
    for row in rows:
        before = query_one("SELECT id FROM publish_records WHERE project_id=?", (row["project_id"],))
        record = upsert_from_project(
            user_id,
            queue_id=row["queue_id"],
            project_id=row["project_id"],
            queue_status=row["queue_status"] or "READY_TO_UPLOAD",
        )
        if record and not before:
            created += 1
    return created


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a record for the API, adding derived URLs and dropping disk paths."""
    out = dict(row)
    out["hashtags"] = loads(row.get("hashtags"), []) or []
    package = Path(row["package_dir"]) if row.get("package_dir") else None
    out["download_url"] = f"/api/publish/{row['id']}/download" if row.get("video_path") else None
    out["thumbnail_url"] = f"/api/publish/{row['id']}/thumbnail" if row.get("thumb_path") else None
    out["package_ready"] = bool(package and package.exists())
    out.pop("video_path", None)
    out.pop("thumb_path", None)
    out.pop("package_dir", None)
    return out


def list_records(user_id: int) -> dict[str, Any]:
    rows = query("SELECT * FROM publish_records WHERE user_id=? ORDER BY updated_at DESC, id DESC", (user_id,))
    groups: dict[str, list[dict[str, Any]]] = {status: [] for status in STATUSES}
    for row in rows:
        groups.setdefault(row["status"], []).append(_public(row))
    return {"records": [_public(r) for r in rows], "groups": groups, "counts": {k: len(v) for k, v in groups.items()}}


def get_record(user_id: int, record_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM publish_records WHERE id=? AND user_id=?", (record_id, user_id))
    if not row:
        raise PublishError("Publish record not found")
    return row


def mark_published(user_id: int, record_id: int, youtube_url: str, *, published_at: str | None = None) -> dict[str, Any]:
    """Record a publication the user confirmed by pasting the real URL."""
    row = get_record(user_id, record_id)
    url = (youtube_url or "").strip()
    if not url:
        raise PublishError("A YouTube URL is required to mark this video published")
    if not re.match(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", url, re.IGNORECASE):
        raise PublishError("That does not look like a YouTube URL")

    video_id = None
    match = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", url)
    if match:
        video_id = match.group(1)

    execute(
        """UPDATE publish_records SET status=?, youtube_url=?, youtube_video_id=?, published_at=?, updated_at=?
           WHERE id=?""",
        (STATUS_PUBLISHED, url, video_id, published_at or utcnow(), utcnow(), record_id),
    )
    if row.get("queue_id"):
        execute("UPDATE queue_items SET status='PUBLISHED', updated_at=? WHERE id=?", (utcnow(), row["queue_id"]))
    log_event(
        "Video marked published",
        scope="publish",
        user_id=user_id,
        context={"record_id": record_id, "url": url},
    )
    return get_record(user_id, record_id)


def schedule(user_id: int, record_id: int, scheduled_at: str | None) -> dict[str, Any]:
    row = get_record(user_id, record_id)
    if row["status"] == STATUS_PUBLISHED:
        raise PublishError("This video is already published")
    if not scheduled_at:
        execute(
            "UPDATE publish_records SET status=?, scheduled_at=NULL, updated_at=? WHERE id=?",
            (STATUS_READY, utcnow(), record_id),
        )
        return get_record(user_id, record_id)
    execute(
        "UPDATE publish_records SET status=?, scheduled_at=?, updated_at=? WHERE id=?",
        (STATUS_SCHEDULED, scheduled_at, utcnow(), record_id),
    )
    return get_record(user_id, record_id)


def approve(user_id: int, record_id: int) -> dict[str, Any]:
    """Clear a pending-review record so it shows up as ready to publish."""
    row = get_record(user_id, record_id)
    if row["status"] == STATUS_PUBLISHED:
        raise PublishError("This video is already published")
    execute(
        "UPDATE publish_records SET status=?, notes=NULL, updated_at=? WHERE id=?",
        (STATUS_READY, utcnow(), record_id),
    )
    if row.get("queue_id"):
        execute("UPDATE queue_items SET status='READY_TO_UPLOAD', updated_at=? WHERE id=?", (utcnow(), row["queue_id"]))
    return get_record(user_id, record_id)


def reject(user_id: int, record_id: int, note: str | None = None) -> dict[str, Any]:
    row = get_record(user_id, record_id)
    if row["status"] == STATUS_PUBLISHED:
        raise PublishError("This video is already published")
    execute(
        "UPDATE publish_records SET status=?, notes=?, updated_at=? WHERE id=?",
        (STATUS_FAILED, (note or "Rejected by user")[:500], utcnow(), record_id),
    )
    if row.get("queue_id"):
        execute("UPDATE queue_items SET status='CANCELLED', updated_at=? WHERE id=?", (utcnow(), row["queue_id"]))
    return get_record(user_id, record_id)


def rebuild_package(user_id: int, record_id: int) -> dict[str, Any]:
    row = get_record(user_id, record_id)
    if not row.get("video_path"):
        raise PublishError("No rendered file recorded for this item")
    package = build_package(
        record_id,
        title=row.get("title"),
        description=row.get("description"),
        hashtags=loads(row.get("hashtags"), []) or [],
        video_path=row["video_path"],
        thumb_path=row.get("thumb_path"),
    )
    thumb = package / "thumbnail.jpg"
    execute(
        "UPDATE publish_records SET package_dir=?, thumb_path=?, updated_at=? WHERE id=?",
        (str(package), str(thumb) if thumb.exists() else None, utcnow(), record_id),
    )
    return get_record(user_id, record_id)
