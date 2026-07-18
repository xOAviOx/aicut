"""Pydantic v2 data contracts for the aicut engine.

These types are the single source of truth shared by transcription, the EDL
compiler, the LLM planner, the API, and (mirrored by hand) the frontend.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


class Word(BaseModel):
    w: str
    start: float
    end: float


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Transcript(BaseModel):
    source: str
    duration: float
    language: str
    segments: list[Segment] = Field(default_factory=list)

    def segment_by_id(self, sid: int) -> Segment | None:
        for s in self.segments:
            if s.id == sid:
                return s
        return None


# ---------------------------------------------------------------------------
# Settings carried on the EDL / project
# ---------------------------------------------------------------------------

Aspect = Literal["source", "9:16", "1:1"]
CaptionGranularity = Literal["segment", "word"]


class CaptionSettings(BaseModel):
    enabled: bool = False
    granularity: CaptionGranularity = "segment"
    font: str = "Arial"
    font_size: int = 48
    max_lines: int = 2


# ---------------------------------------------------------------------------
# Actions (discriminated union on ``type``)
# ---------------------------------------------------------------------------

DEFAULT_FILLERS: list[str] = [
    # English
    "um",
    "uh",
    "uhh",
    "erm",
    "er",
    "ah",
    "hmm",
    "mmm",
    "like",  # only matched standalone (see edl.py)
    "you know",
    "i mean",
    "sort of",
    "kind of",
    "basically",
    "literally",
    "actually",
    # Hinglish
    "matlab",
    "yaar",
    "haan",
    "achha",
]


class Anchor(BaseModel):
    kind: Literal["segment_id", "time"]
    value: float  # segment id (int-valued) or time in seconds


class WordRef(BaseModel):
    segment_id: int
    word_index_start: int
    word_index_end: int  # inclusive


class RemoveSilences(BaseModel):
    type: Literal["remove_silences"] = "remove_silences"
    min_gap_s: float = 0.6
    pad_s: float = 0.08


class RemoveFillers(BaseModel):
    type: Literal["remove_fillers"] = "remove_fillers"
    words: list[str] = Field(default_factory=lambda: list(DEFAULT_FILLERS))


class Trim(BaseModel):
    type: Literal["trim"] = "trim"
    mode: Literal["before", "after"]
    anchor: Anchor


class FilterTopic(BaseModel):
    type: Literal["filter_topic"] = "filter_topic"
    mode: Literal["keep", "remove"]
    query: str
    segment_ids: list[int] | None = None


class CutRanges(BaseModel):
    type: Literal["cut_ranges"] = "cut_ranges"
    ranges: list[tuple[float, float]]


class KeepRanges(BaseModel):
    type: Literal["keep_ranges"] = "keep_ranges"
    ranges: list[tuple[float, float]]


class CutWords(BaseModel):
    type: Literal["cut_words"] = "cut_words"
    word_refs: list[WordRef]


class RestoreWords(BaseModel):
    """Manual inverse of :class:`CutWords` — re-adds word spans to the keep set."""

    type: Literal["restore_words"] = "restore_words"
    word_refs: list[WordRef]


class SetCaptions(BaseModel):
    type: Literal["set_captions"] = "set_captions"
    enabled: bool = True
    granularity: CaptionGranularity = "segment"
    font: str | None = None
    font_size: int | None = None


class SetAspect(BaseModel):
    type: Literal["set_aspect"] = "set_aspect"
    aspect: Aspect


Action = Annotated[
    RemoveSilences
    | RemoveFillers
    | Trim
    | FilterTopic
    | CutRanges
    | KeepRanges
    | CutWords
    | RestoreWords
    | SetCaptions
    | SetAspect,
    Field(discriminator="type"),
]


class EditPlan(BaseModel):
    """What the LLM (or a one-click button) emits."""

    actions: list[Action] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Compiled EDL — what preview and export consume
# ---------------------------------------------------------------------------


class CompiledEDL(BaseModel):
    keep: list[tuple[float, float]] = Field(default_factory=list)
    captions: CaptionSettings = Field(default_factory=CaptionSettings)
    aspect: Aspect = "source"
    duration: float = 0.0  # source duration (for remap / display)

    @property
    def output_duration(self) -> float:
        return sum(e - s for s, e in self.keep)


# ---------------------------------------------------------------------------
# Project & revisions
# ---------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Revision(BaseModel):
    id: str = Field(default_factory=_new_id)
    label: str = ""
    notes: str = ""
    edl: CompiledEDL
    created_at: float = Field(default_factory=_now)


TranscriptStatus = Literal["pending", "running", "ready", "error"]


class ProjectSettings(BaseModel):
    captions: CaptionSettings = Field(default_factory=CaptionSettings)
    aspect: Aspect = "source"


class Project(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str = ""
    source_path: str
    media_url: str = ""
    thumbnail: str | None = None
    duration: float = 0.0
    transcript_status: TranscriptStatus = "pending"
    transcript_error: str | None = None
    transcript_progress: float = 0.0
    language: str | None = None
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    revisions: list[Revision] = Field(default_factory=list)
    head_revision_id: str | None = None
    created_at: float = Field(default_factory=_now)

    def head(self) -> Revision | None:
        if self.head_revision_id is None:
            return None
        for r in self.revisions:
            if r.id == self.head_revision_id:
                return r
        return None

    def revision_index(self, rid: str) -> int:
        for i, r in enumerate(self.revisions):
            if r.id == rid:
                return i
        return -1
