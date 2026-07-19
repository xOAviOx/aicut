"""Tests for the added features: tighten, retake removal, waveform peaks."""

from __future__ import annotations

from array import array

from aicut import edl
from aicut import rangemath as rm
from aicut.edl import retake_similarity
from aicut.models import (
    EditPlan,
    RemoveRetakes,
    Segment,
    Tighten,
    Transcript,
    Word,
)
from aicut.waveform import reduce_to_peaks
from conftest import segment_from


def base_edl(t: Transcript):
    return edl.initial_edl(t)


class TestTighten:
    def _spaced_transcript(self) -> Transcript:
        # Two words per segment with a big 1.0s intra-gap we want capped.
        words = [
            Word(w="hello", start=0.0, end=0.4),
            Word(w="there", start=1.4, end=1.8),  # 1.0s pause before this word
        ]
        seg = Segment(id=0, start=0.0, end=1.8, text="hello there", words=words)
        return Transcript(source="x", duration=2.5, language="en", segments=[seg])

    def test_caps_intra_sentence_gap(self):
        t = self._spaced_transcript()
        e = edl.compile_plan(EditPlan(actions=[Tighten(max_gap_s=0.35)]), base_edl(t), t)
        # the middle of the long pause must be cut
        assert not rm.contains(e.keep, 0.9)
        # both words survive
        assert rm.contains(e.keep, 0.2)
        assert rm.contains(e.keep, 1.6)
        # remaining gap between the words is capped near max_gap_s
        assert e.output_duration < t.duration

    def test_short_gaps_untouched(self):
        # gap of 0.0 between words -> nothing to tighten
        seg = segment_from(0, "one two three four", 0.0, per=0.3, gap=0.0)
        t = Transcript(source="x", duration=seg.end + 0.1, language="en", segments=[seg])
        e = edl.compile_plan(EditPlan(actions=[Tighten(max_gap_s=0.35)]), base_edl(t), t)
        assert e.keep == rm.normalize(base_edl(t).keep)


class TestRetakeSimilarity:
    def test_identical_is_one(self):
        toks = ["let", "me", "show", "you", "the", "demo"]
        assert retake_similarity(toks, toks) == 1.0

    def test_false_start_prefix_scores_high(self):
        short = ["so", "the", "thing", "is"]
        long = ["so", "the", "thing", "is", "really", "important", "here"]
        assert retake_similarity(short, long) >= 0.8

    def test_unrelated_scores_low(self):
        a = ["pricing", "starts", "at", "ten", "dollars"]
        b = ["the", "weather", "is", "nice", "today"]
        assert retake_similarity(a, b) < 0.5


class TestRemoveRetakes:
    def test_keeps_last_take(self):
        segs = [
            segment_from(0, "let me show you the pricing", 0.0),
            segment_from(1, "let me show you the pricing", 3.0),  # retake
            segment_from(2, "anyway thanks for watching", 6.0),
        ]
        t = Transcript(source="x", duration=segs[-1].end + 0.5, language="en", segments=segs)
        e = edl.compile_plan(EditPlan(actions=[RemoveRetakes()]), base_edl(t), t)
        # the first (abandoned) take is cut...
        assert not rm.contains(e.keep, (segs[0].start + segs[0].end) / 2)
        # ...the retake survives...
        assert rm.contains(e.keep, (segs[1].start + segs[1].end) / 2)
        # ...and the unrelated closing line survives.
        assert rm.contains(e.keep, (segs[2].start + segs[2].end) / 2)

    def test_chain_collapses_to_final(self):
        segs = [
            segment_from(0, "the api is really fast", 0.0),
            segment_from(1, "the api is really fast", 3.0),
            segment_from(2, "the api is really fast", 6.0),
        ]
        t = Transcript(source="x", duration=segs[-1].end + 0.5, language="en", segments=segs)
        e = edl.compile_plan(EditPlan(actions=[RemoveRetakes()]), base_edl(t), t)
        assert not rm.contains(e.keep, (segs[0].start + segs[0].end) / 2)
        assert not rm.contains(e.keep, (segs[1].start + segs[1].end) / 2)
        assert rm.contains(e.keep, (segs[2].start + segs[2].end) / 2)

    def test_no_duplicates_no_change(self, simple_transcript):
        e = edl.compile_plan(EditPlan(actions=[RemoveRetakes()]), base_edl(simple_transcript), simple_transcript)
        assert e.keep == rm.normalize(base_edl(simple_transcript).keep)


class TestWaveformPeaks:
    def test_empty_samples(self):
        assert reduce_to_peaks(array("h"), 10) == []

    def test_normalizes_to_unit_max(self):
        samples = array("h", [0, 100, -200, 50, 400, -400, 10, 0])
        peaks = reduce_to_peaks(samples, 4)
        assert len(peaks) == 4
        assert max(peaks) == 1.0
        assert all(0.0 <= p <= 1.0 for p in peaks)

    def test_bucket_count_bounded(self):
        samples = array("h", list(range(-500, 500)))
        peaks = reduce_to_peaks(samples, 50)
        assert len(peaks) <= 50
