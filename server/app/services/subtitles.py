"""Animated subtitle generation.

Produces a real .ass file consumed by FFmpeg's `subtitles` filter. Word-level
timings come from the TTS engine (edge-tts gives exact boundaries, other
providers get proportional estimation). Seven presets share one layout engine.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import settings

STYLES: dict[str, dict[str, Any]] = {
    "mrbeast": {
        "label": "MrBeast-style emphasis",
        "font": "Arial Black",
        "size": 96,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E0FF",
        "outline": "&H00000000",
        "back": "&H80000000",
        "bold": 1,
        "outline_w": 7,
        "shadow": 2,
        "border_style": 1,
        "upper": True,
        "pop": True,
    },
    "minimal-cinematic": {
        "label": "Minimal cinematic",
        "font": "Segoe UI Semibold",
        "size": 68,
        "primary": "&H00FFFFFF",
        "secondary": "&H00C8C8C8",
        "outline": "&H00000000",
        "back": "&H40000000",
        "bold": 0,
        "outline_w": 2,
        "shadow": 1,
        "border_style": 1,
        "upper": False,
        "pop": False,
    },
    "clean-educational": {
        "label": "Clean educational",
        "font": "Segoe UI",
        "size": 70,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000E0FF",
        "outline": "&H00000000",
        "back": "&HC0000000",
        "bold": 1,
        "outline_w": 3,
        "shadow": 1,
        "border_style": 3,
        "upper": False,
        "pop": False,
    },
    "gaming": {
        "label": "Gaming",
        "font": "Impact",
        "size": 92,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000FFC8",
        "outline": "&H00201020",
        "back": "&H90000000",
        "bold": 1,
        "outline_w": 6,
        "shadow": 3,
        "border_style": 1,
        "upper": True,
        "pop": True,
    },
    "neon": {
        "label": "Neon",
        "font": "Consolas",
        "size": 76,
        "primary": "&H00F0E0FF",
        "secondary": "&H00FF40E0",
        "outline": "&H006020A0",
        "back": "&H00000000",
        "bold": 1,
        "outline_w": 4,
        "shadow": 4,
        "border_style": 1,
        "upper": True,
        "pop": True,
    },
    "documentary": {
        "label": "Documentary",
        "font": "Georgia",
        "size": 62,
        "primary": "&H00F5F5F0",
        "secondary": "&H00D8D0C0",
        "outline": "&H00000000",
        "back": "&H50000000",
        "bold": 0,
        "outline_w": 2,
        "shadow": 1,
        "border_style": 1,
        "upper": False,
        "pop": False,
    },
    "modern-bold": {
        "label": "Modern bold",
        "font": "Arial",
        "size": 86,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000D0FF",
        "outline": "&H00000000",
        "back": "&H00000000",
        "bold": 1,
        "outline_w": 5,
        "shadow": 2,
        "border_style": 1,
        "upper": False,
        "pop": True,
    },
}


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _wrap(words: list[str], max_words: int = 4, max_chars: int = 24) -> list[list[str]]:
    lines: list[list[str]] = []
    current: list[str] = []
    for word in words:
        candidate = current + [word]
        if len(candidate) > max_words or len(" ".join(candidate)) > max_chars:
            if current:
                lines.append(current)
            current = [word]
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_ass(
    word_timings: list[dict[str, Any]],
    out_path: Path,
    *,
    style_key: str = "modern-bold",
    font_size: int | None = None,
    primary: str | None = None,
    secondary: str | None = None,
    uppercase: bool | None = None,
    margin_v: int = 320,
    words_per_caption: int = 3,
) -> Path:
    style = dict(STYLES.get(style_key, STYLES["modern-bold"]))
    if font_size:
        style["size"] = font_size
    if primary:
        style["primary"] = primary
    if secondary:
        style["secondary"] = secondary
    if uppercase is not None:
        style["upper"] = uppercase

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{style['font']},{style['size']},{style['primary']},{style['secondary']},{style['outline']},{style['back']},{style['bold']},0,0,0,100,100,0,0,{style['border_style']},{style['outline_w']},{style['shadow']},2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    cleaned = [w for w in word_timings if str(w.get("word", "")).strip()]
    if not cleaned:
        out_path.write_text(header, encoding="utf-8")
        return out_path

    groups = _wrap([str(w["word"]) for w in cleaned], max_words=words_per_caption, max_chars=words_per_caption * 9)
    idx = 0
    for group in groups:
        chunk = cleaned[idx : idx + len(group)]
        idx += len(group)
        if not chunk:
            continue
        start = float(chunk[0]["start"])
        end = float(chunk[-1]["end"])
        end = max(end, start + 0.28)
        # word-by-word highlight inside the caption group
        for i, item in enumerate(chunk):
            w_start = float(item["start"])
            w_end = float(item["end"]) if i < len(chunk) - 1 else end
            w_end = max(w_end, w_start + 0.14)
            parts = []
            for j, other in enumerate(chunk):
                word = str(other["word"])
                if style["upper"]:
                    word = word.upper()
                word = word.replace("{", "(").replace("}", ")")
                if j == i:
                    parts.append(r"{\c" + style["secondary"].replace("&H00", "&H") + "&}" + word + r"{\c" + style["primary"] + "&}")
                else:
                    parts.append(word)
            text = " ".join(parts)
            effect = r"{\fad(80,80)}"
            if style["pop"] and i == 0:
                text = r"{\fscx112\fscy112\t(0,120,\fscx100\fscy100)}" + text
            events.append(
                f"Dialogue: 0,{_ts(w_start)},{_ts(w_end)},Caption,,0,0,0,,{effect}{text}"
            )
    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_path


def word_timings_from_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten per-scene word timings into a global timeline using scene start offsets."""
    out: list[dict[str, Any]] = []
    for scene in scenes:
        offset = float(scene.get("start_at") or 0.0)
        for item in scene.get("words") or []:
            out.append(
                {
                    "word": item.get("word"),
                    "start": round(float(item.get("start", 0)) + offset, 3),
                    "end": round(float(item.get("end", 0)) + offset, 3),
                }
            )
    return out


def srt_from_words(word_timings: list[dict[str, Any]], path: Path, words_per_line: int = 6) -> Path:
    def stamp(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i in range(0, len(word_timings), words_per_line):
        chunk = word_timings[i : i + words_per_line]
        if not chunk:
            continue
        lines.append(
            f"{len(lines) + 1}\n{stamp(float(chunk[0]['start']))} --> {stamp(float(chunk[-1]['end']))}\n"
            + " ".join(str(c["word"]) for c in chunk)
            + "\n"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def subtitle_filter_path(path: Path) -> str:
    """Escape a Windows path for use inside an FFmpeg filter argument."""
    p = str(path).replace("\\", "/")
    p = re.sub(r"([:'])", r"\\\1", p)
    return p


def safe_zone_margin() -> int:
    return 320
