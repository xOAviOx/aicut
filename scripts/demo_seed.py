#!/usr/bin/env python
"""Seed a self-contained demo project that shows off every feature.

Generates a short clip (ffmpeg test pattern + an audio track that alternates
tremolo tone-bursts during "speech" and true silence during gaps, so the
waveform strip and the silence/tighten cuts are visibly meaningful), then
attaches a crafted transcript containing:

  * filler words        -> "Remove fillers"
  * wide + intra gaps   -> "Remove silences" / "Tighten"
  * a near-verbatim repeated take -> "Remove retakes"
  * low word-probabilities        -> the "confidence" shading toggle

No TTS or user video required. Idempotent-ish: run it again for a fresh project.

    uv run python scripts/demo_seed.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from aicut.config import get_settings
from aicut.media import extract_thumbnail
from aicut.models import Segment, Transcript, Word
from aicut.project import ProjectStore

SR = 22050

# (text, seconds of silence BEFORE this line, tone frequency, is_retake)
SCRIPT: list[tuple[str, float, int]] = [
    ("um so welcome to the demo of our new editor", 0.0, 180),
    ("our pricing starts at just ten dollars a month", 1.4, 240),
    ("our pricing starts at just ten dollars a month", 0.5, 240),  # retake
    ("you know the main feature is really fast editing", 1.6, 300),
    ("uh it also adds captions automatically for you", 0.5, 260),
    ("basically thanks so much for watching this", 1.5, 200),
]

# Words whisper would be "unsure" about -> shaded when confidence is on.
LOW_CONF = {"editor", "automatically", "month"}
MID_CONF = {"captions", "pricing", "watching"}


def _norm(tok: str) -> str:
    return "".join(c for c in tok.lower() if c.isalnum())


def _prob(tok: str) -> float:
    n = _norm(tok)
    if n in LOW_CONF:
        return 0.41
    if n in MID_CONF:
        return 0.66
    return 0.94


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _tone(freq: int, dur: float, dest: Path) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={dur:.3f}:sample_rate={SR}",
        "-af", "tremolo=f=6:d=0.7",
        "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dest),
    ])


def _silence(dur: float, dest: Path) -> None:
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono",
        "-t", f"{dur:.3f}", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dest),
    ])


def build_media_and_transcript(work: Path, out_video: Path) -> Transcript:
    parts: list[Path] = []
    segments: list[Segment] = []
    clock = 0.0
    idx = 0
    for text, pre_silence, freq in SCRIPT:
        if pre_silence > 0:
            sp = work / f"sil_{idx}.wav"
            _silence(pre_silence, sp)
            parts.append(sp)
            clock += pre_silence

        tokens = text.split()
        per, gap = 0.30, 0.06
        # give one segment an extra intra-sentence pause so Tighten beats Silences
        big_gap_after = 3 if idx == 3 else -1
        words: list[Word] = []
        t = clock
        for i, tok in enumerate(tokens):
            words.append(Word(w=tok, start=round(t, 3), end=round(t + per, 3), prob=_prob(tok)))
            t += per + (0.7 if i == big_gap_after else gap)
        seg_end = words[-1].end
        segments.append(
            Segment(id=idx, start=round(clock, 3), end=round(seg_end, 3), text=text, words=words)
        )

        tp = work / f"tone_{idx}.wav"
        _tone(freq, seg_end - clock, tp)
        parts.append(tp)
        clock = seg_end
        idx += 1

    total = round(clock + 0.5, 3)

    # concat audio, mux over a test pattern
    listing = work / "list.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    audio = work / "audio.wav"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-ar", str(SR), "-ac", "1", str(audio)])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=854x480:rate=25:duration={total:.3f}",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(out_video),
    ])

    return Transcript(source=str(out_video), duration=total, language="en", segments=segments)


def main() -> int:
    if not _have("ffmpeg"):
        print("ffmpeg not found on PATH; cannot build the demo clip.", file=sys.stderr)
        return 1

    settings = get_settings()
    settings.ensure_dirs()
    demo_dir = settings.home / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    video = demo_dir / "aicut-demo.mp4"

    with tempfile.TemporaryDirectory() as td:
        transcript = build_media_and_transcript(Path(td), video)

    store = ProjectStore(settings)
    project = store.create(str(video), name="Demo — feature tour")
    transcript.source = str(video)
    store.finalize_transcript(project.id, transcript)
    thumb = store.settings.project_dir(project.id) / "thumb.jpg"
    if extract_thumbnail(video, thumb, at=0.5) is not None:
        store.set_thumbnail(project.id, f"/media/{project.id}/thumb")

    print(f"seeded project: {project.id}")
    print(f"open: http://localhost:5173/?open={project.id}")
    return 0


def _have(tool: str) -> bool:
    import shutil

    return shutil.which(tool) is not None


if __name__ == "__main__":
    sys.exit(main())
