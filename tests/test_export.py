"""Export renderer: filtergraph construction (unit) + real ffmpeg render."""

from __future__ import annotations

import shutil

import pytest

from aicut.edl import compile_plan, initial_edl
from aicut.ffmpeg_export import build_command, build_filtergraph, export
from aicut.media import probe_duration, video_dimensions
from aicut.models import (
    EditPlan,
    RemoveFillers,
    RemoveSilences,
    SetAspect,
    SetCaptions,
    Transcript,
)
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
