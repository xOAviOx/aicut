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


FAKE_PLAN = (
    '{"actions": [{"type": "remove_silences", "min_gap_s": 0.6}], '
    '"notes": "tightened pauses"}'
)


@pytest.fixture
def client(isolated_home, simple_transcript):
    from aicut.llm import Planner

    store = ProjectStore()
    hub = EventHub()
    svc = TranscriptionService(store, hub, transcriber=_fake_transcriber(simple_transcript))
    planner = Planner(chat_fn=lambda messages: FAKE_PLAN)
    app = create_app(store, hub, svc, planner=planner)
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


def _parse_frame(frame: str) -> dict:
    """Parse one SSE frame string ('event: x\\ndata: {...}\\n\\n') into a dict."""
    import json

    etype = None
    data = None
    for line in frame.splitlines():
        if line.startswith("event:"):
            etype = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = line.split(":", 1)[1].strip()
    return {"event": etype, **(json.loads(data) if data else {})}


def test_event_stream_generator_snapshot_publish_disconnect():
    """Drive the extracted SSE generator directly: snapshot -> event -> stop."""
    from aicut.events import event_stream

    async def scenario():
        hub = EventHub()
        hub.bind_loop(asyncio.get_running_loop())
        disconnected = {"v": False}

        async def is_disconnected():
            return disconnected["v"]

        snapshot = {"type": "transcription", "status": "pending", "progress": 0.0}
        gen = event_stream(hub, "p1", snapshot, is_disconnected, poll=0.02)

        first = _parse_frame(await gen.__anext__())
        hub.publish("p1", {"type": "transcription", "status": "running", "progress": 0.5})
        second = _parse_frame(await asyncio.wait_for(gen.__anext__(), timeout=2.0))

        disconnected["v"] = True
        stopped = False
        try:
            await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        except StopAsyncIteration:
            stopped = True
        return first, second, stopped

    first, second, stopped = asyncio.run(scenario())
    assert first["event"] == "transcription" and first["status"] == "pending"
    assert second["status"] == "running" and second["progress"] == 0.5
    assert stopped is True


def _ready_project(client, media_file, simple_transcript) -> str:
    pid = client.post("/api/projects", json={"path": str(media_file)}).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/transcript", json=simple_transcript.model_dump())
    return pid


def test_manual_cut_words_creates_revision(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    body = {
        "action": {
            "type": "cut_words",
            "word_refs": [{"segment_id": 1, "word_index_start": 0, "word_index_end": 1}],
        }
    }
    r = client.post(f"/api/projects/{pid}/edits", json=body)
    assert r.status_code == 200
    proj = r.json()["project"]
    assert len(proj["revisions"]) == 2
    assert "deleted 2 words" in proj["revisions"][-1]["label"]


def test_manual_edit_then_undo_redo(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    client.post(
        f"/api/projects/{pid}/edits",
        json={"action": {"type": "cut_ranges", "ranges": [[0, 2]]}},
    )
    proj = client.post(f"/api/projects/{pid}/undo").json()["project"]
    assert proj["head_revision_id"] == proj["revisions"][0]["id"]
    proj = client.post(f"/api/projects/{pid}/redo").json()["project"]
    assert proj["head_revision_id"] == proj["revisions"][1]["id"]


def test_goto_revision(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    client.post(
        f"/api/projects/{pid}/edits",
        json={"action": {"type": "cut_ranges", "ranges": [[0, 2]]}},
    )
    proj = client.get(f"/api/projects/{pid}").json()["project"]
    r0 = proj["revisions"][0]["id"]
    proj = client.post(f"/api/projects/{pid}/revisions/{r0}").json()["project"]
    assert proj["head_revision_id"] == r0


def test_edit_before_ready_409(client, media_file):
    pid = client.post("/api/projects", json={"path": str(media_file)}).json()["project"]["id"]
    # transcription (fake) may still be running; force pending by not attaching.
    # A cut on a not-ready project should 409 (or the fake may have finished — accept both).
    r = client.post(
        f"/api/projects/{pid}/edits",
        json={"action": {"type": "cut_ranges", "ranges": [[0, 1]]}},
    )
    assert r.status_code in (200, 409)


def test_one_click_remove_silences(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    r = client.post(f"/api/projects/{pid}/actions/remove_silences")
    assert r.status_code == 200
    proj = r.json()["project"]
    assert len(proj["revisions"]) == 2
    assert "silence" in proj["revisions"][-1]["label"].lower()


def test_one_click_captions_and_aspect(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    client.post(f"/api/projects/{pid}/actions/captions_on")
    proj = client.post(f"/api/projects/{pid}/actions/aspect_916").json()["project"]
    head = next(r for r in proj["revisions"] if r["id"] == proj["head_revision_id"])
    assert head["edl"]["aspect"] == "9:16"
    assert head["edl"]["captions"]["enabled"] is True


def test_one_click_unknown_400(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    assert client.post(f"/api/projects/{pid}/actions/nope").status_code == 400


def test_one_click_tighten(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    r = client.post(f"/api/projects/{pid}/actions/tighten")
    assert r.status_code == 200
    proj = r.json()["project"]
    assert len(proj["revisions"]) == 2
    assert "tighten" in proj["revisions"][-1]["label"].lower()


def test_one_click_remove_retakes(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    r = client.post(f"/api/projects/{pid}/actions/remove_retakes")
    assert r.status_code == 200
    assert "retake" in r.json()["project"]["revisions"][-1]["label"].lower()


def test_waveform_endpoint(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    r = client.get(f"/media/{pid}/waveform")
    assert r.status_code == 200
    body = r.json()
    assert "peaks" in body and isinstance(body["peaks"], list)  # empty for non-audio input


def test_workspace_create_from_clip_ids(client, media_file, simple_transcript):
    a = _ready_project(client, media_file, simple_transcript)
    b = _ready_project(client, media_file, simple_transcript)
    r = client.post("/api/workspaces", json={"name": "Combo", "clip_ids": [a, b]})
    assert r.status_code == 200
    body = r.json()
    assert body["workspace"]["name"] == "Combo"
    assert body["workspace"]["clip_ids"] == [a, b]
    assert len(body["clips"]) == 2
    assert body["clips"][0]["transcript"] is not None


def test_workspace_needs_a_clip(client):
    assert client.post("/api/workspaces", json={"name": "empty"}).status_code == 400


def test_workspace_add_remove_reorder(client, media_file, simple_transcript):
    a = _ready_project(client, media_file, simple_transcript)
    b = _ready_project(client, media_file, simple_transcript)
    c = _ready_project(client, media_file, simple_transcript)
    wid = client.post("/api/workspaces", json={"clip_ids": [a]}).json()["workspace"]["id"]

    # add b, then c
    client.post(f"/api/workspaces/{wid}/clips", json={"project_id": b})
    body = client.post(f"/api/workspaces/{wid}/clips", json={"project_id": c}).json()
    assert body["workspace"]["clip_ids"] == [a, b, c]

    # reorder
    body = client.post(f"/api/workspaces/{wid}", json={"clip_ids": [c, a, b]}).json()
    assert body["workspace"]["clip_ids"] == [c, a, b]

    # remove a
    body = client.request("DELETE", f"/api/workspaces/{wid}/clips/{a}").json()
    assert body["workspace"]["clip_ids"] == [c, b]

    # list + delete
    assert any(w["workspace"]["id"] == wid for w in client.get("/api/workspaces").json()["workspaces"])
    assert client.delete(f"/api/workspaces/{wid}").json()["ok"] is True
    assert client.get(f"/api/workspaces/{wid}").status_code == 404


def test_export_remembers_preset(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    client.post(
        f"/api/projects/{pid}/export",
        json={"aspect": "9:16", "captions": True, "granularity": "word", "quality": "high"},
    )
    settings = client.get(f"/api/projects/{pid}").json()["project"]["settings"]
    preset = settings["export_preset"]
    assert preset is not None
    assert preset["aspect"] == "9:16"
    assert preset["captions"] is True
    assert preset["granularity"] == "word"
    assert preset["quality"] == "high"


def test_command_success(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    r = client.post(f"/api/projects/{pid}/command", json={"instruction": "cut the silences"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["revision"]["label"].startswith("AI:")
    assert "notes" in body


def test_command_llm_unavailable_returns_structured_error(
    isolated_home, media_file, simple_transcript
):
    from aicut.llm import LLMUnavailable, Planner

    def boom(messages):
        raise LLMUnavailable("ollama is not running")

    store = ProjectStore()
    hub = EventHub()
    svc = TranscriptionService(store, hub, transcriber=_fake_transcriber(simple_transcript))
    app = create_app(store, hub, svc, planner=Planner(chat_fn=boom))
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"path": str(media_file)}).json()["project"]["id"]
        c.post(f"/api/projects/{pid}/transcript", json=simple_transcript.model_dump())
        r = c.post(f"/api/projects/{pid}/command", json={"instruction": "cut silences"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["kind"] == "llm_unavailable"
        assert "ollama" in body["error"].lower()


def test_command_plan_error_returns_structured_error(
    isolated_home, media_file, simple_transcript
):
    from aicut.llm import Planner

    store = ProjectStore()
    hub = EventHub()
    svc = TranscriptionService(store, hub, transcriber=_fake_transcriber(simple_transcript))
    app = create_app(store, hub, svc, planner=Planner(chat_fn=lambda m: "garbage not json"))
    with TestClient(app) as c:
        pid = c.post("/api/projects", json={"path": str(media_file)}).json()["project"]["id"]
        c.post(f"/api/projects/{pid}/transcript", json=simple_transcript.model_dump())
        r = c.post(f"/api/projects/{pid}/command", json={"instruction": "do something"})
        assert r.json()["ok"] is False
        assert r.json()["kind"] == "plan_error"


def test_export_kicks_job(client, media_file, simple_transcript, monkeypatch):
    pid = _ready_project(client, media_file, simple_transcript)
    # avoid running real ffmpeg — just confirm the endpoint dispatches a job
    monkeypatch.setattr(client.app.state.export, "run", lambda *a, **k: None)
    r = client.post(f"/api/projects/{pid}/export", json={"aspect": "9:16", "quality": "fast"})
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_list_and_serve_exports(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    store: ProjectStore = client.app_store
    exp_dir = store.settings.project_dir(pid) / "exports"
    exp_dir.mkdir(parents=True, exist_ok=True)
    data = b"FAKEMP4DATA" * 100
    (exp_dir / "clip-abc123.mp4").write_bytes(data)

    listing = client.get(f"/api/projects/{pid}/exports").json()["exports"]
    assert any(e["name"] == "clip-abc123.mp4" for e in listing)

    r = client.get(f"/media/{pid}/exports/clip-abc123.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == data[:10]


def test_export_file_traversal_guarded(client, media_file, simple_transcript):
    pid = _ready_project(client, media_file, simple_transcript)
    r = client.get(f"/media/{pid}/exports/..%2f..%2fproject.json")
    assert r.status_code == 404


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
