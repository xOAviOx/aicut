# Build `aicut` — an AI-controlled video **editor** (real app, v1)

> **How to use this document:** open Claude Code inside an **empty git repo** and paste this entire file as the first message (or save it as `PROMPT.md` and say: *"Read PROMPT.md and build the whole thing, milestone by milestone."*)

---

## 0. Mission

Build a **real desktop-class editor app** (local web app: React frontend + Python backend, runs on `localhost`) where the user opens a video and edits it two ways:

1. **By talking to it** — an AI command bar: *"cut all the silences and filler words"*, *"keep only the parts where I talk about pricing"*, *"trim everything before the demo starts"*, *"add captions and make it vertical"*. The AI executes the edit and reports what it changed.
2. **By editing the transcript** — Descript-style: the transcript is the timeline. Select words and hit delete → those moments are cut from the video. Click a word → the player seeks there.

Edits preview **instantly** (no re-render — see §6.3). Export renders the final file with ffmpeg.

Work **autonomously**. Do not ask me questions. When a decision is ambiguous, pick the boring, proven option and record it in `DECISIONS.md`.

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

**The core design rule:** the LLM never invents timestamps. It outputs a typed `EditPlan` (JSON actions referencing transcript segment ids); a deterministic compiler resolves actions → keep-ranges, validating and clamping everything against the real transcript. The UI's manual edits produce the same range operations. One engine, two input methods.

---

## 1. Environment & hardware (verify first)

Target machine: **i9-14900K, RTX 4070 Super (12 GB VRAM), 32 GB DDR5**. Detect the OS and adapt (native Windows, WSL2, Linux must all work; `pathlib` everywhere).

Milestone 0 includes **`python -m aicut doctor`**, checking: Python ≥ 3.11 · ffmpeg/ffprobe on PATH (per-OS install hint if missing) · CUDA available to CTranslate2 (report + CPU fallback, never crash) · NVENC in `ffmpeg -encoders` (fallback `libx264`) · Ollama reachable (warn only — the app must work without it; §5) · Node ≥ 20 for the frontend build · disk space. Every hardware feature degrades gracefully; GPU is an optimization, not a requirement.

---

## 2. Stack (locked — do not substitute)

**Backend:** Python 3.11+ (managed with `uv`; fallback venv+pip) · FastAPI + uvicorn · pydantic v2 for every contract · **faster-whisper** (default `large-v3`, `compute_type="int8_float16"` on GPU, `word_timestamps=True`, `vad_filter=True` — content may be **English, Hindi, or Hinglish**, so the multilingual model is a hard requirement; `distil-large-v3` only as an opt-in speed setting) · **sentence-transformers** `paraphrase-multilingual-MiniLM-L12-v2` for semantic ops · **ffmpeg via `subprocess`** for all rendering — **never moviepy**.

**Frontend:** Vite + React + TypeScript · Tailwind · **zustand** for state · plain `<video>` element (no player framework) · no component library bloat — build the handful of controls needed.

**Dev ergonomics:** one command to run everything (`make dev` or `scripts/dev.py`): uvicorn with reload + Vite dev server, CORS wired. `make check` = ruff + pytest + `tsc --noEmit`.

---

## 3. Engine data contracts (pydantic — implement exactly, extend freely)

**Transcript** (cached): `{ source, duration, language, segments: [ { id, start, end, text, words: [ { w, start, end } ] } ] }`

**Actions** — discriminated union on `type`:

| type | params | resolved by |
|---|---|---|
| `remove_silences` | `min_gap_s=0.6`, `pad_s=0.08` | word-gap analysis (no LLM needed) |
| `remove_fillers` | `words: list[str]` (defaults incl. um, uh, like\*, you know, basically, **matlab, yaar** — \*only standalone; config-extensible for Hinglish) | word-timestamp matching |
| `trim` | `mode: before\|after`, `anchor: {kind: segment_id\|time, value}` | drop everything before/after anchor |
| `filter_topic` | `mode: keep\|remove`, `query`, optional `segment_ids` | embeddings over segments; if the LLM supplied `segment_ids`, validate & use directly; expand to close-scoring neighbors |
| `cut_ranges` / `keep_ranges` | `ranges: [[s,e]]` | escape hatch for explicit times ("cut 0:10–0:25"); clamp to `[0, duration]` |
| `cut_words` | `word_refs: [{segment_id, word_index_start, word_index_end}]` | **what transcript-selection deletes compile to** |
| `set_captions` | `enabled`, `granularity: segment\|word`, style opts | toggles project caption setting |
| `set_aspect` | `"source" \| "9:16" \| "1:1"` | toggles project reframe setting |

**EditPlan** = `{ actions: [...], notes: "one-line interpretation summary" }` (LLM output).
**CompiledEDL** = `{ keep: [[s,e]], captions, aspect }` — what preview and export consume.

**Project state & undo model:** a project is `{ id, source_path, media_url, transcript_ref, settings, revisions: [ { id, label, edl, created_at } ] , head_revision_id }`. Every edit — AI command or manual deletion — appends a new revision with a human label (`"AI: removed 47 silences (−2:13)"`, `"Manual: deleted 6 words"`). **Undo/redo = moving `head_revision_id`** along the list (drop the tail on new edit after undo). Persist to `~/aicut/projects/<id>/project.json`. This makes the edit log UI (§6.5) trivial and state recovery free.

**Range math module** (pure functions, zero I/O, heavily unit-tested): merge, invert-within-duration, pad, drop keeps < 0.25 s, clamp, and **`remap_time(t_source) → t_output`** — piecewise-linear mapping through keep-ranges. Needed for captions and the timeline UI. Also the inverse map for seeking.

---

## 4. Backend API

- `POST /api/projects` — body: `{ path }` (import in place, no copy) **or** multipart upload (copied into the project dir). Kicks off transcription automatically.
- `GET /api/projects` / `GET /api/projects/{id}` — includes transcript once ready, revisions, head.
- `GET /api/projects/{id}/events` — **SSE** stream: transcription progress, export progress, plan status. (SSE, not WebSockets — simpler and sufficient.)
- `POST /api/projects/{id}/command` — `{ instruction }` → LLM plan → compile against head revision → new revision. Returns `{ revision, summary, notes }`. On plan failure returns a structured error the UI can show in the command bar ("couldn't map that to an edit").
- `POST /api/projects/{id}/edits` — manual ops from the UI (`cut_words`, `cut_ranges`, restore) → new revision.
- `POST /api/projects/{id}/undo` / `redo`.
- `POST /api/projects/{id}/export` — `{ preset }` → job id; progress via SSE; `GET .../exports` lists finished files.
- `GET /media/{project_id}` — serves the source video. **Must support HTTP Range requests** (Starlette's `FileResponse` does) or `<video>` seeking will silently break. Test this explicitly.

Transcription runs in a background task; free the whisper model from VRAM after each job so the 7B LLM fits comfortably.

---

## 5. LLM planning layer

**Ollama only — no cloud APIs, no API keys anywhere in the codebase.** The client talks to `http://localhost:11434` (`OLLAMA_HOST` overridable) via `POST /api/chat` with `format:"json"` and `temperature:0.1`. Default model `qwen2.5:7b-instruct`; expose the model name in settings so switching to `qwen2.5:14b-instruct` (a stronger planner — q4 fits the 12 GB card, since whisper is freed from VRAM after transcription) is a one-line change. Keep the client behind one small interface (`plan(instruction, transcript, state) -> EditPlan`) purely so tests can mock it — implement Ollama and nothing else.

Prompt = action catalog with JSON schema + 2 worked examples, then the instruction + a **compact numbered transcript** (`[id] mm:ss–mm:ss  text`; if > ~8k tokens, truncate each segment to its first ~15 words). Also pass a one-line current-state summary (`"current cut: 14:32 → 11:07"`) so follow-up commands read naturally.

Worked example to embed:

```
Instruction: "trim everything before I actually start the demo, cut silences, subtitle it"
Plan: { "actions": [
  { "type": "trim", "mode": "before", "anchor": { "kind": "segment_id", "value": 7 } },
  { "type": "remove_silences", "min_gap_s": 0.6 },
  { "type": "set_captions", "enabled": true, "granularity": "segment" }
], "notes": "Demo starts at segment 7; trimming intro, tightening pauses, captions on." }
```

Validate with pydantic; on failure retry **once** with the exact validation error fed back; on second failure surface the structured error. **The app must be fully usable with no LLM running** — manual transcript editing and the built-in one-click actions ("Remove silences", "Remove fillers" buttons) are deterministic and never touch the LLM.

---

## 6. Frontend — the editor

### 6.1 Screens

**Library** (minimal): drag-drop / path import, list of projects with thumbnail (grab one via ffmpeg at import) and status. **Editor**: the main event, laid out as in the diagram — player top-left, transcript filling the right/majority, timeline strip under the player, command bar docked at the bottom of the transcript pane, edit log accessible from the header.

### 6.2 Interactive transcript (the centerpiece)

- Rendered word-by-word, grouped by segment. Click a word → seek. Current word highlights during playback.
- **Select a span of words → press Delete/Backspace → those words are cut.** Cut words stay visible with strikethrough + dimmed (toggle: "show cut text"). Select cut words → Restore.
- **Performance is a first-class requirement:** a 30-min video ≈ 5k+ words. Render segments as memoized components; find the active word via binary search on `currentTime`; update the highlight by toggling a class on at most two word elements (refs), **never** by re-rendering the transcript on `timeupdate`. If scrolling stutters, virtualize by segment.
- Auto-scroll follows playback (with a "follow" toggle that disables on manual scroll).

### 6.3 Preview without rendering (the trick that makes it feel real)

Keep the original file in the `<video>`. Maintain the compiled keep-ranges in the store. In **Edited mode**, a `requestAnimationFrame` loop checks `currentTime`; the moment it enters a cut region, set `currentTime` to the next keep-range start (pause at the end of the last range). Sub-100 ms overshoot is imperceptible; do not try to be cleverer than this in v1. A header toggle switches **Edited ⇄ Original** preview. Show both durations (`14:32 → 11:07, −23%`).

Caption preview = DOM overlay on the player (styled div, current segment/word text) — no ASS in preview. 9:16 preview = CSS crop/letterbox of the player viewport. Both are cosmetic previews of what export burns in.

### 6.4 Timeline strip

A slim horizontal bar under the player: source duration mapped left-to-right, kept regions solid, cut regions dimmed/hatched, playhead line, click-to-seek, hover shows timecode. This is a **canvas or simple SVG** — not a track editor, no dragging in v1.

### 6.5 Command bar + edit log

Chat-style input docked in the transcript pane. Submit → show a pending state → on success, an entry like **"AI: removed 47 silences and 31 filler words (−2:13)"** with the plan's `notes`; on failure, the structured error inline. The **edit log** lists every revision; clicking one time-travels the head there (undo/redo buttons + `Ctrl/Cmd+Z`, `Shift+Ctrl/Cmd+Z`). One-click deterministic actions as buttons beside the bar: *Remove silences · Remove fillers · Captions on/off · 9:16*.

### 6.6 Export

Dialog: aspect (source/9:16/1:1), captions on/off + granularity, quality preset. Kicks the backend job; progress bar from SSE; finished exports listed with an "open folder"/download link.

### 6.7 Keyboard & polish

`Space` play/pause · `Delete` cut selection · `Ctrl/Cmd+Z / +Shift+Z` undo/redo · `←/→` nudge 1 s · `E` toggle Edited/Original. Visible keyboard focus states, sensible empty states ("Drop a video to start"), errors that say what happened and what to do — never toast "Something went wrong".

### 6.8 Design direction (make it look like a product, not a dashboard)

Dark editor chrome, but **not** the default near-black + acid-green AI look. Direction: charcoal surfaces with a warm tint, one restrained accent used only for the playhead + active states, and — the signature — **the transcript treated typographically like a manuscript being cut**: a real reading face at comfortable measure, cuts rendered as elegant strikethrough redactions, timecodes in a small tabular mono. Player chrome quiet and monochrome. Spend the boldness on the transcript; keep everything else disciplined. Respect `prefers-reduced-motion`; animation only where it communicates (playhead, pending AI command shimmer).

---

## 7. Export renderer (ffmpeg)

- Frame-accurate = re-encode. Per keep-range `trim/atrim + setpts/asetpts`, then `concat=n=N:v=1:a=1`. **~15 ms `afade` in/out per segment** so cuts don't click (default on).
- Filler removal ⇒ hundreds of ranges ⇒ command-line length limits (especially Windows): **always** write the graph to a file and use `-filter_complex_script`.
- Captions: generate an **ASS** file from surviving words/segments with every timestamp passed through `remap_time()` — caption times live on the **output** timeline, not source time; drop words whose spans were cut. Burn with `subtitles=`. Style from project settings (bold sans, bottom-center, ≤2 lines, wrapped).
- 9:16: `crop=ih*9/16:ih`, `scale=1080:1920`, applied **before** subtitles so positioning is correct. Skip crop if source is already at/under target aspect.
- Encode `h264_nvenc -preset p5 -cq 19` when available, else `libx264 -crf 18 -preset medium`; `aac -b:a 192k`; `-movflags +faststart`. Parse `ffmpeg -progress` into SSE events.

---

## 8. Testing

- **Engine (bulk of tests, pytest):** range math edge cases (adjacent, nested, zero-length, out-of-bounds), `remap_time` + inverse, every action's compiler path, filler matching (case/punctuation), revision/undo model, plan validation incl. malformed-LLM-JSON retry (mock the LLM), ASS builder golden file.
- **API (httpx + TestClient):** project lifecycle, manual edit → new revision, undo/redo, **Range request returns 206 with correct byte spans**, SSE emits transcription + export events (mock heavy deps).
- **Fixture:** `tests/make_fixture.py` synthesizes a ~60–90 s video — TTS via `espeak-ng`/`say`/`piper` (whichever exists; if none, print manual instructions and skip integration gracefully) speaking a script with known filler words, deliberate 1–2 s silences, and three distinct topics, muxed over an ffmpeg test pattern. Commit the script, not binaries.
- **Integration (skip cleanly if deps missing):** silence-removal shortens the fixture measurably; `filter_topic keep` selects the right spans (assert on the EDL, not pixels); caption export renders; full no-LLM flow works.
- **Frontend:** vitest for pure utils (range/remap mirrors, transcript selection→word_refs mapping). No Playwright in v1 — instead ship `QA.md`, a 15-step manual test script.

---

## 9. Milestones — commit after each, in order

- **M0** — repo scaffold (backend + frontend), `doctor`, config, `make dev` / `make check`.
- **M1** — engine core: transcription + caching, range math + remap, revision model. Unit tests green.
- **M2** — API + minimal editor shell: import a video, watch transcription progress live, see the transcript, click-to-seek, play. **Media serving with working Range/seek.**
- **M3** — manual editing: word selection → delete/restore → revisions, skip-preview Edited mode, timeline strip, undo/redo, edit log. *(Already a real editor with zero AI.)*
- **M4** — deterministic one-click actions (silences/fillers) + LLM command bar (Ollama client, plan→compile→revision, error surface).
- **M5** — captions (preview overlay + ASS export) and 9:16 (preview + export). Export dialog + SSE progress.
- **M6** — polish: design pass per §6.8, keyboard map, empty/error states, README with screenshots, `QA.md`, `DECISIONS.md` tidy.

---

## 10. Non-goals for v1 — do not build these

Multi-clip/multi-track timeline · b-roll, music, images · transitions · waveform rendering · speaker diarization · auto-shorts/virality clipping · face-tracking reframe · translation/dubbing · collaboration/auth/cloud · Electron packaging (the web app must be architected so wrapping it later is trivial, but do not do it now). Tempted? Write it in `IDEAS.md` and move on.

---

## 11. Definition of done

- `doctor` passes here; degrades gracefully elsewhere.
- Real ~10-min talking-head video: import → transcribed with live progress → *"remove silences and filler words, add captions, make it vertical"* in the command bar → preview reflects it instantly → export produces a watchable 1080×1920 mp4 with correctly-timed burned captions and click-free cuts via NVENC.
- Selecting a sentence in the transcript and hitting Delete cuts it; playback skips it; undo brings it back; the edit log shows both revisions.
- Kill Ollama: the app still fully works for manual + one-click editing, and the command bar fails with a helpful message.
- `make check` clean (ruff, pytest, tsc). README accurate with screenshots. `DECISIONS.md` explains every judgment call.

Build it. Ask nothing. Ship each milestone as a commit with a clear message.