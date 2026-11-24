"""End-to-end production pipeline and quality control.

Each step writes real rows, real files and real status transitions. Failures
raise PipelineError, which the automation engine records and retries.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Callable

from ..config import settings
from ..db import dumps, execute, insert, loads, log_event, query, query_one, utcnow
from . import ai, research, scripts, subtitles, tts, visuals
from .hub import emit

STEPS = [
    "RESEARCHING",
    "SCRIPT_READY",
    "GENERATING_AUDIO",
    "GENERATING_VISUALS",
    "RENDERING",
    "QUALITY_CHECK",
    "READY_TO_UPLOAD",
]

QUEUE_ORDER = [
    "IDEA", "RESEARCHING", "SCRIPT_READY", "WAITING_FOR_APPROVAL", "GENERATING_AUDIO",
    "GENERATING_VISUALS", "RENDERING", "QUALITY_CHECK", "READY_TO_UPLOAD", "UPLOADING",
    "SCHEDULED", "PUBLISHED", "FAILED", "CANCELLED",
]


class PipelineError(RuntimeError):
    pass


class ItemBusyError(PipelineError):
    """Raised when the same queue item is already being produced."""


# Guard against two callers (engine loop, run-now, REST produce) rendering the
# same item at once: they would share temp files and race on status updates.
_ITEM_LOCKS: dict[int, asyncio.Lock] = {}
_ITEM_LOCKS_GUARD = asyncio.Lock()


async def _item_lock(queue_id: int) -> asyncio.Lock:
    async with _ITEM_LOCKS_GUARD:
        lock = _ITEM_LOCKS.get(queue_id)
        if lock is None:
            lock = asyncio.Lock()
            _ITEM_LOCKS[queue_id] = lock
        return lock


def settings_for(user_id: int) -> dict[str, Any]:
    rows = query("SELECT key, value FROM app_settings WHERE user_id=?", (user_id,))
    out: dict[str, Any] = {}
    for row in rows:
        val = row.get("value")
        try:
            out[row["key"]] = json.loads(val) if val and val[0] in "[{0123456789tfn\"" else val
        except (json.JSONDecodeError, TypeError, IndexError):
            out[row["key"]] = val
    return out


def set_setting(user_id: int, key: str, value: Any) -> None:
    raw = json.dumps(value) if not isinstance(value, str) else json.dumps(value)
    existing = query_one("SELECT id FROM app_settings WHERE user_id=? AND key=?", (user_id, key))
    if existing:
        execute("UPDATE app_settings SET value=?, updated_at=? WHERE id=?", (raw, utcnow(), existing["id"]))
    else:
        insert("app_settings", {"user_id": user_id, "key": key, "value": raw, "updated_at": utcnow()})


def defaults_for(user_id: int) -> dict[str, Any]:
    return {
        "ai_model": None,
        "ai_temperature": 0.8,
        "script_seconds": 45,
        "language": "en",
        "content_style": "energetic-explainer",
        "tts_provider": "auto",
        "tts_voice": "en-US-GuyNeural",
        "tts_rate": 0,
        "subtitle_style": "modern-bold",
        "subtitle_size": 86,
        "render_preset": "balanced",
        "music_enabled": True,
        "music_volume": 0.18,
        "quality_threshold": 75,
        "auto_improve": True,
    }


def effective_settings(user_id: int) -> dict[str, Any]:
    return {**defaults_for(user_id), **settings_for(user_id)}


def approval_required(user_id: int) -> bool:
    """Approval gate lives on the schedule row; default to requiring approval."""
    row = query_one("SELECT approval_mode FROM schedules WHERE user_id=?", (user_id,))
    if row is None:
        return True
    return int(row.get("approval_mode") or 0) != 0


def timeline_add(queue_id: int, status: str, note: str | None = None) -> None:
    row = query_one("SELECT timeline FROM queue_items WHERE id=?", (queue_id,))
    if not row:
        return
    timeline = loads(row.get("timeline"), []) or []
    timeline.append({"status": status, "at": utcnow(), "note": note})
    execute("UPDATE queue_items SET timeline=?, updated_at=? WHERE id=?", (dumps(timeline), utcnow(), queue_id))


def set_queue_status(user_id: int, queue_id: int, status: str, note: str | None = None, error: str | None = None) -> None:
    execute(
        "UPDATE queue_items SET status=?, updated_at=?, last_error=? WHERE id=?",
        (status, utcnow(), error, queue_id),
    )
    idea = query_one("SELECT idea_id FROM queue_items WHERE id=?", (queue_id,))
    if idea:
        execute("UPDATE content_ideas SET status=?, updated_at=? WHERE id=?", (status, utcnow(), idea["idea_id"]))
    timeline_add(queue_id, status, note)
    emit(user_id, "queue_update", {"queue_id": queue_id, "status": status, "note": note, "error": error})


async def create_idea(
    user_id: int,
    *,
    niche: dict[str, Any] | None = None,
    topic: str | None = None,
    angle: str | None = None,
    channel_row_id: int | None = None,
) -> dict[str, Any]:
    niche = niche or query_one("SELECT * FROM niches WHERE user_id=? AND active=1", (user_id,))
    if not topic:
        topic, angle = await ai_topic_for(user_id, niche)
    fp = scripts.fingerprint(topic, angle)
    dup = query_one("SELECT id FROM content_ideas WHERE user_id=? AND fingerprint=?", (user_id, fp))
    if dup:
        return query_one("SELECT * FROM content_ideas WHERE id=?", (dup["id"],)) or {}

    idea_id = insert(
        "content_ideas",
        {
            "user_id": user_id,
            "channel_id": channel_row_id,
            "niche_id": niche["id"] if niche else None,
            "topic": topic[:300],
            "angle": (angle or "")[:400],
            "hook": "",
            "audience": (niche or {}).get("audience") or "general audience",
            "why_watch": "",
            "kind": "evergreen",
            "novelty_score": None,
            "confidence_score": None,
            "est_seconds": None,
            "fingerprint": fp,
            "status": "IDEA",
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    insert(
        "topic_history",
        {"user_id": user_id, "fingerprint": fp, "topic": topic[:300], "used_at": utcnow()},
    )
    return query_one("SELECT * FROM content_ideas WHERE id=?", (idea_id,)) or {}


async def ai_topic_for(user_id: int, niche: dict[str, Any] | None) -> tuple[str, str]:
    used = [r["topic"] for r in query("SELECT topic FROM content_ideas WHERE user_id=? ORDER BY id DESC LIMIT 40", (user_id,))]
    niche_name = (niche or {}).get("name") or "general knowledge"
    desc = (niche or {}).get("description") or ""
    prompt = (
        f"Suggest ONE fresh YouTube Shorts topic for the niche: {niche_name}. {desc}\n"
        f"Avoid these already-used topics: {json.dumps(used[:30])}\n"
        'Return JSON {"topic": str, "angle": str, "hook": str, "why_watch": str, "audience": str, '
        '"kind": "evergreen"|"trending", "est_seconds": int}'
    )
    try:
        raw = await ai.generate(prompt, system="You output JSON only. Be specific and non-clickbait.", json_mode=True, temperature=0.95)
        data = ai.extract_json(raw)
        topic = str(data.get("topic") or "").strip()
        if topic:
            return topic[:300], str(data.get("angle") or "")[:400]
    except Exception:
        pass
    fallback_pool = {
        "AI & Technology": ["How a neural network actually learns", "Why GPUs beat CPUs for AI", "What an AI model really sees"],
        "Interesting Facts": ["The science behind déjà vu", "Why octopuses have nine brains", "How Iceland runs on geothermal power"],
        "History": ["The day the printing press changed everything", "How the Silk Road moved ideas", "Why the Library of Alexandria mattered"],
        "Space": ["What happens inside a black hole's edge", "Why Mars lost its atmosphere", "How we measure a star's distance"],
    }
    pool = fallback_pool.get(niche_name) or [
        f"A surprising fact about {niche_name}",
        f"How {niche_name} actually works",
        f"The biggest myth about {niche_name}",
    ]
    pick = pool[len(used) % len(pool)]
    return pick, f"A tight 45-second explainer on {pick.lower()}."


async def run_research(user_id: int, idea: dict[str, Any]) -> list[dict[str, Any]]:
    set_idea_status(user_id, idea["id"], "RESEARCHING")
    sources = await research.gather(user_id, idea["topic"], angle=idea.get("angle") or "")
    execute("DELETE FROM research_sources WHERE idea_id=?", (idea["id"],))
    for src in sources[:10]:
        insert(
            "research_sources",
            {
                "idea_id": idea["id"],
                "title": (src.get("title") or "")[:300],
                "url": src.get("url"),
                "source_type": src.get("source_type"),
                "snippet": (src.get("snippet") or "")[:1200],
                "fetched_at": utcnow(),
            },
        )
    confidence = min(98.0, 45.0 + len(sources) * 7.0)
    novelty = 90.0 if len(sources) <= 3 else max(55.0, 95.0 - len(sources) * 3)
    execute(
        "UPDATE content_ideas SET confidence_score=?, novelty_score=?, updated_at=? WHERE id=?",
        (round(confidence, 1), round(novelty, 1), utcnow(), idea["id"]),
    )
    return sources


def set_idea_status(user_id: int, idea_id: int, status: str) -> None:
    execute("UPDATE content_ideas SET status=?, updated_at=? WHERE id=?", (status, utcnow(), idea_id))
    emit(user_id, "idea_update", {"idea_id": idea_id, "status": status})


def sources_for(idea_id: int) -> list[dict[str, Any]]:
    return query("SELECT * FROM research_sources WHERE idea_id=? ORDER BY id", (idea_id,))


async def run_script(
    user_id: int,
    idea: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    seconds: int | None = None,
) -> dict[str, Any]:
    cfg = effective_settings(user_id)
    script = await scripts.generate_script(
        user_id,
        idea,
        sources,
        seconds=seconds or int(cfg.get("script_seconds") or 45),
        language=str(cfg.get("language") or "en"),
        style=str(cfg.get("content_style") or "energetic-explainer"),
        temperature=float(cfg.get("ai_temperature") or 0.8),
        model=cfg.get("ai_model"),
    )
    set_idea_status(user_id, idea["id"], "SCRIPT_READY")
    return script


async def run_audio(user_id: int, script: dict[str, Any]) -> dict[str, Any]:
    cfg = effective_settings(user_id)
    scenes = scripts.scenes_for(script["id"])
    if not scenes:
        raise PipelineError("Script has no scenes")
    audio_dir = settings.dirs()["audio"] / f"user_{user_id}" / f"idea_{script['idea_id']}"
    audio_dir.mkdir(parents=True, exist_ok=True)

    total = 0.0
    for scene in scenes:
        narration = (scene.get("narration") or "").strip()
        if not narration:
            continue
        result = await tts.synthesize(
            narration,
            audio_dir,
            voice=cfg.get("tts_voice"),
            provider=cfg.get("tts_provider") or "auto",
            rate_pct=int(cfg.get("tts_rate") or 0),
        )
        duration = max(1.2, result.duration)
        audio_id = insert(
            "audio_files",
            {
                "user_id": user_id,
                "idea_id": script["idea_id"],
                "kind": "narration",
                "path": result.path,
                "duration": duration,
                "sample_rate": 48000,
                "voice": result.voice,
                "provider": result.provider,
                "bytes": Path(result.path).stat().st_size if Path(result.path).exists() else None,
                "created_at": utcnow(),
            },
        )
        execute(
            "UPDATE scenes SET audio_id=?, duration=? WHERE id=?",
            (audio_id, round(duration, 3), scene["id"]),
        )
        scene["audio_id"] = audio_id
        scene["audio_path"] = result.path
        scene["duration"] = duration
        scene["words"] = result.words
        total += duration

    execute(
        "UPDATE video_projects SET voice_path=?, duration=?, status='audio_ready', updated_at=? WHERE idea_id=?",
        (str(audio_dir), round(total, 3), utcnow(), script["idea_id"]),
    )
    return {"scenes": scripts.scenes_for(script["id"]), "duration": round(total, 3), "dir": str(audio_dir)}


def build_visuals(user_id: int, idea_id: int, script_id: int) -> list[dict[str, Any]]:
    scenes = scripts.scenes_for(script_id)
    enriched = visuals.ensure_scene_assets(user_id, idea_id, scenes)
    for scene in enriched:
        execute("UPDATE scenes SET asset_id=? WHERE id=?", (scene["asset_id"], scene["id"]))
    return enriched


def _scene_audio_lookup(scene: dict[str, Any]) -> str | None:
    if scene.get("audio_id"):
        row = query_one("SELECT path FROM audio_files WHERE id=?", (scene["audio_id"],))
        if row and row.get("path") and Path(row["path"]).exists():
            return row["path"]
    return None


def build_subtitles(user_id: int, script: dict[str, Any], scenes: list[dict[str, Any]], *, total_override: float | None = None) -> dict[str, Any]:
    cfg = effective_settings(user_id)
    words: list[dict[str, Any]] = []
    for scene in scenes:
        audio_id = scene.get("audio_id")
        if not audio_id:
            continue
        row = query_one("SELECT * FROM audio_files WHERE id=?", (audio_id,))
        if not row:
            continue
        narration_words = re.findall(r"[^\s]+", scene.get("narration") or "")
        words.extend(
            [
                {
                    "word": w,
                    "start": round(float(scene.get("start_at") or 0) + t, 3),
                    "end": round(float(scene.get("start_at") or 0) + t + span, 3),
                }
                for w, t, span in _estimate(narration_words, float(row.get("duration") or scene.get("duration") or 3.0), float(scene.get("start_at") or 0))
            ]
        )

    if words:
        natural_end = max(float(w["end"]) for w in words)
        limit = total_override if total_override and total_override > 0 else natural_end
        if natural_end > limit > 0:
            scale = limit / natural_end
            for word in words:
                word["start"] = round(float(word["start"]) * scale, 3)
                word["end"] = round(float(word["end"]) * scale, 3)

    out_dir = settings.dirs()["videos"] / f"user_{user_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_path = out_dir / f"captions_{script['id']}.ass"
    subtitles.build_ass(
        words,
        ass_path,
        style_key=str(cfg.get("subtitle_style") or "modern-bold"),
        font_size=int(cfg.get("subtitle_size") or 86),
    )
    return {"path": str(ass_path), "word_count": len(words)}


def _estimate(words: list[str], duration: float, offset: float) -> list[tuple[str, float, float]]:
    if not words or duration <= 0:
        return []
    weights = [max(2, len(w)) for w in words]
    total = sum(weights)
    cursor = 0.0
    out = []
    for word, weight in zip(words, weights):
        span = duration * (weight / total)
        out.append((word, cursor, span))
        cursor += span
    return out


def resequence_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    for scene in scenes:
        duration = float(scene.get("duration") or 3.0)
        execute("UPDATE scenes SET start_at=?, duration=? WHERE id=?", (round(cursor, 3), duration, scene["id"]))
        scene["start_at"] = round(cursor, 3)
        cursor += duration
    return scenes


def quality_report(
    user_id: int,
    idea: dict[str, Any],
    script: dict[str, Any],
    scenes: list[dict[str, Any]],
    output_path: str,
    subtitle_info: dict[str, Any],
) -> dict[str, Any]:
    from .renderer import probe

    cfg = effective_settings(user_id)
    meta = probe(output_path)
    video_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    duration = float(meta.get("format", {}).get("duration") or 0)

    body = script.get("body") or ""
    hook = (script.get("hook") or body.split(".")[0])[:140]
    words = scripts.word_count(body)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    avg_sentence = words / max(1, len(sentences))

    checks: list[dict[str, Any]] = []

    def add(name: str, score: float, weight: float, detail: str) -> None:
        checks.append({"name": name, "score": round(max(0, min(100, score)), 1), "weight": weight, "detail": detail})

    hook_score = 55.0
    if len(hook) <= 90:
        hook_score += 15
    if re.search(r"\d", hook):
        hook_score += 10
    if any(w in hook.lower() for w in ("why", "how", "nobody", "most", "stop", "the truth", "what")):
        hook_score += 15
    if hook.endswith("?"):
        hook_score += 5
    add("Hook strength", hook_score, 0.18, f"{len(hook)} chars, first sentence: {hook[:70]}")

    script_score = 60.0
    if 28 <= words <= 175:
        script_score += 15
    if avg_sentence <= 16:
        script_score += 15
    if len(sentences) >= 4:
        script_score += 10
    add("Script quality", script_score, 0.18, f"{words} words, avg sentence {avg_sentence:.1f}")

    audio_score = 40.0
    if duration > 5:
        audio_score += 30
    audio_streams = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    if audio_streams:
        audio_score += 30
    add("Audio presence", audio_score, 0.12, f"{len(audio_streams)} audio stream(s), {duration:.1f}s total")

    sub_score = 70.0 if subtitle_info.get("word_count", 0) > 15 else 35.0
    if subtitle_info.get("word_count", 0) > 40:
        sub_score = 92.0
    add("Subtitle coverage", sub_score, 0.12, f"{subtitle_info.get('word_count', 0)} captioned words")

    res_score = 100.0 if (width >= 1000 and height >= 1700) else (78.0 if height >= 1200 else 50.0)
    add("Video resolution", res_score, 0.12, f"{width}x{height}")

    visual_score = 85.0 if len(scenes) >= 3 else 55.0
    add("Visual consistency", visual_score, 0.08, f"{len(scenes)} scenes")

    timing_ok = all(float(s.get("duration") or 0) >= 1.2 for s in scenes)
    add("Scene timing", 90.0 if timing_ok else 60.0, 0.08, "all scenes >= 1.2s" if timing_ok else "short scenes present")

    target = float(script.get("target_seconds") or 0)
    if target > 0:
        ratio = duration / target
        length_score = 100.0 if 0.75 <= ratio <= 1.35 else max(20.0, 100.0 - abs(1 - ratio) * 120.0)
        add(
            "Target length",
            length_score,
            0.10,
            f"{duration:.1f}s vs {target:.0f}s target ({ratio * 100:.0f}%)",
        )

    unverified = scripts.unsourced_numbers(body, sources_for(idea["id"]))
    fact_score = 100.0 if not unverified else max(30.0, 100.0 - 20.0 * len(unverified))
    add(
        "Claim verification",
        fact_score,
        0.08,
        "no unsourced figures" if not unverified else "unsourced figures: " + ", ".join(unverified[:4]),
    )

    accuracy = 70.0
    sources = sources_for(idea["id"])
    if sources:
        accuracy += min(25.0, len(sources) * 6)
    add("Source grounding", accuracy, 0.06, f"{len(sources)} source(s) attached")

    novelty = float(idea.get("novelty_score") or 70)
    add("Repetition check", novelty, 0.04, f"novelty {novelty:.0f}")

    copyright_score = 95.0
    add("Copyright risk", copyright_score, 0.02, "locally generated visuals + synthesized music only")

    title = (script.get("title") or "").strip()
    title_score = 60.0
    if 25 <= len(title) <= 90:
        title_score += 20
    if "shorts" not in title.lower():
        title_score += 10
    add("Title quality", title_score, 0.02, f"{len(title)} chars")

    total_weight = sum(c["weight"] for c in checks) or 1
    score = sum(c["score"] * c["weight"] for c in checks) / total_weight
    suggestions = []
    if hook_score < 75:
        suggestions.append("Sharpen the hook: lead with the surprising fact or a question.")
    if sub_score < 75:
        suggestions.append("Narration produced too few caption words - check TTS output length.")
    if res_score < 90:
        suggestions.append("Switch render preset to Balanced or High for full 1080x1920 output.")
    if accuracy < 80:
        suggestions.append("Add at least one more research source for grounding.")
    if target > 0 and not 0.75 <= duration / target <= 1.35:
        suggestions.append(
            f"Video runs {duration:.1f}s against a {target:.0f}s target - adjust script length or scenes."
        )
    if unverified:
        suggestions.append(
            "Unverified figures spoken in the script: "
            + ", ".join(unverified[:4])
            + " - rework these against a source before publishing."
        )

    report = {
        "score": round(score, 1),
        "threshold": float(cfg.get("quality_threshold") or 75),
        "checks": checks,
        "suggestions": suggestions,
        "width": width,
        "height": height,
        "duration": round(duration, 2),
        "unsourced_figures": unverified,
        "requires_review": bool(unverified),
    }
    execute(
        "UPDATE video_projects SET quality_score=?, quality_report=?, updated_at=? WHERE idea_id=?",
        (report["score"], dumps(report), utcnow(), idea["id"]),
    )
    return report


def ensure_project(user_id: int, idea: dict[str, Any], script: dict[str, Any]) -> dict[str, Any]:
    row = query_one("SELECT * FROM video_projects WHERE idea_id=?", (idea["id"],))
    if row:
        execute(
            "UPDATE video_projects SET script_id=?, title=?, updated_at=? WHERE id=?",
            (script["id"], script.get("title"), utcnow(), row["id"]),
        )
        return query_one("SELECT * FROM video_projects WHERE id=?", (row["id"],)) or row
    project_id = insert(
        "video_projects",
        {
            "user_id": user_id,
            "idea_id": idea["id"],
            "script_id": script["id"],
            "title": script.get("title"),
            "status": "draft",
            "settings": dumps(effective_settings(user_id)),
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    return query_one("SELECT * FROM video_projects WHERE id=?", (project_id,)) or {}


async def produce_video(
    user_id: int,
    queue_id: int,
    *,
    force: bool = False,
    progress: Callable[[str, float, str], None] | None = None,
) -> dict[str, Any]:
    """Run the full pipeline for one queue item. Returns a result summary."""
    lock = await _item_lock(queue_id)
    if lock.locked():
        raise ItemBusyError(f"Queue item {queue_id} is already being produced")
    async with lock:
        return await _produce_video_locked(user_id, queue_id, force=force, progress=progress)


async def _produce_video_locked(
    user_id: int,
    queue_id: int,
    *,
    force: bool = False,
    progress: Callable[[str, float, str], None] | None = None,
) -> dict[str, Any]:
    cfg = effective_settings(user_id)
    item = query_one("SELECT * FROM queue_items WHERE id=? AND user_id=?", (queue_id, user_id))
    if not item:
        raise PipelineError("Queue item not found")
    idea = query_one("SELECT * FROM content_ideas WHERE id=?", (item["idea_id"],))
    if not idea:
        raise PipelineError("Idea missing for queue item")

    def note(step: str, pct: float, msg: str) -> None:
        execute("UPDATE automation_state SET current_step=?, current_progress=?, updated_at=? WHERE user_id=?", (step, pct, utcnow(), user_id))
        emit(user_id, "pipeline", {"queue_id": queue_id, "step": step, "progress": pct, "message": msg})
        if progress:
            progress(step, pct, msg)

    sources = sources_for(idea["id"])
    if not sources or force:
        set_queue_status(user_id, queue_id, "RESEARCHING")
        note("RESEARCHING", 8, "Gathering sources")
        sources = await run_research(user_id, idea)
        idea = query_one("SELECT * FROM content_ideas WHERE id=?", (idea["id"],)) or idea

    script = scripts.get_script(user_id, idea["id"])
    if not script or force:
        set_queue_status(user_id, queue_id, "SCRIPT_READY")
        note("SCRIPT_READY", 20, "Writing script")
        script = await run_script(user_id, idea, sources)

    if not script:
        raise PipelineError("Script generation produced nothing")

    if not force and approval_required(user_id) and not script.get("approved"):
        set_queue_status(user_id, queue_id, "WAITING_FOR_APPROVAL", "Awaiting script approval")
        note("WAITING_FOR_APPROVAL", 25, "Waiting for approval")
        return {"status": "WAITING_FOR_APPROVAL", "script_id": script["id"]}

    set_queue_status(user_id, queue_id, "GENERATING_AUDIO")
    note("GENERATING_AUDIO", 34, "Synthesizing narration")
    audio = await run_audio(user_id, script)

    set_queue_status(user_id, queue_id, "GENERATING_VISUALS")
    note("GENERATING_VISUALS", 48, "Building scene visuals")
    scenes = build_visuals(user_id, idea["id"], script["id"])
    scenes = resequence_scenes(scenes)

    project = ensure_project(user_id, idea, script)
    music_path = None
    if cfg.get("music_enabled", True):
        total = sum(float(s.get("duration") or 3.0) for s in scenes) + 1.0
        bed = settings.dirs()["music"] / f"auto_{idea['id']}.wav"
        generated = visuals.music_bed(total, bed, mood="uplifting")
        music_path = str(generated) if generated else None
    subs = build_subtitles(user_id, script, scenes, total_override=sum(float(s.get("duration") or 3.0) for s in scenes))

    set_queue_status(user_id, queue_id, "RENDERING")
    note("RENDERING", 60, "Rendering with FFmpeg")
    job_id = insert(
        "render_jobs",
        {
            "project_id": project["id"],
            "preset": cfg.get("render_preset") or "balanced",
            "status": "running",
            "progress": 0,
            "step": "starting",
            "started_at": utcnow(),
            "created_at": utcnow(),
        },
    )

    scene_payload = [
        {
            **scene,
            "asset_path": scene.get("asset_path") or _asset_path(scene),
            "audio_path": _scene_audio_lookup(scene),
        }
        for scene in scenes
    ]
    if any(not s.get("audio_path") for s in scene_payload):
        raise PipelineError("One or more scenes are missing narration audio")

    def render_progress(pct: float, step: str) -> None:
        execute("UPDATE render_jobs SET progress=?, step=? WHERE id=?", (pct, step, job_id))
        note("RENDERING", 60 + pct * 0.28, step)

    from .renderer import RenderError, render_project

    try:
        result = await asyncio.to_thread(
            render_project,
            project,
            scene_payload,
            voice_path=project.get("voice_path"),
            music_path=music_path,
            subtitle_file=subs.get("path"),
            preset_key=str(cfg.get("render_preset") or "balanced"),
            music_volume=float(cfg.get("music_volume") or 0.18),
            job_id=job_id,
            progress_cb=render_progress,
        )
    except RenderError as exc:
        execute("UPDATE render_jobs SET status='failed', error=?, finished_at=? WHERE id=?", (str(exc), utcnow(), job_id))
        raise PipelineError(str(exc)) from exc

    set_queue_status(user_id, queue_id, "QUALITY_CHECK")
    note("QUALITY_CHECK", 92, "Scoring output")
    report = quality_report(user_id, idea, script, scenes, result.output_path, subs)

    improved = False
    if report["score"] < report["threshold"] and cfg.get("auto_improve", True) and not force:
        note("QUALITY_CHECK", 94, "Score below threshold - improving once")
        improved = True
        sharper = (script.get("hook") or "").strip()
        if not sharper:
            alt = loads(script.get("alt_hooks"), [])
            sharper = alt[0] if alt else f"Here is what nobody tells you about {idea['topic']}."
        scripts.update_script(user_id, script["id"], {"hook": sharper})
        script = scripts.get_script(user_id, idea["id"]) or script
        scenes = resequence_scenes(scripts.scenes_for(script["id"]))
        report = quality_report(user_id, idea, script, scenes, result.output_path, subs)

    execute(
        "UPDATE video_projects SET status='ready', quality_score=?, quality_report=?, updated_at=? WHERE id=?",
        (report["score"], dumps(report), utcnow(), project["id"]),
    )

    if report["score"] < report["threshold"]:
        set_queue_status(user_id, queue_id, "WAITING_FOR_APPROVAL", f"Quality {report['score']} below {report['threshold']}")
        _register_publish(user_id, queue_id, project["id"], "WAITING_FOR_APPROVAL")
        return {"status": "NEEDS_REVIEW", "report": report, "output": result.output_path, "improved": improved, "project_id": project["id"], "queue_id": queue_id}

    # A high score must not hide invented statistics: those need a human to
    # check the numbers against the sources before anything is published.
    if report.get("requires_review") and not force:
        figures = ", ".join(report.get("unsourced_figures") or [])
        set_queue_status(user_id, queue_id, "WAITING_FOR_APPROVAL", f"Unverified figures: {figures}")
        _register_publish(user_id, queue_id, project["id"], "WAITING_FOR_APPROVAL")
        return {
            "status": "NEEDS_REVIEW",
            "report": report,
            "output": result.output_path,
            "improved": improved,
            "project_id": project["id"],
            "queue_id": queue_id,
            "reason": f"unverified figures: {figures}",
        }

    set_queue_status(user_id, queue_id, "READY_TO_UPLOAD", f"Quality {report['score']}")
    note("READY_TO_UPLOAD", 100, "Video ready")
    _register_publish(user_id, queue_id, project["id"], "READY_TO_UPLOAD")
    return {"status": "READY_TO_UPLOAD", "report": report, "output": result.output_path, "project_id": project["id"], "queue_id": queue_id, "improved": improved}


def _register_publish(user_id: int, queue_id: int, project_id: int, queue_status: str) -> None:
    """Create the local publish package. Never fails the render over packaging."""
    from . import publishing

    try:
        publishing.upsert_from_project(
            user_id, queue_id=queue_id, project_id=project_id, queue_status=queue_status
        )
    except Exception as exc:  # noqa: BLE001
        log_event(
            "Publish package registration failed",
            level="warn",
            scope="publish",
            user_id=user_id,
            context={"queue_id": queue_id, "error": str(exc)},
        )


def _asset_path(scene: dict[str, Any]) -> str | None:
    if not scene.get("asset_id"):
        return None
    row = query_one("SELECT path FROM assets WHERE id=?", (scene["asset_id"],))
    return row.get("path") if row else None


async def enqueue_idea(user_id: int, idea_id: int, *, position: int | None = None) -> dict[str, Any]:
    existing = query_one("SELECT * FROM queue_items WHERE idea_id=?", (idea_id,))
    if existing:
        return existing
    max_pos = query_one("SELECT COALESCE(MAX(position), 0) AS p FROM queue_items WHERE user_id=?", (user_id,))
    pos = position if position is not None else int(max_pos["p"] if max_pos else 0) + 1
    queue_id = insert(
        "queue_items",
        {
            "user_id": user_id,
            "idea_id": idea_id,
            "position": pos,
            "status": "IDEA",
            "priority": 0,
            "attempts": 0,
            "timeline": dumps([{"status": "IDEA", "at": utcnow(), "note": "Queued"}]),
            "created_at": utcnow(),
            "updated_at": utcnow(),
        },
    )
    emit(user_id, "queue_update", {"queue_id": queue_id, "status": "IDEA"})
    return query_one("SELECT * FROM queue_items WHERE id=?", (queue_id,)) or {}


def next_queue_item(user_id: int) -> dict[str, Any] | None:
    return query_one(
        """SELECT * FROM queue_items
           WHERE user_id=? AND status IN ('IDEA','RESEARCHING','SCRIPT_READY','GENERATING_AUDIO',
                'GENERATING_VISUALS','RENDERING','QUALITY_CHECK','FAILED')
           ORDER BY priority DESC, position ASC, id ASC LIMIT 1""",
        (user_id,),
    )
