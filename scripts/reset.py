"""Reset the AUTOSHORT AI database and media to a clean state.

Usage: .venv\\Scripts\\python.exe scripts\\reset.py [--keep-niches]
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.config import settings  # noqa: E402

TABLES = [
    "scenes",
    "scripts",
    "video_projects",
    "queue_items",
    "content_ideas",
    "research_sources",
    "render_jobs",
    "assets",
    "logs",
    "audio_files",
    "upload_jobs",
    "published_videos",
    "analytics_snapshots",
    "topic_history",
]


def main() -> int:
    conn = sqlite3.connect(settings.DB_PATH)
    for table in TABLES:
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError as exc:
            print(f"  skip {table}: {exc}")
    conn.execute(
        "UPDATE schedules SET enabled=0, approval_mode=1, videos_per_day=1, "
        "quiet_start=NULL, quiet_end=NULL, min_gap_minutes=90"
    )
    conn.execute("UPDATE automation_state SET status='idle', current_queue_id=NULL, last_error=NULL, paused_reason=NULL")
    conn.commit()
    conn.close()

    for sub in ("images", "videos", "audio", "thumbs", "music", "tmp"):
        target = settings.media_dir / sub
        if target.exists():
            for child in target.iterdir():
                if child.name.startswith("user_") or sub == "tmp":
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)

    print("Reset complete: tables cleared, schedule defaults restored, media pruned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
