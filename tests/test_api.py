"""API tests: lifecycle, Range serving, SSE, transcript attach. Heavy deps mocked."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from aicut.app import create_app
from aicut.events import EventHub
from aicut.project import ProjectStore
from aicut.services import TranscriptionService


def _fake_transcriber(transcript):
    def _t(source_path, progress_cb):
        progress_cb(0.25)
        progress_cb(0.75)
        progress_cb(1.0)
        return transcript.model_copy(update={"source": source_path})

    return _t


@pytest.fixture
def client(isolated_home, simple_transcript):
    store = ProjectStore()
    hub = EventHub()
    svc = TranscriptionService(store, hub, transcriber=_fake_transcriber(simple_transcript))
    app = create_app(store, hub, svc)
    with TestClient(app) as c:
        c.app_store = store  # type: ignore[attr-defined]
        c.app_hub = hub  # type: ignore[attr-defined]
        yield c


@pytest.fixture
def media_file(isolated_home):
    p = isolated_home / "clip.bin"
    p.write_bytes(bytes(range(256)) * 400)  # 102_400 bytes of known content
    return p


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_project_lifecycle(client, media_file):
    r = client.post("/api/projects", json={"path": str(media_file)})
    assert r.status_code == 200
    pid = r.json()["project"]["id"]

    # background transcription (fake) should finish quickly
    deadline = time.time() + 5
    payload = None
    while time.time() < deadline:
        payload = client.get(f"/api/projects/{pid}").json()
        if payload["project"]["transcript_status"] == "ready":
            break
        time.sleep(0.05)
    assert payload["project"]["transcript_status"] == "ready"
    assert payload["transcript"] is not None
    assert len(payload["transcript"]["segments"]) == 4
    # seeded 'Original' revision
    assert len(payload["project"]["revisions"]) == 1
    assert payload["project"]["head_revision_id"] is not None

    # appears in list
    lst = client.get("/api/projects").json()["projects"]
    assert any(p["id"] == pid for p in lst)


def test_import_missing_file_400(client):
    r = client.post("/api/projects", json={"path": "/does/not/exist.mp4"})
    assert r.status_code == 400


def test_attach_transcript(client, media_file, simple_transcript):
    pid = client.post("/api/projects", json={"path": str(media_file)}).json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/transcript", json=simple_transcript.model_dump())
    assert r.status_code == 200
    assert r.json()["project"]["transcript_status"] == "ready"


def test_media_range_returns_206(client, media_file):
    store: ProjectStore = client.app_store
    project = store.create(str(media_file), name="range")
    r = client.get(f"/media/{project.id}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-99/{media_file.stat().st_size}"
    assert len(r.content) == 100
    assert r.content == media_file.read_bytes()[:100]


def test_media_range_middle_slice(client, media_file):
    store: ProjectStore = client.app_store
    project = store.create(str(media_file), name="range2")
    r = client.get(f"/media/{project.id}", headers={"Range": "bytes=1000-1099"})
    assert r.status_code == 206
    assert r.content == media_file.read_bytes()[1000:1100]


def test_media_full_request_200(client, media_file):
    store: ProjectStore = client.app_store
    project = store.create(str(media_file), name="full")
    r = client.get(f"/media/{project.id}")
    assert r.status_code == 200
    assert r.headers.get("accept-ranges") == "bytes"


def test_media_404(client):
    r = client.get("/media/nonexistent")
    assert r.status_code == 404


def _read_sse_event(line_iter) -> dict:
    """Accumulate lines until a blank line -> parse one SSE frame."""
    import json

    event_type = None
    data = None
    for raw in line_iter:
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line == "":
            if data is not None:
                return {"event": event_type, **json.loads(data)}
            continue
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = line.split(":", 1)[1].strip()
    raise AssertionError("stream ended before a full event")


def test_sse_snapshot_and_published_event(client, media_file):
    store: ProjectStore = client.app_store
    hub: EventHub = client.app_hub
    project = store.create(str(media_file), name="sse")
    pid = project.id

    with client.stream("GET", f"/api/projects/{pid}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = r.iter_lines()
        # 1) initial snapshot
        snapshot = _read_sse_event(lines)
        assert snapshot["event"] == "transcription"
        assert snapshot["status"] == "pending"
        # 2) a published progress event reaches the subscriber
        hub.publish(pid, {"type": "transcription", "status": "running", "progress": 0.5})
        evt = _read_sse_event(lines)
        assert evt["status"] == "running"
        assert evt["progress"] == 0.5


def test_event_hub_thread_safe_delivery():
    async def scenario():
        hub = EventHub()
        hub.bind_loop(asyncio.get_running_loop())
        q = hub.subscribe("p1")
        # simulate a worker thread publishing
        await asyncio.to_thread(
            hub.publish, "p1", {"type": "transcription", "status": "ready"}
        )
        return await asyncio.wait_for(q.get(), timeout=2.0)

    evt = asyncio.run(scenario())
    assert evt["status"] == "ready"
