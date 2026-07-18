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

## Still to record

(Filled in as later milestones land: export ffmpeg flag choices, caption ASS
styling, 9:16 crop math, frontend performance tactics.)
