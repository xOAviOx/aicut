"""Speaker diarization: pure engine + filter_speaker compiler + real clusterer."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from aicut import rangemath as rm
from aicut.diarize import assign_speakers, diarize_local, speakers_in
from aicut.edl import CompileError, compile_plan, initial_edl
from aicut.models import EditPlan, FilterSpeaker, Transcript
from conftest import segment_from


def _labeled(*specs) -> Transcript:
    """Build a transcript from (id, text, start, speaker) tuples."""
    segs = []
    for sid, text, start, speaker in specs:
        seg = segment_from(sid, text, start)
        seg.speaker = speaker
        segs.append(seg)
    return Transcript(source="x", duration=segs[-1].end + 1.0, language="en", segments=segs)


class TestPureEngine:
    def test_assign_speakers_by_overlap(self):
        segs = [segment_from(0, "hello there friend", 0.0), segment_from(1, "how are you", 4.0)]
        t = Transcript(source="x", duration=6.0, language="en", segments=segs)
        turns = [(0.0, 2.0, "Speaker 1"), (3.5, 6.0, "Speaker 2")]
        out = assign_speakers(t, turns)
        assert out.segments[0].speaker == "Speaker 1"
        assert out.segments[1].speaker == "Speaker 2"
        # original transcript is untouched (assign returns a copy)
        assert t.segments[0].speaker is None

    def test_no_overlap_leaves_speaker_none(self):
        segs = [segment_from(0, "way over here", 10.0)]
        t = Transcript(source="x", duration=13.0, language="en", segments=segs)
        out = assign_speakers(t, [(0.0, 2.0, "Speaker 1")])
        assert out.segments[0].speaker is None

    def test_speakers_in_order_of_appearance(self):
        t = _labeled(
            (0, "a b", 0.0, "Speaker 2"),
            (1, "c d", 2.0, "Speaker 1"),
            (2, "e f", 4.0, "Speaker 2"),
        )
        assert speakers_in(t) == ["Speaker 2", "Speaker 1"]


class TestFilterSpeaker:
    def _three(self) -> Transcript:
        return _labeled(
            (0, "alice intro here", 0.0, "Speaker 1"),
            (1, "bob chimes in", 2.0, "Speaker 2"),
            (2, "alice wraps up", 4.0, "Speaker 1"),
        )

    def test_keep_only_one_speaker(self):
        t = self._three()
        e = compile_plan(
            EditPlan(actions=[FilterSpeaker(mode="keep", speaker="Speaker 1")]), initial_edl(t), t
        )
        mid = lambda s: (s.start + s.end) / 2  # noqa: E731
        assert rm.contains(e.keep, mid(t.segments[0]))       # alice kept
        assert not rm.contains(e.keep, mid(t.segments[1]))   # bob dropped
        assert rm.contains(e.keep, mid(t.segments[2]))       # alice kept

    def test_remove_one_speaker(self):
        t = self._three()
        e = compile_plan(
            EditPlan(actions=[FilterSpeaker(mode="remove", speaker="Speaker 2")]), initial_edl(t), t
        )
        assert not rm.contains(e.keep, (t.segments[1].start + t.segments[1].end) / 2)
        assert rm.contains(e.keep, (t.segments[0].start + t.segments[0].end) / 2)

    def test_unknown_speaker_raises(self):
        t = self._three()
        with pytest.raises(CompileError):
            compile_plan(
                EditPlan(actions=[FilterSpeaker(mode="keep", speaker="Nobody")]), initial_edl(t), t
            )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_local_diarizer_separates_two_voices(tmp_path):
    wav = tmp_path / "two.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=1600:duration=3",
            "-filter_complex", "[0][1]concat=n=2:v=0:a=1[a]", "-map", "[a]",
            "-ar", "16000", "-ac", "1", str(wav),
        ],
        check=True,
        capture_output=True,
    )
    turns = diarize_local(str(wav), num_speakers=2)
    assert turns, "expected diarization turns"
    first = {lab for s, e, lab in turns if e <= 3.0}
    second = {lab for s, e, lab in turns if s >= 3.0}
    # each half is one consistent speaker, and the two halves differ
    assert len(first) == 1 and len(second) == 1 and first != second


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_default_finds_two_voices(tmp_path):
    wav = tmp_path / "two.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=1600:duration=3",
            "-filter_complex", "[0][1]concat=n=2:v=0:a=1[a]", "-map", "[a]",
            "-ar", "16000", "-ac", "1", str(wav),
        ],
        check=True,
        capture_output=True,
    )
    # num_speakers=None -> default of 2 splits two clearly-distinct voices
    turns = diarize_local(str(wav))
    assert turns
    assert len({lab for _, _, lab in turns}) == 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_uniform_audio_is_single_speaker(tmp_path):
    wav = tmp_path / "one.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
            "-ar", "16000", "-ac", "1", str(wav),
        ],
        check=True,
        capture_output=True,
    )
    # near-constant audio (a held tone) collapses to one speaker, not a phantom two
    turns = diarize_local(str(wav))
    assert turns
    assert len({lab for _, _, lab in turns}) == 1
