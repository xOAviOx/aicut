"""ffprobe / ffmpeg helpers shared by transcription and export.

Thin ``subprocess`` wrappers — never moviepy. All paths are ``pathlib.Path``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def probe_duration(path: str | Path) -> float:
    """Return media duration in seconds via ffprobe."""
    path = Path(path)
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise FFmpegError("ffprobe not found on PATH") from e
    if out.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {out.stderr.strip()[:200]}")
    try:
        data = json.loads(out.stdout)
        return float(data["format"]["duration"])
    except Exception as e:  # pragma: no cover
        raise FFmpegError(f"could not parse ffprobe output: {e}") from e


def probe_streams(path: str | Path) -> dict:
    """Return the raw ffprobe JSON (streams + format)."""
    path = Path(path)
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def video_dimensions(path: str | Path) -> tuple[int, int] | None:
    """(width, height) of the first video stream, or None if audio-only."""
    try:
        data = probe_streams(path)
    except FFmpegError:
        return None
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and s.get("width") and s.get("height"):
            return int(s["width"]), int(s["height"])
    return None


def has_audio(path: str | Path) -> bool:
    try:
        data = probe_streams(path)
    except FFmpegError:
        return False
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def extract_thumbnail(src: str | Path, dest: str | Path, at: float = 1.0) -> Path | None:
    """Grab a single frame as a JPEG thumbnail. Returns the path or None."""
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-ss",
        str(at),
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-1",
        "-q:v",
        "4",
        str(dest),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return None
    if out.returncode != 0 or not dest.exists():
        # audio-only or failure — not fatal
        return None
    return dest
