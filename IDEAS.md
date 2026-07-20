# Ideas (deferred — explicitly out of scope for v1)

Parked here per the spec's non-goals so they don't creep into v1.

- **Unified single-timeline editor** — both transcripts in *one* continuous
  scroll, one timeline spanning all clips, and seamless playback across the join.
  Note: a **multi-clip Workspace is now shipped** (clip tabs: group clips, edit
  each with the full toolset, export stitched A→B→…). The still-deferred piece is
  fusing them into a single editing surface with one playhead.
- B-roll, music beds, image overlays.
- Speaker diarization ("keep only what Alice said").
- Virality scoring / hook detection (ML). Note: a deterministic **auto-short
  (Highlights)** pass is now shipped — it keeps the strongest segments up to a
  time budget. The still-deferred piece is *learned* virality/hook ranking.
- Face-tracking / content-aware reframe for 9:16 (v1 does center crop).
- Translation / dubbing of the transcript.
- Collaboration, auth, cloud sync.
- Electron packaging (architected to allow it later; not built now).

## Shipped after v1 (were nice-to-haves)

- **Waveform under the timeline strip** — ffmpeg peak extraction (cached),
  drawn on a canvas behind the kept/cut overlay.
- **Word-level confidence shading** — whisper per-word probability, toggled on
  in the transcript header; likely mishearings get a dotted underline.
- **"Keep only the last take"** — `remove_retakes` detects repeated attempts at
  a line (lexical similarity) and cuts all but the final one.
- **Per-segment "tighten"** — `tighten` caps *every* pause (incl. intra-sentence
  dead air), punchier than `remove_silences`.
- **Export presets remembered per project** — the Export dialog reopens with the
  last-used aspect/captions/quality.
- **Retake detection via embeddings** — `remove_retakes` now takes an optional
  semantic scorer (sentence-transformers), so paraphrased restarts are caught,
  not just near-verbatim ones; lexical stays the zero-dep fallback.
- **Undo grouping** — a burst of manual edits within a few seconds folds into a
  single history entry (one undo reverts the whole burst).
- **Highlights (auto-short)** — `find_highlights` scores every segment on
  content density, sentence completeness, and filler load, then keeps the
  strongest ones (chronologically) up to a budget of
  `min(target_s, current_content × max_fraction)`. Deterministic, no ML deps;
  available as a one-click button and via the AI command bar.
- **Transitions (crossfade / wipe)** — `set_transition` joins consecutive kept
  ranges with an ffmpeg `xfade`+`acrossfade` on export (hard cut stays the
  default). The overlap is clamped so it can never exceed the shortest segment,
  falls back to a hard cut when too tight, and captions are pulled back onto the
  crossfade-compressed timeline so they stay in sync. The timeline strip marks
  each transition join. (A live crossfade *preview* in the player — as opposed
  to the marker — is still deferred; it renders correctly on export.)

## Multi-clip merge + workspaces (shipped)

- **Merge at export** — stitch several clips A→B→… into one file, normalized to a
  common canvas/fps, captions offset per clip.
- **Workspaces** — group clips and edit each with the full toolset via clip tabs,
  then export merged.
