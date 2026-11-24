"""Central configuration for AUTOSHORT AI.

All values can be overridden through the .env file in the project root.
Nothing here requires a paid service.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _path(name: str, default: Path) -> Path:
    """Resolve a configured path against the project root, not the CWD.

    Relative paths in .env must mean "relative to the project", otherwise
    starting the server from a different directory silently creates a second
    database and media tree.
    """
    raw = os.getenv(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate


class Settings:
    APP_NAME = "AUTOSHORT AI"
    APP_VERSION = "1.0.0"

    HOST = os.getenv("AUTOSHORT_HOST", "127.0.0.1")
    PORT = _int("AUTOSHORT_PORT", 8787)
    WEB_DEV_URL = os.getenv("AUTOSHORT_WEB_DEV_URL", "http://127.0.0.1:5273")

    @property
    def base_url(self) -> str:
        return os.getenv("AUTOSHORT_BASE_URL", f"http://{self.HOST}:{self.PORT}")

    DATA_DIR = _path("AUTOSHORT_DATA_DIR", PROJECT_ROOT / "data")
    DB_PATH = _path("AUTOSHORT_DB_PATH", DATA_DIR / "autoshort.db")
    SECRET_KEY_FILE = _path("AUTOSHORT_SECRET_FILE", DATA_DIR / "secret.key")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    GOOGLE_REDIRECT_PATH = "/api/auth/google/callback"
    GOOGLE_SCOPES = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    # Local publishing is the default. Google/YouTube API upload is an optional
    # extra that stays completely dormant unless credentials are supplied.
    PUBLISH_MODE = os.getenv("AUTOSHORT_PUBLISH_MODE", "local").strip().lower()

    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    COMFYUI_URL = os.getenv("COMFYUI_URL", "").strip().rstrip("/")

    FFMPEG_BIN = os.getenv("FFMPEG_BIN", "") or shutil.which("ffmpeg") or "ffmpeg"
    FFPROBE_BIN = os.getenv("FFPROBE_BIN", "") or shutil.which("ffprobe") or "ffprobe"

    SESSION_COOKIE = "autoshort_session"
    SESSION_DAYS = _int("AUTOSHORT_SESSION_DAYS", 30)

    MAX_UPLOAD_MB = _int("AUTOSHORT_MAX_UPLOAD_MB", 512)
    LOG_RETENTION_DAYS = _int("AUTOSHORT_LOG_RETENTION_DAYS", 30)
    RENDER_WORKERS = _int("AUTOSHORT_RENDER_WORKERS", 1)

    ALLOWED_ORIGINS = [
        o.strip()
        for o in os.getenv(
            "AUTOSHORT_ALLOWED_ORIGINS",
            "http://127.0.0.1:5273,http://localhost:5273,http://127.0.0.1:8787,http://localhost:8787",
        ).split(",")
        if o.strip()
    ]

    @property
    def media_dir(self) -> Path:
        return self.DATA_DIR / "media"

    def dirs(self) -> dict[str, Path]:
        d = {
            "data": self.DATA_DIR,
            "media": self.media_dir,
            "audio": self.media_dir / "audio",
            "images": self.media_dir / "images",
            "videos": self.media_dir / "videos",
            "thumbs": self.media_dir / "thumbs",
            "music": self.media_dir / "music",
            "fonts": self.media_dir / "fonts",
            "tmp": self.media_dir / "tmp",
            "logs": self.DATA_DIR / "logs",
        }
        return d

    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)


settings = Settings()


def ensure_dirs() -> None:
    for path in settings.dirs().values():
        path.mkdir(parents=True, exist_ok=True)


def optional_str(value: Optional[str]) -> str:
    return (value or "").strip()
