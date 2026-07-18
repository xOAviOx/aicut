"""aicut — an AI-controlled, transcript-driven video editor.

The package is split into a pure, dependency-light *engine* (data contracts,
range math, EDL compiler, revision model) and thin *integration* layers
(transcription, embeddings, LLM planning, ffmpeg export, FastAPI app). Heavy
ML dependencies are imported lazily so the engine and API run without them.
"""

__version__ = "0.1.0"
