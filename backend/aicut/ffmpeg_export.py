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
from .ass_builder import build_ass, caption_events, render_ass
from .media import ffmpeg_bin, has_audio, video_dimensions
from .models import CaptionSettings, CompiledEDL, Transcript

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


# ---------------------------------------------------------------------------
# Multi-clip merge (append / stitch A -> B -> ...)
# ---------------------------------------------------------------------------


@dataclass
class MergeClip:
    """One clip in a stitched export: its source, its keep-ranges, and the
    transcript (for captions). ``keep`` is in the clip's own source time."""

    src: Path
    keep: rm.Ranges
    transcript: Transcript
    src_dims: tuple[int, int] | None = None
    has_audio: bool = True


def _reframe_chain(aspect: str, src_dims: tuple[int, int] | None, tw: int, th: int) -> str:
    """Per-clip video normalization so every segment matches the merge canvas."""
    if aspect in ("9:16", "1:1") and _needs_crop(aspect, src_dims):
        crop = "crop=ih*9/16:ih" if aspect == "9:16" else "crop=ih:ih"
        return f"{crop},scale={tw}:{th}"
    return (
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2"
    )


def build_merge_filtergraph(
    clips: list[MergeClip],
    aspect: str,
    target_dims: tuple[int, int],
    fps: int,
    ass_name: str | None,
    audio: bool,
) -> tuple[str, str, str | None]:
    """Filter graph that trims each clip's keeps, normalizes them to one canvas,
    and concats them in order. Returns (graph, video_label, audio_label|None)."""
    tw, th = target_dims
    parts: list[str] = []
    vlabels: list[str] = []
    alabels: list[str] = []
    k = 0
    for ci, clip in enumerate(clips):
        reframe = _reframe_chain(aspect, clip.src_dims, tw, th)
        for s, e in rm.normalize(clip.keep):
            parts.append(
                f"[{ci}:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS,"
                f"{reframe},fps={fps},setsar=1[v{k}]"
            )
            vlabels.append(f"[v{k}]")
            if audio:
                d = e - s
                fo = max(0.0, d - 0.015)
                parts.append(
                    f"[{ci}:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:st=0:d=0.015,afade=t=out:st={fo:.3f}:d=0.015,"
                    f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{k}]"
                )
                alabels.append(f"[a{k}]")
            k += 1

    if k == 0:
        raise ValueError("merge: nothing to render")
    if audio:
        inter = "".join(f"{v}{a}" for v, a in zip(vlabels, alabels, strict=True))
        parts.append(f"{inter}concat=n={k}:v=1:a=1[vcat][acat]")
        acur: str | None = "[acat]"
    else:
        parts.append("".join(vlabels) + f"concat=n={k}:v=1:a=0[vcat]")
        acur = None
    vcur = "[vcat]"
    if ass_name:
        parts.append(f"{vcur}subtitles=filename={ass_name}[vsub]")
        vcur = "[vsub]"
    return ";\n".join(parts), vcur, acur


def build_merge_command(
    srcs: list[Path],
    out_name: str,
    vlabel: str,
    alabel: str | None,
    quality: str,
    use_nvenc: bool = True,
) -> list[str]:
    q = QUALITY.get(quality, QUALITY["balanced"])
    cmd = [ffmpeg_bin(), "-y"]
    for s in srcs:
        cmd += ["-i", str(s)]
    cmd += ["-filter_complex_script", "filter.txt", "-map", vlabel]
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


def export_merge(
    clips: list[MergeClip],
    out_path: str | Path,
    preset: ExportPreset | None = None,
    progress_cb: ProgressCb | None = None,
) -> Path:
    """Stitch ``clips`` (each already edited to its keep-ranges) into one file.

    Every clip is normalized to a common canvas + fps so concat is valid across
    differing sources; audio is kept only if *all* clips have it. Captions, when
    enabled, are one ASS whose events are offset by each clip's output start.
    """
    preset = preset or ExportPreset()
    out_path = Path(out_path)
    workdir = out_path.parent
    workdir.mkdir(parents=True, exist_ok=True)

    clips = [c for c in clips if rm.normalize(c.keep)]
    if not clips:
        raise ValueError("nothing to export: every clip's edit removed all content")

    aspect = preset.aspect or "source"
    audio = all(c.has_audio for c in clips)
    if aspect in TARGET_SIZE:
        target = TARGET_SIZE[aspect]
    else:
        base = clips[0].src_dims or (1280, 720)
        target = (base[0] - base[0] % 2, base[1] - base[1] % 2)  # even dims for yuv420p
    fps = 30

    ass_name = None
    if preset.captions:
        cap = CaptionSettings(enabled=True, granularity=(preset.granularity or "segment"))  # type: ignore[arg-type]
        style_edl = CompiledEDL(captions=cap, aspect=aspect)
        events: list[tuple[float, float, str]] = []
        offset = 0.0
        for c in clips:
            clip_edl = CompiledEDL(keep=c.keep, captions=cap)
            events += caption_events(clip_edl, c.transcript, keep=c.keep, time_offset=offset)
            offset += rm.total(c.keep)
        (workdir / "captions.ass").write_text(
            render_ass(events, style_edl, play_res=target), encoding="utf-8"
        )
        ass_name = "captions.ass"

    graph, vlabel, alabel = build_merge_filtergraph(clips, aspect, target, fps, ass_name, audio)
    (workdir / "filter.txt").write_text(graph, encoding="utf-8")

    srcs = [c.src for c in clips]
    output_dur = sum(rm.total(c.keep) for c in clips)
    encoders = [True, False] if nvenc_available() else [False]
    last_tail = ""
    for use_nvenc in encoders:
        cmd = build_merge_command(srcs, out_path.name, vlabel, alabel, preset.quality, use_nvenc)
        cmd += ["-progress", "pipe:1", "-nostats"]
        rc, last_tail = _run_ffmpeg(cmd, workdir, output_dur, progress_cb)
        if rc == 0:
            if progress_cb:
                progress_cb(1.0)
            return out_path
    raise RuntimeError(f"ffmpeg merge failed:\n{last_tail}")


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
