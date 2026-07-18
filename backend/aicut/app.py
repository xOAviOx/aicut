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
from .events import EventHub, sse_format
from .models import Transcript
from .project import ProjectStore
from .services import TranscriptionService, import_media_path

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

    app.state.store = store
    app.state.hub = hub
    app.state.transcription = transcription

    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Request/response bodies
# ---------------------------------------------------------------------------


class CreateProjectBody(BaseModel):
    path: str
    name: str | None = None


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

    # -- SSE -------------------------------------------------------------
    @app.get("/api/projects/{pid}/events")
    async def events(pid: str, request: Request) -> StreamingResponse:
        project = store.get(pid)
        if project is None:
            raise HTTPException(404, "project not found")
        queue = hub.subscribe(pid)

        async def gen():
            # initial snapshot so a late subscriber knows current status
            snapshot = {
                "type": "transcription",
                "status": project.transcript_status,
                "progress": project.transcript_progress,
            }
            if project.transcript_error:
                snapshot["error"] = project.transcript_error
            yield sse_format(snapshot)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield sse_format(event)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                hub.unsubscribe(pid, queue)

        return StreamingResponse(
            gen(),
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
