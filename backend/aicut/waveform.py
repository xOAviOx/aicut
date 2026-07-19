"""Audio waveform peak extraction for the timeline strip.

We decode the source audio to low-rate mono PCM via ffmpeg, then reduce it to a
fixed number of normalized peak amplitudes (an envelope) the frontend renders on
a canvas. Peaks are cached per project so the (few-second) decode happens once.

Pure ``array``/``subprocess`` — no numpy, no moviepy. Silent/audio-less inputs
yield an empty list, which the frontend simply doesn't draw.
"""

from __future__ import annotations

import json
import subprocess
import sys
from array import array
from pathlib import Path

from .media import ffmpeg_bin, has_audio

# Fixed low decode rate keeps the work bounded regardless of clip length
# (30 min * 2000 Hz * 2 bytes ~= 7 MB) while preserving the amplitude envelope.
SAMPLE_RATE = 2000
DEFAULT_BUCKETS = 900
CACHE_VERSION = 1


def audio_peaks(src: str | Path, buckets: int = DEFAULT_BUCKETS) -> list[float]:
    """Return ``buckets`` normalized peak amplitudes (0..1) for ``src``.

    Returns ``[]`` if the source has no audio stream or ffmpeg is unavailable.
    """
    src = Path(src)
    if not src.exists() or not has_audio(src):
        return []

    cmd = [
        ffmpeg_bin(),
        "-v",
        "error",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=180)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0 or not out.stdout:
        return []

    samples = array("h")
    # Trim to a whole number of 16-bit frames before parsing.
    raw = out.stdout
    samples.frombytes(raw[: len(raw) - (len(raw) % samples.itemsize)])
    if sys.byteorder == "big":  # s16le -> native
        samples.byteswap()
    return reduce_to_peaks(samples, buckets)


def reduce_to_peaks(samples: array, buckets: int) -> list[float]:
    """Reduce signed 16-bit PCM ``samples`` to ``buckets`` normalized peaks.

    Each bucket takes the max absolute amplitude in its window (an envelope),
    then the whole set is normalized so the loudest bucket is 1.0. Pure and
    ffmpeg-free so it can be unit-tested directly.
    """
    n = len(samples)
    if n == 0:
        return []
    buckets = max(1, buckets)
    step = max(1, -(-n // buckets))  # ceil division
    peaks: list[float] = []
    for i in range(0, n, step):
        chunk = samples[i : i + step]
        if not chunk:
            break
        peaks.append(float(max(max(chunk), -min(chunk))))

    top = max(peaks) if peaks else 0.0
    if top <= 0:
        return [0.0 for _ in peaks]
    return [round(p / top, 4) for p in peaks]


def get_or_build_peaks(
    src: str | Path, cache_path: str | Path, buckets: int = DEFAULT_BUCKETS
) -> list[float]:
    """Peaks for ``src``, cached as JSON at ``cache_path``."""
    cache_path = Path(cache_path)
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION and data.get("buckets") == buckets:
                return data.get("peaks", [])
        except Exception:
            pass
    peaks = audio_peaks(src, buckets)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"version": CACHE_VERSION, "buckets": buckets, "peaks": peaks}),
            encoding="utf-8",
        )
    except Exception:
        pass
    return peaks
