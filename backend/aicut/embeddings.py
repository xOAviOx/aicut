"""Semantic topic resolver for ``filter_topic`` when the LLM didn't scope it.

Lazy-imports ``sentence-transformers`` (the ``ml`` extra). The selection maths
is a pure function so it can be unit-tested without the model. If the library
isn't installed, :func:`get_topic_resolver` returns ``None`` and the compiler
surfaces a clear "needs segment_ids or embeddings" error.
"""

from __future__ import annotations

from functools import lru_cache

from .config import Settings, get_settings
from .edl import TopicResolver
from .models import Transcript


def available() -> bool:
    try:
        import sentence_transformers  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _model(model_name: str):  # pragma: no cover - needs the heavy dep + network
    from sentence_transformers import SentenceTransformer  # type: ignore

    return SentenceTransformer(model_name)


def select_segment_indices(
    scores: list[float],
    *,
    abs_floor: float = 0.28,
    rel_frac: float = 0.55,
) -> list[int]:
    """Choose segment indices from cosine scores.

    Keeps segments scoring above both an absolute floor and a fraction of the
    best score — this naturally 'expands to close-scoring neighbors' without
    needing an explicit adjacency pass.
    """
    if not scores:
        return []
    top = max(scores)
    if top <= 0:
        return []
    threshold = max(abs_floor, top * rel_frac)
    return [i for i, s in enumerate(scores) if s >= threshold]


def resolve_topic(
    query: str,
    transcript: Transcript,
    mode: str,
    settings: Settings | None = None,
) -> list[int]:  # pragma: no cover - exercised only with the ml extra installed
    settings = settings or get_settings()
    model = _model(settings.embedding_model)
    texts = [seg.text for seg in transcript.segments]
    if not texts:
        return []
    emb = model.encode([query] + texts, normalize_embeddings=True)
    q = emb[0]
    seg_vecs = emb[1:]
    scores = [float(v @ q) for v in seg_vecs]
    idxs = select_segment_indices(scores)
    return [transcript.segments[i].id for i in idxs]


def get_topic_resolver(settings: Settings | None = None) -> TopicResolver | None:
    """Return a resolver bound to the real model, or None if ML deps are absent."""
    if not available():
        return None
    settings = settings or get_settings()

    def _resolver(query: str, transcript: Transcript, mode: str) -> list[int]:
        return resolve_topic(query, transcript, mode, settings)

    return _resolver
