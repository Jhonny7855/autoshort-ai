"""SQLite persistence layer for AUTOSHORT AI.

Zero-cost, file-backed, WAL mode, migration-tracked. All tables use explicit
relations via foreign keys and ON DELETE behaviour so the queue can be pruned
without orphan rows.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .config import ensure_dirs, settings

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  google_sub TEXT UNIQUE,
  email TEXT,
  name TEXT,
  picture TEXT,
  locale TEXT,
  created_at TEXT NOT NULL,
  last_login_at TEXT,
  role TEXT NOT NULL DEFAULT 'owner'
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS google_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  google_sub TEXT NOT NULL,
  email TEXT,
  scopes TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, google_sub)
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL DEFAULT 'google',
  access_token_enc TEXT,
  refresh_token_enc TEXT,
  token_type TEXT,
  scope TEXT,
  expires_at TEXT,
  updated_at TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  UNIQUE(user_id, provider)
);

CREATE TABLE IF NOT EXISTS youtube_channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel_id TEXT NOT NULL,
  title TEXT,
  description TEXT,
  custom_url TEXT,
  thumbnail TEXT,
  country TEXT,
  subscriber_count INTEGER,
  video_count INTEGER,
  view_count INTEGER,
  is_selected INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, channel_id)
);

CREATE TABLE IF NOT EXISTS ai_providers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  base_url TEXT,
  api_key_enc TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_models (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id INTEGER NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  size_bytes INTEGER,
  family TEXT,
  parameter_size TEXT,
  quantization TEXT,
  installed INTEGER NOT NULL DEFAULT 1,
  last_checked_at TEXT,
  UNIQUE(provider_id, name)
);

CREATE TABLE IF NOT EXISTS niches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  audience TEXT,
  visual_style TEXT,
  demand_score REAL,
  competition_score REAL,
  shorts_fit_score REAL,
  repeatability_score REAL,
  difficulty_score REAL,
  monetization_score REAL,
  evergreen_score REAL,
  visual_score REAL,
  total_score REAL,
  rationale TEXT,
  source TEXT NOT NULL DEFAULT 'preset',
  active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, slug)
);

CREATE TABLE IF NOT EXISTS content_ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel_id INTEGER REFERENCES youtube_channels(id) ON DELETE SET NULL,
  niche_id INTEGER REFERENCES niches(id) ON DELETE SET NULL,
  topic TEXT NOT NULL,
  angle TEXT,
  hook TEXT,
  audience TEXT,
  why_watch TEXT,
  kind TEXT NOT NULL DEFAULT 'evergreen',
  novelty_score REAL,
  confidence_score REAL,
  est_seconds INTEGER,
  fingerprint TEXT,
  status TEXT NOT NULL DEFAULT 'IDEA',
  payload TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON content_ideas(user_id, status);
CREATE INDEX IF NOT EXISTS idx_ideas_fingerprint ON content_ideas(user_id, fingerprint);

CREATE TABLE IF NOT EXISTS research_sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  title TEXT,
  url TEXT,
  source_type TEXT,
  snippet TEXT,
  fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS scripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  hook TEXT,
  body TEXT NOT NULL,
  cta TEXT,
  alt_hooks TEXT,
  title TEXT,
  description TEXT,
  hashtags TEXT,
  keywords TEXT,
  pinned_comment TEXT,
  voice_direction TEXT,
  target_seconds INTEGER NOT NULL DEFAULT 45,
  language TEXT NOT NULL DEFAULT 'en',
  style TEXT,
  word_count INTEGER,
  version INTEGER NOT NULL DEFAULT 1,
  approved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scripts_idea ON scripts(idea_id);

CREATE TABLE IF NOT EXISTS scenes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
  scene_no INTEGER NOT NULL,
  narration TEXT NOT NULL,
  visual_prompt TEXT,
  overlay_text TEXT,
  transition TEXT DEFAULT 'fade',
  motion TEXT DEFAULT 'zoom_in',
  duration REAL,
  start_at REAL,
  asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
  audio_id INTEGER REFERENCES audio_files(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_script ON scenes(script_id, scene_no);

CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  idea_id INTEGER REFERENCES content_ideas(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  url TEXT,
  width INTEGER,
  height INTEGER,
  bytes INTEGER,
  license TEXT,
  attribution TEXT,
  provider TEXT,
  meta TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  idea_id INTEGER REFERENCES content_ideas(id) ON DELETE SET NULL,
  kind TEXT NOT NULL DEFAULT 'narration',
  path TEXT NOT NULL,
  duration REAL,
  sample_rate INTEGER,
  voice TEXT,
  provider TEXT,
  bytes INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  idea_id INTEGER NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  script_id INTEGER REFERENCES scripts(id) ON DELETE SET NULL,
  title TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  settings TEXT,
  voice_path TEXT,
  music_path TEXT,
  subtitle_path TEXT,
  output_path TEXT,
  duration REAL,
  quality_score REAL,
  quality_report TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(idea_id)
);

CREATE TABLE IF NOT EXISTS render_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES video_projects(id) ON DELETE CASCADE,
  preset TEXT NOT NULL DEFAULT 'balanced',
  status TEXT NOT NULL DEFAULT 'queued',
  progress REAL NOT NULL DEFAULT 0,
  step TEXT,
  command TEXT,
  log_path TEXT,
  error TEXT,
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_render_project ON render_jobs(project_id);

CREATE TABLE IF NOT EXISTS queue_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  idea_id INTEGER NOT NULL REFERENCES content_ideas(id) ON DELETE CASCADE,
  project_id INTEGER REFERENCES video_projects(id) ON DELETE SET NULL,
  position INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'IDEA',
  priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  timeline TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(idea_id)
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_items(user_id, status);

CREATE TABLE IF NOT EXISTS upload_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id INTEGER NOT NULL REFERENCES video_projects(id) ON DELETE CASCADE,
  channel_id INTEGER REFERENCES youtube_channels(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  visibility TEXT NOT NULL DEFAULT 'private',
  publish_at TEXT,
  youtube_video_id TEXT,
  title TEXT,
  description TEXT,
  tags TEXT,
  progress REAL NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_status ON upload_jobs(user_id, status);

CREATE TABLE IF NOT EXISTS published_videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel_id INTEGER REFERENCES youtube_channels(id) ON DELETE SET NULL,
  project_id INTEGER REFERENCES video_projects(id) ON DELETE SET NULL,
  youtube_video_id TEXT NOT NULL,
  title TEXT,
  description TEXT,
  thumbnail TEXT,
  visibility TEXT,
  published_at TEXT,
  scheduled_at TEXT,
  status TEXT NOT NULL DEFAULT 'published',
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  last_synced_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(channel_id, youtube_video_id)
);

CREATE TABLE IF NOT EXISTS analytics_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  published_video_id INTEGER REFERENCES published_videos(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  watch_minutes REAL NOT NULL DEFAULT 0,
  avg_view_duration REAL,
  subscribers_gained INTEGER,
  source TEXT NOT NULL DEFAULT 'youtube_data_api',
  created_at TEXT NOT NULL,
  UNIQUE(published_video_id, day, source)
);

CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 0,
  approval_mode INTEGER NOT NULL DEFAULT 1,
  videos_per_day INTEGER NOT NULL DEFAULT 1,
  publish_times TEXT NOT NULL DEFAULT '["19:00"]',
  timezone TEXT NOT NULL DEFAULT 'UTC',
  days_of_week TEXT NOT NULL DEFAULT '[1,2,3,4,5,6,7]',
  min_gap_minutes INTEGER NOT NULL DEFAULT 90,
  quiet_start TEXT,
  quiet_end TEXT,
  visibility TEXT NOT NULL DEFAULT 'private',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, key)
);

CREATE TABLE IF NOT EXISTS automation_state (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'idle',
  current_queue_id INTEGER,
  current_step TEXT,
  current_progress REAL NOT NULL DEFAULT 0,
  last_run_at TEXT,
  next_run_at TEXT,
  last_error TEXT,
  paused_reason TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  payload TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  priority INTEGER NOT NULL DEFAULT 0,
  run_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  last_error TEXT,
  dedupe_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(status, run_at);

CREATE TABLE IF NOT EXISTS topic_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  fingerprint TEXT NOT NULL,
  topic TEXT NOT NULL,
  used_at TEXT NOT NULL,
  UNIQUE(user_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS publish_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  queue_id INTEGER REFERENCES queue_items(id) ON DELETE SET NULL,
  project_id INTEGER REFERENCES video_projects(id) ON DELETE CASCADE,
  title TEXT,
  description TEXT,
  hashtags TEXT,
  video_path TEXT,
  thumb_path TEXT,
  package_dir TEXT,
  youtube_url TEXT,
  youtube_video_id TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  scheduled_at TEXT,
  published_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publish_status ON publish_records(user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_project ON publish_records(project_id);

CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  level TEXT NOT NULL DEFAULT 'info',
  scope TEXT,
  message TEXT NOT NULL,
  context TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with db() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        current = row["v"] or 0
        if current < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)",
                (SCHEMA_VERSION, utcnow()),
            )


def query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    with db() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid or cur.rowcount


def execute_many(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    with db() as conn:
        conn.executemany(sql, list(seq))


def insert(table: str, data: dict[str, Any]) -> int:
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    return execute(sql, tuple(data.values()))


def update(table: str, row_id: int, data: dict[str, Any], id_col: str = "id") -> None:
    if not data:
        return
    assignments = ", ".join(f"{k}=?" for k in data)
    sql = f"UPDATE {table} SET {assignments} WHERE {id_col}=?"
    execute(sql, (*data.values(), row_id))


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def log_event(
    message: str,
    *,
    level: str = "info",
    scope: str = "app",
    user_id: int | None = None,
    context: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> None:
    try:
        execute(
            "INSERT INTO logs(user_id, level, scope, message, context, created_at) VALUES (?,?,?,?,?,?)",
            (
                user_id,
                level,
                scope,
                message[:4000],
                dumps(context) if context else None,
                utcnow(),
            ),
        )
    except Exception:
        pass


def wait_for_db(timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with db() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            time.sleep(0.25)
    return False
