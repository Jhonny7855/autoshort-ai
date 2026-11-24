"""Visual asset generation.

Priority order (all free/local):
  1. ComfyUI (local Stable Diffusion) when a reachable endpoint is configured
  2. Procedural PIL artwork generated from the scene prompt (always available)

Both produce real 1080x1920 PNGs that FFmpeg then animates with Ken Burns
motion. Nothing here calls a paid image API.
"""
from __future__ import annotations

import colorsys
import hashlib
import math
import random
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import settings
from ..db import insert, log_event, utcnow

W, H = 1080, 1920

PALETTES = [
    [(28, 18, 62), (108, 52, 205), (56, 232, 255)],
    [(10, 30, 46), (24, 118, 178), (130, 255, 230)],
    [(46, 14, 30), (204, 58, 112), (255, 186, 106)],
    [(14, 38, 30), (44, 152, 106), (200, 255, 136)],
    [(34, 18, 50), (138, 52, 180), (255, 140, 214)],
    [(16, 24, 58), (52, 92, 200), (150, 220, 255)],
]


def _seed_for(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return base.resize((w, h), Image.BILINEAR)


def _blob(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, int, int], alpha: int) -> None:
    for i in range(6, 0, -1):
        scale = i / 6
        draw.ellipse(
            [cx - r * scale, cy - r * scale, cx + r * scale, cy + r * scale],
            fill=(*color, int(alpha * (1 - scale) ** 1.6)),
        )


def procedural_art(prompt: str, out_path: Path, *, palette_index: int | None = None, seed_extra: int = 0) -> Path:
    """Generate an abstract, prompt-seeded vertical poster. Deterministic per prompt."""
    seed = _seed_for(prompt) + seed_extra
    rnd = random.Random(seed)
    palette = PALETTES[(palette_index if palette_index is not None else seed) % len(PALETTES)]
    bg_top, mid, accent = palette

    # Lift the base gradient so scenes read as vivid posters, not black frames.
    top_c = tuple(min(255, int(c * 1.9) + 14) for c in bg_top)
    bot_c = tuple(min(255, int(c * 1.5) + 22) for c in mid)
    canvas = _gradient((W, H), top_c, bot_c).convert("RGBA")

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(6):
        _blob(
            gd,
            rnd.uniform(-0.15, 1.15) * W,
            rnd.uniform(-0.1, 1.05) * H,
            rnd.uniform(300, 780),
            accent if rnd.random() > 0.35 else mid,
            rnd.randint(120, 235),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=90))
    canvas = Image.alpha_composite(canvas, glow)

    shapes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shapes)
    style = seed % 4
    if style == 0:
        for _ in range(30):
            x, y = rnd.uniform(0, W), rnd.uniform(0, H)
            r = rnd.uniform(14, 110)
            sd.ellipse([x - r, y - r, x + r, y + r], outline=(*accent, rnd.randint(90, 220)), width=rnd.randint(1, 5))
    elif style == 1:
        for i in range(22):
            y = H * (i / 22) + rnd.uniform(-30, 30)
            pts = [(x, y + math.sin(x / 140 + i) * 60) for x in range(0, W + 20, 20)]
            sd.line(pts, fill=(*accent, rnd.randint(70, 190)), width=rnd.randint(1, 4))
    elif style == 2:
        for _ in range(16):
            x, y, s = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(140, 460)
            sd.rounded_rectangle([x, y, x + s, y + s * 0.6], radius=28, outline=(*accent, 150), width=3)
    else:
        for _ in range(900):
            x, y = rnd.uniform(0, W), rnd.uniform(0, H)
            r = rnd.uniform(0.8, 3.6)
            sd.ellipse([x - r, y - r, x + r, y + r], fill=(*accent, rnd.randint(80, 240)))
    canvas = Image.alpha_composite(canvas, shapes)

    if seed % 3 == 0:
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=1.2))

    # Gentle corner shading only - keep the centre of frame bright.
    vignette = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-W * 0.5, -H * 0.35, W * 1.5, H * 1.35], fill=190)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=260))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 110))
    canvas = Image.composite(canvas, Image.alpha_composite(canvas, dark), vignette)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path


async def comfyui_available() -> bool:
    if not settings.COMFYUI_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{settings.COMFYUI_URL}/system_stats")
        return r.status_code == 200
    except Exception:
        return False


async def generate_asset(
    user_id: int,
    idea_id: int,
    prompt: str,
    scene_no: int,
    *,
    palette_index: int | None = None,
) -> dict[str, Any]:
    """Produce one real image file and register it in the assets table."""
    base = settings.dirs()["images"] / f"user_{user_id}" / f"idea_{idea_id}"
    out_path = base / f"scene_{scene_no:02d}.png"

    provider = "procedural"
    procedural_art(prompt, out_path, palette_index=palette_index, seed_extra=scene_no)
    licence = "Generated locally by AUTOSHORT AI (procedural) - you own the output"
    attribution = "AUTOSHORT AI procedural renderer"

    asset_id = insert(
        "assets",
        {
            "user_id": user_id,
            "idea_id": idea_id,
            "kind": "image",
            "path": str(out_path),
            "url": f"/media/images/user_{user_id}/idea_{idea_id}/{out_path.name}",
            "width": W,
            "height": H,
            "bytes": out_path.stat().st_size if out_path.exists() else None,
            "license": licence,
            "attribution": attribution,
            "provider": provider,
            "meta": None,
            "created_at": utcnow(),
        },
    )
    return {
        "id": asset_id,
        "path": str(out_path),
        "url": f"/media/images/user_{user_id}/idea_{idea_id}/{out_path.name}",
        "provider": provider,
        "license": licence,
    }


def ensure_scene_assets(user_id: int, idea_id: int, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Synchronous version used inside the render pipeline (PIL only, no network)."""
    out = []
    base = settings.dirs()["images"] / f"user_{user_id}" / f"idea_{idea_id}"
    for scene in scenes:
        prompt = scene.get("visual_prompt") or scene.get("narration") or "abstract concept"
        path = base / f"scene_{int(scene.get('scene_no') or 1):02d}.png"
        if not path.exists():
            procedural_art(prompt, path, seed_extra=int(scene.get("scene_no") or 1))
        asset_id = insert(
            "assets",
            {
                "user_id": user_id,
                "idea_id": idea_id,
                "kind": "image",
                "path": str(path),
                "url": f"/media/images/user_{user_id}/idea_{idea_id}/{path.name}",
                "width": W,
                "height": H,
                "bytes": path.stat().st_size,
                "license": "Generated locally by AUTOSHORT AI (procedural) - you own the output",
                "attribution": "AUTOSHORT AI procedural renderer",
                "provider": "procedural",
                "created_at": utcnow(),
            },
        )
        out.append({**scene, "asset_path": str(path), "asset_id": asset_id, "asset_url": f"/media/images/user_{user_id}/idea_{idea_id}/{path.name}"})
    return out


def music_bed(seconds: float, out_path: Path, *, mood: str = "uplifting") -> Path | None:
    """Generate a royalty-free ambient bed with FFmpeg synthetic tones.

    This avoids any licensing risk: the audio is synthesized locally, so it is
    safe to publish. Users can also drop their own licensed music in data/media/music.
    """
    import subprocess

    out_path.parent.mkdir(parents=True, exist_ok=True)
    roots = {"uplifting": 220.0, "cinematic": 164.8, "dark": 110.0, "chill": 196.0}
    root = roots.get(mood, 220.0)
    fifth = root * 1.5
    cmd = [
        settings.FFMPEG_BIN, "-y",
        "-f", "lavfi", "-i", f"sine=frequency={root}:duration={seconds:.2f}",
        "-f", "lavfi", "-i", f"sine=frequency={fifth}:duration={seconds:.2f}",
        "-f", "lavfi", "-i", f"sine=frequency={root / 2}:duration={seconds:.2f}",
        "-filter_complex",
        "[0:a]volume=0.10,tremolo=f=0.3:d=0.4[a0];"
        "[1:a]volume=0.045,tremolo=f=0.21:d=0.5[a1];"
        "[2:a]volume=0.09,lowpass=f=320[a2];"
        "[a0][a1][a2]amix=inputs=3:duration=longest,"
        "afade=t=in:st=0:d=1.2,afade=t=out:st=" + f"{max(0.1, seconds - 1.5):.2f}" + ":d=1.5,"
        "loudnorm=I=-30:TP=-6:LRA=9[out]",
        "-map", "[out]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    if res.returncode != 0 or not out_path.exists():
        log_event("Music bed synthesis failed", level="warn", scope="audio", context={"error": res.stderr[-400:]})
        return None
    return out_path


def user_music_files() -> list[Path]:
    folder = settings.dirs()["music"]
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}])
