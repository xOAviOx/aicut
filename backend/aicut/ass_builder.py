"""Build an ASS subtitle file from surviving words on the OUTPUT timeline.

Every timestamp is passed through ``remap_time`` so captions line up with the
cut video (caption times live on the output timeline, not source time). Words
whose spans were cut are dropped. Style comes from the project's caption
settings: bold sans, bottom-center, wrapped to at most ``max_lines``.
"""

from __future__ import annotations

from . import rangemath as rm
from .models import CompiledEDL, Transcript

# libass default resolution the style is authored against.
DEFAULT_PLAY_RES = (1080, 1920)


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").strip()


def _wrap(words: list[str], max_lines: int, per_line: int = 42) -> str:
    """Greedy wrap into at most ``max_lines`` lines (\\N separated)."""
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = f"{cur} {w}".strip()
        if len(candidate) > per_line and cur:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
        else:
            cur = candidate
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return "\\N".join(_escape(line) for line in lines)


def _surviving_words(seg, keep: rm.Ranges):
    out = []
    for w in seg.words:
        mid = (w.start + w.end) / 2
        if rm.contains(keep, mid):
            out.append(w)
    return out


def _header(edl: CompiledEDL, play_res: tuple[int, int]) -> str:
    cap = edl.captions
    w, h = play_res
    margin_v = max(40, int(h * 0.06))
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{cap.font},{cap.font_size},&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )


def caption_events(
    edl: CompiledEDL,
    transcript: Transcript,
    keep: rm.Ranges | None = None,
    time_offset: float = 0.0,
) -> list[tuple[float, float, str]]:
    """Surviving caption events as ``(start, end, text)`` on the output timeline.

    ``time_offset`` shifts every event later — used when stitching multiple
    clips so clip B's captions land after clip A's output duration.
    """
    keep = rm.normalize(edl.keep if keep is None else keep)
    cap = edl.captions
    events: list[tuple[float, float, str]] = []

    for seg in transcript.segments:
        surviving = _surviving_words(seg, keep)
        if not surviving:
            continue
        if cap.granularity == "word":
            for w in surviving:
                s = rm.remap_time(w.start, keep) + time_offset
                e = rm.remap_time(w.end, keep) + time_offset
                if e - s < 0.05:
                    e = s + 0.05
                events.append((s, e, _escape(w.w)))
        else:  # segment
            s = rm.remap_time(surviving[0].start, keep) + time_offset
            e = rm.remap_time(surviving[-1].end, keep) + time_offset
            text = _wrap([w.w for w in surviving], cap.max_lines)
            events.append((s, e, text))
    return events


def render_ass(
    events: list[tuple[float, float, str]],
    style_edl: CompiledEDL,
    play_res: tuple[int, int] = DEFAULT_PLAY_RES,
) -> str:
    """Render caption events into a complete ASS document."""
    lines = [_header(style_edl, play_res)]
    for s, e, text in sorted(events, key=lambda ev: ev[0]):
        lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{text}\n")
    return "".join(lines)


def build_ass(
    edl: CompiledEDL,
    transcript: Transcript,
    play_res: tuple[int, int] = DEFAULT_PLAY_RES,
) -> str:
    """Return a complete ASS document for the surviving captions."""
    return render_ass(caption_events(edl, transcript), edl, play_res)
