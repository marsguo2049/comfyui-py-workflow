from __future__ import annotations

import threading
import json
from http.client import HTTPConnection

import pytest

from comfyui_py_workflow import batch_studio
from comfyui_py_workflow.batch_studio import BatchStudio

PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


def test_video_tool_available():
    assert "first-last-video" in {tool["id"] for tool in batch_studio.BATCH_TOOLS}


def records(first, last):
    return [dict(name=name, role=role, path=f"{role}/{i}")
            for role, names in (("first", first), ("last", last))
            for i, name in enumerate(names)]


def test_pairing_broadcast_natural_order_and_names():
    from comfyui_py_workflow.batch_video import pair_frames
    pairs = pair_frames(records(["fixed.png"], ["10.png", "2.png"]), "order")
    assert [(p["first"]["name"], p["last"]["name"]) for p in pairs] == [
        ("fixed.png", "2.png"), ("fixed.png", "10.png")]
    pairs = pair_frames(records(["10.png", "2.png"], ["fixed.png"]), "name")
    assert [p["first"]["name"] for p in pairs] == ["2.png", "10.png"]
    pairs = pair_frames(records(["b.png", "A.png"], ["a.jpg", "B.webp"]), "name")
    assert [(p["first"]["name"], p["last"]["name"]) for p in pairs] == [
        ("A.png", "a.jpg"), ("b.png", "B.webp")]


@pytest.mark.parametrize("first,last,mode", [
    ([], ["a.png"], "order"), (["a.png"], [], "name"),
    (["a.png", "b.png"], ["a.png", "b.png", "c.png"], "order"),
    (["a.png", "b.png"], ["a.png", "c.png"], "name"),
    (["a.png", "a.jpg"], ["a.png", "a.jpg"], "name"),
    (["a.png"], ["a.png"], "unknown"),
])
def test_invalid_pairs_rejected(first, last, mode):
    from comfyui_py_workflow.batch_video import pair_frames
    with pytest.raises(ValueError):
        pair_frames(records(first, last), mode)


def draft(studio):
    job = studio.create("first-last-video")
    studio.upload(job["id"], "first.jpg", PNG, role="first")
    studio.upload(job["id"], "last2.png", PNG, role="last")
    return studio.upload(job["id"], "last10.png", PNG, role="last")


class FakeClient:
    input_reference = staticmethod(batch_studio.ComfyUIClient.input_reference)
    output_assets = staticmethod(batch_studio.ComfyUIClient.output_assets)

    def __init__(self):
        self.workflows = []
        self.uploads = []

    def check_health(self):
        pass

    def upload_image(self, path, **kwargs):
        self.uploads.append(path)
        return dict(name=kwargs["filename"], subfolder="cpw", type="input")

    def run(self, workflow, **kwargs):
        self.workflows.append(workflow)
        return "prompt-1", {"outputs": {"24": {"images": [
            dict(filename="clip.mp4", subfolder="video", type="output")]}}}

    def submit(self, workflow):
        self.pending = workflow
        return {"prompt_id": "prompt-1"}

    def wait_for_completion(self, prompt_id, **kwargs):
        return self.run(self.pending, **kwargs)[1]

    def download_asset(self, asset, destination):
        destination.write_bytes(b"video")
        return destination


def finish(studio, job_id):
    studio._threads[job_id].join(3)
    assert not studio._threads[job_id].is_alive()
    return studio.get(job_id)


def test_video_settings_and_results_survive_restart(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: client)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    studio.start(job["id"], dict(prompt="camera moves", duration_seconds=4,
        aspect_ratio="16:9 (Widescreen)", megapixels=0.8, steps=12, base_seed=71))
    result = finish(studio, job["id"])
    assert result["status"] == "succeeded", result
    assert result["completed"] == result["succeeded"] == len(result["pairs"]) == 2
    assert len(client.workflows) == 2
    for index, workflow in enumerate(client.workflows):
        assert workflow["12"]["inputs"]["prompt"] == "camera moves"
        assert workflow["26"]["inputs"]["value"] == 4
        assert workflow["23"]["inputs"]["aspect_ratio"] == "16:9 (Widescreen)"
        assert workflow["23"]["inputs"]["megapixels"] == 0.8
        assert workflow["8"]["inputs"]["steps"] == 12
        assert workflow["3"]["inputs"]["seed"] == 71 + index
        assert workflow["22"]["inputs"]["image"] != workflow["20"]["inputs"]["image"]
    assert len({r["output"] for r in result["results"]}) == 2
    assert result["settings"]["actual_duration_seconds"] >= 4
    assert result["results"][0]["last_source"]
    for item in result["results"]:
        assert studio.media_path(job["id"], item["output"]).read_bytes() == b"video"
    assert BatchStudio(tmp_path).get(job["id"]) == result


@pytest.mark.parametrize("settings", [
    {"duration_seconds": 0}, {"duration_seconds": float("nan")},
    {"duration_seconds": 10000}, {"megapixels": -1}, {"steps": 0},
    {"steps": 2.5}, {"aspect_ratio": "bad"}, {"pairing_mode": "bad"},
])
def test_invalid_settings_leave_draft(tmp_path, settings):
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    with pytest.raises(ValueError):
        studio.start(job["id"], {"prompt": "move", **settings})
    assert studio.get(job["id"])["status"] == "draft"


def test_video_failure_keeps_success_and_continues(tmp_path, monkeypatch):
    client = FakeClient()
    original = client.run
    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(client.workflows) == 1:
            from comfyui_py_workflow.client import ComfyUIExecutionError
            raise ComfyUIExecutionError("generation failed")
        return result
    client.run = run
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: client)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    studio.start(job["id"], {"prompt": "move"})
    result = finish(studio, job["id"])
    assert result["status"] == "completed_with_errors"
    assert result["failed"] == result["succeeded"] == 1
    assert "generation failed" in result["results"][0]["error"]
    assert result["results"][1]["output"]


def test_video_cancellation_and_cross_tool_lock(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    client = FakeClient()
    original = client.run
    def run(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)
    client.run = run
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: client)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    other = studio.create()
    studio.upload(other["id"], "image.png", PNG)
    studio.start(job["id"], {"prompt": "move"})
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError):
            studio.start(other["id"], {"prompt": "edit"})
        studio.cancel(job["id"])
    finally:
        release.set()
    result = finish(studio, job["id"])
    assert result["status"] == "cancelled"
    assert result["completed"] == 1


def test_upload_requires_frame_role(tmp_path):
    studio = BatchStudio(tmp_path)
    job = studio.create("first-last-video")
    with pytest.raises(ValueError):
        studio.upload(job["id"], "a.png", PNG)
    assert not studio.get(job["id"])["files"]


def test_http_video_preview_upload_and_range_download(tmp_path, monkeypatch):
    from comfyui_py_workflow.local_ui import SingleInstanceHTTPServer, StudioRequestHandler
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: FakeClient())
    class Handler(StudioRequestHandler):
        batch = BatchStudio(tmp_path)
        def log_message(self, *args):
            pass
    server = SingleInstanceHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    def request(path, body, headers=None):
        connection.request("POST", path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    try:
        files = records(["start.png"], ["2.png", "10.png"])
        status, preview = request("/api/batch/video-preview", json.dumps(dict(files=files, duration_seconds=5)))
        assert status == 200 and len(preview["pairs"]) == 2
        assert preview["frame_count"] % 17 == 5
        assert not Handler.batch.list_jobs()
        assert request("/api/batch/video-preview", b'{"files":[{}]}')[0] == 400
        assert request("/api/batch/video-preview", json.dumps(dict(files=files)),
                       {"Origin": "https://example.com"})[0] == 400
        status, job = request("/api/batch/create", b'{"kind":"first-last-video"}')
        assert status == 201
        for role in ("first", "last"):
            status, uploaded = request(f"/api/batch/upload?id={job['id']}&filename={role}.png&role={role}", PNG)
            assert status == 201
            assert uploaded["files"][-1]["role"] == role
        status, _ = request("/api/batch/start", json.dumps(dict(id=job["id"], prompt="move")))
        assert status == 202
        result = finish(Handler.batch, job["id"])
        assert result["status"] == "succeeded"
        connection.request("GET", f"/batch-media/{job['id']}/{result['results'][0]['output']}",
                           headers={"Range": "bytes=0-2"})
        response = connection.getresponse()
        assert response.status == 206
        assert response.getheader("Content-Type") == "video/mp4"
        assert response.read() == b"vid"
        connection.request("HEAD", f"/batch-media/{job['id']}/{result['results'][0]['output']}")
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Length") == "5"
        assert response.read() == b""
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_timeout_preserves_prompt_and_does_not_submit_next_pair(tmp_path, monkeypatch):
    client = FakeClient()
    def timeout(*args, **kwargs):
        client.workflows.append(client.pending)
        raise TimeoutError("still running")
    client.wait_for_completion = timeout
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: client)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    studio.start(job["id"], {"prompt": "move"})
    result = finish(studio, job["id"])
    assert result["status"] == "failed"
    assert result["completed"] == 1 and len(client.workflows) == 1
    assert result["results"][0]["prompt_id"] == "prompt-1"
    assert "ComfyUI" in result["message"]
