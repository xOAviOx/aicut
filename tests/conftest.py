"""Shared pytest fixtures: synthetic transcripts and an isolated data home."""

from __future__ import annotations

import pytest

from aicut.models import Segment, Transcript, Word


def make_words(text: str, start: float, per: float = 0.3, gap: float = 0.0) -> list[Word]:
    """Lay words out sequentially from ``start``, each ``per`` s with ``gap`` between."""
    words = []
    t = start
    for tok in text.split():
        words.append(Word(w=tok, start=round(t, 3), end=round(t + per, 3)))
        t += per + gap
    return words


def segment_from(sid: int, text: str, start: float, per: float = 0.3, gap: float = 0.0) -> Segment:
    words = make_words(text, start, per, gap)
    return Segment(
        id=sid,
        start=words[0].start if words else start,
        end=words[-1].end if words else start,
        text=text,
        words=words,
    )


@pytest.fixture
def simple_transcript() -> Transcript:
    """Three topics, some fillers, and a deliberate silence gap.

    Timeline (approx):
      seg0  0.0–2.7   intro w/ 'um'      (pricing-ish)
      GAP   2.7–4.0   silence (1.3 s)
      seg1  4.0–7.0   pricing 'you know'
      seg2  7.0–9.7   features
      seg3  9.7–12.4  support 'basically'
    """
    segs = [
        segment_from(0, "um so welcome to the demo", 0.0),
        segment_from(1, "you know our pricing starts at ten dollars", 4.0),
        segment_from(2, "the main feature is fast video editing", 7.0),
        segment_from(3, "basically support is available all week", 9.7),
    ]
    duration = 13.0
    return Transcript(source="test.mp4", duration=duration, language="en", segments=segs)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point AICUT_HOME at a temp dir and reset the settings cache."""
    monkeypatch.setenv("AICUT_HOME", str(tmp_path))
    import aicut.config as config

    config.get_settings.cache_clear()
    import aicut.project as project

    project._store = None
    yield tmp_path
    config.get_settings.cache_clear()
    project._store = None
