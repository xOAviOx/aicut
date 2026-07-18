"""Pydantic contract validation: the discriminated Action union + EditPlan."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aicut.models import (
    CutWords,
    EditPlan,
    RemoveSilences,
    Trim,
)


def test_plan_parses_mixed_actions():
    data = {
        "actions": [
            {"type": "trim", "mode": "before", "anchor": {"kind": "segment_id", "value": 7}},
            {"type": "remove_silences", "min_gap_s": 0.6},
            {"type": "set_captions", "enabled": True, "granularity": "segment"},
        ],
        "notes": "demo starts at 7",
    }
    plan = EditPlan.model_validate(data)
    assert len(plan.actions) == 3
    assert isinstance(plan.actions[0], Trim)
    assert isinstance(plan.actions[1], RemoveSilences)
    assert plan.notes.startswith("demo")


def test_defaults_applied():
    rs = RemoveSilences()
    assert rs.min_gap_s == 0.6
    assert rs.pad_s == 0.08


def test_unknown_action_type_rejected():
    with pytest.raises(ValidationError):
        EditPlan.model_validate({"actions": [{"type": "teleport"}]})


def test_missing_required_field_rejected():
    # trim requires mode + anchor
    with pytest.raises(ValidationError):
        EditPlan.model_validate({"actions": [{"type": "trim"}]})


def test_cut_words_roundtrip():
    cw = CutWords(word_refs=[{"segment_id": 1, "word_index_start": 0, "word_index_end": 3}])
    assert cw.word_refs[0].segment_id == 1
    dumped = cw.model_dump()
    assert dumped["type"] == "cut_words"


def test_empty_plan_valid():
    plan = EditPlan.model_validate({"actions": [], "notes": ""})
    assert plan.actions == []


def test_malformed_json_raises():
    with pytest.raises(ValidationError):
        EditPlan.model_validate({"actions": [{"type": "filter_topic", "mode": "sideways"}]})
