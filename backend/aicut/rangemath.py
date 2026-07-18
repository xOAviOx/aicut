"""Pure range math — zero I/O, no engine imports, exhaustively unit-tested.

A *range set* is a list of ``(start, end)`` tuples in seconds. Unless noted,
functions accept arbitrary (possibly overlapping, unsorted, degenerate) input
and return a **normalized** set: sorted, merged, no zero/negative-length spans.

The two remap functions convert between the *source* timeline (the original
media) and the *output* timeline (what you get after cuts) — needed for
caption timing, the timeline strip, and seeking.
"""

from __future__ import annotations

Range = tuple[float, float]
Ranges = list[Range]

# Spans shorter than this (seconds) are dropped as noise / unplayable.
MIN_KEEP = 0.25
# Floating-point slack for merge/adjacency decisions.
EPS = 1e-6


def normalize(ranges: Ranges, *, eps: float = EPS) -> Ranges:
    """Sort, drop empty/negative spans, and merge overlapping/adjacent ones."""
    cleaned = [(float(s), float(e)) for s, e in ranges if e - s > eps]
    if not cleaned:
        return []
    cleaned.sort(key=lambda r: r[0])
    out: Ranges = [cleaned[0]]
    for s, e in cleaned[1:]:
        ls, le = out[-1]
        if s <= le + eps:  # overlap or touch → merge
            out[-1] = (ls, max(le, e))
        else:
            out.append((s, e))
    return out


def clamp(ranges: Ranges, lo: float, hi: float) -> Ranges:
    """Clamp every span into ``[lo, hi]`` then normalize."""
    out: Ranges = []
    for s, e in ranges:
        s2 = max(lo, min(s, hi))
        e2 = max(lo, min(e, hi))
        if e2 - s2 > EPS:
            out.append((s2, e2))
    return normalize(out)


def total(ranges: Ranges) -> float:
    """Total covered duration of a (not-necessarily-normalized) set."""
    return sum(e - s for s, e in normalize(ranges))


def subtract(a: Ranges, b: Ranges) -> Ranges:
    """Set difference ``a \\ b``."""
    a_n = normalize(a)
    b_n = normalize(b)
    if not b_n:
        return a_n
    out: Ranges = []
    for s, e in a_n:
        cur = s
        for bs, be in b_n:
            if be <= cur or bs >= e:
                continue
            if bs > cur:
                out.append((cur, min(bs, e)))
            cur = max(cur, be)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return normalize(out)


def intersect(a: Ranges, b: Ranges) -> Ranges:
    """Set intersection ``a ∩ b``."""
    a_n = normalize(a)
    b_n = normalize(b)
    out: Ranges = []
    i = j = 0
    while i < len(a_n) and j < len(b_n):
        s = max(a_n[i][0], b_n[j][0])
        e = min(a_n[i][1], b_n[j][1])
        if e - s > EPS:
            out.append((s, e))
        if a_n[i][1] < b_n[j][1]:
            i += 1
        else:
            j += 1
    return normalize(out)


def union(a: Ranges, b: Ranges) -> Ranges:
    return normalize(list(a) + list(b))


def invert(ranges: Ranges, duration: float) -> Ranges:
    """Complement of ``ranges`` within ``[0, duration]``."""
    return subtract([(0.0, duration)], ranges)


def pad(ranges: Ranges, pad_s: float, duration: float) -> Ranges:
    """Grow each span by ``pad_s`` on both sides, clamped to ``[0, duration]``."""
    grown = [(s - pad_s, e + pad_s) for s, e in ranges]
    return clamp(grown, 0.0, duration)


def drop_short(ranges: Ranges, min_len: float = MIN_KEEP) -> Ranges:
    """Remove spans shorter than ``min_len`` (after normalization)."""
    return [(s, e) for s, e in normalize(ranges) if e - s >= min_len - EPS]


def remap_time(t: float, keep: Ranges) -> float:
    """Map a *source* time to the *output* timeline through ``keep``.

    Times inside a cut region collapse onto the boundary (the cumulative kept
    duration up to that point), which is exactly what caption/seek logic wants.
    """
    keep_n = normalize(keep)
    out = 0.0
    for s, e in keep_n:
        if t < s:
            return out
        if t <= e:
            return out + (t - s)
        out += e - s
    return out


def inverse_remap(t_out: float, keep: Ranges) -> float:
    """Map an *output* time back to *source* time through ``keep``."""
    keep_n = normalize(keep)
    if not keep_n:
        return 0.0
    if t_out <= 0:
        return keep_n[0][0]
    acc = 0.0
    for s, e in keep_n:
        length = e - s
        if t_out <= acc + length + EPS:
            return s + (t_out - acc)
        acc += length
    return keep_n[-1][1]


def contains(keep: Ranges, t: float) -> bool:
    """Is source time ``t`` inside a kept span?"""
    for s, e in normalize(keep):
        if s - EPS <= t <= e + EPS:
            return True
    return False


def next_keep_start(keep: Ranges, t: float) -> float | None:
    """First kept-span start strictly after ``t`` (for skip-preview)."""
    for s, _e in normalize(keep):
        if s > t + EPS:
            return s
    return None
