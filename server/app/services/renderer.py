"""FFmpeg render pipeline: scenes -> motion -> overlays -> audio mix -> captions -> MP4."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from ..config import settings
from ..db import execute, insert, log_event, query, query_one, utcnow

PRESETS: dict[str, dict[str, Any]] = {
    "fast": {"w": 720, "h": 1280, "fps": 24, "crf": 28, "preset": "veryfast", "audio": "128k", "label": "Fast (low-end PC)"},
    "balanced": {"w": 1080, "h": 1920, "fps": 30, "crf": 23, "preset": "medium", "audio": "192k", "label": "Balanced (default)"},
    "high": {"w": 1080, "h": 1920, "fps": 30, "crf": 18, "preset": "slow", "audio": "256k", "label": "High quality"},
    "lowend": {"w": 540, "h": 960, "fps": 24, "crf": 30, "preset": "ultrafast", "audio": "96k", "label": "Low-end PC (540p)"},
}

MOTION_EXPR = {
    "zoom_in": "zoom+0.0012",
    "zoom_out": "if(lte(zoom,1.0),1.12,max(1.001,zoom-0.0012))",
    "pan_left": "1.08",
    "pan_right": "1.08",
    "ken_burns": "zoom+0.0008",
}

XFADE_MAP = {"fade": "fade", "slide": "slideleft", "whip": "wipeleft", "none": None}


@dataclass
class RenderResult:
    output_path: str
    duration: float
    log_path: str
    command: str


class RenderError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    return settings.FFMPEG_BIN


def ffprobe_bin() -> str:
    return settings.FFPROBE_BIN


def check_ffmpeg() -> dict[str, Any]:
    info = {"ffmpeg": None, "ffprobe": None, "ok": False, "version": None}
    try:
        r = subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            info["ffmpeg"] = shutil.which(ffmpeg_bin()) or ffmpeg_bin()
            info["version"] = (r.stdout or "").splitlines()[0] if r.stdout else None
    except Exception:
        pass
    try:
        r2 = subprocess.run([ffprobe_bin(), "-version"], capture_output=True, text=True, timeout=20)
        if r2.returncode == 0:
            info["ffprobe"] = shutil.which(ffprobe_bin()) or ffprobe_bin()
    except Exception:
        pass
    info["ok"] = bool(info["ffmpeg"] and info["ffprobe"])
    return info


def probe(path: str) -> dict[str, Any]:
    try:
        out = subprocess.run(
            [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True,
            text=True,
            timeout=90,
        )
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def duration_of(path: str) -> float:
    data = probe(path)
    try:
        return float(data.get("format", {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _run(cmd: list[str], log_path: Path, progress_cb: Callable[[float, str], None] | None = None, total: float = 0.0) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            if progress_cb and total > 0:
                m = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                if m:
                    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    done = h * 3600 + mi * 60 + s
                    progress_cb(min(99.0, 100.0 * done / total), "encoding")
        proc.wait()
        return proc.returncode


def _scene_clip(
    image: str,
    audio: str,
    duration: float,
    out: Path,
    motion: str,
    preset: dict[str, Any],
    log: Path,
    *,
    transition: str = "fade",
    is_first: bool = False,
    is_last: bool = False,
) -> None:
    w, h, fps = preset["w"], preset["h"], preset["fps"]
    frames = max(2, int(round(duration * fps)))
    span = max(1, frames - 1)
    zoom = MOTION_EXPR.get(motion, MOTION_EXPR["ken_burns"])
    if motion == "pan_left":
        x_expr, y_expr = f"(iw-iw/zoom)*(on/{span})", "(ih-ih/zoom)/2"
    elif motion == "pan_right":
        x_expr, y_expr = f"(iw-iw/zoom)*(1-on/{span})", "(ih-ih/zoom)/2"
    else:
        x_expr, y_expr = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"

    fade = 0.28 if duration > 0.9 else min(0.18, duration / 4)
    fades: list[str] = []
    if transition != "none" and not is_first:
        fades.append(f"fade=t=in:st=0:d={fade:.3f}")
    if transition != "none" and not is_last:
        fades.append(f"fade=t=out:st={max(0.0, duration - fade):.3f}:d={fade:.3f}")

    vf = (
        f"scale={int(w * 1.35)}:-2,"
        f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':d=1:s={w}x{h}:fps={fps},"
        "setsar=1"
        + ("," + ",".join(fades) if fades else "")
    )
    cmd = [
        ffmpeg_bin(), "-y",
        "-loop", "1", "-framerate", str(fps), "-i", image,
        "-i", audio,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", preset["preset"], "-crf", str(preset["crf"]),
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", preset["audio"], "-ar", "48000", "-ac", "2",
        "-shortest", str(out),
    ]
    rc = _run(cmd, log)
    if rc != 0 or not out.exists():
        raise RenderError(f"Scene render failed for {Path(image).name} (see {log})")


def _concat(clips: Sequence[Path], out: Path, log: Path, transitions: Sequence[str], durations: Sequence[float], preset: dict[str, Any]) -> None:
    """Concatenate scene clips without altering narration timing.

    Transitions are rendered as per-clip visual fades inside _scene_clip; the
    concatenation itself is a straight join so no spoken word is ever dropped.
    """
    if len(clips) == 1:
        shutil.copyfile(clips[0], out)
        return
    parts: list[str] = []
    filter_chunks: list[str] = []
    for i, clip in enumerate(clips):
        parts += ["-i", str(clip)]
        filter_chunks.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[v{i}]")
        filter_chunks.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")

    inputs = " ".join(f"[v{i}][a{i}]" for i in range(len(clips)))
    filter_chunks.append(f"{inputs}concat=n={len(clips)}:v=1:a=1[vout][aout]")

    cmd = [
        ffmpeg_bin(), "-y", *parts,
        "-filter_complex", ";".join(filter_chunks),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", preset["preset"], "-crf", str(preset["crf"]),
        "-pix_fmt", "yuv420p", "-r", str(preset["fps"]),
        "-c:a", "aac", "-b:a", preset["audio"], "-ar", "48000", "-ac", "2",
        str(out),
    ]
    rc = _run(cmd, log)
    if rc != 0 or not out.exists():
        raise RenderError(f"Scene concatenation failed (see {log})")


def _final_mux(
    base: Path,
    out: Path,
    *,
    subtitle_file: Path | None,
    music: Path | None,
    voice_volume: float,
    music_volume: float,
    preset: dict[str, Any],
    log: Path,
    progress_cb: Callable[[float, str], None] | None,
    total: float,
) -> None:
    cmd = [ffmpeg_bin(), "-y", "-i", str(base)]
    filter_parts: list[str] = []
    audio_maps = ["-map", "0:a:0"] if not (music and music.exists()) else []
    if music and music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filter_parts.append(f"[0:a]volume={voice_volume:.2f}[voice]")
        filter_parts.append(f"[1:a]volume={music_volume:.2f},atrim=0:{total:.3f}[bed]")
        filter_parts.append("[voice][bed]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        audio_maps = ["-map", "[aout]"]
    else:
        filter_parts.append(f"[0:a]volume={voice_volume:.2f},loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        audio_maps = ["-map", "[aout]"]

    video_maps = ["-map", "0:v:0"]
    if subtitle_file and subtitle_file.exists():
        from .subtitles import subtitle_filter_path

        esc = subtitle_filter_path(subtitle_file)
        fonts = subtitle_filter_path(settings.dirs()["fonts"])
        filter_parts.append(f"[0:v]subtitles='{esc}':fontsdir='{fonts}'[vout]")
        video_maps = ["-map", "[vout]"]

    cmd += ["-filter_complex", ";".join(filter_parts), *video_maps, *audio_maps]
    cmd += [
        "-c:v", "libx264", "-preset", preset["preset"], "-crf", str(preset["crf"]),
        "-pix_fmt", "yuv420p", "-r", str(preset["fps"]),
        "-c:a", "aac", "-b:a", preset["audio"], "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out),
    ]
    rc = _run(cmd, log, progress_cb, total)
    if rc != 0 or not out.exists():
        raise RenderError(f"Final mux failed (see {log})")


def render_project(
    project: dict[str, Any],
    scenes: list[dict[str, Any]],
    *,
    voice_path: str | None,
    music_path: str | None,
    subtitle_file: str | None,
    preset_key: str = "balanced",
    voice_volume: float = 1.0,
    music_volume: float = 0.18,
    job_id: int | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> RenderResult:
    preset = PRESETS.get(preset_key, PRESETS["balanced"])
    # A unique work dir per render attempt: two pipelines can otherwise target
    # the same project and read each other's half-written clips.
    attempt = f"{int(time.time() * 1000)}_{os.getpid()}"
    work = settings.dirs()["tmp"] / f"project_{project['id']}" / f"run_{attempt}"
    work.mkdir(parents=True, exist_ok=True)
    logs = settings.dirs()["logs"]
    log_path = logs / f"render_{project['id']}_{int(time.time())}.log"
    stem = f"short_{project['id']}"
    output = settings.dirs()["videos"] / f"user_{project['user_id']}" / f"{stem}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    durations: list[float] = []
    transitions: list[str] = []

    if not scenes:
        raise RenderError("No scenes to render")

    for i, scene in enumerate(scenes):
        image = scene.get("asset_path") or scene.get("asset")
        if not image or not Path(image).exists():
            raise RenderError(f"Scene {scene.get('scene_no')} has no visual asset")
        duration = float(scene.get("duration") or 3.0)
        if duration <= 0.2:
            duration = 2.5
        audio = scene.get("audio_path") or voice_path
        if not audio or not Path(audio).exists():
            raise RenderError(f"Scene {scene.get('scene_no')} has no narration audio")
        clip = work / f"clip_{i:02d}.mp4"
        if progress_cb:
            progress_cb(5.0 + (i / max(1, len(scenes))) * 55.0, f"Rendering scene {i + 1}/{len(scenes)}")
        _scene_clip(
            str(image),
            str(audio),
            duration,
            clip,
            scene.get("motion") or "ken_burns",
            preset,
            log_path,
            transition=scene.get("transition") or "fade",
            is_first=(i == 0),
            is_last=(i == len(scenes) - 1),
        )
        clips.append(clip)
        durations.append(duration)
        transitions.append(scene.get("transition") or "fade")

    stitched = work / "stitched.mp4"
    if progress_cb:
        progress_cb(62.0, "Stitching scenes")
    _concat(clips, stitched, log_path, transitions, durations, preset)

    total = duration_of(str(stitched)) or sum(durations)
    if progress_cb:
        progress_cb(70.0, "Mixing audio and burning captions")
    _final_mux(
        stitched,
        output,
        subtitle_file=Path(subtitle_file) if subtitle_file else None,
        music=Path(music_path) if music_path else None,
        voice_volume=voice_volume,
        music_volume=music_volume,
        preset=preset,
        log=log_path,
        progress_cb=progress_cb,
        total=total,
    )
    final_duration = duration_of(str(output))

    thumb = settings.dirs()["thumbs"] / f"{stem}.jpg"
    try:
        subprocess.run(
            [ffmpeg_bin(), "-y", "-ss", str(min(1.5, max(0.1, final_duration / 8))), "-i", str(output),
             "-frames:v", "1", "-vf", "scale=540:-2", str(thumb)],
            capture_output=True, timeout=120,
        )
    except Exception:
        pass

    for clip in clips:
        try:
            clip.unlink()
        except OSError:
            pass
    try:
        stitched.unlink()
    except OSError:
        pass

    if project.get("id"):
        execute(
            "UPDATE video_projects SET output_path=?, duration=?, status='rendered', updated_at=? WHERE id=?",
            (str(output), final_duration, utcnow(), project["id"]),
        )
    if job_id:
        execute(
            "UPDATE render_jobs SET status='done', progress=100, finished_at=?, log_path=? WHERE id=?",
            (utcnow(), str(log_path), job_id),
        )
    return RenderResult(output_path=str(output), duration=final_duration, log_path=str(log_path), command="ffmpeg")
