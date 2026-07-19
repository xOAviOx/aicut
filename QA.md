# QA — manual test script

A ~15-step smoke test of the whole app. Takes about 10 minutes. Run
`python scripts/dev.py` (backend + Vite) and open http://localhost:5173.

For a fully offline run (no whisper model), first build the fixture and note
that you can attach its transcript via `POST /api/projects/{id}/transcript`:

```bash
python tests/make_fixture.py        # -> tests/fixtures/fixture.{mp4,transcript.json}
```

Prereqs to exercise everything: `uv sync --extra ml` for real transcription and
`ollama serve` + `ollama pull qwen2.5:7b-instruct` for the AI command bar. The
app must also work with **both** of those absent — that's steps 13–14.

| # | Step | Expected |
|---|------|----------|
| 1 | **Import.** On the library, paste a path to a talking-head video (or drag-drop) and click Import. | A project appears; you land in the editor; a progress overlay shows "Transcribing…". |
| 2 | **Live progress.** Watch the overlay. | The percentage climbs via SSE; on completion the transcript renders. |
| 3 | **Playback + active word.** Press `Space`. | Video plays; the current word highlights in amber and the transcript auto-scrolls (with "follow" on). |
| 4 | **Click-to-seek.** Click any word. | The player jumps to that word's time. |
| 5 | **Timeline.** Hover and click the strip under the player. | Hover shows a timecode; click seeks; the playhead tracks playback. |
| 6 | **Select + delete.** Drag across a sentence (or click a word, Shift-click another) and press `Delete`. | The words render struck-through/redacted; duration delta in the header drops; a revision is added. |
| 7 | **Skip-preview.** With preview = **Edited**, play across the deleted span. | Playback skips the cut region seamlessly. |
| 8 | **Edited ⇄ Original.** Press `E` (or the toggle). | Preview switches; "Original" plays the uncut video; the header shows `mm:ss → mm:ss, −xx%`. |
| 9 | **Restore.** Select the struck-through words and click Restore. | The words return un-struck; a new revision is added. |
| 10 | **Undo / redo.** Press `Ctrl/⌘+Z`, then `Shift+Ctrl/⌘+Z`. | Head moves back then forward; the edit changes accordingly. |
| 11 | **Edit log.** Open **History**; click an earlier revision. | Head time-travels there; later revisions dim as "future". |
| 12 | **One-click actions.** Click **Remove silences**, then **Remove fillers**. | Duration drops measurably each time (no AI needed); revisions log "Removed silences/filler words". |
| 13 | **AI command (LLM up).** Type *"remove silences and filler words, add captions, make it vertical"* → Run. | A pending shimmer, then a revision "AI: …"; captions preview appears; player reframes to 9:16. |
| 14 | **AI command (LLM down).** Stop Ollama and Run any command. | A clear inline error ("Ollama not reachable…"); the rest of the app keeps working. |
| 15 | **Export.** Open **Export**, choose 9:16 + captions on + a quality, click Export video. | Progress bar advances via SSE; a finished file appears with a working download link; the file plays with correctly-timed burned captions and click-free cuts. |

## Post-v1 feature checks

| # | Step | Expected |
|---|------|----------|
| 16 | **Waveform.** Look at the timeline strip under the player. | An audio waveform envelope is drawn; kept regions are tinted, cut regions dimmed; playhead tracks. Audio-less clips just show no waveform (no error). |
| 17 | **Tighten.** Click **Tighten**. | Duration drops (more than plain *Remove silences*, since intra-sentence pauses are capped too); a "Tightened pauses" revision is logged. |
| 18 | **Remove retakes.** On a clip with a repeated line, click **Remove retakes**. | Earlier attempts are cut, the last take stays; a "Removed retakes" revision is logged. Works with Ollama and the ML extra both absent. |
| 19 | **Confidence shading.** Toggle **confidence** in the transcript header. | Low-probability words get a dotted underline; toggling is instant and doesn't stutter the transcript. Toggle off → underlines vanish. |
| 20 | **Export presets remembered.** Export once with 9:16 + captions, close, reopen **Export**. | The dialog reopens with the same aspect/captions/quality you last used. |

## Things to specifically watch for

- **No stutter** scrolling/among 5k+ words while playing (the transcript must not
  re-render on `timeupdate`).
- **Range seeking works** — scrubbing the native controls or clicking far ahead
  seeks instantly (server returns HTTP 206).
- **Captions land on the output timeline** — after cuts, subtitles stay in sync
  in the exported file, and words that were cut don't appear.
- **Cuts don't click** — the exported audio has no pop at each join (~15 ms fades).
- **Errors say what happened and what to do** — never a bare "Something went wrong".
- **`prefers-reduced-motion`** — with it on, the shimmer/auto-scroll animations
  are suppressed.
