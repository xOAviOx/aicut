"""ASS caption builder: golden file + timeline-remap correctness."""

from __future__ import annotations

from pathlib import Path

from aicut.ass_builder import build_ass
from aicut.models import CaptionSettings, CompiledEDL, Segment, Transcript, Word

GOLDEN = Path(__file__).parent / "golden" / "captions_segment.ass"


def _sample():
    segs = [
        Segment(
            id=0,
            start=0,
            end=1.2,
            text="hello there world",
            words=[
                Word(w="hello", start=0, end=0.4),
                Word(w="there", start=0.4, end=0.8),
                Word(w="world", start=0.8, end=1.2),
            ],
        ),
        Segment(
            id=1,
            start=2.0,
            end=3.0,
            text="cut kept",
            words=[Word(w="cut", start=2.0, end=2.4), Word(w="kept", start=2.6, end=3.0)],
        ),
    ]
    t = Transcript(source="x", duration=3.0, language="en", segments=segs)
    edl = CompiledEDL(
        keep=[(0.0, 1.2), (2.5, 3.0)],
        captions=CaptionSettings(enabled=True, granularity="segment", font="Arial", font_size=48),
        aspect="9:16",
        duration=3.0,
    )
    return edl, t


def test_ass_matches_golden():
    edl, t = _sample()
    out = build_ass(edl, t, play_res=(1080, 1920))
    expected = GOLDEN.read_text(encoding="utf-8")
    assert out.strip() == expected.strip()


def test_caption_times_on_output_timeline():
    edl, t = _sample()
    out = build_ass(edl, t, play_res=(1080, 1920))
    # the 'kept' word (source 2.6-3.0) lands at output 1.30-1.70 after the cut
    assert "0:00:01.30,0:00:01.70,Default,,0,0,0,,kept" in out
    # the cut word 'cut' must NOT appear as its own event
    assert ",,cut\n" not in out


def test_word_granularity_emits_per_word():
    edl, t = _sample()
    edl.captions.granularity = "word"
    out = build_ass(edl, t)
    # three surviving words in seg0 + one in seg1 = 4 dialogue lines
    assert out.count("Dialogue:") == 4


def test_empty_when_all_cut():
    edl, t = _sample()
    edl.keep = [(10.0, 11.0)]  # nothing overlaps the transcript
    out = build_ass(edl, t)
    assert out.count("Dialogue:") == 0
