# Decisions

Judgment calls made while building autonomously. The rule from the spec: when a
decision is ambiguous, pick the boring, proven option and record it here.

## Repo & tooling

- **Package lives at `backend/aicut`, installed editable via hatchling.** Keeps
  the backend/frontend split from the spec diagram while letting
  `python -m aicut` and `pytest` (via `pythonpath = ["backend"]`) both resolve
  the package. `uv sync` builds it editable.
- **Heavy ML deps (`faster-whisper`, `sentence-transformers`) are an optional
  `ml` extra.** The engine, API, tests, and `doctor` all run without gigabytes
  of torch/CUDA wheels. Heavy modules are imported lazily inside functions, so
  importing `aicut.*` never pulls torch. `uv sync --extra ml` enables real
  transcription/embeddings.
- **Data root is `~/aicut` (overridable via `AICUT_HOME`).** Matches the spec's
  `~/aicut/projects/<id>/project.json`. `pathlib` everywhere for OS portability.
- **Default backend port 8756** (uncommon, avoids clashes). Vite dev server on
  5173 (its default), proxied to the backend.
- **Console output is ASCII + stdout reconfigured to UTF-8.** Windows legacy
  consoles are cp1252; `doctor` must never crash on a stray glyph.

## Engine

- **A revision stores a full compiled EDL snapshot** (`keep` ranges + caption +
  aspect settings), not a diff. Undo/redo = moving `head_revision_id`; this
  makes state recovery and the edit-log UI trivial, exactly as the spec argues.
- **Word cut/uncut state is *derived* from keep-ranges** (a word is "cut" if its
  midpoint falls outside every kept span), rather than stored separately. One
  source of truth. `remove_silences` cuts inter-word gaps, so words stay
  un-struck through it — which is the correct UX.
- **`cut_words` cuts exactly `[first_word.start, last_word.end]`; restore re-adds
  the same span.** Symmetric and predictable. Trailing inter-word silence is
  handled by the separate `remove_silences` action rather than by fuzzy
  span-extension, keeping restore an exact inverse.
- **Each action is applied against the *current* keep set** (subtract/intersect/
  union), so edits compose and every edit yields a fresh revision. `filter_topic
  keep` intersects; `remove`/`cut_*`/`trim` subtract; `restore` unions.
- **Keeps shorter than 0.25 s are dropped** after every compile step (spec
  §3): unplayable slivers, click sources.
- **`filter_topic` prefers LLM-supplied `segment_ids`** (validated against the
  transcript); only if absent does it fall back to the embedding resolver. This
  keeps the common path pure and testable and means topic filtering can work
  even with sentence-transformers uninstalled when the LLM scopes it.
- **Range math uses an epsilon (1e-6) for merge/adjacency.** Avoids float-noise
  fragmentation; adjacent ranges (`(0,1),(1,2)`) merge.

## LLM

- **Ollama only, no cloud, no API keys** (spec §5). One `plan()` interface so
  tests can mock it; the real client posts to `/api/chat` with
  `format:"json"`, `temperature:0.1`.
- **Validation failure retries once** with the pydantic error fed back, then
  surfaces a structured error. The app is fully usable with Ollama down.

## API & services

- **SSE, not WebSockets** (spec §4). One-way progress is all we need. The
  `EventHub` publishes from worker threads onto the loop via
  `call_soon_threadsafe`; the stream generator is extracted from the route so
  it's unit-testable and subscribes *before* emitting the snapshot (no missed
  events).
- **Transcription is injectable** (`TranscriptionService(transcriber=…)`) so the
  API is testable without the ML stack; the default wraps faster-whisper.
- **An `attach transcript` endpoint** exists for the no-ML path (import an
  existing transcript / drive the app without whisper). To make it race-free
  against the auto-started background job, store mutations are atomic and
  field-scoped (`begin_transcription`, `set_thumbnail`) and a failing job never
  clobbers a project that's already `ready`.
- **Media served with Starlette `FileResponse`** which honours `Range` (206);
  explicitly tested. Export files served the same way with a basename-only
  path-traversal guard.

## LLM & embeddings

- **`filter_topic` prefers LLM `segment_ids`**; the embedding resolver is only a
  fallback and is injected into the compiler so the engine stays pure. The
  selection maths (`select_segment_indices`) is a pure, tested function; the
  sentence-transformers model load is lazy and cached.
- **Command failures return `{ok:false, kind, error}` at HTTP 200** so the UI can
  render them inline in the command bar rather than throwing.

## Export (ffmpeg)

- **Filter graph always written to `-filter_complex_script`** — filler removal
  can produce hundreds of ranges and blow past the command-line length limit,
  especially on Windows.
- **~15 ms `afade` in/out per kept segment** so concatenated cuts don't click.
- **9:16 crop happens before subtitles** so caption positioning is correct;
  crop is skipped if the source is already at/under the target aspect (then we
  scale+pad instead).
- **NVENC with automatic libx264 fallback.** `ffmpeg -encoders` listing NVENC
  doesn't guarantee a usable GPU/driver (it's listed but non-functional in some
  environments), so if the NVENC encode fails we transparently retry with
  `libx264 -crf`. `doctor`'s NVENC check is a *listing* check and says so.
- **Captions burned from an ASS file** whose every timestamp is mapped through
  `remap_time` onto the output timeline; cut words are dropped. No ASS in
  preview — the preview caption is a clock-driven DOM overlay (§6.3).

## Frontend performance & UX

- **A playback clock outside React state.** The `<video>` rAF loop pushes time
  into a small pub/sub `clock`; the active-word highlight, timeline playhead,
  caption overlay, and time readout subscribe imperatively and mutate the DOM —
  so a 5k-word transcript never re-renders on `timeupdate` (spec §6.2). The
  active word is found by binary search and updated by toggling a class on at
  most two elements.
- **Selection painting is imperative too** — dragging across thousands of words
  toggles a class on the affected nodes rather than re-rendering; the final
  coords are committed to the store on mouse-up.
- **Deep-link `/?open=<id>`** jumps straight into the editor (also how the README
  screenshots are captured, via `scripts/shot.mjs` + headless Chrome/CDP).
- **Design (§6.8):** warm-charcoal surfaces, a single amber accent reserved for
  the playhead + active states, the transcript set in a serif reading face with
  cuts as ink-red strikethrough redactions and timecodes in tabular mono.
  `prefers-reduced-motion` respected; visible `:focus-visible` rings.
