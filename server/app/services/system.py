"""System telemetry: CPU, RAM, disk, GPU (via nvidia-smi when present)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import settings


def _mem() -> dict[str, float]:
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$os=Get-CimInstance Win32_OperatingSystem;"
                 "[pscustomobject]@{total=$os.TotalVisibleMemorySize;free=$os.FreePhysicalMemory} | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=25,
            )
            import json

            data = json.loads(out.stdout or "{}")
            total = float(data.get("total", 0)) / 1024 / 1024
            free = float(data.get("free", 0)) / 1024 / 1024
            used = max(0.0, total - free)
            return {"total_gb": round(total, 2), "used_gb": round(used, 2), "percent": round(used / total * 100, 1) if total else 0.0}
        except Exception:
            return {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}
    try:
        with open("/proc/meminfo") as fh:
            info = {line.split(":")[0]: line.split(":")[1].strip() for line in fh}
        total = int(info["MemTotal"].split()[0]) / 1024 / 1024
        avail = int(info["MemAvailable"].split()[0]) / 1024 / 1024
        used = total - avail
        return {"total_gb": round(total, 2), "used_gb": round(used, 2), "percent": round(used / total * 100, 1)}
    except Exception:
        return {"total_gb": 0.0, "used_gb": 0.0, "percent": 0.0}


def _cpu() -> dict[str, Any]:
    percent = None
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                capture_output=True, text=True, timeout=20,
            )
            percent = float((out.stdout or "0").strip() or 0)
        else:
            load = os.getloadavg()[0]
            percent = min(100.0, load / (os.cpu_count() or 1) * 100)
    except Exception:
        percent = None
    return {"percent": round(percent, 1) if percent is not None else None, "cores": os.cpu_count()}


def _disk() -> dict[str, float]:
    try:
        usage = shutil.disk_usage(str(settings.DATA_DIR))
        return {
            "total_gb": round(usage.total / 1e9, 1),
            "used_gb": round(usage.used / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}


def _gpu() -> list[dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
        gpus = []
        for line in (out.stdout or "").strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                gpus.append(
                    {
                        "name": parts[0],
                        "vram_total_mb": float(parts[1]) if parts[1].replace('.', '').isdigit() else None,
                        "vram_used_mb": float(parts[2]) if parts[2].replace('.', '').isdigit() else None,
                        "util_percent": float(parts[3]) if parts[3].replace('.', '').isdigit() else None,
                        "temp_c": float(parts[4]) if len(parts) > 4 and parts[4].replace('.', '').isdigit() else None,
                    }
                )
        return gpus
    except Exception:
        return []


def _storage_breakdown() -> list[dict[str, Any]]:
    out = []
    for name, path in settings.dirs().items():
        if name in {"data", "logs"}:
            continue
        size = 0
        count = 0
        if path.exists():
            for file in path.rglob("*"):
                if file.is_file():
                    size += file.stat().st_size
                    count += 1
        out.append({"name": name, "bytes": size, "mb": round(size / 1e6, 1), "files": count})
    return out


def snapshot() -> dict[str, Any]:
    return {
        "cpu": _cpu(),
        "memory": _mem(),
        "disk": _disk(),
        "gpu": _gpu(),
        "storage": _storage_breakdown(),
        "ffmpeg": settings.FFMPEG_BIN,
        "data_dir": str(settings.DATA_DIR),
    }


def cleanup_temp(older_than_hours: float = 6.0) -> dict[str, Any]:
    import time

    tmp = settings.dirs()["tmp"]
    removed = 0
    freed = 0
    if tmp.exists():
        cutoff = time.time() - older_than_hours * 3600
        for file in tmp.rglob("*"):
            try:
                if file.is_file() and file.stat().st_mtime < cutoff:
                    freed += file.stat().st_size
                    file.unlink()
                    removed += 1
            except OSError:
                continue
    return {"removed": removed, "freed_mb": round(freed / 1e6, 1)}
