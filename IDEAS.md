# Ideas (deferred — explicitly out of scope for v1)

Parked here per the spec's non-goals so they don't creep into v1.

- Multi-clip / multi-track timeline; drag-to-trim clips.
- B-roll, music beds, image overlays.
- Transitions (crossfades, wipes) between kept ranges.
- Waveform rendering under the timeline strip.
- Speaker diarization ("keep only what Alice said").
- Auto-shorts / virality clipping; hook detection.
- Face-tracking / content-aware reframe for 9:16 (v1 does center crop).
- Translation / dubbing of the transcript.
- Collaboration, auth, cloud sync.
- Electron packaging (architected to allow it later; not built now).

## Smaller nice-to-haves noticed while building

- Word-level confidence shading in the transcript.
- "Cut everything except the last take" (detect repeated phrasings).
- Per-segment "tighten" that also removes intra-sentence dead air.
- Export presets remembered per project.
- Undo grouping (collapse a burst of manual deletes into one history entry).
