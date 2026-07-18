# aicut — an AI-controlled video editor

`aicut` is a local, desktop-class video **editor** you drive two ways:

1. **By talking to it.** An AI command bar: *"cut all the silences and filler
   words"*, *"keep only the parts where I talk about pricing"*, *"trim
   everything before the demo starts"*, *"add captions and make it vertical"*.
2. **By editing the transcript.** Descript-style: the transcript **is** the
   timeline. Select words, hit Delete → those moments are cut. Click a word →
   the player seeks there.

Edits preview **instantly** — no re-render. Export renders the final file with
ffmpeg (NVENC when available).

The core design rule: **the LLM never invents timestamps.** It emits a typed
`EditPlan` (JSON actions that reference transcript segment/word ids); a
deterministic compiler resolves actions → keep-ranges, validating and clamping
everything against the real transcript. The manual UI edits produce the *same*
range operations. One engine, two input methods.

```
┌──────────────────────────── frontend (React) ───────────────────────────┐
│  player (skip-preview, caption overlay)  │  interactive transcript      │
│  timeline strip (kept/cut, playhead)     │  AI command bar + edit log   │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ REST + SSE                       │ <video src> (HTTP Range)
┌───────────────▼─────────────── backend (FastAPI) ───────────────────────┐
│ projects · transcription (faster-whisper, GPU) · embeddings · LLM plans │
│ EDL compiler & range math · ffmpeg export (NVENC) · media serving       │
└─────────────────────────────────────────────────────────────────────────┘
```

## Quick start

```bash
# 0. Check your environment (never crashes; degrades gracefully)
uv run python -m aicut doctor

# 1. Install deps
uv sync                 # engine + API + tests (light)
uv sync --extra ml      # + faster-whisper + sentence-transformers (heavy, GPU)
cd frontend && npm install && cd ..

# 2. Run everything (backend reload + Vite dev server)
python scripts/dev.py         # or: make dev

# 3. Open http://localhost:5173
```

For the AI command bar, install [Ollama](https://ollama.com) and pull a model:

```bash
ollama pull qwen2.5:7b-instruct     # default planner
# ollama pull qwen2.5:14b-instruct  # stronger; fits 12 GB VRAM (whisper is freed after transcription)
```

**The app is fully usable without Ollama** — manual transcript editing and the
one-click *Remove silences / Remove fillers / Captions / 9:16* actions are
deterministic and never touch the LLM.

## How it works

- **Transcription** — `faster-whisper` `large-v3` with word timestamps and VAD.
  Multilingual (English / Hindi / Hinglish). Runs on GPU (`int8_float16`) with a
  clean CPU fallback; the model is freed from VRAM after each job so the LLM
  fits.
- **Engine** — a pure, dependency-light core: [`rangemath.py`](backend/aicut/rangemath.py)
  (merge/subtract/intersect/invert/pad + `remap_time`), the
  [EDL compiler](backend/aicut/edl.py) (actions → keep-ranges), and the
  [revision model](backend/aicut/project.py) (undo = moving a head pointer).
- **Preview without rendering** — the original file stays in `<video>`; a
  `requestAnimationFrame` loop skips over cut regions. Captions and 9:16 are
  cosmetic DOM/CSS previews of what export burns in.
- **Export** — ffmpeg re-encodes per keep-range (`trim/atrim` + `setpts` +
  `concat`), with ~15 ms audio fades so cuts don't click, ASS captions on the
  **output** timeline, and optional 9:16 crop. `h264_nvenc` when available,
  else `libx264`.

## Layout

```
backend/aicut/     engine + FastAPI app
  models.py        pydantic contracts (Transcript, Action union, EDL, Project)
  rangemath.py     pure range math (unit-tested to death)
  edl.py           action → keep-range compiler
  project.py       persistence + revision/undo model
  transcribe.py    faster-whisper wrapper (lazy import)
  embeddings.py    sentence-transformers topic resolver (lazy import)
  llm.py           Ollama planning client
  ffmpeg_export.py export renderer
  ass_builder.py   caption ASS generator
  app.py           REST + SSE API
frontend/          Vite + React + TS + Tailwind + zustand
tests/             pytest engine/API tests + make_fixture.py
scripts/dev.py     one-command dev runner
```

## Development

```bash
make dev      # backend (reload) + frontend (Vite)
make check    # ruff + pytest + tsc --noEmit
make test     # pytest only
```

See [`DECISIONS.md`](DECISIONS.md) for every judgment call, [`QA.md`](QA.md)
for the manual test script, and [`IDEAS.md`](IDEAS.md) for deferred features.

## Status

Built milestone by milestone (M0–M6); see git history. Screenshots are added in
the M6 polish pass.

## License

MIT
