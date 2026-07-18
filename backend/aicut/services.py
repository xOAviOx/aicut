"""Background services: transcription jobs (M2) and export jobs (M5).

The transcriber is injectable so the API can be tested without the heavy ML
stack — the real one wraps :func:`aicut.transcribe.transcribe`.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from pathlib import Path

from .config import get_settings
from .events import EventHub
from .media import extract_thumbnail
from .models import Transcript
from .project import ProjectStore

# transcriber(source_path, progress_cb) -> Transcript
Transcriber = Callable[[str, Callable[[float], None]], Transcript]


def default_transcriber(source_path: str, progress_cb: Callable[[float], None]) -> Transcript:
    from .transcribe import transcribe

    return transcribe(source_path, progress_cb=progress_cb)


class TranscriptionService:
    def __init__(
        self,
        store: ProjectStore,
        hub: EventHub,
        transcriber: Transcriber | None = None,
    ) -> None:
        self.store = store
        self.hub = hub
        self.transcriber = transcriber or default_transcriber

    def run(self, pid: str) -> None:
        """Run transcription for a project (blocking; call in a thread)."""
        project = self.store.get(pid)
        if project is None:
            return

        # thumbnail (best-effort, non-fatal)
        try:
            dest = self.store.settings.project_dir(pid) / "thumb.jpg"
            if extract_thumbnail(project.source_path, dest) is not None:
                project.thumbnail = f"/media/{pid}/thumb"
        except Exception:
            pass

        project.transcript_status = "running"
        project.transcript_progress = 0.0
        self.store.save(project)
        self.hub.publish(pid, {"type": "transcription", "status": "running", "progress": 0.0})

        last_emit = 0.0

        def progress(frac: float) -> None:
            nonlocal last_emit
            now = time.time()
            if now - last_emit >= 0.4 or frac >= 0.999:
                last_emit = now
                self.hub.publish(
                    pid,
                    {"type": "transcription", "status": "running", "progress": round(frac, 4)},
                )

        try:
            transcript = self.transcriber(project.source_path, progress)
            self.store.finalize_transcript(pid, transcript)
            updated = self.store.get(pid)
            self.hub.publish(
                pid,
                {
                    "type": "transcription",
                    "status": "ready",
                    "progress": 1.0,
                    "duration": transcript.duration,
                    "language": transcript.language,
                    "segments": len(transcript.segments),
                    "head_revision_id": updated.head_revision_id if updated else None,
                },
            )
        except ModuleNotFoundError:
            msg = (
                "faster-whisper is not installed. Run `uv sync --extra ml` to enable "
                "transcription, or attach a transcript via the API."
            )
            self._fail(pid, msg)
        except Exception as e:  # pragma: no cover - defensive
            traceback.print_exc()
            self._fail(pid, f"transcription failed: {e}")

    def _fail(self, pid: str, message: str) -> None:
        project = self.store.get(pid)
        if project is not None:
            project.transcript_status = "error"
            project.transcript_error = message
            self.store.save(project)
        self.hub.publish(pid, {"type": "transcription", "status": "error", "error": message})


def import_media_path(raw: str) -> tuple[Path, str | None]:
    """Validate a filesystem import path. Returns (path, error)."""
    settings = get_settings()  # noqa: F841 - reserved for future sandboxing
    p = Path(raw).expanduser()
    if not p.exists():
        return p, f"file not found: {p}"
    if not p.is_file():
        return p, f"not a file: {p}"
    return p, None
