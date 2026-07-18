"""LLM planning layer: prompt building, validation, retry, and topic selection.

The Ollama HTTP client is never hit — a fake ``chat_fn`` is injected.
"""

from __future__ import annotations

import pytest

from aicut.embeddings import select_segment_indices
from aicut.llm import (
    LLMUnavailable,
    PlanError,
    Planner,
    compact_transcript,
    state_summary,
)
from aicut.models import RemoveSilences, SetCaptions, Trim

VALID_PLAN = (
    '{"actions": [{"type": "remove_silences", "min_gap_s": 0.6}, '
    '{"type": "set_captions", "enabled": true, "granularity": "segment"}], '
    '"notes": "tightened pauses and turned captions on"}'
)


def test_plan_success(simple_transcript):
    planner = Planner(chat_fn=lambda messages: VALID_PLAN)
    plan = planner.plan("cut silences and add captions", simple_transcript, "current cut: 0:13 → 0:13")
    assert len(plan.actions) == 2
    assert isinstance(plan.actions[0], RemoveSilences)
    assert isinstance(plan.actions[1], SetCaptions)
    assert "captions" in plan.notes


def test_plan_strips_markdown_fences(simple_transcript):
    fenced = "```json\n" + VALID_PLAN + "\n```"
    planner = Planner(chat_fn=lambda m: fenced)
    plan = planner.plan("x", simple_transcript, "s")
    assert len(plan.actions) == 2


def test_plan_retries_once_on_bad_json(simple_transcript):
    calls = {"n": 0}

    def chat(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return VALID_PLAN

    planner = Planner(chat_fn=chat)
    plan = planner.plan("x", simple_transcript, "s")
    assert calls["n"] == 2
    assert len(plan.actions) == 2


def test_plan_retry_feeds_error_and_second_failure_raises(simple_transcript):
    seen_retry = {"v": False}

    def chat(messages):
        if len(messages) > 6:  # retry adds the assistant+user error turns
            seen_retry["v"] = True
        return "{ still broken"

    planner = Planner(chat_fn=chat)
    with pytest.raises(PlanError) as ei:
        planner.plan("x", simple_transcript, "s")
    assert seen_retry["v"] is True
    assert ei.value.detail  # carries the validation detail


def test_plan_invalid_action_type_retries_then_raises(simple_transcript):
    def chat(messages):
        return '{"actions": [{"type": "teleport"}], "notes": "nope"}'

    planner = Planner(chat_fn=chat)
    with pytest.raises(PlanError):
        planner.plan("x", simple_transcript, "s")


def test_llm_unavailable_propagates(simple_transcript):
    def chat(messages):
        raise LLMUnavailable("ollama down")

    planner = Planner(chat_fn=chat)
    with pytest.raises(LLMUnavailable):
        planner.plan("x", simple_transcript, "s")


def test_valid_trim_plan_by_segment_id(simple_transcript):
    raw = (
        '{"actions": [{"type": "trim", "mode": "before", '
        '"anchor": {"kind": "segment_id", "value": 2}}], "notes": "trim intro"}'
    )
    planner = Planner(chat_fn=lambda m: raw)
    plan = planner.plan("trim intro", simple_transcript, "s")
    assert isinstance(plan.actions[0], Trim)


class TestPromptHelpers:
    def test_compact_transcript_format(self, simple_transcript):
        txt = compact_transcript(simple_transcript)
        assert txt.startswith("[0] 0:00")
        assert "[1]" in txt

    def test_compact_transcript_truncates_when_huge(self):
        from aicut.models import Segment, Transcript, Word

        words = [Word(w=f"word{i}", start=i * 0.3, end=i * 0.3 + 0.3) for i in range(60)]
        seg = Segment(id=0, start=0, end=18, text=" ".join(w.w for w in words), words=words)
        t = Transcript(source="x", duration=18, language="en", segments=[seg] * 1)
        # force truncation with a tiny budget
        txt = compact_transcript(t, max_chars=10)
        assert "…" in txt

    def test_state_summary(self):
        assert state_summary(872, 667) == "current cut: 14:32 → 11:07"


class TestSelectSegments:
    def test_selects_above_threshold(self):
        # best 0.9; threshold max(0.28, 0.55*0.9=0.495)=0.495 -> keep >=0.495
        assert select_segment_indices([0.9, 0.5, 0.1, 0.6]) == [0, 1, 3]

    def test_abs_floor_applies_when_scores_low(self):
        # best 0.4; rel 0.55*0.4=0.22 < abs floor 0.28 -> threshold 0.28
        assert select_segment_indices([0.4, 0.3, 0.2]) == [0, 1]

    def test_empty(self):
        assert select_segment_indices([]) == []

    def test_all_low(self):
        assert select_segment_indices([0.1, 0.05]) == []
