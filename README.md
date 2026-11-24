# AUTOSHORT AI

A self-hosted, zero-cost YouTube Shorts factory. It researches a topic, writes a
script with a local LLM, narrates it, generates visuals, renders a vertical video
with FFmpeg, scores the result, and (optionally) uploads it to YouTube — all on
your own machine, with no paid APIs.

Everything runs locally: local model via Ollama, local text-to-speech, locally
rendered artwork and music, local SQLite database, local file storage.

> **Live interface preview:** <https://jhonny7855.github.io/autoshort-ai/>
>
> That link renders the real React interface from `web/` as a static site. It is a
> UI preview only — the generator needs the local FastAPI server, FFmpeg, TTS and
> Ollama, which cannot run in a browser. Download the repo and run `start.bat` to
> use it for real.

---

## What it actually does

```
topic idea -> research (Wikipedia/RSS/Reddit) -> script (local LLM)
   -> narration (TTS) -> scene visuals -> subtitles -> FFmpeg render
   -> quality report -> ready-to-upload MP4
   -> optional YouTube upload
```

Each step writes real output to disk. Nothing is stubbed:

| Stage | Implementation |
| --- | --- |
| Ideas | Local LLM over your active niche, de-duplicated by topic fingerprint |
| Research | Wikipedia REST API, public RSS feeds, Reddit JSON — no keys |
| Script | Ollama with a JSON schema; deterministic template writer as fallback |
| Narration | Windows SAPI, `edge-tts`, or Piper (first available) |
| Visuals | Procedural art via Pillow + numpy; optional ComfyUI endpoint |
| Subtitles | Word-timed ASS captions generated from real audio durations |
| Render | FFmpeg: 1080x1920, per-scene motion, fades, music bed, burned captions |
| Quality | 13 weighted checks including target length and unsourced-figure detection |
| Upload | YouTube Data API v3, private by default |

If the local model is unavailable, the script module says so: the script is
marked `_origin: "template"` and logged as a warning. It never pretends AI output
exists when it does not.

---

## Requirements

- **Windows 10/11** (batch launchers target Windows; the Python/Node code is portable)
- **Python 3.12+**
- **Node.js 20+**
- **FFmpeg** on `PATH` — `winget install Gyan.FFmpeg`
- **Ollama** (optional but recommended) — https://ollama.com
- A local model, e.g. `ollama pull qwen2.5:1.5b`

GPU is not required. A 1.5B model runs acceptably on CPU and in ~1 GB of RAM;
larger models improve script quality if you have the memory.

---

## Install

```bat
install.bat
```

This creates `.venv`, installs Python dependencies, copies `.env.example` to
`.env`, builds the web interface, and reports anything missing (FFmpeg, Node,
Ollama, models).

## Run

```bat
start.bat
```

Open http://127.0.0.1:8787 and press **Continue on this PC** — no Google account is
needed for local use.

## Stop / update

```bat
stop.bat
update.bat
```

---

## Using it

1. **Onboarding** — pick a niche (20 presets ship with the app).
2. **Ideas** — generate topic ideas, then run research to attach sources.
3. **Script Studio** — generate a script, edit the hook/body/scenes, approve it.
   The approval gate is on by default, so nothing renders until you approve.
4. **Video Studio** — produce the video, watch per-step progress,
   review the quality report and the rendered MP4.
5. **Queue / Calendar** — schedule automated runs.
6. **Published / Analytics** — after connecting YouTube.

Default behaviour is deliberately cautious: uploads are **private**, automation
starts **paused**, and approval is **required**.

---

## YouTube upload (optional)

Only needed if you want the app to publish for you.

1. Go to Google Cloud Console, create a project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen (External, add yourself as a test user).
4. Create an **OAuth 2.0 Client ID** of type **Web application**.
5. Add this exact authorized redirect URI:

   ```
   http://127.0.0.1:8787/api/auth/google/callback
   ```

6. Put the credentials in `.env`:

   ```ini
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```

7. Restart, then use **Settings → Connect Google**.

Until this is done, `POST /api/system/test/youtube` correctly reports
"No Google token available" and everything else keeps working.

---

## Configuration

All settings live in `.env` (see `.env.example`) and in the in-app **Settings**
page. Notable ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTOSHORT_PORT` | `8787` | Backend and web port |
| `AUTOSHORT_DATA_DIR` | `data` | Database, media, logs |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local model endpoint |
| `COMFYUI_URL` | *(empty)* | Optional image backend |
| `FFMPEG_BIN` | auto | FFmpeg path override |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | *(empty)* | YouTube upload |

Render presets: `lowend` (540p), `fast` (720p), `balanced` (1080p, default), `high` (1080p).
Subtitle styles: `mrbeast`, `minimal-cinematic`, `clean-educational`, `gaming`, `neon`, `documentary`, `modern-bold`.

---

## Data layout

```
data/
  autoshort.db          SQLite database
  secret.key            Encryption key for stored tokens
  logs/                 Render and server logs
  media/audio/          Narration WAV/MP3 per idea
  media/images/         Generated scene art
  media/videos/         Rendered MP4s and .ass captions
  media/music/          Generated music beds
  media/thumbs/         Thumbnails
  media/tmp/            Scratch space
```

Back up `data/` to keep your projects. Delete it to start clean.

---

## Development

```bat
REM backend, auto-reload
set PYTHONPATH=%CD%\server
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload

REM frontend dev server on 5273 (proxies /api and /media to 8787)
cd web
npm run dev
```

Project layout:

```
server/app/
  main.py              app wiring, /media, SPA mount, WebSocket
  config.py            env-driven settings
  db.py                schema + SQL helpers
  services/            ai, niches, research, scripts, tts, visuals,
                       subtitles, renderer, pipeline, automation, system, youtube
  routers/             auth, ai_settings, content, production,
                       queue_control, dashboard, system_routes
web/src/
  pages/               16 screens
  lib/                 api client, store, design system
scripts/smoke_test.py  end-to-end verification
```

### Verification

```bat
.venv\Scripts\python.exe scripts\smoke_test.py
```

Runs 33 checks against a live server: health, FFmpeg, local login, Ollama and
model inference, niches, idea, research, script, approval default, TTS, full
production, MP4 size, quality report, media serving, download, queue, dashboard,
resources, logs, self-tests, and SPA. Every check must pass.

Frontend types and build:

```bat
cd web
npm run typecheck
npm run build
```

---

## Notes and limits

- Script quality is bounded by the model. A 1.5B model produces usable but plain
  copy; `llama3.2:3b` or larger reads noticeably better if RAM allows.
- The word budget is enforced in code, so the video length tracks the target even
  when the model undershoots.
- Invented statistics are flagged by the quality report rather than silently
  rewritten — check the "Claim verification" line before publishing.
- Visuals are abstract procedural art, not photoreal footage.
- Single-user by design. Local login is for a machine you control; do not expose
  the port to the internet.

## License

Personal use. Review YouTube's Terms of Service and copyright rules before
publishing automated content.
