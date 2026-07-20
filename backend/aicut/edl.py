"""EDL compiler: resolve typed :class:`Action`s into keep-ranges.

This is the deterministic heart of aicut. The LLM never invents timestamps —
it emits actions referencing transcript segment/word ids, and this module
resolves them against the *real* transcript, validating and clamping every
range. The manual UI edits (``cut_words`` / ``restore_words`` / ``cut_ranges``)
flow through the exact same engine. One engine, two input methods.

Each action is applied against the *current* keep set (from the head revision),
so edits compose naturally and each produces a new revision snapshot.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher

from . import rangemath as rm
from .models import (
    DEFAULT_FILLERS,
    Action,
    CaptionSettings,
    CompiledEDL,
    CutRanges,
    CutWords,
    EditPlan,
    FilterTopic,
    FindHighlights,
    KeepRanges,
    RemoveFillers,
    RemoveRetakes,
    RemoveSilences,
    RestoreWords,
    Segment,
    SetAspect,
    SetCaptions,
    SetTransition,
    Tighten,
    Transcript,
    TransitionSettings,
    Trim,
    WordRef,
)

# An embedder resolves a topic query to a list of matching segment ids.
# Signature: (query, transcript, mode) -> list[segment_id]. Injected so the
# engine stays pure and testable; the real one lives in embeddings.py.
TopicResolver = Callable[[str, Transcript, str], list[int]]

# Optional semantic similarity of two texts in [0, 1], used to catch *paraphrased*
# retakes that lexical matching misses. Injected; None = lexical-only.
RetakeScorer = Callable[[str, str], float]


class CompileError(ValueError):
    """Raised when an action cannot be resolved against the transcript."""


_PUNCT = re.compile(r"[^\w']", flags=re.UNICODE)


def _norm_token(w: str) -> str:
    return _PUNCT.sub("", w.strip().lower())


def initial_edl(transcript: Transcript, settings=None) -> CompiledEDL:
    """The starting EDL after transcription: keep everything."""
    from .models import ProjectSettings

    settings = settings or ProjectSettings()
    return CompiledEDL(
        keep=[(0.0, transcript.duration)],
        captions=settings.captions.model_copy(deep=True),
        aspect=settings.aspect,
        duration=transcript.duration,
    )


# ---------------------------------------------------------------------------
# Per-action resolvers → produce a set of *cut* ranges (or new keep / settings)
# ---------------------------------------------------------------------------


def _silence_cuts(t: Transcript, min_gap_s: float, pad_s: float) -> rm.Ranges:
    """Cut ranges for gaps between words wider than ``min_gap_s``."""
    words = [w for seg in t.segments for w in seg.words if w.end > w.start]
    words.sort(key=lambda w: w.start)
    cuts: rm.Ranges = []
    if not words:
        return cuts
    # leading silence
    if words[0].start > min_gap_s:
        cuts.append((0.0, words[0].start - pad_s))
    for a, b in zip(words, words[1:], strict=False):
        gap = b.start - a.end
        if gap > min_gap_s:
            cuts.append((a.end + pad_s, b.start - pad_s))
    # trailing silence
    if t.duration - words[-1].end > min_gap_s:
        cuts.append((words[-1].end + pad_s, t.duration))
    return rm.clamp(cuts, 0.0, t.duration)


def _filler_cuts(t: Transcript, filler_words: list[str]) -> rm.Ranges:
    """Cut ranges covering filler word occurrences.

    Multi-word phrases ("you know") match greedily across consecutive words.
    ``like`` is only cut when standalone (which it always is here, being a
    single token — the guard exists for future phrase forms like "like like").
    """
    singles = {_norm_token(w) for w in filler_words if " " not in w}
    phrases = [tuple(_norm_token(p) for p in w.split()) for w in filler_words if " " in w]
    cuts: rm.Ranges = []
    for seg in t.segments:
        ws = seg.words
        i = 0
        n = len(ws)
        while i < n:
            matched = False
            # try longest phrases first
            for phrase in sorted(phrases, key=len, reverse=True):
                pl = len(phrase)
                if i + pl <= n:
                    window = tuple(_norm_token(ws[i + k].w) for k in range(pl))
                    if window == phrase:
                        cuts.append((ws[i].start, ws[i + pl - 1].end))
                        i += pl
                        matched = True
                        break
            if matched:
                continue
            if _norm_token(ws[i].w) in singles:
                cuts.append((ws[i].start, ws[i].end))
            i += 1
    return rm.clamp(cuts, 0.0, t.duration)


def _tighten_cuts(t: Transcript, max_gap_s: float, pad_s: float) -> rm.Ranges:
    """Cut ranges that cap *every* inter-word gap to ``max_gap_s``.

    Unlike :func:`_silence_cuts` (which only touches gaps wider than a large
    ``min_gap_s``), this trims the excess out of *all* pauses — including the
    short breaths within a sentence — leaving at most ``max_gap_s`` of each.
    """
    words = [w for seg in t.segments for w in seg.words if w.end > w.start]
    words.sort(key=lambda w: w.start)
    cuts: rm.Ranges = []
    if not words:
        return cuts
    half = max_gap_s / 2.0
    # leading dead air beyond the cap
    if words[0].start > max_gap_s:
        cuts.append((0.0, words[0].start - max_gap_s))
    for a, b in zip(words, words[1:], strict=False):
        gap = b.start - a.end
        if gap > max_gap_s + pad_s:
            cuts.append((a.end + half, b.start - half))
    # trailing dead air beyond the cap
    if t.duration - words[-1].end > max_gap_s:
        cuts.append((words[-1].end + max_gap_s, t.duration))
    return rm.clamp(cuts, 0.0, t.duration)


def _seg_tokens(seg: Segment) -> list[str]:
    """Normalized token list for a segment (word timings preferred over text)."""
    source = [w.w for w in seg.words] if seg.words else seg.text.split()
    return [tok for tok in (_norm_token(w) for w in source) if tok]


def _contiguous_subseq(short: list[str], long: list[str]) -> bool:
    if not short or len(short) > len(long):
        return False
    first = short[0]
    span = len(short)
    for i in range(len(long) - span + 1):
        if long[i] == first and long[i : i + span] == short:
            return True
    return False


def retake_similarity(a: list[str], b: list[str]) -> float:
    """Similarity of two token lists in [0, 1].

    Uses :class:`difflib.SequenceMatcher` for near-verbatim overlap, with a
    containment boost so an abandoned false start (a prefix of the retake) still
    scores as a duplicate.
    """
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 3 and _contiguous_subseq(short, long):
        cover = len(short) / len(long)
        ratio = max(ratio, 0.6 + 0.4 * cover)
    return ratio


def _retake_cuts(
    t: Transcript, similarity: float, scorer: RetakeScorer | None = None
) -> rm.Ranges:
    """Cut earlier attempts of repeated lines, keeping the last take.

    Compares each segment with the next; when they're near-duplicates the
    earlier one is cut up to the start of its retake. Chains (A≈B≈C) collapse
    naturally to just C because each adjacent pair contributes a cut. When a
    semantic ``scorer`` is supplied, the pair score is ``max(lexical, semantic)``
    so *paraphrased* restarts are caught too, not just near-verbatim ones.
    """
    segs = t.segments
    cuts: rm.Ranges = []
    for i in range(len(segs) - 1):
        a = _seg_tokens(segs[i])
        b = _seg_tokens(segs[i + 1])
        if len(a) < 2 or len(b) < 2:
            continue
        score = retake_similarity(a, b)
        if scorer is not None and score < similarity:
            score = max(score, scorer(segs[i].text, segs[i + 1].text))
        if score >= similarity:
            cuts.append((segs[i].start, segs[i + 1].start))
    return rm.clamp(cuts, 0.0, t.duration)


_FILLER_SINGLES = frozenset(_norm_token(w) for w in DEFAULT_FILLERS if " " not in w)


def _highlight_score(seg: Segment) -> float:
    """A deterministic 'keep-worthiness' score for one segment.

    Rewards content (more words), complete thoughts (ends on . ! ?), and
    penalizes filler-heavy or fragmentary lines. No ML — pure text heuristics.
    """
    toks = _seg_tokens(seg)
    n = len(toks)
    if n == 0:
        return 0.0
    filler_n = sum(1 for tk in toks if tk in _FILLER_SINGLES)
    score = float(n) * (1.0 - 0.5 * (filler_n / n))
    if seg.text.strip().endswith((".", "!", "?")):
        score *= 1.15
    if n < 3:  # very short fragments rarely stand alone
        score *= 0.3
    return score


def _highlight_spans(t: Transcript, budget_s: float) -> rm.Ranges:
    """Pick the highest-scoring segments (chronologically ordered) until their
    cumulative duration reaches ``budget_s``. Always returns at least one span
    when the transcript has segments, so it never wipes the clip."""
    segs = [s for s in t.segments if s.end > s.start]
    if not segs or budget_s <= 0:
        return []
    ranked = sorted(segs, key=lambda s: (_highlight_score(s), -s.start), reverse=True)
    chosen: list[Segment] = []
    total = 0.0
    for s in ranked:
        chosen.append(s)
        total += s.end - s.start
        if total >= budget_s:
            break
    chosen.sort(key=lambda s: s.start)
    return rm.clamp([(s.start, s.end) for s in chosen], 0.0, t.duration)


def _resolve_word_refs(t: Transcript, refs: list[WordRef]) -> rm.Ranges:
    spans: rm.Ranges = []
    for ref in refs:
        seg = t.segment_by_id(ref.segment_id)
        if seg is None:
            raise CompileError(f"unknown segment id {ref.segment_id}")
        if not seg.words:
            spans.append((seg.start, seg.end))
            continue
        lo = max(0, min(ref.word_index_start, len(seg.words) - 1))
        hi = max(0, min(ref.word_index_end, len(seg.words) - 1))
        if hi < lo:
            lo, hi = hi, lo
        spans.append((seg.words[lo].start, seg.words[hi].end))
    return rm.clamp(spans, 0.0, t.duration)


def _trim_cut(t: Transcript, action: Trim) -> rm.Ranges:
    if action.anchor.kind == "segment_id":
        seg = t.segment_by_id(int(action.anchor.value))
        if seg is None:
            raise CompileError(f"trim anchor: unknown segment id {action.anchor.value}")
        anchor_t = seg.start if action.mode == "before" else seg.end
    else:
        anchor_t = float(action.anchor.value)
    anchor_t = max(0.0, min(anchor_t, t.duration))
    if action.mode == "before":
        return [(0.0, anchor_t)]
    return [(anchor_t, t.duration)]


# ---------------------------------------------------------------------------
# Apply one action to a running (keep, captions, aspect) state
# ---------------------------------------------------------------------------


def apply_action(
    action: Action,
    keep: rm.Ranges,
    captions: CaptionSettings,
    aspect: str,
    transcript: Transcript,
    topic_resolver: TopicResolver | None = None,
    retake_scorer: RetakeScorer | None = None,
    transition: TransitionSettings | None = None,
) -> tuple[rm.Ranges, CaptionSettings, str, TransitionSettings]:
    dur = transcript.duration
    transition = transition.model_copy(deep=True) if transition else TransitionSettings()

    if isinstance(action, RemoveSilences):
        cuts = _silence_cuts(transcript, action.min_gap_s, action.pad_s)
        keep = rm.subtract(keep, cuts)

    elif isinstance(action, RemoveFillers):
        cuts = _filler_cuts(transcript, action.words)
        keep = rm.subtract(keep, cuts)

    elif isinstance(action, Tighten):
        cuts = _tighten_cuts(transcript, action.max_gap_s, action.pad_s)
        keep = rm.subtract(keep, cuts)

    elif isinstance(action, RemoveRetakes):
        cuts = _retake_cuts(transcript, action.similarity, retake_scorer)
        keep = rm.subtract(keep, cuts)

    elif isinstance(action, FindHighlights):
        # Budget scales with what's currently kept so the reel always tightens.
        budget = min(action.target_s, rm.total(keep) * action.max_fraction)
        spans = _highlight_spans(transcript, budget)
        if spans:  # empty only when there are no segments → leave keep untouched
            keep = rm.intersect(keep, spans)

    elif isinstance(action, Trim):
        keep = rm.subtract(keep, _trim_cut(transcript, action))

    elif isinstance(action, CutRanges):
        keep = rm.subtract(keep, rm.clamp([tuple(r) for r in action.ranges], 0.0, dur))

    elif isinstance(action, KeepRanges):
        keep = rm.intersect(keep, rm.clamp([tuple(r) for r in action.ranges], 0.0, dur))

    elif isinstance(action, CutWords):
        keep = rm.subtract(keep, _resolve_word_refs(transcript, action.word_refs))

    elif isinstance(action, RestoreWords):
        keep = rm.union(keep, _resolve_word_refs(transcript, action.word_refs))
        keep = rm.clamp(keep, 0.0, dur)

    elif isinstance(action, FilterTopic):
        seg_ids = _resolve_topic(action, transcript, topic_resolver)
        spans: rm.Ranges = []
        for sid in seg_ids:
            seg = transcript.segment_by_id(sid)
            if seg is not None:
                spans.append((seg.start, seg.end))
        spans = rm.clamp(spans, 0.0, dur)
        if action.mode == "keep":
            keep = rm.intersect(keep, spans)
        else:
            keep = rm.subtract(keep, spans)

    elif isinstance(action, SetCaptions):
        captions = captions.model_copy(deep=True)
        captions.enabled = action.enabled
        captions.granularity = action.granularity
        if action.font:
            captions.font = action.font
        if action.font_size:
            captions.font_size = action.font_size

    elif isinstance(action, SetAspect):
        aspect = action.aspect

    elif isinstance(action, SetTransition):
        transition.kind = action.kind
        if action.duration_s is not None:
            transition.duration_s = action.duration_s

    else:  # pragma: no cover - discriminated union is exhaustive
        raise CompileError(f"unhandled action type: {getattr(action, 'type', action)}")

    # keep-set housekeeping: drop unplayably short slivers, but never return
    # an empty keep set for cut operations that removed everything — the caller
    # decides how to warn; here we just keep it well-formed.
    keep = rm.drop_short(keep, rm.MIN_KEEP)
    return keep, captions, aspect, transition


def _resolve_topic(
    action: FilterTopic, transcript: Transcript, resolver: TopicResolver | None
) -> list[int]:
    valid_ids = {s.id for s in transcript.segments}
    if action.segment_ids:
        # LLM supplied ids directly → validate & use.
        ids = [sid for sid in action.segment_ids if sid in valid_ids]
        if ids:
            return ids
    if resolver is None:
        raise CompileError(
            "filter_topic needs either segment_ids or an embedding resolver "
            "(sentence-transformers not available)"
        )
    ids = resolver(action.query, transcript, action.mode)
    return [sid for sid in ids if sid in valid_ids]


# ---------------------------------------------------------------------------
# Compile a whole plan against a base EDL
# ---------------------------------------------------------------------------


def compile_plan(
    plan: EditPlan,
    base: CompiledEDL,
    transcript: Transcript,
    topic_resolver: TopicResolver | None = None,
    retake_scorer: RetakeScorer | None = None,
) -> CompiledEDL:
    """Apply every action in ``plan`` on top of ``base`` → a new EDL."""
    keep = rm.normalize(base.keep)
    captions = base.captions.model_copy(deep=True)
    aspect = base.aspect
    transition = base.transition.model_copy(deep=True)
    for action in plan.actions:
        keep, captions, aspect, transition = apply_action(
            action, keep, captions, aspect, transcript, topic_resolver, retake_scorer, transition
        )
    return CompiledEDL(
        keep=keep,
        captions=captions,
        aspect=aspect,
        transition=transition,
        duration=transcript.duration,
    )


def summarize_delta(before: CompiledEDL, after: CompiledEDL) -> str:
    """Human-readable summary of the duration change (for revision labels)."""
    b = before.output_duration
    a = after.output_duration
    delta = a - b
    pct = (delta / b * 100.0) if b > 0 else 0.0
    return f"{_fmt(b)} → {_fmt(a)} ({'+' if delta >= 0 else '−'}{_fmt(abs(delta))}, {pct:+.0f}%)"


def _fmt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(int(round(seconds)), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _count_words(refs) -> int:
    return sum(abs(r.word_index_end - r.word_index_start) + 1 for r in refs)


def label_for_action(action: Action) -> str:
    """A human, revision-log-worthy label for a single manual/AI action."""
    if isinstance(action, CutWords):
        n = _count_words(action.word_refs)
        return f"Manual: deleted {n} word{'s' if n != 1 else ''}"
    if isinstance(action, RestoreWords):
        n = _count_words(action.word_refs)
        return f"Manual: restored {n} word{'s' if n != 1 else ''}"
    if isinstance(action, CutRanges):
        return f"Manual: cut {len(action.ranges)} range{'s' if len(action.ranges) != 1 else ''}"
    if isinstance(action, KeepRanges):
        return "Manual: kept selection"
    if isinstance(action, RemoveSilences):
        return "Removed silences"
    if isinstance(action, RemoveFillers):
        return "Removed filler words"
    if isinstance(action, Tighten):
        return "Tightened pauses"
    if isinstance(action, RemoveRetakes):
        return "Removed retakes"
    if isinstance(action, FindHighlights):
        return "Kept highlights"
    if isinstance(action, Trim):
        return f"Trimmed {action.mode} anchor"
    if isinstance(action, FilterTopic):
        return f"{'Kept' if action.mode == 'keep' else 'Removed'} topic: {action.query!r}"
    if isinstance(action, SetCaptions):
        return f"Captions {'on' if action.enabled else 'off'}"
    if isinstance(action, SetAspect):
        return f"Aspect → {action.aspect}"
    if isinstance(action, SetTransition):
        return "Hard cuts" if action.kind == "none" else f"Transition → {action.kind}"
    return "Edit"
