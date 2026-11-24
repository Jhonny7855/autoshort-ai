"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ensure_dirs, settings
from .db import init_db, log_event, query_one
from .routers import (
    ai_settings,
    auth,
    content,
    dashboard,
    production,
    publish,
    queue_control,
    system_routes,
)
from .security import current_user_optional
from .services import automation, niches
from .services.hub import hub

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# Windows can map .css to application/x-css via the registry, which browsers
# refuse to apply as a stylesheet. Pin the web asset types explicitly.
for _ext, _type in {
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".vtt": "text/vtt",
}.items():
    mimetypes.add_type(_type, _ext)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    init_db()
    log_event("AUTOSHORT AI backend started", scope="boot")
    await automation.engine.start()
    try:
        yield
    finally:
        await automation.engine.stop()
        log_event("AUTOSHORT AI backend stopped", scope="boot")


app = FastAPI(title="AUTOSHORT AI", version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_user(request: Request, call_next):
    request.state.user = current_user_optional(request)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log_event(
        f"Unhandled error on {request.url.path}: {exc}",
        level="error",
        scope="http",
        context={"path": str(request.url.path)},
    )
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"[:400]})


for router in (
    auth.router,
    ai_settings.router,
    content.router,
    production.router,
    publish.router,
    queue_control.router,
    dashboard.router,
    system_routes.router,
):
    app.include_router(router)


@app.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    user = current_user_optional(ws)  # type: ignore[arg-type]
    if not user:
        await ws.close(code=4401)
        return
    await hub.connect(user["id"], ws)
    try:
        while True:
            await asyncio.wait_for(ws.receive_text(), timeout=120)
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        await hub.disconnect(user["id"], ws)


settings.dirs()["media"].mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(settings.dirs()["media"])), name="media")

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "app": settings.APP_NAME,
            "status": "running",
            "web_build": "missing - run `npm run build` in web/ or use the Vite dev server",
            "docs": "/docs",
        }
