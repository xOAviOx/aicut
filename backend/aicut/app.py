"""FastAPI application: REST + SSE.

M2 wires project import, live transcription progress (SSE), transcript delivery,
and Range-capable media serving. Later milestones add manual edits (M3), the
command bar (M4), and export (M5) onto the same app/store/hub.
"""

from __future__ import annotations

import asyncio
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import __version__
from .diarize import assign_speakers, get_diarizer, speakers_in
from .edl import CompileError, label_for_action
from .embeddings import get_retake_scorer, get_topic_resolver
from .events import EventHub, event_stream
from .llm import LLMUnavailable, PlanError, Planner, state_summary
from .models import (
    Action,
    EditPlan,
    ExportPresetSettings,
    FindHighlights,
    RemoveFillers,
    RemoveRetakes,
    RemoveSilences,
    SetAspect,
    SetCaptions,
    SetTransition,
    Tighten,
    Transcript,
)
from .project import ProjectStore
from .services import ExportService, TranscriptionService, import_media_path
from .waveform import get_or_build_peaks

# Held references to detached background tasks so they aren't GC'd.
_bg_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub: EventHub = app.state.hub
    hub.bind_loop(asyncio.get_running_loop())
    yield


def create_app(
    store: ProjectStore | None = None,
    hub: EventHub | None = None,
    transcription: TranscriptionService | None = None,
    planner: Planner | None = None,
) -> FastAPI:
    app = FastAPI(title="aicut", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = store or ProjectStore()
    hub = hub or EventHub()
    transcription = transcription or TranscriptionService(store, hub)
    planner = planner or Planner()
    export_service = ExportService(store, hub)

    app.state.store = store
    app.state.hub = hub
    app.state.transcription = transcription
    app.state.planner = planner
    app.state.export = export_service

    _register_routes(app)
    return app


# One-click deterministic actions — never touch the LLM.
ONE_CLICK: dict[str, EditPlan] = {
    "remove_silences": EditPlan(actions=[RemoveSilences()], notes="Removed silences."),
    "remove_fillers": EditPlan(actions=[RemoveFillers()], notes="Removed filler words."),
    "tighten": EditPlan(actions=[Tighten()], notes="Tightened pauses."),
    "remove_retakes": EditPlan(
        actions=[RemoveRetakes()], notes="Removed repeated takes, kept the last."
    ),
    "highlights": EditPlan(
        actions=[FindHighlights()], notes="Kept the highlights — a tight auto-short."
    ),
    "captions_on": EditPlan(
        actions=[SetCaptions(enabled=True, granularity="segment")], notes="Captions on."
    ),
    "captions_off": EditPlan(actions=[SetCaptions(enabled=False)], notes="Captions off."),
    "aspect_916": EditPlan(actions=[SetAspect(aspect="9:16")], notes="Reframed to 9:16."),
    "aspect_11": EditPlan(actions=[SetAspect(aspect="1:1")], notes="Reframed to 1:1."),
    "aspect_source": EditPlan(actions=[SetAspect(aspect="source")], notes="Aspect back to source."),
    "crossfade_on": EditPlan(
        actions=[SetTransition(kind="crossfade")], notes="Crossfade between cuts."
    ),
    "wipe_on": EditPlan(actions=[SetTransition(kind="wipe")], notes="Wipe between cuts."),
    "transition_off": EditPlan(
        actions=[SetTransition(kind="none")], notes="Hard cuts (no transition)."
    ),
}


def _ai_label(plan: EditPlan) -> str:
    if not plan.actions:
        return "AI: no change"
    return "AI: " + " · ".join(label_for_action(a).replace("Manual: ", "") for a in plan.actions)


# ---------------------------------------------------------------------------
# Request/response bodies
# ---------------------------------------------------------------------------


class CreateProjectBody(BaseModel):
    path: str
    name: str | None = None


class EditRequest(BaseModel):
    action: Action
    notes: str | None = None


class DiarizeBody(BaseModel):
    num_speakers: int | None = None  # None = let the diarizer decide (defaults to 2)


class CommandBody(BaseModel):
    instruction: str


class ExportBody(BaseModel):
    aspect: str | None = None
    captions: bool | None = None
    granularity: str | None = None
    quality: str = "balanced"
    # Other project ids to stitch after this one (append / merge). Empty = single.
    append_project_ids: list[str] = []


class CreateWorkspaceBody(BaseModel):
    name: str | None = None
    clip_ids: list[str] = []  # group existing projects
    paths: list[str] = []  # or import new videos as clips


class AddClipBody(BaseModel):
    project_id: str | None = None
    path: str | None = None


class UpdateWorkspaceBody(BaseModel):
    name: str | None = None
    clip_ids: list[str] | None = None  # reorder


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def _project_payload(store: ProjectStore, pid: str) -> dict[str, Any]:
    project = store.get(pid)
    if project is None:
        raise HTTPException(404, "project not found")
    transcript = store.get_transcript(pid)
    return {
        "project": project.model_dump(),
        "transcript": transcript.model_dump() if transcript else None,
    }


def _workspace_payload(store: ProjectStore, wid: str) -> dict[str, Any]:
    ws = store.get_workspace(wid)
    if ws is None:
        raise HTTPException(404, "workspace not found")
    clips = []
    for cid in ws.clip_ids:
        project = store.get(cid)
        if project is None:
            continue
        transcript = store.get_transcript(cid)
        clips.append(
            {
                "project": project.model_dump(),
                "transcript": transcript.model_dump() if transcript else None,
            }
        )
    return {"workspace": ws.model_dump(), "clips": clips}


def _register_routes(app: FastAPI) -> None:
    store: ProjectStore = app.state.store
    hub: EventHub = app.state.hub
    transcription: TranscriptionService = app.state.transcription

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__, "service": "aicut"}

    # -- projects --------------------------------------------------------
    @app.get("/api/projects")
    def list_projects() -> dict:
        return {"projects": [p.model_dump() for p in store.list()]}

    @app.post("/api/projects")
    async def create_project(body: CreateProjectBody) -> dict:
        path, err = import_media_path(body.path)
        if err:
            raise HTTPException(400, err)
        project = store.create(str(path), name=body.name or "")
        _spawn(asyncio.to_thread(transcription.run, project.id))
        return {"project": project.model_dump()}

    @app.post("/api/projects/upload")
    async def upload_project(file: UploadFile) -> dict:
        project = store.create(file.filename or "upload.mp4", name="")
        dest = store.settings.project_dir(project.id) / (file.filename or "source.mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        project.source_path = str(dest)
        store.save(project)
        _spawn(asyncio.to_thread(transcription.run, project.id))
        return {"project": project.model_dump()}

    @app.get("/api/projects/{pid}")
    def get_project(pid: str) -> dict:
        return _project_payload(store, pid)

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: str) -> dict:
        store.delete(pid)
        return {"ok": True}

    # -- workspaces (edit multiple clips together) -----------------------
    def _import_clip(raw: str) -> str:
        path, err = import_media_path(raw)
        if err:
            raise HTTPException(400, err)
        proj = store.create(str(path))
        _spawn(asyncio.to_thread(transcription.run, proj.id))
        return proj.id

    @app.get("/api/workspaces")
    def list_workspaces() -> dict:
        out = []
        for ws in store.list_workspaces():
            clips = [store.get(cid) for cid in ws.clip_ids]
            out.append(
                {
                    "workspace": ws.model_dump(),
                    "clips": [c.model_dump() for c in clips if c is not None],
                }
            )
        return {"workspaces": out}

    @app.post("/api/workspaces")
    async def create_workspace(body: CreateWorkspaceBody) -> dict:
        clip_ids = [cid for cid in body.clip_ids if store.get(cid) is not None]
        for raw in body.paths:
            clip_ids.append(_import_clip(raw))
        if not clip_ids:
            raise HTTPException(400, "a workspace needs at least one clip")
        ws = store.create_workspace(body.name or "Workspace", clip_ids)
        return _workspace_payload(store, ws.id)

    @app.get("/api/workspaces/{wid}")
    def get_workspace(wid: str) -> dict:
        return _workspace_payload(store, wid)

    @app.post("/api/workspaces/{wid}")
    def update_workspace(wid: str, body: UpdateWorkspaceBody) -> dict:
        ws = store.get_workspace(wid)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        clip_ids = body.clip_ids
        if clip_ids is not None:
            # keep only known projects, preserve requested order
            clip_ids = [cid for cid in clip_ids if store.get(cid) is not None]
        store.update_workspace(wid, name=body.name, clip_ids=clip_ids)
        return _workspace_payload(store, wid)

    @app.delete("/api/workspaces/{wid}")
    def delete_workspace(wid: str) -> dict:
        store.delete_workspace(wid)
        return {"ok": True}

    @app.post("/api/workspaces/{wid}/clips")
    async def add_clip(wid: str, body: AddClipBody) -> dict:
        ws = store.get_workspace(wid)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        cid = body.project_id
        if body.path:
            cid = _import_clip(body.path)
        if not cid or store.get(cid) is None:
            raise HTTPException(400, "provide a valid project_id or path")
        store.update_workspace(wid, clip_ids=[*ws.clip_ids, cid])
        return _workspace_payload(store, wid)

    @app.delete("/api/workspaces/{wid}/clips/{cid}")
    def remove_clip(wid: str, cid: str) -> dict:
        ws = store.get_workspace(wid)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        store.update_workspace(wid, clip_ids=[c for c in ws.clip_ids if c != cid])
        return _workspace_payload(store, wid)

    # -- attach transcript directly (import existing / no-ML path) --------
    @app.post("/api/projects/{pid}/transcript")
    def attach_transcript(pid: str, transcript: Transcript) -> dict:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        store.finalize_transcript(pid, transcript)
        hub.publish(
            pid,
            {
                "type": "transcription",
                "status": "ready",
                "progress": 1.0,
                "duration": transcript.duration,
                "segments": len(transcript.segments),
            },
        )
        return _project_payload(store, pid)

    # -- speaker diarization --------------------------------------------
    @app.post("/api/projects/{pid}/diarize")
    async def diarize_project(pid: str, body: DiarizeBody) -> dict:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        if project.transcript_status != "ready":
            raise HTTPException(409, "transcript not ready")
        transcript = store.get_transcript(pid)
        if transcript is None:
            raise HTTPException(409, "transcript not ready")
        diarizer = get_diarizer()
        if diarizer is None:
            raise HTTPException(
                501,
                "diarization unavailable — install numpy for the local diarizer, "
                "or the 'diarize' extra (pyannote) for the accurate one",
            )
        turns = await asyncio.to_thread(diarizer, project.source_path, body.num_speakers)
        if not turns:
            raise HTTPException(422, "diarization produced no speakers for this audio")
        labeled = assign_speakers(transcript, turns)
        store.save_transcript(pid, labeled)
        return {
            "project": store.get(pid).model_dump(),
            "transcript": labeled.model_dump(),
            "speakers": speakers_in(labeled),
        }

    # -- manual edits (M3) ----------------------------------------------
    @app.post("/api/projects/{pid}/edits")
    def manual_edit(pid: str, body: EditRequest) -> dict:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        if project.transcript_status != "ready":
            raise HTTPException(409, "transcript not ready")
        plan = EditPlan(actions=[body.action], notes=body.notes or "")
        try:
            # Manual edits within a short window collapse into one history entry.
            store.append_revision(pid, plan, label_for_action(body.action), group_key="manual")
        except CompileError as e:
            raise HTTPException(400, str(e)) from e
        return _project_payload(store, pid)

    @app.post("/api/projects/{pid}/undo")
    def undo(pid: str) -> dict:
        if store.get(pid) is None:
            raise HTTPException(404, "project not found")
        store.undo(pid)
        return _project_payload(store, pid)

    @app.post("/api/projects/{pid}/redo")
    def redo(pid: str) -> dict:
        if store.get(pid) is None:
            raise HTTPException(404, "project not found")
        store.redo(pid)
        return _project_payload(store, pid)

    @app.post("/api/projects/{pid}/revisions/{rid}")
    def goto_revision(pid: str, rid: str) -> dict:
        if store.get(pid) is None:
            raise HTTPException(404, "project not found")
        store.goto_revision(pid, rid)
        return _project_payload(store, pid)

    # -- one-click deterministic actions (M4, no LLM) --------------------
    @app.post("/api/projects/{pid}/actions/{kind}")
    def one_click(pid: str, kind: str) -> dict:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        if project.transcript_status != "ready":
            raise HTTPException(409, "transcript not ready")
        plan = ONE_CLICK.get(kind)
        if plan is None:
            raise HTTPException(400, f"unknown action '{kind}'")
        label = plan.actions[0].__class__.__name__
        try:
            store.append_revision(
                pid, plan, label_for_action(plan.actions[0]), retake_scorer=get_retake_scorer()
            )
        except CompileError as e:
            raise HTTPException(400, str(e)) from e
        _ = label
        return _project_payload(store, pid)

    # -- AI command bar (M4) --------------------------------------------
    @app.post("/api/projects/{pid}/command")
    def command(pid: str, body: CommandBody) -> dict:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        if project.transcript_status != "ready":
            raise HTTPException(409, "transcript not ready")
        transcript = store.get_transcript(pid)
        if transcript is None:
            raise HTTPException(409, "transcript not ready")

        head = store.head_edl(project, transcript)
        state = state_summary(transcript.duration, head.output_duration)
        hub.publish(pid, {"type": "plan", "status": "planning"})
        try:
            plan = app.state.planner.plan(body.instruction, transcript, state)
        except LLMUnavailable as e:
            hub.publish(pid, {"type": "plan", "status": "error"})
            return {"ok": False, "error": str(e), "kind": "llm_unavailable"}
        except PlanError as e:
            hub.publish(pid, {"type": "plan", "status": "error"})
            return {"ok": False, "error": str(e), "detail": e.detail, "kind": "plan_error"}

        try:
            _, rev = store.append_revision(
                pid,
                plan,
                _ai_label(plan),
                topic_resolver=get_topic_resolver(),
                retake_scorer=get_retake_scorer(),
            )
        except CompileError as e:
            hub.publish(pid, {"type": "plan", "status": "error"})
            return {"ok": False, "error": f"Couldn't apply that edit: {e}", "kind": "compile_error"}

        hub.publish(pid, {"type": "plan", "status": "done", "revision_id": rev.id})
        return {
            "ok": True,
            "revision": rev.model_dump(),
            "summary": rev.label,
            "notes": plan.notes,
            "project": store.get(pid).model_dump(),
            "transcript": transcript.model_dump(),
        }

    # -- export (M5) -----------------------------------------------------
    @app.post("/api/projects/{pid}/export")
    async def export_project(pid: str, body: ExportBody) -> dict:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        if project.transcript_status != "ready":
            raise HTTPException(409, "transcript not ready")
        import uuid

        # Remember these options so the Export dialog reopens where it left off.
        store.remember_export_preset(
            pid,
            ExportPresetSettings(
                aspect=body.aspect,  # type: ignore[arg-type]
                captions=body.captions,
                granularity=body.granularity or "segment",  # type: ignore[arg-type]
                quality=body.quality,
            ),
        )

        job_id = uuid.uuid4().hex
        _spawn(asyncio.to_thread(app.state.export.run, pid, body.model_dump(), job_id))
        return {"job_id": job_id}

    @app.get("/api/projects/{pid}/exports")
    def list_exports(pid: str) -> dict:
        d = store.settings.project_dir(pid) / "exports"
        out = []
        if d.exists():
            for f in sorted(d.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
                out.append(
                    {"name": f.name, "url": f"/media/{pid}/exports/{f.name}", "size": f.stat().st_size}
                )
        return {"exports": out}

    @app.get("/media/{pid}/exports/{name}")
    def export_file(pid: str, name: str):
        # basename-only guard against path traversal
        safe = Path(name).name
        f = store.settings.project_dir(pid) / "exports" / safe
        if not f.exists():
            raise HTTPException(404, "export not found")
        return FileResponse(f, headers={"Accept-Ranges": "bytes"})

    # -- SSE -------------------------------------------------------------
    @app.get("/api/projects/{pid}/events")
    async def events(pid: str, request: Request) -> StreamingResponse:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        snapshot: dict[str, Any] = {
            "type": "transcription",
            "status": project.transcript_status,
            "progress": project.transcript_progress,
        }
        if project.transcript_error:
            snapshot["error"] = project.transcript_error
        return StreamingResponse(
            event_stream(hub, pid, snapshot, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- media (Range-capable) -------------------------------------------
    @app.get("/media/{pid}")
    def media(pid: str, request: Request):
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        path = Path(project.source_path)
        if not path.exists():
            raise HTTPException(404, "media file missing")
        # Starlette's FileResponse honors the Range header (206 + Content-Range).
        return FileResponse(path, headers={"Accept-Ranges": "bytes"})

    @app.get("/media/{pid}/waveform")
    def waveform(pid: str):
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        path = Path(project.source_path)
        if not path.exists():
            raise HTTPException(404, "media file missing")
        cache = store.settings.project_dir(pid) / "waveform.json"
        peaks = get_or_build_peaks(path, cache)
        return {"peaks": peaks, "duration": project.duration}

    @app.get("/media/{pid}/thumb")
    def thumb(pid: str):
        p = store.settings.project_dir(pid) / "thumb.jpg"
        if not p.exists():
            raise HTTPException(404, "no thumbnail")
        return FileResponse(p)

    @app.exception_handler(KeyError)
    async def _key_error(_request: Request, _exc: KeyError):
        return JSONResponse(status_code=404, content={"error": "not found"})


app = create_app()
