"""Runtime configuration and filesystem layout.

Everything lives under a single data root (``~/aicut`` by default, overridable
with ``AICUT_HOME``). ``pathlib`` is used everywhere so Windows, WSL2, and Linux
all behave identically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _default_home() -> Path:
    env = os.environ.get("AICUT_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / "aicut"


@dataclass
class Settings:
    """Process-wide settings, populated from environment variables."""

    home: Path = field(default_factory=_default_home)

    # Whisper / transcription
    whisper_model: str = field(
        default_factory=lambda: os.environ.get("AICUT_WHISPER_MODEL", "large-v3")
    )
    whisper_compute_type: str = field(
        default_factory=lambda: os.environ.get("AICUT_WHISPER_COMPUTE", "int8_float16")
    )
    whisper_device: str = field(
        default_factory=lambda: os.environ.get("AICUT_WHISPER_DEVICE", "auto")
    )

    # Embeddings
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(
            "AICUT_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
        )
    )

    # Diarization (optional pyannote path; the local numpy fallback needs no model)
    diarization_model: str = field(
        default_factory=lambda: os.environ.get(
            "AICUT_DIARIZE_MODEL", "pyannote/speaker-diarization-3.1"
        )
    )

    # LLM (Ollama)
    ollama_host: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("AICUT_LLM_MODEL", "qwen2.5:7b-instruct")
    )

    # Server
    host: str = field(default_factory=lambda: os.environ.get("AICUT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("AICUT_PORT", "8756")))

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def workspaces_dir(self) -> Path:
        return self.home / "workspaces"

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def ensure_dirs(self) -> None:
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    return s
