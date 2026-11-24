"""Script generation for 15-60 second Shorts.

The local model is used when available. When it is not (or fails), a
deterministic structured generator produces a real script from the idea and
research snippets so the pipeline still yields usable, non-fabricated content.
"""
from __future__ import annotations

import html
import json
import math
import re
from typing import Any

from ..db import dumps, execute, insert, loads, query, query_one, utcnow
from . import ai

WORDS_PER_SECOND = 2.6

SYSTEM = (
    "You are a senior YouTube Shorts scriptwriter. You write tight, factual, conversational "
    "scripts. You never invent statistics or quotes. If a fact is uncertain you phrase it "
    "carefully. Output JSON only when asked."
)


def _target_words(seconds: int) -> int:
    return max(28, int(seconds * WORDS_PER_SECOND))


ABBREVIATIONS = {
    "vs", "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "ft", "no", "fig", "approx",
    "e.g", "i.e", "etc", "inc", "ltd", "co", "corp", "dept", "est", "min", "max", "avg",
}


def split_sentences(text: str) -> list[str]:
    """Split into sentences without breaking on abbreviations or decimals."""
    text = (text or "").strip()
    if not text:
        return []
    parts: list[str] = []
    buffer = ""
    for token in re.split(r"(\s+)", text):
        buffer += token
        core = token.strip()
        if not core:
            continue
        if not core.endswith((".", "!", "?")):
            continue
        word = re.sub(r"[^\w.]", "", core).rstrip(".!?").lower()
        if core.endswith(".") and (word in ABBREVIATIONS or re.fullmatch(r"[\d.]+", word)):
            continue
        if core.endswith(".") and len(word) == 1:
            continue
        parts.append(buffer.strip())
        buffer = ""
    if buffer.strip():
        parts.append(buffer.strip())
    return [p for p in parts if p]


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def fingerprint(topic: str, angle: str | None = None) -> str:
    norm = re.sub(r"[^a-z0-9 ]", "", f"{topic} {angle or ''}".lower())
    tokens = sorted({t for t in norm.split() if len(t) > 2})
    return "-".join(tokens[:8])


NUMBER_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:billion|million|thousand|trillion|percent|%|km|kilometers?|miles?|years?|"
    r"light[- ]years?|degrees?|tons?|kg|meters?|feet|inches)?\b",
    re.I,
)


def unsourced_numbers(body: str, sources: list[dict[str, Any]]) -> list[str]:
    """Numbers spoken in the script that appear nowhere in the research snippets.

    The local model happily invents statistics ("500 million elephants"). Those
    claims are reported rather than silently rewritten, so a human can rework the
    script before it is published.
    """
    corpus = " ".join(
        f"{s.get('title') or ''} {s.get('snippet') or ''}" for s in sources
    ).lower()
    corpus_digits = set(re.findall(r"\d[\d,\.]*", corpus))
    flagged: list[str] = []
    for match in NUMBER_RE.finditer(body or ""):
        token = match.group(0).strip()
        digits = re.sub(r"[^\d]", "", token)
        if not digits:
            continue
        if digits in {re.sub(r"[^\d]", "", d) for d in corpus_digits}:
            continue
        if token not in flagged:
            flagged.append(token)
    return flagged


def _clean_text(text: str) -> str:
    """Repair mojibake, decode entities and strip feed noise from research snippets."""
    text = html.unescape(html.unescape(text or ""))
    text = (text or "").replace("\u00e2\u20ac\u2122", "'").replace("\u00e2\u20ac\u0153", '"').replace("\u00e2\u20ac\u009d", '"')
    text = text.replace("\u00e2\u20ac\u201d", " - ").replace("\u00e2\u20ac\u201c", " - ")
    text = text.replace("\ufffd", " ")
    text = re.sub(r"\s+-\s+[^-]{0,40}(?:Key Differences|Universe|Tech|News|Times|Today|Report)\b.*$", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


DIRECTION_RE = re.compile(
    r"\b(the narrator|a video plays|close[- ]up|wide shot|medium shot|cut to|camera|on screen|"
    r"we see|shot of|stock footage|b-roll|visuali[sz]e|the screen shows|footage of)\b",
    re.I,
)


def looks_like_direction(text: str) -> bool:
    """True when a line describes camera work instead of spoken words."""
    return bool(DIRECTION_RE.search(text or ""))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _align_scenes_to_body(
    scenes: list[dict[str, Any]], body: str, payload: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Rebuild narration from the spoken body, keeping the model's visual direction.

    Models write scene narration as free prose that drifts from ``body`` (extra
    sentences, camera directions, other topics). The body is the single source of
    truth for what gets spoken, so scenes are regrouped from it and only the
    visual prompt, overlay, motion and transition are borrowed from the model.
    """
    if not body.strip():
        return scenes

    rebuilt = build_scenes_from_text(body, payload, count=max(3, min(len(scenes), 6)))
    if not rebuilt:
        return scenes

    merged: list[dict[str, Any]] = []
    for idx, scene in enumerate(rebuilt):
        donor = scenes[idx] if idx < len(scenes) and isinstance(scenes[idx], dict) else {}
        prompt = str(donor.get("visual_prompt") or "").strip()
        if prompt:
            scene["visual_prompt"] = prompt[:600]
        if donor.get("motion"):
            scene["motion"] = donor["motion"]
        if donor.get("transition"):
            scene["transition"] = donor["transition"]
        overlay = str(donor.get("overlay_text") or "").strip()
        if overlay:
            scene["overlay_text"] = overlay
        merged.append(scene)
    return merged


def _finish_sentence(body: str) -> str:
    """Drop a trailing fragment so narration never stops mid-sentence."""
    text = (body or "").strip()
    if not text:
        return text
    if text[-1] in ".!?\"'":
        return text
    cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "))
    if cut == -1:
        return text if text[-1] in ".!?" else text.rstrip(",;:-") + "."
    return text[: cut + 1].strip()


def _fit_to_budget(body: str, max_words: int) -> str:
    """Trim a script down to the spoken word budget without breaking the payoff."""
    if max_words <= 0 or word_count(body) <= max_words:
        return body
    sentences = [s for s in split_sentences(body) if s.strip()]
    if len(sentences) <= 2:
        return body

    hook, middle, payoff = sentences[0], list(sentences[1:-1]), sentences[-1]

    def joined() -> str:
        return " ".join([hook, *middle, payoff]).strip()

    while middle and word_count(joined()) > max_words:
        middle.pop()
    return joined()


def _narratable(sentence: str) -> bool:
    """Reject fragments, headlines and feed junk that would sound broken when read aloud."""
    s = sentence.strip()
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", s)
    if len(words) < 8:
        return False
    if s.endswith((",", ":", ";", "-", "vs.", "vs", "and", "the", "of", "a", "in", "to")):
        return False
    if re.search(r"[\u2013\u2014|]", s):
        return False
    if re.search(r"\s+-\s+[A-Z]", s):
        return False
    if s.count("..") > 1 or s.endswith("?"):
        return False
    if re.search(r"\b(Discover Magazine|NASA SVS|Space News|Times|Today|Report|\.gov|\.com)\b", s):
        return False
    if re.search(r"\b(McKinsey|Bain|Deloitte|private equity|press release|according to a report|"
                 r"study finds|experts say|in the words of)\b", s, re.I):
        return False
    if "&amp;" in s or "&nbsp;" in s or re.search(r"&#\d+;", s):
        return False
    if sum(1 for c in s if not c.isascii()) > max(2, len(s) * 0.04):
        return False
    return True


def _fallback_script(idea: dict[str, Any], sources: list[dict[str, Any]], seconds: int) -> dict[str, Any]:
    topic = _clean_text(idea.get("topic") or "this topic")
    angle = _clean_text(idea.get("angle") or "")
    hook = idea.get("hook") or f"What if the story behind {topic.lower()} is not what you were told?"

    # Wikipedia summaries read as prose; feed headlines do not. Prefer them.
    ranked = sorted(sources, key=lambda s: 0 if s.get("source_type") == "wikipedia" else 1)
    facts: list[str] = []
    for src in ranked:
        for sentence in split_sentences(_clean_text(src.get("snippet") or "")):
            if _narratable(sentence) and sentence not in facts:
                facts.append(sentence)
    facts = facts[:4]

    if facts:
        body = " ".join(facts)
    else:
        subject = (angle or topic).rstrip(".")
        body = (
            f"Start with one idea that makes everything else click. {subject} is really a story about "
            f"scale, cause and effect. Once that pattern is clear, the rest of the details stop feeling random. "
            f"Hold that picture in mind and the pieces arrange themselves."
        )
    subject = (angle or topic).rstrip(".")
    payoff = (
        f"The takeaway: once you see the pattern, {subject.lower()} stops being trivia and starts making sense."
        if not facts
        else f"The takeaway: that is why {subject.lower()} keeps showing up in the headlines."
    )
    cta = "Follow for more short explainers like this."
    full = " ".join([hook, body, payoff]).strip()
    return {
        "hook": hook,
        "body": full,
        "cta": cta,
        "alt_hooks": [
            f"Nobody explains {topic.lower()} like this.",
            f"The {topic.lower()} detail almost everyone misses.",
            f"This changes how you think about {topic.lower()}.",
        ],
        "title": topic[:70],
        "description": (
            f"{angle or topic}. A short explainer built from public sources.\n\n"
            + " ".join(f"Source: {s['url']}" for s in sources[:3] if s.get("url"))
        ),
        "hashtags": ["#shorts", "#facts", "#explained"],
        "keywords": [w for w in re.findall(r"[a-zA-Z]{4,}", topic.lower())][:8],
        "pinned_comment": f"Which part surprised you most about {topic.lower()}?",
        "voice_direction": "Calm, confident, slight upward energy on the hook. Slow down on the payoff.",
    }


def _normalize_payload(data: Any) -> dict[str, Any]:
    """Unwrap models that nest the script under a wrapper key, and repair scene shapes."""
    if not isinstance(data, dict):
        return {}
    for wrapper in ("script", "result", "output", "data", "response"):
        inner = data.get(wrapper)
        if isinstance(inner, dict) and ("body" in inner or "hook" in inner):
            data = {**data, **inner}
            break
    if not data.get("body"):
        for value in data.values():
            if isinstance(value, dict) and value.get("body"):
                data = {**data, **value}
                break
    scenes = data.get("scenes")
    if isinstance(scenes, dict):
        for key in ("scenes", "items", "list"):
            if isinstance(scenes.get(key), list):
                scenes = scenes[key]
                break
    if isinstance(scenes, list):
        repaired = []
        for entry in scenes:
            if isinstance(entry, str) and entry.strip():
                repaired.append({"narration": entry.strip()})
            elif isinstance(entry, dict):
                narration = entry.get("narration") or entry.get("text") or entry.get("line")
                if not narration:
                    continue
                repaired.append(
                    {
                        **entry,
                        "narration": str(narration).strip(),
                        "visual_prompt": entry.get("visual_prompt") or entry.get("visual") or entry.get("vISTUAL PROMPT") or "",
                    }
                )
        data["scenes"] = repaired

    # Some models return scenes but no body; rebuild the narration from scenes
    # instead of throwing away a perfectly good script.
    if not data.get("body"):
        hooks = data.get("hooks")
        if not data.get("hook") and isinstance(hooks, list) and hooks:
            data["hook"] = str(hooks[0]).strip()
        narration_parts = [
            str(s.get("narration") or "").strip()
            for s in data.get("scenes") or []
            if isinstance(s, dict) and str(s.get("narration") or "").strip()
        ]
        if narration_parts:
            data["body"] = " ".join(narration_parts)
        if not data.get("alt_hooks") and isinstance(hooks, list):
            data["alt_hooks"] = [str(h) for h in hooks[1:4] if str(h).strip()]
    return data


async def generate_script(
    user_id: int,
    idea: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    seconds: int = 45,
    language: str = "en",
    style: str = "energetic-explainer",
    temperature: float = 0.6,
    model: str | None = None,
) -> dict[str, Any]:
    target = _target_words(seconds)
    source_block = "\n".join(
        f"- {s.get('title', '')} :: {(s.get('snippet') or '')[:300]} :: {s.get('url', '')}"
        for s in sources[:6]
    ) or "- (no external sources retrieved; keep claims general and safe)"

    prompt = f"""Write a YouTube Shorts script.

Topic: {idea.get('topic')}
Angle: {idea.get('angle') or 'n/a'}
Audience: {idea.get('audience') or 'general audience'}
Suggested hook: {idea.get('hook') or 'n/a'}
Language: {language}
Style: {style}
Target length: {seconds} seconds. The spoken body MUST be {target}-{target + 15} words.
Write 4-6 sentences for the body. Do not write fewer than {target} words.

Research notes (ground truth - do not invent beyond these, avoid unverifiable numbers):
{source_block}

Rules: hook in the first sentence, no intro like "hey guys", short sentences, no fake statistics,
no clickbait lies, end with a natural payoff. If sources are thin, stay general.
Narration must be only the words a narrator speaks - never camera directions, shot lists or
descriptions of the video. Keep every sentence on the topic above; do not drift into unrelated
stories. Use plain text only: no HTML entities such as &amp;, no markdown, no URLs.

Return JSON with keys:
hook, body (the full spoken script including hook and payoff), cta, alt_hooks (array of 3),
title (<=90 chars), description, hashtags (array, no duplicates), keywords (array),
pinned_comment, voice_direction, scenes (array of 4-6 objects with keys narration, visual_prompt,
overlay_text, motion (zoom_in|zoom_out|pan_left|pan_right|ken_burns), transition (fade|slide|whip|none))"""

    payload: dict[str, Any]
    origin = "ai"
    attempts = 0
    last_error: str | None = None
    while attempts < 2:
        attempts += 1
        try:
            raw = await ai.generate(
                prompt, system=SYSTEM, model=model, temperature=temperature, json_mode=True, num_predict=2400
            )
            data = _normalize_payload(ai.extract_json(raw))
            if data.get("body"):
                payload = data
                break
            last_error = "model JSON lacked a usable body/scenes"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:200]
    else:
        payload = _fallback_script(idea, sources, seconds)
        origin = "template"
        if last_error:
            from ..db import log_event

            log_event("Script fell back to template writer", level="warn", scope="script", context={"reason": last_error})

    body = _clean_text(str(payload.get("body") or "")).strip()
    hook = _clean_text(str(payload.get("hook") or "")).strip()
    if len(hook) > 90:
        first = (split_sentences(hook) or [hook])[0]
        hook = first[:120]
    if hook and not body.startswith(hook[:24]):
        body = f"{hook} {body}".strip()

    # Small local models routinely undershoot the word budget, which yields a
    # video far shorter than requested. Ask once more, explicitly, for length.
    if origin == "ai" and word_count(body) < target * 0.75:
        try:
            expand_prompt = (
                f"Rewrite this YouTube Shorts script so the spoken body is between {target} and "
                f"{target + 10} words, staying strictly on topic. Keep the hook and the payoff. "
                f"Do not add camera directions, HTML entities or URLs.\n\nTopic: {idea.get('topic')}\n"
                f"Current script ({word_count(body)} words):\n{body}\n\n"
                "Return JSON with keys: hook, body."
            )
            raw = await ai.generate(
                expand_prompt, system=SYSTEM, model=model, temperature=temperature, json_mode=True, num_predict=900
            )
            longer = _clean_text(str(_normalize_payload(ai.extract_json(raw)).get("body") or "")).strip()
            if word_count(longer) > word_count(body):
                body = f"{hook} {longer}".strip() if hook and not longer.startswith(hook[:24]) else longer
        except Exception as exc:  # noqa: BLE001
            from ..db import log_event

            log_event(
                "Script expansion pass failed",
                level="warn",
                scope="script",
                context={"reason": str(exc)[:160]},
            )

    body = _fit_to_budget(body, target + 15)
    body = _finish_sentence(body)
    wc = word_count(body)
    est_seconds = int(round(wc / WORDS_PER_SECOND))

    scenes = payload.get("scenes")
    if isinstance(scenes, list) and scenes:
        scenes = [
            s
            for s in scenes
            if isinstance(s, dict) and str(s.get("narration") or "").strip()
        ]
    if not isinstance(scenes, list) or len(scenes) < 3:
        scenes = build_scenes_from_text(body, payload)
    else:
        scenes = _align_scenes_to_body(scenes, body, payload)

    row = {
        "idea_id": idea["id"],
        "user_id": user_id,
        "hook": hook,
        "body": body,
        "cta": str(payload.get("cta") or "").strip(),
        "alt_hooks": dumps(payload.get("alt_hooks") or []),
        "title": str(payload.get("title") or idea.get("topic") or "")[:100],
        "description": str(payload.get("description") or "")[:4900],
        "hashtags": dumps(payload.get("hashtags") or []),
        "keywords": dumps(payload.get("keywords") or []),
        "pinned_comment": str(payload.get("pinned_comment") or "")[:400],
        "voice_direction": str(payload.get("voice_direction") or "")[:600],
        "target_seconds": seconds,
        "language": language,
        "style": style,
        "word_count": wc,
        "version": 1,
        "approved": 0,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    execute("DELETE FROM scripts WHERE idea_id=?", (idea["id"],))
    script_id = insert("scripts", row)
    execute("DELETE FROM scenes WHERE script_id=?", (script_id,))
    save_scenes(script_id, scenes, est_seconds)
    result = query_one("SELECT * FROM scripts WHERE id=?", (script_id,)) or {}
    result["alt_hooks"] = loads(result.get("alt_hooks"), [])
    result["hashtags"] = loads(result.get("hashtags"), [])
    result["keywords"] = loads(result.get("keywords"), [])
    result["scenes"] = scenes_for(script_id)
    result["_origin"] = origin
    result["_est_seconds"] = est_seconds
    return result


def build_scenes_from_text(
    body: str, payload: dict[str, Any] | None = None, *, count: int | None = None
) -> list[dict[str, Any]]:
    payload = payload or {}
    sentences = [s for s in split_sentences(body) if s]
    if not sentences:
        sentences = [body]

    desired = max(1, min(int(count or 4), 6))
    target_scenes = max(1, min(desired, len(sentences)))
    total_words = sum(word_count(s) for s in sentences) or 1
    per_scene = total_words / target_scenes

    # Group whole sentences so narration is never cut mid-thought, while keeping
    # each scene close to an even share of the spoken words.
    sentences = [s for s in sentences if s]
    groups: list[list[str]] = []
    buffer: list[str] = []
    for idx, sentence in enumerate(sentences):
        remaining_scenes = target_scenes - len(groups)
        remaining_sentences = len(sentences) - idx
        if buffer and (
            sum(word_count(x) for x in buffer) >= per_scene
            or remaining_sentences <= remaining_scenes - 1
        ):
            groups.append(buffer)
            buffer = []
        buffer.append(sentence)
    if buffer:
        groups.append(buffer)
    while len(groups) > target_scenes and len(groups) > 1:
        groups[-2].extend(groups[-1])
        groups.pop()

    motions = ["zoom_in", "ken_burns", "pan_right", "zoom_out", "pan_left", "ken_burns"]
    topic = re.sub(r"[^a-zA-Z0-9 ]", "", (payload.get("title") or body[:60])).strip()
    scenes = []
    for idx, group in enumerate(groups):
        narration = " ".join(group)
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{4,}", narration) if w.lower() not in {
            "about", "there", "these", "those", "which", "would", "could", "because", "their", "other", "every",
        }]
        key_terms = ", ".join(dict.fromkeys(words[:4])) or topic
        overlay = ""
        if group:
            first = re.findall(r"[A-Za-z][A-Za-z'-]+", group[0])
            overlay = " ".join(first[:4]).upper()
        scenes.append(
            {
                "scene_no": idx + 1,
                "narration": narration,
                "visual_prompt": (
                    f"Vertical 9:16 cinematic illustration about {topic}, focusing on {key_terms}, "
                    "high contrast, dramatic lighting, no text, no watermark"
                ),
                "overlay_text": overlay[:60],
                "motion": motions[idx % len(motions)],
                "transition": "fade" if idx else "none",
            }
        )
    return scenes


def save_scenes(script_id: int, scenes: list[dict[str, Any]], est_seconds: int) -> list[dict[str, Any]]:
    total_words = sum(word_count(str(s.get("narration") or "")) for s in scenes) or 1
    created = []
    for idx, scene in enumerate(scenes, start=1):
        words = word_count(str(scene.get("narration") or ""))
        duration = max(1.5, round(est_seconds * (words / total_words), 2))
        motion = str(scene.get("motion") or "zoom_in")
        if motion not in {"zoom_in", "zoom_out", "pan_left", "pan_right", "ken_burns"}:
            motion = "ken_burns"
        transition = str(scene.get("transition") or "fade")
        if transition not in {"fade", "slide", "whip", "none"}:
            transition = "fade"
        scene_id = insert(
            "scenes",
            {
                "script_id": script_id,
                "scene_no": scene.get("scene_no") or idx,
                "narration": str(scene.get("narration") or "").strip(),
                "visual_prompt": str(scene.get("visual_prompt") or "").strip()[:600],
                "overlay_text": str(scene.get("overlay_text") or "").strip()[:80],
                "transition": transition,
                "motion": motion,
                "duration": duration,
                "start_at": 0.0,
                "created_at": utcnow(),
            },
        )
        created.append(query_one("SELECT * FROM scenes WHERE id=?", (scene_id,)) or {})
    return created


def scenes_for(script_id: int) -> list[dict[str, Any]]:
    return query("SELECT * FROM scenes WHERE script_id=? ORDER BY scene_no", (script_id,))


def resequence(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recompute start times / durations from actual narration durations."""
    cursor = 0.0
    out = []
    for scene in scenes:
        duration = float(scene.get("duration") or 3.0)
        execute("UPDATE scenes SET start_at=?, duration=? WHERE id=?", (round(cursor, 3), duration, scene["id"]))
        out.append({**scene, "start_at": round(cursor, 3)})
        cursor += duration
    return out


def get_script(user_id: int, idea_id: int) -> dict[str, Any] | None:
    row = query_one(
        "SELECT * FROM scripts WHERE idea_id=? AND user_id=? ORDER BY version DESC, id DESC LIMIT 1",
        (idea_id, user_id),
    )
    if row:
        row["alt_hooks"] = loads(row.get("alt_hooks"), [])
        row["hashtags"] = loads(row.get("hashtags"), [])
        row["keywords"] = loads(row.get("keywords"), [])
        row["scenes"] = scenes_for(row["id"])
    return row


def update_script(user_id: int, script_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    row = query_one("SELECT * FROM scripts WHERE id=? AND user_id=?", (script_id, user_id))
    if not row:
        raise ValueError("Script not found")
    allowed = {
        "hook", "body", "cta", "title", "description", "pinned_comment", "voice_direction",
        "target_seconds", "language", "style", "approved",
    }
    data: dict[str, Any] = {}
    for key in allowed:
        if key in patch and patch[key] is not None:
            data[key] = patch[key]
    for key in ("alt_hooks", "hashtags", "keywords"):
        if key in patch and patch[key] is not None:
            val = patch[key]
            data[key] = dumps(val if isinstance(val, list) else [val])
    if "body" in data:
        data["word_count"] = word_count(str(data["body"]))
    if data:
        data["updated_at"] = utcnow()
        assignments = ", ".join(f"{k}=?" for k in data)
        execute(f"UPDATE scripts SET {assignments} WHERE id=?", (*data.values(), script_id))
    return get_script(user_id, row["idea_id"]) or row


def regenerate_scenes(script_id: int, seconds: int) -> list[dict[str, Any]]:
    script = query_one("SELECT * FROM scripts WHERE id=?", (script_id,))
    if not script:
        raise ValueError("Script not found")
    execute("DELETE FROM scenes WHERE script_id=?", (script_id,))
    scenes = build_scenes_from_text(script["body"], {"title": script.get("title")})
    return save_scenes(script_id, scenes, seconds)
