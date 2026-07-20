"""Export renderer: filtergraph construction (unit) + real ffmpeg render."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from aicut.ass_builder import caption_events
from aicut.edl import compile_plan, initial_edl
from aicut.ffmpeg_export import (
    ExportPreset,
    MergeClip,
    _retimed_for_transition,
    build_command,
    build_filtergraph,
    build_merge_filtergraph,
    effective_transition,
    export,
    export_merge,
)
from aicut.media import probe_duration, video_dimensions
from aicut.models import (
    EditPlan,
    RemoveFillers,
    RemoveSilences,
    SetAspect,
    SetCaptions,
    Transcript,
    TransitionSettings,
)
from conftest import segment_from
from make_fixture import ensure_fixture


class TestFiltergraph:
    def test_basic_concat_with_audio(self):
        graph, v, a = build_filtergraph([(0, 1), (2, 3)], "source", None, True, (640, 360))
        assert "trim=start=0.000:end=1.000" in graph
        assert "atrim=start=2.000:end=3.000" in graph
        assert "afade=t=in" in graph and "afade=t=out" in graph
        assert "concat=n=2:v=1:a=1" in graph
        assert v == "[vcat]" and a == "[acat]"

    def test_9x16_crop_before_subtitles(self):
        graph, v, a = build_filtergraph([(0, 1)], "9:16", "captions.ass", True, (640, 360))
        assert "crop=ih*9/16:ih" in graph
        assert "scale=1080:1920" in graph
        # subtitles come after the reframe label
        assert graph.index("scale=1080:1920") < graph.index("subtitles=")
        assert "subtitles=filename=captions.ass" in graph
        assert v == "[vsub]"

    def test_portrait_source_not_cropped(self):
        # a 1080x1920 source is already <= 9:16 -> pad/scale, no crop
        graph, _, _ = build_filtergraph([(0, 1)], "9:16", None, True, (1080, 1920))
        assert "crop=" not in graph

    def test_no_audio(self):
        graph, v, a = build_filtergraph([(0, 1)], "source", None, False, None)
        assert "concat=n=1:v=1:a=0" in graph
        assert a is None

    def test_command_uses_script_and_faststart(self):
        cmd = build_command(
            __import__("pathlib").Path("in.mp4"),
            __import__("pathlib").Path("."),
            "out.mp4",
            "[vsub]",
            "[acat]",
            "balanced",
        )
        assert "-filter_complex_script" in cmd
        assert "filter.txt" in cmd
        assert "+faststart" in cmd


class TestTransitions:
    def test_effective_transition_clamps_and_falls_back(self):
        cf = TransitionSettings(kind="crossfade", duration_s=0.5)
        # one segment: nothing to transition between
        assert effective_transition([(0, 2)], cf)[0] == "none"
        # second segment too short for a 0.5s overlap -> hard cut
        assert effective_transition([(0, 2), (3, 3.1)], cf)[0] == "none"
        # normal: kind kept, duration clamped under the shortest segment
        kind, d = effective_transition(
            [(0, 2), (3, 5)], TransitionSettings(kind="crossfade", duration_s=5.0)
        )
        assert kind == "crossfade" and 0.1 <= d <= 2.0

    def test_crossfade_builds_xfade_chain(self):
        graph, v, a = build_filtergraph(
            [(0, 2), (3, 5), (6, 8)], "source", None, True,
            (640, 360), transition=TransitionSettings(kind="crossfade", duration_s=0.5),
        )
        assert "xfade=transition=fade:duration=0.500" in graph
        assert "acrossfade=d=0.500" in graph
        assert "concat=" not in graph          # crossfade replaces hard concat
        assert "afade=t=in" not in graph        # no per-segment micro-fades
        # progressive offsets: 2.0-0.5, then (2+2-0.5)-0.5
        assert "offset=1.500" in graph and "offset=3.000" in graph
        assert v == "[vx2]" and a == "[ax2]"

    def test_wipe_uses_wiperight(self):
        graph, _v, _a = build_filtergraph(
            [(0, 2), (3, 5)], "source", None, False,
            (640, 360), transition=TransitionSettings(kind="wipe", duration_s=0.4),
        )
        assert "xfade=transition=wiperight:duration=0.400" in graph

    def test_single_segment_falls_back_to_concat(self):
        graph, _v, _a = build_filtergraph(
            [(0, 2)], "source", None, True, (640, 360),
            transition=TransitionSettings(kind="crossfade"),
        )
        assert "xfade" not in graph and "concat=n=1:v=1:a=1" in graph

    def test_none_transition_is_unchanged_concat(self):
        graph, _v, _a = build_filtergraph(
            [(0, 2), (3, 5)], "source", None, True, (640, 360),
            transition=TransitionSettings(kind="none"),
        )
        assert "xfade" not in graph and "concat=n=2:v=1:a=1" in graph

    def test_caption_retime_pulls_back_by_join(self):
        keep = [(0.0, 2.0), (3.0, 5.0)]  # plain output segments [0,2] and [2,4]
        events = [(1.0, 1.8, "a"), (2.2, 3.6, "b")]  # b lands in output seg 1
        out = _retimed_for_transition(events, keep, 0.5)
        assert out[0] == (1.0, 1.8, "a")               # seg 0 untouched
        assert abs(out[1][0] - (2.2 - 0.5)) < 1e-6     # seg 1 pulled back by d
        assert abs(out[1][1] - (3.6 - 0.5)) < 1e-6


class TestMergeFiltergraph:
    def _clips(self):
        ta = Transcript(source="a", duration=3.0, language="en", segments=[])
        tb = Transcript(source="b", duration=3.0, language="en", segments=[])
        return [
            MergeClip(src="a.mp4", keep=[(0, 1.5)], transcript=ta, src_dims=(640, 360)),
            MergeClip(src="b.mp4", keep=[(0, 1.0), (2, 3)], transcript=tb, src_dims=(1280, 720)),
        ]

    def test_two_inputs_concatenated(self):
        graph, v, a = build_merge_filtergraph(self._clips(), "source", (1280, 720), 30, None, True)
        assert "[0:v]trim=start=0.000:end=1.500" in graph  # clip A
        assert "[1:v]trim=start=2.000:end=3.000" in graph  # clip B, second keep
        # 3 total segments (1 from A, 2 from B)
        assert "concat=n=3:v=1:a=1" in graph
        assert "fps=30" in graph
        assert v == "[vcat]" and a == "[acat]"

    def test_no_audio_when_any_clip_silent(self):
        graph, _v, a = build_merge_filtergraph(self._clips(), "source", (640, 360), 30, None, False)
        assert "concat=n=3:v=1:a=0" in graph
        assert a is None

    def test_captions_offset_by_prior_clip_output(self):
        # clip A keeps 2s of a word at t=0.5; clip B's caption must land after 2s
        seg_a = segment_from(0, "hello world here", 0.0)  # ~0.9s of words
        ta = Transcript(source="a", duration=3.0, language="en", segments=[seg_a])
        from aicut.models import CaptionSettings, CompiledEDL

        cap = CaptionSettings(enabled=True, granularity="segment")
        edl = CompiledEDL(keep=[(0.0, 3.0)], captions=cap)
        base = caption_events(edl, ta, keep=[(0.0, 3.0)], time_offset=0.0)
        shifted = caption_events(edl, ta, keep=[(0.0, 3.0)], time_offset=2.0)
        assert base and shifted
        assert abs(shifted[0][0] - (base[0][0] + 2.0)) < 1e-6


def _make_clip(path, dur: float = 2.0, size: str = "320x240", freq: int = 220) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={dur}",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_merge_two_clips_renders(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _make_clip(a, 2.0, freq=220)
    _make_clip(b, 2.0, freq=440)
    ta = Transcript(source=str(a), duration=2.0, language="en", segments=[])
    tb = Transcript(source=str(b), duration=2.0, language="en", segments=[])
    clips = [
        MergeClip(src=a, keep=[(0.0, 1.5)], transcript=ta, src_dims=(320, 240), has_audio=True),
        MergeClip(src=b, keep=[(0.0, 1.0)], transcript=tb, src_dims=(320, 240), has_audio=True),
    ]
    out = tmp_path / "merged.mp4"
    export_merge(clips, out, ExportPreset(aspect="source", quality="fast"))
    assert out.exists() and out.stat().st_size > 0
    # kept 1.5s + 1.0s ~= 2.5s
    assert abs(probe_duration(out) - 2.5) < 0.7


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_export_renders_shorter_vertical_captioned(tmp_path):
    built = ensure_fixture()
    if built is None:
        pytest.skip("fixture could not be built (espeak-ng/ffmpeg missing)")
    transcript = Transcript.model_validate_json(built.transcript.read_text(encoding="utf-8"))

    plan = EditPlan(
        actions=[
            RemoveSilences(),
            RemoveFillers(),
            SetCaptions(enabled=True, granularity="segment"),
            SetAspect(aspect="9:16"),
        ]
    )
    edl = compile_plan(plan, initial_edl(transcript), transcript)

    out = tmp_path / "out.mp4"
    progress = []
    export(edl, transcript, str(built.video), out, progress_cb=progress.append)

    assert out.exists() and out.stat().st_size > 0
    # measurably shorter than the source
    assert probe_duration(out) < transcript.duration - 1.0
    # reframed to vertical 1080x1920
    assert video_dimensions(out) == (1080, 1920)
    # progress was reported and reached completion
    assert progress and progress[-1] == 1.0
