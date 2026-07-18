"""ffmpeg export renderer.

Frame-accurate = re-encode. For each keep-range we ``trim/atrim`` + reset PTS,
add a ~15 ms audio fade in/out (so cuts don't click), then ``concat`` them.
Optional 9:16 crop happens *before* subtitles so caption positioning is correct.
The whole filter graph is written to a file and passed via
``-filter_complex_script`` — hundreds of ranges would otherwise blow past the
command-line length limit (especially on Windows).

Encoding uses ``h264_nvenc`` when available, else ``libx264``. ffmpeg
``-progress`` output is parsed into a fraction for SSE.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import rangemath as rm
from .ass_builder import build_ass
from .media import ffmpeg_bin, has_audio, video_dimensions
from .models import CompiledEDL, Transcript

ProgressCb = Callable[[float], None]


@dataclass
class ExportPreset:
    aspect: str | None = None  # override edl.aspect if set
    captions: bool | None = None  # override edl.captions.enabled if set
    granularity: str | None = None  # override edl.captions.granularity if set
    quality: str = "balanced"  # high | balanced | fast


QUALITY = {
    "high": {"nvenc_cq": "18", "x264_crf": "17", "x264_preset": "slow"},
    "balanced": {"nvenc_cq": "19", "x264_crf": "18", "x264_preset": "medium"},
    "fast": {"nvenc_cq": "23", "x264_crf": "22", "x264_preset": "veryfast"},
}

TARGET_SIZE = {"9:16": (1080, 1920), "1:1": (1080, 1080)}


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10
        )
        return "h264_nvenc" in out.stdout
    except Exception:
        return False


def _needs_crop(aspect: str, src_dims: tuple[int, int] | None) -> bool:
    """Skip crop if the source is already at/under the target aspect."""
    if aspect not in ("9:16", "1:1"):
        return False
    if not src_dims:
        return True
    w, h = src_dims
    src_ratio = w / h if h else 1.0
    target_ratio = 9 / 16 if aspect == "9:16" else 1.0
    return src_ratio > target_ratio + 1e-3


def build_filtergraph(
    keep: rm.Ranges,
    aspect: str,
    ass_name: str | None,
    audio: bool,
    src_dims: tuple[int, int] | None,
) -> tuple[str, str, str | None]:
    """Return (graph_text, video_out_label, audio_out_label|None)."""
    keep = rm.normalize(keep)
    parts: list[str] = []
    concat_inputs: list[str] = []
    for i, (s, e) in enumerate(keep):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        concat_inputs.append(f"[v{i}]")
        if audio:
            d = e - s
            fo = max(0.0, d - 0.015)
            parts.append(
                f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d=0.015,afade=t=out:st={fo:.3f}:d=0.015[a{i}]"
            )
            concat_inputs.append(f"[a{i}]")

    n = len(keep)
    if audio:
        parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=1[vcat][acat]")
        acur: str | None = "[acat]"
    else:
        parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=0[vcat]")
        acur = None
    vcur = "[vcat]"

    if aspect in ("9:16", "1:1"):
        tw, th = TARGET_SIZE[aspect]
        if _needs_crop(aspect, src_dims):
            crop = "crop=ih*9/16:ih" if aspect == "9:16" else "crop=ih:ih"
            parts.append(f"{vcur}{crop},scale={tw}:{th},setsar=1[vre]")
        else:
            parts.append(f"{vcur}scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                         f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1[vre]")
        vcur = "[vre]"

    if ass_name:
        # referenced relative to the ffmpeg working dir (the export folder), so
        # no Windows path-escaping headaches.
        parts.append(f"{vcur}subtitles=filename={ass_name}[vsub]")
        vcur = "[vsub]"

    return ";\n".join(parts), vcur, acur


def build_command(
    src: Path,
    workdir: Path,
    out_name: str,
    vlabel: str,
    alabel: str | None,
    quality: str,
    use_nvenc: bool = True,
) -> list[str]:
    q = QUALITY.get(quality, QUALITY["balanced"])
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        str(src),
        "-filter_complex_script",
        "filter.txt",
        "-map",
        vlabel,
    ]
    if alabel:
        cmd += ["-map", alabel]
    if use_nvenc and nvenc_available():
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", q["nvenc_cq"], "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-crf", q["x264_crf"], "-preset", q["x264_preset"]]
    cmd += ["-pix_fmt", "yuv420p"]
    if alabel:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", out_name]
    return cmd


def export(
    edl: CompiledEDL,
    transcript: Transcript,
    src_path: str | Path,
    out_path: str | Path,
    preset: ExportPreset | None = None,
    progress_cb: ProgressCb | None = None,
) -> Path:
    preset = preset or ExportPreset()
    src = Path(src_path)
    out_path = Path(out_path)
    workdir = out_path.parent
    workdir.mkdir(parents=True, exist_ok=True)

    keep = rm.normalize(edl.keep)
    if not keep:
        raise ValueError("nothing to export: the edit removed all content")

    aspect = preset.aspect or edl.aspect
    captions_on = edl.captions.enabled if preset.captions is None else preset.captions
    audio = has_audio(src)
    src_dims = video_dimensions(src)

    ass_name = None
    if captions_on:
        if preset.granularity or edl.captions.enabled != captions_on:
            edl = edl.model_copy(deep=True)
            edl.captions.enabled = True
            if preset.granularity:
                edl.captions.granularity = preset.granularity  # type: ignore[assignment]
        play_res = TARGET_SIZE.get(aspect) or (src_dims or (1920, 1080))
        ass_text = build_ass(edl, transcript, play_res=play_res)
        ass_name = "captions.ass"
        (workdir / ass_name).write_text(ass_text, encoding="utf-8")

    graph, vlabel, alabel = build_filtergraph(keep, aspect, ass_name, audio, src_dims)
    (workdir / "filter.txt").write_text(graph, encoding="utf-8")

    output_dur = rm.total(keep)
    # Prefer NVENC when compiled in, but it may be listed yet non-functional
    # (no usable GPU / driver). Fall back to libx264 if the encode fails.
    encoders = [True, False] if nvenc_available() else [False]
    last_tail = ""
    for use_nvenc in encoders:
        cmd = build_command(
            src, workdir, out_path.name, vlabel, alabel, preset.quality, use_nvenc=use_nvenc
        )
        cmd += ["-progress", "pipe:1", "-nostats"]
        rc, last_tail = _run_ffmpeg(cmd, workdir, output_dur, progress_cb)
        if rc == 0:
            if progress_cb:
                progress_cb(1.0)
            return out_path
    raise RuntimeError(f"ffmpeg export failed:\n{last_tail}")


def _run_ffmpeg(
    cmd: list[str], workdir: Path, output_dur: float, progress_cb: ProgressCb | None
) -> tuple[int, str]:
    log = (workdir / "ffmpeg.log").open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(workdir), stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    val = int(line.split("=", 1)[1])
                    secs = val / (1_000_000 if "us" in line else 1000)
                    if progress_cb and output_dur > 0:
                        progress_cb(min(secs / output_dur, 0.999))
                except ValueError:
                    pass
        proc.wait()
    finally:
        log.close()
    tail = (workdir / "ffmpeg.log").read_text(encoding="utf-8", errors="replace")[-800:]
    return proc.returncode, tail
