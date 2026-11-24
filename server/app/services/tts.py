"""Free text-to-speech with a provider chain and word-level timings.

Providers (all zero-cost, no API keys):
  1. piper    - local neural TTS (fully offline) if piper.exe + a voice model exist
  2. sapi     - Windows built-in System.Speech (fully offline, always present on Windows)
  3. edge     - Microsoft Edge read-aloud endpoint via `edge-tts` (free, needs internet)

The chain is attempted in order and the first success wins. If everything
fails we raise so the pipeline records a real error instead of faking audio.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings
from ..db import log_event

SAPI_VOICES: list[dict[str, str]] = []

EDGE_VOICES = [
    {"id": "en-US-AriaNeural", "label": "Aria - Female, warm (US)"},
    {"id": "en-US-GuyNeural", "label": "Guy - Male, energetic (US)"},
    {"id": "en-US-JennyNeural", "label": "Jenny - Female, friendly (US)"},
    {"id": "en-US-ChristopherNeural", "label": "Christopher - Male, deep (US)"},
    {"id": "en-GB-RyanNeural", "label": "Ryan - Male (UK)"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia - Female (UK)"},
    {"id": "en-IN-NeerjaNeural", "label": "Neerja - Female (India)"},
    {"id": "en-IN-PrabhatNeural", "label": "Prabhat - Male (India)"},
    {"id": "hi-IN-SwaraNeural", "label": "Swara - Female (Hindi)"},
    {"id": "es-ES-ElviraNeural", "label": "Elvira - Female (Spanish)"},
    {"id": "fr-FR-DeniseNeural", "label": "Denise - Female (French)"},
    {"id": "de-DE-KatjaNeural", "label": "Katja - Female (German)"},
]


@dataclass
class TTSResult:
    path: str
    duration: float
    provider: str
    voice: str
    words: list[dict[str, Any]]


def ffmpeg() -> str:
    return settings.FFMPEG_BIN


def ffprobe() -> str:
    return settings.FFPROBE_BIN


def probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        data = json.loads(out.stdout or "{}")
        return float(data.get("format", {}).get("duration") or 0.0)
    except Exception:
        return 0.0


def _ps() -> str:
    return shutil.which("powershell") or shutil.which("pwsh") or "powershell"


def list_sapi_voices() -> list[dict[str, str]]:
    if not sys.platform.startswith("win"):
        return []
    if SAPI_VOICES:
        return SAPI_VOICES
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices() | ForEach-Object { $i=$_.VoiceInfo; "
        "[pscustomobject]@{name=$i.Name;culture=$i.Culture.Name;gender=$i.Gender.ToString()} } | "
        "ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            [_ps(), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=45,
        )
        raw = (out.stdout or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        SAPI_VOICES.extend(
            {"id": d["name"], "label": f"{d['name']} ({d.get('gender', '?')}, {d.get('culture', '')})"}
            for d in data
            if d.get("name")
        )
    except Exception as exc:  # noqa: BLE001
        log_event("SAPI voice enumeration failed", level="warn", scope="tts", context={"error": str(exc)})
    return SAPI_VOICES


def piper_available() -> bool:
    return bool(shutil.which("piper")) and bool(os.getenv("PIPER_VOICE_MODEL"))


def capabilities() -> dict[str, Any]:
    sapi = list_sapi_voices()
    edge_ok = _module_available("edge_tts")
    chain = []
    if piper_available():
        chain.append("piper")
    if sapi:
        chain.append("sapi")
    if edge_ok:
        chain.append("edge")
    return {
        "piper": {"available": piper_available(), "detail": os.getenv("PIPER_VOICE_MODEL") or ""},
        "sapi": {"available": bool(sapi), "voices": sapi},
        "edge": {"available": edge_ok, "voices": EDGE_VOICES, "needs_internet": True},
        "chain": chain,
        "offline_capable": bool(piper_available() or sapi),
    }


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _sanitize(text: str) -> str:
    text = re.sub(r"[*_#`]", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def estimate_word_timings(words: list[str], duration: float, start: float = 0.0) -> list[dict[str, Any]]:
    if not words or duration <= 0:
        return []
    weights = [max(2, len(w)) for w in words]
    total = sum(weights)
    cursor = start
    out = []
    for word, weight in zip(words, weights):
        span = duration * (weight / total)
        out.append({"word": word, "start": round(cursor, 3), "end": round(cursor + span, 3)})
        cursor += span
    return out


def _post_process(raw: Path, out: Path) -> None:
    """Normalise loudness, trim leading/trailing silence, encode to 48k mono wav."""
    cmd = [
        ffmpeg(), "-y", "-i", str(raw),
        "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
               "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
               "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
        "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0 or not out.exists():
        shutil.copyfile(raw, out)


async def _edge_tts(text: str, voice: str, rate: str, out_raw: Path) -> list[dict[str, Any]]:
    import edge_tts

    words: list[dict[str, Any]] = []
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    with open(out_raw, "wb") as fh:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                end = start + (chunk["duration"] / 10_000_000)
                words.append({"word": chunk["text"], "start": round(start, 3), "end": round(end, 3)})
    if not out_raw.exists() or out_raw.stat().st_size < 1000:
        raise RuntimeError("edge-tts produced no audio")
    return words


def _sapi_tts(text: str, voice: str, rate_pct: int, out_raw: Path) -> None:
    tmp_txt = out_raw.with_suffix(".txt")
    tmp_txt.write_text(text, encoding="utf-8")
    escaped_voice = voice.replace("'", "''")
    escaped_path = str(out_raw).replace("'", "''")
    escaped_txt = str(tmp_txt).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate={max(-10, min(10, int(rate_pct / 10)))};"
        f"try {{ $s.SelectVoice('{escaped_voice}') }} catch {{}};"
        f"$t=Get-Content -Raw -Encoding UTF8 '{escaped_txt}';"
        f"$s.SetOutputToWaveFile('{escaped_path}');"
        "$s.Speak($t);$s.Dispose()"
    )
    res = subprocess.run(
        [_ps(), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=600,
    )
    try:
        tmp_txt.unlink()
    except OSError:
        pass
    if res.returncode != 0 or not out_raw.exists():
        raise RuntimeError(f"SAPI TTS failed: {(res.stderr or res.stdout)[:300]}")


def _piper_tts(text: str, out_raw: Path) -> None:
    model = os.getenv("PIPER_VOICE_MODEL", "")
    exe = shutil.which("piper") or "piper"
    res = subprocess.run(
        [exe, "--model", model, "--output_file", str(out_raw)],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=600,
    )
    if res.returncode != 0 or not out_raw.exists():
        raise RuntimeError(f"Piper failed: {(res.stderr or b'').decode('utf-8', 'ignore')[:300]}")


async def synthesize(
    text: str,
    out_dir: Path,
    *,
    voice: str | None = None,
    provider: str | None = None,
    rate_pct: int = 0,
    pitch_pct: int = 0,
) -> TTSResult:
    text = _sanitize(text)
    if not text:
        raise ValueError("Cannot synthesize empty text")
    out_dir.mkdir(parents=True, exist_ok=True)
    caps = capabilities()
    chain = [provider] if provider and provider != "auto" else caps["chain"]
    errors: list[str] = []

    for prov in chain:
        raw = out_dir / f"raw_{prov}_{abs(hash(text)) % 10**8}.mp3"
        final = out_dir / f"voice_{abs(hash(text + str(voice))) % 10**10}.wav"
        try:
            if prov == "piper" and caps["piper"]["available"]:
                raw = raw.with_suffix(".wav")
                _piper_tts(text, raw)
                words = estimate_word_timings(text.split(), probe_duration(str(raw)))
            elif prov == "sapi" and caps["sapi"]["available"]:
                chosen = voice if voice and any(v["id"] == voice for v in caps["sapi"]["voices"]) else caps["sapi"]["voices"][0]["id"]
                _sapi_tts(text, chosen, rate_pct, raw)
                words = estimate_word_timings(text.split(), probe_duration(str(raw)))
            elif prov == "edge" and caps["edge"]["available"]:
                chosen = voice if voice and any(v["id"] == voice for v in EDGE_VOICES) else EDGE_VOICES[0]["id"]
                rate = f"{rate_pct:+d}%" if rate_pct else "+0%"
                words = await _edge_tts(text, chosen, rate, raw)
            else:
                continue

            _post_process(raw, final)
            duration = probe_duration(str(final))
            if duration <= 0:
                raise RuntimeError("Post-processed audio has zero duration")
            try:
                raw.unlink()
            except OSError:
                pass
            return TTSResult(
                path=str(final),
                duration=round(duration, 3),
                provider=prov,
                voice=voice or "default",
                words=words,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{prov}: {exc}")
            log_event("TTS provider failed", level="warn", scope="tts", context={"provider": prov, "error": str(exc)})
            continue

    raise RuntimeError(
        "No TTS provider succeeded. Install a voice engine: `pip install edge-tts` (free, internet) "
        "or enable Windows speech. Details: " + "; ".join(errors)
    )


async def list_edge_voices(locale: str = "en") -> list[dict[str, str]]:
    try:
        import edge_tts

        voices = await edge_tts.list_voices()
        return [
            {"id": v["ShortName"], "label": f"{v['ShortName']} ({v.get('Gender', '')})"}
            for v in voices
            if v.get("ShortName", "").lower().startswith(locale.lower())
        ]
    except Exception:
        return [v for v in EDGE_VOICES if v["id"].lower().startswith(locale.lower())] or EDGE_VOICES


def available_voices() -> dict[str, Any]:
    caps = capabilities()
    return {
        "providers": caps,
        "voices": {
            "edge": EDGE_VOICES,
            "sapi": caps["sapi"]["voices"],
        },
        "default": next(iter(caps["chain"]), None),
    }
