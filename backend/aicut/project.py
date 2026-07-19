"""Project persistence + the revision/undo model.

Every edit — AI command or manual deletion — appends a :class:`Revision` (a
full EDL snapshot with a human label). Undo/redo just moves ``head_revision_id``
along the list; editing after an undo drops the now-orphaned tail. State
recovery is free because the whole thing round-trips through ``project.json``.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .config import Settings, get_settings
from .edl import compile_plan, initial_edl, summarize_delta
from .models import (
    CompiledEDL,
    EditPlan,
    Project,
    Revision,
    Transcript,
    Workspace,
)


class ProjectStore:
    """Thread-safe, file-backed store of projects and their transcripts."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self._locks: dict[str, threading.RLock] = {}
        self._global = threading.RLock()

    # -- paths -----------------------------------------------------------
    def _dir(self, pid: str) -> Path:
        return self.settings.project_dir(pid)

    def _project_file(self, pid: str) -> Path:
        return self._dir(pid) / "project.json"

    def _transcript_file(self, pid: str) -> Path:
        return self._dir(pid) / "transcript.json"

    def _lock(self, pid: str) -> threading.RLock:
        with self._global:
            if pid not in self._locks:
                self._locks[pid] = threading.RLock()
            return self._locks[pid]

    # -- create ----------------------------------------------------------
    def create(self, source_path: str, name: str = "") -> Project:
        project = Project(source_path=source_path, name=name or Path(source_path).stem)
        project.media_url = f"/media/{project.id}"
        self._dir(project.id).mkdir(parents=True, exist_ok=True)
        self.save(project)
        return project

    # -- load / save -----------------------------------------------------
    def save(self, project: Project) -> None:
        with self._lock(project.id):
            self._dir(project.id).mkdir(parents=True, exist_ok=True)
            tmp = self._project_file(project.id).with_suffix(".json.tmp")
            tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._project_file(project.id))

    def get(self, pid: str) -> Project | None:
        f = self._project_file(pid)
        if not f.exists():
            return None
        return Project.model_validate_json(f.read_text(encoding="utf-8"))

    def list(self) -> list[Project]:
        out: list[Project] = []
        if not self.settings.projects_dir.exists():
            return out
        for d in sorted(self.settings.projects_dir.iterdir()):
            pf = d / "project.json"
            if pf.exists():
                try:
                    out.append(Project.model_validate_json(pf.read_text(encoding="utf-8")))
                except Exception:
                    continue
        out.sort(key=lambda p: p.created_at, reverse=True)
        return out

    def delete(self, pid: str) -> None:
        import shutil

        with self._lock(pid):
            d = self._dir(pid)
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    # -- transcript ------------------------------------------------------
    def save_transcript(self, pid: str, transcript: Transcript) -> None:
        with self._lock(pid):
            self._dir(pid).mkdir(parents=True, exist_ok=True)
            self._transcript_file(pid).write_text(
                transcript.model_dump_json(indent=2), encoding="utf-8"
            )

    def get_transcript(self, pid: str) -> Transcript | None:
        f = self._transcript_file(pid)
        if not f.exists():
            return None
        return Transcript.model_validate_json(f.read_text(encoding="utf-8"))

    def begin_transcription(self, pid: str) -> bool:
        """Atomically move to 'running'. Returns False if already ready (skip)."""
        with self._lock(pid):
            project = self.get(pid)
            if project is None or project.transcript_status == "ready":
                return False
            project.transcript_status = "running"
            project.transcript_progress = 0.0
            self.save(project)
            return True

    def remember_export_preset(self, pid: str, preset) -> None:
        """Persist the last-used export options (field-scoped write)."""
        with self._lock(pid):
            project = self.get(pid)
            if project is None:
                return
            project.settings.export_preset = preset
            self.save(project)

    def set_thumbnail(self, pid: str, url: str) -> None:
        """Update just the thumbnail field, preserving any concurrent changes."""
        with self._lock(pid):
            project = self.get(pid)
            if project is None:
                return
            project.thumbnail = url
            self.save(project)

    def finalize_transcript(self, pid: str, transcript: Transcript) -> Project:
        """Persist a finished transcript and seed the initial ('Original') revision."""
        with self._lock(pid):
            project = self.get(pid)
            if project is None:
                raise KeyError(pid)
            self.save_transcript(pid, transcript)
            project.transcript_status = "ready"
            project.transcript_progress = 1.0
            project.duration = transcript.duration
            project.language = transcript.language
            if not project.revisions:
                edl = initial_edl(transcript, project.settings)
                rev = Revision(label="Original", notes="Full transcript, no cuts.", edl=edl)
                project.revisions = [rev]
                project.head_revision_id = rev.id
            self.save(project)
            return project

    # -- revisions -------------------------------------------------------
    def head_edl(self, project: Project, transcript: Transcript) -> CompiledEDL:
        head = project.head()
        if head is not None:
            return head.edl
        return initial_edl(transcript, project.settings)

    def append_revision(
        self,
        pid: str,
        plan: EditPlan,
        label_prefix: str,
        topic_resolver=None,
    ) -> tuple[Project, Revision]:
        """Compile ``plan`` on top of head, append a revision, advance head.

        If head is not the last revision (we're mid-undo), the tail is dropped
        before appending — standard editor redo semantics.
        """
        with self._lock(pid):
            project = self.get(pid)
            if project is None:
                raise KeyError(pid)
            transcript = self.get_transcript(pid)
            if transcript is None:
                raise RuntimeError("transcript not ready")

            base = self.head_edl(project, transcript)
            new_edl = compile_plan(plan, base, transcript, topic_resolver)
            delta = summarize_delta(base, new_edl)

            # drop redo tail
            if project.head_revision_id is not None:
                idx = project.revision_index(project.head_revision_id)
                if idx >= 0:
                    project.revisions = project.revisions[: idx + 1]

            label = f"{label_prefix} ({delta})" if label_prefix else delta
            rev = Revision(label=label, notes=plan.notes, edl=new_edl)
            project.revisions.append(rev)
            project.head_revision_id = rev.id
            # mirror latest caption/aspect onto project settings for convenience
            project.settings.captions = new_edl.captions.model_copy(deep=True)
            project.settings.aspect = new_edl.aspect
            self.save(project)
            return project, rev

    def undo(self, pid: str) -> Project:
        return self._move_head(pid, -1)

    def redo(self, pid: str) -> Project:
        return self._move_head(pid, +1)

    def _move_head(self, pid: str, direction: int) -> Project:
        with self._lock(pid):
            project = self.get(pid)
            if project is None:
                raise KeyError(pid)
            if not project.revisions or project.head_revision_id is None:
                return project
            idx = project.revision_index(project.head_revision_id)
            new_idx = idx + direction
            if 0 <= new_idx < len(project.revisions):
                project.head_revision_id = project.revisions[new_idx].id
                head = project.revisions[new_idx].edl
                project.settings.captions = head.captions.model_copy(deep=True)
                project.settings.aspect = head.aspect
                self.save(project)
            return project

    def goto_revision(self, pid: str, rid: str) -> Project:
        """Time-travel head to a specific revision (edit-log click)."""
        with self._lock(pid):
            project = self.get(pid)
            if project is None:
                raise KeyError(pid)
            if project.revision_index(rid) >= 0:
                project.head_revision_id = rid
                head = project.head()
                if head is not None:
                    project.settings.captions = head.edl.captions.model_copy(deep=True)
                    project.settings.aspect = head.edl.aspect
                self.save(project)
            return project


    # -- workspaces (ordered groups of clips) ----------------------------
    def _workspace_file(self, wid: str) -> Path:
        return self.settings.workspaces_dir / f"{wid}.json"

    def save_workspace(self, ws: Workspace) -> None:
        with self._lock(ws.id):
            self.settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._workspace_file(ws.id).with_suffix(".json.tmp")
            tmp.write_text(ws.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._workspace_file(ws.id))

    def get_workspace(self, wid: str) -> Workspace | None:
        f = self._workspace_file(wid)
        if not f.exists():
            return None
        return Workspace.model_validate_json(f.read_text(encoding="utf-8"))

    def list_workspaces(self) -> list[Workspace]:
        out: list[Workspace] = []
        d = self.settings.workspaces_dir
        if not d.exists():
            return out
        for f in d.glob("*.json"):
            try:
                out.append(Workspace.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        out.sort(key=lambda w: w.created_at, reverse=True)
        return out

    def create_workspace(self, name: str, clip_ids: list[str]) -> Workspace:
        ws = Workspace(name=name or "Workspace", clip_ids=list(clip_ids))
        self.save_workspace(ws)
        return ws

    def update_workspace(
        self, wid: str, *, name: str | None = None, clip_ids: list[str] | None = None
    ) -> Workspace | None:
        with self._lock(wid):
            ws = self.get_workspace(wid)
            if ws is None:
                return None
            if name is not None:
                ws.name = name
            if clip_ids is not None:
                ws.clip_ids = list(clip_ids)
            self.save_workspace(ws)
            return ws

    def delete_workspace(self, wid: str) -> None:
        """Ungroup the workspace. Clip projects are left intact."""
        with self._lock(wid):
            f = self._workspace_file(wid)
            if f.exists():
                f.unlink()


_store: ProjectStore | None = None


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        _store = ProjectStore()
    return _store
