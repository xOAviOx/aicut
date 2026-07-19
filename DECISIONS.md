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

## Post-v1 features (waveform, tighten, retakes, confidence, presets)

- **`tighten` caps every gap; `remove_silences` only removes wide ones.** They
  are deliberately distinct actions rather than one parameterized action, so the
  LLM and the one-click buttons can pick the right feel: `remove_silences`
  (min_gap 0.6s) drops obvious dead air, while `tighten` (max_gap 0.35s) also
  trims the breaths *inside* sentences, leaving at most `max_gap_s` of each. Both
  are pure range math and compose with everything else.
- **Retake detection is lexical, not embedding-based.** Repeated takes are
  usually near-verbatim restarts, so `difflib.SequenceMatcher` over normalized
  tokens (plus a containment boost for abandoned false starts) is precise,
  fully deterministic, unit-testable, and — crucially — needs **zero ML deps**,
  keeping it on the "fully usable without the `ml` extra" path. Embedding-based
  detection of paraphrased restarts is parked in `IDEAS.md`. A retake cuts
  `[earlier.start, retake.start]` so chains (A≈B≈C) collapse cleanly to C.
- **Waveform peaks come from a low-rate PCM decode, not numpy.** ffmpeg decodes
  to 2 kHz mono `s16le`; we reduce to ~900 max-abs buckets with the stdlib
  `array` module (C-speed slice max/min). Bounded work regardless of clip length,
  no new dependency. Peaks are cached per project (`waveform.json`) and served
  lazily on first request; audio-less inputs yield `[]` and the canvas draws
  nothing. The reduction is a pure function (`reduce_to_peaks`) so it's tested
  without ffmpeg.
- **Confidence shading is CSS-gated, always in the DOM.** Each word carries its
  shading class (`word-lowconf` < 0.5, `word-midconf` < 0.72) unconditionally;
  the styles only apply under a `.show-confidence` container class. Toggling the
  reader's view is a single class flip — it never re-renders the 5k-word
  transcript or touches the imperative highlight/selection paths. `Word.prob` is
  optional so older cached transcripts and hand-built fixtures still validate.
- **Export presets live on `ProjectSettings.export_preset`, written on export.**
  A field-scoped store write (`remember_export_preset`) that undo/redo and
  revision appends leave untouched. The dialog prefers the saved preset, falling
  back to the current edit's aspect/captions so a first export still makes sense.

## Multi-clip merge (append / stitch)

- **Merge happens at export, not in the editor.** A full in-editor multi-clip
  timeline (both transcripts in one surface, drag-reorder) breaks the single-
  source assumption baked into the project model, engine, preview, and revision
  system — it was a deliberate v1 non-goal. Instead, each video stays its own
  single-source project (edited with the full existing toolset) and the Export
  dialog stitches the chosen projects' *head edits* A→B→… into one file. This
  reuses the entire engine unchanged and is additive: single-clip export is
  byte-for-byte the same path as before (the merge branch only triggers when
  `append_project_ids` is non-empty).
- **Every clip is normalized to one canvas + fps before `concat`.** ffmpeg's
  concat filter demands identical size/SAR/fps/audio-format across inputs, so
  each clip's segments are scaled+padded (or cropped for 9:16/1:1) to the target
  dimensions, forced to 30 fps and SAR 1, and audio is `aresample`d to 48 kHz
  `fltp` stereo. Target canvas = the aspect preset's size, or clip 1's dimensions
  (rounded to even) for "source".
- **Audio is kept only if *all* clips have it.** Mixed audio/silent inputs would
  desync the `concat` (which needs every segment to carry both streams); rather
  than synthesize silence per gap, v1 drops audio entirely in that rare case.
- **Captions across a merge are one ASS, offset per clip.** `caption_events`
  gained a `time_offset`; each clip's events are remapped onto its own output
  timeline then shifted by the cumulative output duration of prior clips, so
  subtitles stay in sync across the join. The single-clip `build_ass` is now a
  thin wrapper over `caption_events` + `render_ass` (output unchanged; golden
  test still passes).

## Multi-clip Workspace (edit several clips together)

- **A Workspace is a thin ordered group of clips, not a new engine.** Each clip
  stays an ordinary single-source `Project` with its own transcript, revisions,
  and edits; a `Workspace` just stores `{name, clip_ids[]}` in `~/aicut/
  workspaces/{id}.json`. This reuses the entire editor, revision/undo model, and
  per-clip transcription untouched — the single-source assumptions never had to
  change. It's the pragmatic "clip tabs" design; a fused single-timeline editor
  (one playhead across clips) remains in `IDEAS.md`.
- **The workspace UI mounts the existing `Editor` for the selected clip.** A
  `WorkspaceBar` renders above it with clip tabs; picking a tab is just
  `openProject(clipId)` under the hood. `applyPayload` keeps the clip rail's copy
  of each project fresh so the combined-duration readout stays live as you edit.
- **Merged export reuses the append path, driven off clip 0.** "Export merged"
  calls the normal `POST /projects/{clip0}/export` with `append_project_ids =`
  the remaining clips, so there's one export code path. Progress is read via a
  dedicated SSE subscription on clip 0 (independent of which clip is on screen),
  and the finished file lands in clip 0's exports.
- **Workspace deletion only ungroups.** Removing a workspace (or a clip from it)
  never deletes the underlying clip projects — they remain usable on their own.

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
