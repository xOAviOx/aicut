# Ideas (deferred — explicitly out of scope for v1)

Parked here per the spec's non-goals so they don't creep into v1.

- **Unified single-timeline editor** — both transcripts in *one* continuous
  scroll, one timeline spanning all clips, and seamless playback across the join.
  Note: a **multi-clip Workspace is now shipped** (clip tabs: group clips, edit
  each with the full toolset, export stitched A→B→…). The still-deferred piece is
  fusing them into a single editing surface with one playhead.
- B-roll, music beds, image overlays.
- Transitions (crossfades, wipes) between kept ranges.
- Speaker diarization ("keep only what Alice said").
- Auto-shorts / virality clipping; hook detection.
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

## Still smaller nice-to-haves

- Retake detection via embeddings (paraphrased restarts, not just near-verbatim).
- Undo grouping (collapse a burst of manual deletes into one history entry).
