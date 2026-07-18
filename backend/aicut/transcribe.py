"""faster-whisper transcription with word timestamps, VAD, and caching.

Heavy deps (``faster_whisper``, ``torch``/``ctranslate2``) are imported lazily
so the rest of aicut runs without them. The model is freed from VRAM after each
job (spec §4) so the 7B/14B planner LLM fits comfortably on a 12 GB card.

``large-v3`` is the default because content may be English, Hindi, or Hinglish —
the multilingual model is a hard requirement. ``distil-large-v3`` is an opt-in
speed setting (English-only) via ``AICUT_WHISPER_MODEL``.
"""

from __future__ import annotations

import gc
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from .config import Settings, get_settings
from .media import probe_duration
from .models import Segment, Transcript, Word

ProgressCb = Callable[[float], None]


def _file_hash(path: Path, model: str) -> str:
    """Content hash (size + head/tail bytes) keyed by model — cheap and stable."""
    h = hashlib.sha256()
    h.update(model.encode())
    st = path.stat()
    h.update(str(st.st_size).encode())
    with path.open("rb") as f:
        h.update(f.read(1 << 20))  # first 1 MB
        if st.st_size > (1 << 21):
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))  # last 1 MB
    return h.hexdigest()[:24]


def _cache_path(settings: Settings, key: str) -> Path:
    return settings.cache_dir / f"transcript-{key}.json"


def load_cached(media_path: str | Path, settings: Settings | None = None) -> Transcript | None:
    settings = settings or get_settings()
    settings.ensure_dirs()
    path = Path(media_path)
    if not path.exists():
        return None
    key = _file_hash(path, settings.whisper_model)
    cp = _cache_path(settings, key)
    if cp.exists():
        try:
            return Transcript.model_validate_json(cp.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _resolve_device(settings: Settings) -> tuple[str, str]:
    """Pick (device, compute_type), falling back to CPU cleanly."""
    want = settings.whisper_device
    if want in ("cpu",):
        return "cpu", "int8"
    # try CUDA
    try:
        import ctranslate2  # type: ignore

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", settings.whisper_compute_type
    except Exception:
        pass
    if want == "cuda":
        # explicitly requested but unavailable — still fall back, don't crash
        return "cpu", "int8"
    return "cpu", "int8"


def transcribe(
    media_path: str | Path,
    *,
    settings: Settings | None = None,
    progress_cb: ProgressCb | None = None,
    use_cache: bool = True,
) -> Transcript:
    """Transcribe ``media_path`` into a :class:`Transcript` with word timestamps.

    Raises ``ModuleNotFoundError`` if faster-whisper is not installed (install
    with ``uv sync --extra ml``).
    """
    settings = settings or get_settings()
    settings.ensure_dirs()
    path = Path(media_path)
    duration = probe_duration(path)

    if use_cache:
        cached = load_cached(path, settings)
        if cached is not None:
            if progress_cb:
                progress_cb(1.0)
            return cached

    # Lazy heavy import.
    from faster_whisper import WhisperModel  # type: ignore

    device, compute_type = _resolve_device(settings)
    model = WhisperModel(settings.whisper_model, device=device, compute_type=compute_type)

    try:
        seg_iter, info = model.transcribe(
            str(path),
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
        )
        segments: list[Segment] = []
        for i, seg in enumerate(seg_iter):
            words = [
                Word(w=w.word, start=float(w.start), end=float(w.end))
                for w in (seg.words or [])
                if w.start is not None and w.end is not None
            ]
            segments.append(
                Segment(
                    id=i,
                    start=float(seg.start),
                    end=float(seg.end),
                    text=(seg.text or "").strip(),
                    words=words,
                )
            )
            if progress_cb and duration > 0:
                progress_cb(min(seg.end / duration, 0.999))

        transcript = Transcript(
            source=str(path),
            duration=duration,
            language=getattr(info, "language", "en") or "en",
            segments=segments,
        )
    finally:
        # Free VRAM so the LLM planner fits.
        del model
        gc.collect()
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    if use_cache:
        key = _file_hash(path, settings.whisper_model)
        _cache_path(settings, key).write_text(
            transcript.model_dump_json(indent=2), encoding="utf-8"
        )

    if progress_cb:
        progress_cb(1.0)
    return transcript


def transcript_from_json(data: dict) -> Transcript:
    """Build a Transcript from a plain dict (used by tests / fixtures)."""
    return Transcript.model_validate(data)


def save_transcript_json(transcript: Transcript, dest: str | Path) -> None:
    Path(dest).write_text(json.dumps(transcript.model_dump(), indent=2), encoding="utf-8")
