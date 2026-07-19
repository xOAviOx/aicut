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

        # Atomically claim the job; bail if a transcript was already attached.
        if not self.store.begin_transcription(pid):
            return

        # thumbnail (best-effort, non-fatal, field-scoped write)
        try:
            dest = self.store.settings.project_dir(pid) / "thumb.jpg"
            if extract_thumbnail(project.source_path, dest) is not None:
                self.store.set_thumbnail(pid, f"/media/{pid}/thumb")
        except Exception:
            pass

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
        if project is None:
            return
        # Don't clobber a transcript that was attached out-of-band (no-ML path)
        # while this job was failing to load the model.
        if project.transcript_status == "ready":
            return
        project.transcript_status = "error"
        project.transcript_error = message
        self.store.save(project)
        self.hub.publish(pid, {"type": "transcription", "status": "error", "error": message})


class ExportService:
    """Background ffmpeg export jobs with SSE progress."""

    def __init__(self, store: ProjectStore, hub: EventHub) -> None:
        self.store = store
        self.hub = hub

    def exports_dir(self, pid: str) -> Path:
        d = self.store.settings.project_dir(pid) / "exports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run(self, pid: str, preset: dict, job_id: str) -> None:
        import time
        from pathlib import Path as _Path

        from .ffmpeg_export import ExportPreset, MergeClip, export, export_merge
        from .media import has_audio, video_dimensions

        project = self.store.get(pid)
        transcript = self.store.get_transcript(pid)
        if project is None or transcript is None:
            self.hub.publish(
                pid, {"type": "export", "job_id": job_id, "status": "error", "error": "not ready"}
            )
            return

        head = self.store.head_edl(project, transcript)
        out_name = f"{_safe_name(project.name)}-{job_id[:6]}.mp4"
        out_path = self.exports_dir(pid) / out_name

        # Resolve any clips to stitch after this one (append/merge).
        append_ids = preset.get("append_project_ids") or []
        merge_clips: list[MergeClip] = []
        if append_ids:
            def _clip(proj, tr) -> MergeClip:
                edl = self.store.head_edl(proj, tr)
                return MergeClip(
                    src=_Path(proj.source_path),
                    keep=edl.keep,
                    transcript=tr,
                    src_dims=video_dimensions(proj.source_path),
                    has_audio=has_audio(proj.source_path),
                )

            merge_clips.append(_clip(project, transcript))
            for aid in append_ids:
                ap = self.store.get(aid)
                at = self.store.get_transcript(aid)
                if ap is not None and at is not None and ap.transcript_status == "ready":
                    merge_clips.append(_clip(ap, at))

        export_preset = ExportPreset(
            aspect=preset.get("aspect"),
            captions=preset.get("captions"),
            granularity=preset.get("granularity"),
            quality=preset.get("quality", "balanced"),
        )

        self.hub.publish(pid, {"type": "export", "job_id": job_id, "status": "running", "progress": 0.0})
        last = 0.0

        def cb(frac: float) -> None:
            nonlocal last
            now = time.time()
            if now - last >= 0.4 or frac >= 0.999:
                last = now
                self.hub.publish(
                    pid,
                    {"type": "export", "job_id": job_id, "status": "running", "progress": round(frac, 4)},
                )

        try:
            if len(merge_clips) > 1:
                export_merge(merge_clips, out_path, export_preset, cb)
            else:
                export(head, transcript, project.source_path, out_path, export_preset, cb)
            self.hub.publish(
                pid,
                {
                    "type": "export",
                    "job_id": job_id,
                    "status": "done",
                    "progress": 1.0,
                    "name": out_name,
                    "url": f"/media/{pid}/exports/{out_name}",
                    "size": out_path.stat().st_size if out_path.exists() else 0,
                },
            )
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.hub.publish(
                pid, {"type": "export", "job_id": job_id, "status": "error", "error": str(e)[:500]}
            )


def _safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-")
    return keep or "export"


def import_media_path(raw: str) -> tuple[Path, str | None]:
    """Validate a filesystem import path. Returns (path, error)."""
    settings = get_settings()  # noqa: F841 - reserved for future sandboxing
    p = Path(raw).expanduser()
    if not p.exists():
        return p, f"file not found: {p}"
    if not p.is_file():
        return p, f"not a file: {p}"
    return p, None
