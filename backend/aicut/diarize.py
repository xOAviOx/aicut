"""Speaker diarization: label transcript segments with who's talking.

Two layers, mirroring :mod:`aicut.embeddings`:

* **Pure engine** — :func:`assign_speakers` (turns → per-segment labels) and
  :func:`speakers_in` are dependency-free and unit-tested without any model.
* **Diarizer** — :func:`diarize` turns audio into speaker turns. It prefers
  ``pyannote.audio`` (accurate; the optional ``diarize`` extra + a HF token)
  and falls back to a light **numpy + ffmpeg** MFCC/k-means clusterer that runs
  anywhere ffmpeg does. If neither is available it returns ``None`` and the API
  surfaces a clear "diarization unavailable" message.

The compiler's ``filter_speaker`` action only ever reads the labels this module
writes onto the transcript, so "keep only Speaker 1" stays fully deterministic.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from .config import Settings, get_settings
from .media import ffmpeg_bin
from .models import Transcript

# (start_s, end_s, speaker_label)
Turn = tuple[float, float, str]
# diarizer(source_path, num_speakers|None) -> list[Turn] | None
Diarizer = Callable[[str, int | None], "list[Turn] | None"]

_SR = 16000
_FRAME_S = 1.0  # non-overlapping analysis window


def speaker_label(index: int) -> str:
    """Human label for the ``index``-th distinct speaker (0-based)."""
    return f"Speaker {index + 1}"


# ---------------------------------------------------------------------------
# Pure engine (no audio, no numpy) — unit-tested directly
# ---------------------------------------------------------------------------


def assign_speakers(transcript: Transcript, turns: list[Turn]) -> Transcript:
    """Return a copy of ``transcript`` with each segment's ``speaker`` set to the
    label whose turns overlap it most. Segments with no overlap stay ``None``."""
    new_segments = []
    for seg in transcript.segments:
        by_label: dict[str, float] = {}
        for ts, te, label in turns:
            overlap = min(seg.end, te) - max(seg.start, ts)
            if overlap > 0:
                by_label[label] = by_label.get(label, 0.0) + overlap
        best = max(by_label, key=by_label.__getitem__) if by_label else None
        new_segments.append(seg.model_copy(update={"speaker": best}))
    return transcript.model_copy(update={"segments": new_segments})


def speakers_in(transcript: Transcript) -> list[str]:
    """Distinct speaker labels, in order of first appearance."""
    seen: list[str] = []
    for seg in transcript.segments:
        if seg.speaker and seg.speaker not in seen:
            seen.append(seg.speaker)
    return seen


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def local_available() -> bool:
    """The numpy+ffmpeg fallback needs only numpy (ffmpeg is checked at run)."""
    try:
        import numpy  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def pyannote_available() -> bool:
    try:
        import pyannote.audio  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def available() -> bool:
    return pyannote_available() or local_available()


# ---------------------------------------------------------------------------
# Local numpy + ffmpeg diarizer (MFCC features → k-means → merged turns)
# ---------------------------------------------------------------------------


def _load_audio(path: str):
    """Decode ``path`` to mono float32 PCM at 16 kHz via ffmpeg → numpy array."""
    import numpy as np

    cmd = [
        ffmpeg_bin(), "-v", "error", "-i", str(path),
        "-f", "f32le", "-ac", "1", "-ar", str(_SR), "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float64)


def _mel_filterbank(sr: int, n_fft: int, n_mels: int):
    import numpy as np

    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    mels = np.linspace(hz2mel(0.0), hz2mel(sr / 2), n_mels + 2)
    bins = np.floor((n_fft + 1) * mel2hz(mels) / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        left, center, right = bins[m - 1], bins[m], bins[m + 1]
        center = max(center, left + 1)
        right = max(right, center + 1)
        for k in range(left, center):
            if 0 <= k < fb.shape[1]:
                fb[m - 1, k] = (k - left) / (center - left)
        for k in range(center, right):
            if 0 <= k < fb.shape[1]:
                fb[m - 1, k] = (right - k) / (right - center)
    return fb


def _dct_matrix(n_mfcc: int, n_mels: int):
    import numpy as np

    m = np.arange(n_mfcc)[:, None]
    k = np.arange(n_mels)[None, :]
    d = np.cos(np.pi * (k + 0.5) * m / n_mels) * np.sqrt(2.0 / n_mels)
    d[0, :] *= 1.0 / np.sqrt(2.0)
    return d


def _mfcc_window(samples, fb, dct, n_fft=400, hop=160):
    """Mean MFCC vector over a window (averaged across its short sub-frames)."""
    import numpy as np

    if len(samples) < n_fft:
        return None
    window = np.hanning(n_fft)
    frames = []
    for start in range(0, len(samples) - n_fft + 1, hop):
        seg = samples[start : start + n_fft] * window
        power = np.abs(np.fft.rfft(seg)) ** 2
        logmel = np.log(fb @ power + 1e-10)
        frames.append(dct @ logmel)
    if not frames:
        return None
    return np.mean(frames, axis=0)


def _kmeans(x, k: int, iters: int = 40, seed: int = 0):
    import numpy as np

    n = len(x)
    if n <= k:
        return np.arange(n) % k
    rng = np.random.default_rng(seed)
    # k-means++ seeding for a stable, well-spread start
    centers = [x[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min([np.sum((x - c) ** 2, axis=1) for c in centers], axis=0)
        total = d2.sum()
        probs = d2 / total if total > 0 else None
        centers.append(x[rng.choice(n, p=probs)])
    c = np.array(centers, dtype=float)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dists = np.sum((x[:, None, :] - c[None, :, :]) ** 2, axis=2)
        new = np.argmin(dists, axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            members = x[labels == j]
            if len(members):
                c[j] = members.mean(axis=0)
    return labels


def _near_constant(x_raw) -> bool:
    """True when the audio's features barely vary — silence, a held tone, or a
    music bed. Such a clip has no speaker structure, so we treat it as one voice
    instead of forcing a phantom split. (Real speech varies far above this floor,
    so this never collapses a genuine single speaker's phonetic variation.)"""
    import numpy as np

    return float(np.mean(x_raw.std(0))) < 0.5


def _merge_turns(times, labels) -> list[Turn]:
    """Relabel clusters by first appearance and merge adjacent same-speaker frames."""
    order: dict[int, str] = {}
    merged: list[Turn] = []
    for (ts, te), lab in zip(times, labels, strict=True):
        lab = int(lab)
        if lab not in order:
            order[lab] = speaker_label(len(order))
        name = order[lab]
        if merged and merged[-1][2] == name and abs(merged[-1][1] - ts) < 1e-3:
            s, _e, _n = merged[-1]
            merged[-1] = (s, te, name)
        else:
            merged.append((ts, te, name))
    return merged


def diarize_local(source_path: str, num_speakers: int | None = None) -> list[Turn] | None:
    """Cluster 1-second MFCC windows into speakers. Crude but dependency-light —
    good enough to split a 2-3 person conversation; returns ``None`` on failure.

    ``num_speakers`` is honored when given. When ``None`` it defaults to 2 (the
    UI lets the user pick), except for near-constant audio (silence / music),
    which collapses to one. Reliable auto speaker-counting is what the optional
    pyannote path is for."""
    import numpy as np

    audio = _load_audio(source_path)
    if audio is None or len(audio) < _SR:  # need at least ~1s
        return None
    win = int(_SR * _FRAME_S)
    fb = _mel_filterbank(_SR, 400, 40)
    dct = _dct_matrix(13, 40)
    feats, times = [], []
    for i in range(0, len(audio) - win + 1, win):
        vec = _mfcc_window(audio[i : i + win], fb, dct)
        if vec is not None:
            feats.append(vec[1:])  # drop the 0th (energy) coefficient
            times.append((i / _SR, (i + win) / _SR))
    if len(feats) < 2:
        return None
    x_raw = np.array(feats)
    if num_speakers is None and _near_constant(x_raw):
        k = 1  # silence / held tone / music bed → a single speaker
    else:
        k = num_speakers or 2  # crude default; caller (UI) can override
    x = (x_raw - x_raw.mean(0)) / (x_raw.std(0) + 1e-8)
    k = max(1, min(k, len(x)))
    labels = _kmeans(x, k)
    return _merge_turns(times, labels)


def diarize_pyannote(  # pragma: no cover - needs the heavy dep + HF token
    source_path: str, num_speakers: int | None, settings: Settings
) -> list[Turn] | None:
    from pyannote.audio import Pipeline  # type: ignore

    pipeline = Pipeline.from_pretrained(settings.diarization_model)
    kw = {"num_speakers": num_speakers} if num_speakers else {}
    annotation = pipeline(source_path, **kw)
    order: dict[str, str] = {}
    turns: list[Turn] = []
    for segment, _track, spk in annotation.itertracks(yield_label=True):
        if spk not in order:
            order[spk] = speaker_label(len(order))
        turns.append((segment.start, segment.end, order[spk]))
    return turns


def diarize(
    source_path: str, num_speakers: int | None = None, settings: Settings | None = None
) -> list[Turn] | None:
    """Diarize ``source_path``. Prefers pyannote, falls back to the local
    clusterer, and returns ``None`` if nothing is available/usable."""
    settings = settings or get_settings()
    if pyannote_available():
        try:
            return diarize_pyannote(source_path, num_speakers, settings)
        except Exception:
            pass  # fall back to the local clusterer
    if local_available():
        return diarize_local(source_path, num_speakers)
    return None


def get_diarizer(settings: Settings | None = None) -> Diarizer | None:
    """Return a diarizer callable, or ``None`` if no backend is available."""
    if not available():
        return None
    settings = settings or get_settings()

    def _diarizer(source_path: str, num_speakers: int | None = None) -> list[Turn] | None:
        return diarize(source_path, num_speakers, settings)

    return _diarizer
