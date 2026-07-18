"""EDL compiler: every action path, filler matching, topic resolution."""

from __future__ import annotations

import pytest

from aicut import edl
from aicut import rangemath as rm
from aicut.models import (
    Anchor,
    CutRanges,
    CutWords,
    EditPlan,
    FilterTopic,
    KeepRanges,
    RemoveFillers,
    RemoveSilences,
    RestoreWords,
    Segment,
    SetAspect,
    SetCaptions,
    Transcript,
    Trim,
    Word,
    WordRef,
)
from conftest import segment_from


def base_edl(t: Transcript):
    return edl.initial_edl(t)


class TestInitial:
    def test_keeps_everything(self, simple_transcript):
        e = base_edl(simple_transcript)
        assert e.keep == [(0.0, simple_transcript.duration)]
        assert e.aspect == "source"
        assert e.captions.enabled is False


class TestRemoveSilences:
    def test_removes_the_gap(self, simple_transcript):
        # gap between seg0 (ends ~1.5) and seg1 (starts 4.0) is > 0.6s
        plan = EditPlan(actions=[RemoveSilences(min_gap_s=0.6, pad_s=0.08)])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        # total kept should be less than full duration
        assert e.output_duration < simple_transcript.duration
        # the middle of the gap (say 3.0) must not be kept
        assert not rm.contains(e.keep, 3.0)
        # a word inside seg1 must still be kept
        assert rm.contains(e.keep, 4.1)

    def test_no_words_no_change(self):
        t = Transcript(source="x", duration=5, language="en", segments=[])
        plan = EditPlan(actions=[RemoveSilences()])
        e = edl.compile_plan(plan, edl.initial_edl(t), t)
        assert e.keep == [(0.0, 5.0)]


class TestRemoveFillers:
    def test_cuts_um_and_phrase(self, simple_transcript):
        plan = EditPlan(actions=[RemoveFillers()])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        # 'um' is the first word of seg0 (0.0-0.3) -> cut
        assert not rm.contains(e.keep, 0.15)
        # 'you know' phrase at start of seg1 (4.0-4.6) -> cut
        assert not rm.contains(e.keep, 4.3)

    def test_punctuation_and_case_insensitive(self):
        seg = Segment(
            id=0,
            start=0,
            end=2,
            text="Um, hello Uh.",
            words=[
                Word(w="Um,", start=0.0, end=0.4),
                Word(w="hello", start=0.4, end=0.9),
                Word(w="Uh.", start=0.9, end=1.3),
            ],
        )
        t = Transcript(source="x", duration=2, language="en", segments=[seg])
        e = edl.compile_plan(EditPlan(actions=[RemoveFillers()]), edl.initial_edl(t), t)
        assert not rm.contains(e.keep, 0.2)  # Um,
        assert rm.contains(e.keep, 0.6)  # hello kept
        assert not rm.contains(e.keep, 1.1)  # Uh.

    def test_custom_filler_list(self):
        seg = segment_from(0, "so anyway the thing", 0.0)
        t = Transcript(source="x", duration=2, language="en", segments=[seg])
        e = edl.compile_plan(
            EditPlan(actions=[RemoveFillers(words=["anyway"])]), edl.initial_edl(t), t
        )
        # 'anyway' is the 2nd word (0.3-0.6)
        assert not rm.contains(e.keep, 0.45)
        assert rm.contains(e.keep, 0.15)  # 'so' kept


class TestTrim:
    def test_before_segment(self, simple_transcript):
        plan = EditPlan(
            actions=[Trim(mode="before", anchor=Anchor(kind="segment_id", value=2))]
        )
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        seg2 = simple_transcript.segment_by_id(2)
        assert not rm.contains(e.keep, seg2.start - 0.5)
        assert rm.contains(e.keep, seg2.start + 0.1)

    def test_after_time(self, simple_transcript):
        plan = EditPlan(actions=[Trim(mode="after", anchor=Anchor(kind="time", value=7.0))])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        assert rm.contains(e.keep, 6.5)
        assert not rm.contains(e.keep, 8.0)

    def test_bad_segment_raises(self, simple_transcript):
        plan = EditPlan(
            actions=[Trim(mode="before", anchor=Anchor(kind="segment_id", value=999))]
        )
        with pytest.raises(edl.CompileError):
            edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)


class TestCutKeepRanges:
    def test_cut_ranges_clamped(self, simple_transcript):
        plan = EditPlan(actions=[CutRanges(ranges=[(-5, 2), (100, 200)])])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        assert not rm.contains(e.keep, 1.0)  # 0-2 cut
        assert rm.contains(e.keep, 5.0)

    def test_keep_ranges_intersect(self, simple_transcript):
        plan = EditPlan(actions=[KeepRanges(ranges=[(4, 7)])])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        assert rm.contains(e.keep, 5.0)
        assert not rm.contains(e.keep, 1.0)
        assert not rm.contains(e.keep, 9.0)


class TestCutRestoreWords:
    def test_cut_then_restore_is_inverse(self, simple_transcript):
        ref = WordRef(segment_id=1, word_index_start=2, word_index_end=3)
        cut = EditPlan(actions=[CutWords(word_refs=[ref])])
        e1 = edl.compile_plan(cut, base_edl(simple_transcript), simple_transcript)
        seg1 = simple_transcript.segment_by_id(1)
        mid = (seg1.words[2].start + seg1.words[3].end) / 2
        assert not rm.contains(e1.keep, mid)

        restore = EditPlan(actions=[RestoreWords(word_refs=[ref])])
        e2 = edl.compile_plan(restore, e1, simple_transcript)
        assert rm.contains(e2.keep, mid)

    def test_reversed_indices_normalized(self, simple_transcript):
        ref = WordRef(segment_id=1, word_index_start=3, word_index_end=2)
        e = edl.compile_plan(
            EditPlan(actions=[CutWords(word_refs=[ref])]),
            base_edl(simple_transcript),
            simple_transcript,
        )
        seg1 = simple_transcript.segment_by_id(1)
        mid = (seg1.words[2].start + seg1.words[3].end) / 2
        assert not rm.contains(e.keep, mid)

    def test_unknown_segment_raises(self, simple_transcript):
        ref = WordRef(segment_id=42, word_index_start=0, word_index_end=1)
        with pytest.raises(edl.CompileError):
            edl.compile_plan(
                EditPlan(actions=[CutWords(word_refs=[ref])]),
                base_edl(simple_transcript),
                simple_transcript,
            )


class TestFilterTopic:
    def test_keep_with_explicit_ids(self, simple_transcript):
        plan = EditPlan(actions=[FilterTopic(mode="keep", query="pricing", segment_ids=[1])])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        seg1 = simple_transcript.segment_by_id(1)
        assert rm.contains(e.keep, (seg1.start + seg1.end) / 2)
        # seg2 (features) should be gone
        seg2 = simple_transcript.segment_by_id(2)
        assert not rm.contains(e.keep, (seg2.start + seg2.end) / 2)

    def test_remove_with_explicit_ids(self, simple_transcript):
        plan = EditPlan(actions=[FilterTopic(mode="remove", query="x", segment_ids=[2])])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        seg2 = simple_transcript.segment_by_id(2)
        assert not rm.contains(e.keep, (seg2.start + seg2.end) / 2)

    def test_uses_resolver_when_no_ids(self, simple_transcript):
        calls = {}

        def resolver(query, transcript, mode):
            calls["q"] = query
            return [3]

        plan = EditPlan(actions=[FilterTopic(mode="keep", query="support")])
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript, resolver)
        assert calls["q"] == "support"
        seg3 = simple_transcript.segment_by_id(3)
        assert rm.contains(e.keep, (seg3.start + seg3.end) / 2)

    def test_no_resolver_no_ids_raises(self, simple_transcript):
        plan = EditPlan(actions=[FilterTopic(mode="keep", query="support")])
        with pytest.raises(edl.CompileError):
            edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)

    def test_invalid_explicit_ids_fall_back_to_resolver(self, simple_transcript):
        plan = EditPlan(
            actions=[FilterTopic(mode="keep", query="q", segment_ids=[999])]
        )
        e = edl.compile_plan(
            plan, base_edl(simple_transcript), simple_transcript, lambda q, t, m: [0]
        )
        assert rm.contains(e.keep, 0.1)


class TestSettings:
    def test_set_captions_and_aspect(self, simple_transcript):
        plan = EditPlan(
            actions=[
                SetCaptions(enabled=True, granularity="word"),
                SetAspect(aspect="9:16"),
            ]
        )
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        assert e.captions.enabled is True
        assert e.captions.granularity == "word"
        assert e.aspect == "9:16"
        # keep unchanged
        assert e.keep == [(0.0, simple_transcript.duration)]


class TestComposition:
    def test_actions_compose_in_order(self, simple_transcript):
        plan = EditPlan(
            actions=[
                Trim(mode="before", anchor=Anchor(kind="time", value=4.0)),
                RemoveFillers(),
                SetCaptions(enabled=True),
            ]
        )
        e = edl.compile_plan(plan, base_edl(simple_transcript), simple_transcript)
        assert not rm.contains(e.keep, 1.0)  # trimmed intro
        assert not rm.contains(e.keep, 4.3)  # 'you know' filler cut
        assert e.captions.enabled is True

    def test_summarize_delta_format(self, simple_transcript):
        before = base_edl(simple_transcript)
        after = edl.compile_plan(
            EditPlan(actions=[Trim(mode="before", anchor=Anchor(kind="time", value=4.0))]),
            before,
            simple_transcript,
        )
        s = edl.summarize_delta(before, after)
        assert "→" in s and "%" in s
