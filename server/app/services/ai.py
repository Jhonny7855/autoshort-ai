"""Local-first AI provider (Ollama / any OpenAI-compatible local endpoint).

No paid key required. If no model is reachable we degrade gracefully and let
the caller fall back to deterministic templated generation so the pipeline
never dies silently.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx

from ..config import settings
from ..db import log_event, query_one


class AIError(RuntimeError):
    pass


def ollama_base() -> str:
    row = query_one("SELECT base_url FROM ai_providers WHERE kind='ollama' AND enabled=1")
    if row and row.get("base_url"):
        return row["base_url"].rstrip("/")
    return settings.OLLAMA_URL


async def health() -> dict[str, Any]:
    base = ollama_base()
    out: dict[str, Any] = {"reachable": False, "base_url": base, "models": [], "error": None}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            data = r.json()
        out["reachable"] = True
        out["models"] = [
            {
                "name": m.get("name"),
                "size": m.get("size"),
                "family": (m.get("details") or {}).get("family"),
                "parameter_size": (m.get("details") or {}).get("parameter_size"),
                "quantization": (m.get("details") or {}).get("quantization_level"),
                "modified_at": m.get("modified_at"),
            }
            for m in data.get("models", [])
        ]
    except Exception as exc:  # noqa: BLE001 - surfaced to UI verbatim
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


async def pick_model(preferred: str | None) -> str | None:
    info = await health()
    names = [m["name"] for m in info.get("models", []) if m.get("name")]
    if not names:
        return None
    if preferred and preferred in names:
        return preferred
    row = query_one("SELECT value FROM app_settings WHERE key='ai_model' ORDER BY id DESC LIMIT 1")
    if row and row.get("value") in names:
        return row["value"]
    return names[0]


async def generate(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    temperature: float = 0.8,
    num_predict: int = 900,
    json_mode: bool = False,
    timeout: float = 180.0,
) -> str:
    chosen = await pick_model(model)
    if not chosen:
        raise AIError(
            "No local AI model is installed. Run `ollama pull llama3.2:3b` (or another model) "
            "and retry, or continue in template mode."
        )
    base = ollama_base()
    payload: dict[str, Any] = {
        "model": chosen,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
        "keep_alive": "15m",
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(f"{base}/api/generate", json=payload)
                r.raise_for_status()
                data = r.json()
            text = (data.get("response") or "").strip()
            if not text:
                raise AIError("Model returned an empty response")
            return text
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            if status < 500 or attempt == 3:
                break
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == 3:
                break
        await asyncio.sleep(1.5 * attempt)

    detail = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    log_event(
        "AI request failed",
        level="error",
        scope="ai",
        context={"error": detail, "model": chosen, "prompt_chars": len(prompt)},
    )
    raise AIError(f"Local AI request failed: {detail}")


def _repair_json(text: str) -> Any:
    """Salvage a truncated JSON object by closing strings/brackets and retrying."""
    start = text.find("{")
    if start < 0:
        raise AIError("Could not parse JSON from model response")
    chunk = text[start:]

    cut_points = [i for i, ch in enumerate(chunk) if ch in ",{}[]"]
    attempts = [len(chunk)] + list(reversed(cut_points))[:400]
    for end in attempts:
        candidate = chunk[:end]
        stack: list[str] = []
        in_str = False
        esc = False
        for ch in candidate:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            candidate += '"'
        candidate = candidate.rstrip().rstrip(",")
        candidate += "".join(reversed(stack))
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed:
            return parsed
    raise AIError("Could not parse JSON from model response")


def extract_json(text: str) -> Any:
    """Best-effort JSON extraction from a model reply that may include prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = text[start : i + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    start = None
    return _repair_json(text)


async def pull_model(name: str) -> AsyncIterator[dict[str, Any]]:
    base = ollama_base()
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{base}/api/pull", json={"name": name, "stream": True}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
