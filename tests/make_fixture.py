"""Synthesize a ~60 s talking-head-ish fixture for integration tests + demos.

Speaks a scripted monologue (with known filler words, deliberate silences, and
three distinct topics) via espeak-ng, muxes it over an ffmpeg test pattern, and
writes an *aligned synthetic transcript* so the engine can be exercised without
the multi-GB whisper model. Only the script (below) is committed; the .mp4 /
.json are generated on demand and gitignored.

Usage:
    python tests/make_fixture.py            # writes tests/fixtures/fixture.{mp4,transcript.json}
    python -c "from tests.make_fixture import ensure_fixture; ensure_fixture()"

Gracefully no-ops (returns None) if espeak-ng or ffmpeg is missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# (topic, spoken line, seconds of silence BEFORE this line)
# Fillers: um, uh, you know, basically, matlab, yaar. Topics: pricing/features/support.
SCRIPT: list[tuple[str, str, float]] = [
    ("pricing", "um so welcome to the demo of our product", 0.0),
    ("pricing", "you know our basic pricing starts at ten dollars a month", 1.5),
    ("pricing", "the pro plan is twenty five dollars basically", 0.4),
    ("features", "the main feature is really fast video editing", 1.8),
    ("features", "uh you can also add captions automatically", 0.5),
    ("features", "matlab it works in many languages yaar", 0.5),
    ("support", "our support team is available all week", 1.6),
    ("support", "um you can reach us by email anytime", 0.5),
    ("support", "thanks so much for watching the demo", 1.2),
]

SAMPLE_RATE = 22050


@dataclass
class Built:
    video: Path
    transcript: Path


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _espeak(text: str, dest: Path) -> None:
    exe = shutil.which("espeak-ng") or "espeak-ng"
    subprocess.run(
        [exe, "-s", "150", "-w", str(dest), text],
        check=True,
        capture_output=True,
    )


def _silence(dur: float, dest: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono",
            "-t", f"{dur:.3f}", "-ar", str(SAMPLE_RATE), "-ac", "1", str(dest),
        ],
        check=True,
        capture_output=True,
    )


def build(out_dir: Path = FIXTURE_DIR) -> Built | None:
    if not (_have("espeak-ng") and _have("ffmpeg")):
        print("[make_fixture] espeak-ng or ffmpeg missing; skipping", file=sys.stderr)
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(exist_ok=True)

    parts: list[Path] = []
    segments = []
    clock = 0.0
    seg_id = 0

    for topic, line, pre_silence in SCRIPT:
        if pre_silence > 0:
            sp = work / f"sil_{seg_id}.wav"
            _silence(pre_silence, sp)
            parts.append(sp)
            clock += pre_silence

        wp = work / f"line_{seg_id}.wav"
        _espeak(line, wp)
        dur = _wav_duration(wp)
        parts.append(wp)

        # distribute words evenly across the spoken span (approximate alignment)
        tokens = line.split()
        per = dur / max(len(tokens), 1)
        words = []
        for i, tok in enumerate(tokens):
            ws = round(clock + i * per, 3)
            we = round(clock + (i + 1) * per, 3)
            words.append({"w": tok, "start": ws, "end": we})
        segments.append(
            {
                "id": seg_id,
                "start": round(clock, 3),
                "end": round(clock + dur, 3),
                "text": line,
                "words": words,
                "topic": topic,  # extra field, ignored by the model
            }
        )
        clock += dur
        seg_id += 1

    total = clock

    # concat all audio parts
    concat_list = work / "list.txt"
    concat_list.write_text(
        "".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8"
    )
    audio = work / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-ar", str(SAMPLE_RATE), "-ac", "1", str(audio)],
        check=True, capture_output=True, cwd=str(work),
    )

    # mux over a test pattern
    video = out_dir / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=25:duration={total:.3f}",
            "-i", str(audio),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(video),
        ],
        check=True, capture_output=True,
    )

    transcript = {
        "source": str(video),
        "duration": round(total, 3),
        "language": "en",
        "segments": [
            {k: v for k, v in s.items() if k != "topic"} for s in segments
        ],
    }
    tpath = out_dir / "fixture.transcript.json"
    tpath.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

    shutil.rmtree(work, ignore_errors=True)
    print(f"[make_fixture] wrote {video} ({total:.1f}s) and {tpath}")
    return Built(video=video, transcript=tpath)


def ensure_fixture(out_dir: Path = FIXTURE_DIR) -> Built | None:
    """Build the fixture if not already present."""
    v = out_dir / "fixture.mp4"
    t = out_dir / "fixture.transcript.json"
    if v.exists() and t.exists():
        return Built(video=v, transcript=t)
    return build(out_dir)


if __name__ == "__main__":
    result = build()
    if result is None:
        print("Fixture not built (missing espeak-ng/ffmpeg). See tests/make_fixture.py.")
        sys.exit(0)
