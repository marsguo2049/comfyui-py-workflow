from __future__ import annotations

import json
import threading
from html.parser import HTMLParser
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote

import pytest

from comfyui_py_workflow import batch_studio
from comfyui_py_workflow.batch_image_edit import BatchItemResult, BatchRunResult
from comfyui_py_workflow.batch_studio import BatchStudio
from comfyui_py_workflow.local_ui import SingleInstanceHTTPServer, StudioRequestHandler, WEB_ROOT
from comfyui_py_workflow.studio import OfflineStudio

PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


def draft(studio):
    job = studio.create()
    return studio.upload(job["id"], "photo.png", PNG)


def finish(studio, job_id):
    studio._threads[job_id].join(timeout=3)
    assert not studio._threads[job_id].is_alive()
    return studio.get(job_id)


def test_upload_names_limits_and_private_media(tmp_path, monkeypatch):
    studio = BatchStudio(tmp_path)
    job = studio.create()
    job = studio.upload(job["id"], "../../secret.png", PNG)
    assert job["files"][0]["name"] == "secret.png"
    assert studio.media_path(job["id"], job["files"][0]["path"]).read_bytes() == PNG
    for relative in ["job.json", "../job.json", "input/../../secret.png"]:
        with pytest.raises(FileNotFoundError): studio.media_path(job["id"], relative)
    with pytest.raises(ValueError): studio.get("../outside")
    with pytest.raises(ValueError): studio.upload(job["id"], "fake.png", b"<html>no</html>")
    monkeypatch.setattr(batch_studio, "MAX_FILES", 1)
    with pytest.raises(ValueError): studio.upload(job["id"], "second.png", PNG)
    monkeypatch.setattr(batch_studio, "MAX_FILES", 200)
    monkeypatch.setattr(batch_studio, "MAX_JOB_BYTES", len(PNG))
    with pytest.raises(ValueError): studio.upload(job["id"], "second.png", PNG)
    monkeypatch.setattr(batch_studio, "MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError): studio.upload(job["id"], "second.png", PNG)


@pytest.mark.parametrize("settings", [
    {"prompt": ""}, {"prompt": "edit", "comfyui_url": "https://example.com"},
    {"prompt": "edit", "base_seed": -1}, {"prompt": "edit", "timeout_seconds": 0},
    {"prompt": "edit", "timeout_seconds": float("nan")},
    {"prompt": "edit", "timeout_seconds": float("inf")},
])
def test_invalid_settings_do_not_start_job(tmp_path, settings):
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    with pytest.raises(ValueError): studio.start(job["id"], settings)
    assert studio.get(job["id"])["status"] == "draft"


def test_real_editor_integration_preserves_settings_and_results(tmp_path, monkeypatch):
    from test_batch_image_edit import FakeClient
    client = FakeClient()
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: client)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    studio.upload(job["id"], "photo.png", PNG)
    studio.start(job["id"], {"prompt": "blue sky", "negative_prompt": "text", "base_seed": 55})
    completed = finish(studio, job["id"])
    assert completed["status"] == "succeeded"
    assert completed["completed"] == completed["succeeded"] == 2
    assert [w["433:3"]["inputs"]["seed"] for w in client.workflows] == [55, 56]
    assert all(w["433:111"]["inputs"]["prompt"] == "blue sky" for w in client.workflows)
    assert len({r["output"] for r in completed["results"]}) == 2
    for result in completed["results"]:
        assert studio.media_path(job["id"], result["output"]).read_bytes() == b"result"
    restored = BatchStudio(tmp_path).get(job["id"])
    assert restored == completed
    with pytest.raises(ValueError): studio.start(job["id"], {"prompt": "again"})
    with pytest.raises(ValueError): studio.upload(job["id"], "extra.png", PNG)


def test_cancel_finishes_current_image_and_blocks_duplicate_jobs(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def run(self, **kwargs):
        entered.set()
        assert release.wait(3)
        assert kwargs["cancel_event"].is_set()
        source = kwargs["images"][0]
        output = kwargs["output_dir"] / "first.png"
        output.parent.mkdir()
        output.write_bytes(PNG)
        item = BatchItemResult(source, output, "fake", 43)
        kwargs["on_progress"](1, 2, item)
        return BatchRunResult((item,), cancelled=True)

    monkeypatch.setattr(batch_studio.QwenBatchImageEditor, "run", run)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    studio.upload(job["id"], "second.png", PNG)
    other = draft(studio)
    studio.start(job["id"], {"prompt": "edit"})
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError): studio.start(job["id"], {"prompt": "edit"})
        with pytest.raises(ValueError): studio.start(other["id"], {"prompt": "edit"})
        assert studio.cancel(job["id"])["status"] == "stopping"
    finally:
        release.set()
    result = finish(studio, job["id"])
    assert result["status"] == "cancelled"
    assert result["completed"] == result["succeeded"] == 1


def test_partial_failure_and_startup_failure(tmp_path, monkeypatch):
    from test_batch_image_edit import FakeClient
    client = FakeClient()
    monkeypatch.setattr(batch_studio, "ComfyUIClient", lambda url: client)
    def fail_download(*args): raise RuntimeError("fake download failure")
    monkeypatch.setattr(client, "download_asset", fail_download)
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    studio.start(job["id"], {"prompt": "edit"})
    result = finish(studio, job["id"])
    assert result["status"] == "completed_with_errors"
    assert result["failed"] == 1 and result["results"][0]["error"]
    def fail_health(): raise RuntimeError("fake connection failure")
    monkeypatch.setattr(client, "check_health", fail_health)
    job = draft(studio)
    studio.start(job["id"], {"prompt": "edit"})
    result = finish(studio, job["id"])
    assert result["status"] == "failed" and "connection" in result["message"]


def test_restart_marks_abandoned_job_interrupted(tmp_path):
    studio = BatchStudio(tmp_path)
    job = draft(studio)
    job["status"] = "running"
    studio._save(job)
    recovered = BatchStudio(tmp_path).get(job["id"])
    assert recovered["status"] == "interrupted"
    assert recovered["files"] == job["files"]


def test_second_server_cannot_mark_existing_jobs_interrupted(tmp_path, monkeypatch):
    import sys
    from comfyui_py_workflow.local_ui import main
    studio = BatchStudio(tmp_path / "batch-jobs")
    job = draft(studio)
    job["status"] = "running"
    studio._save(job)
    first = SingleInstanceHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
    monkeypatch.setattr(sys, "argv", ["cpw-local-ui", "--project-root", str(tmp_path),
                                    "--port", str(first.server_address[1]), "--no-browser"])
    try:
        with pytest.raises(SystemExit): main()
        assert studio.get(job["id"])["status"] == "running"
    finally:
        first.server_close()


def test_http_batch_upload_media_and_origin(tmp_path):
    class Handler(StudioRequestHandler):
        studio = OfflineStudio(tmp_path / "stories")
        batch = BatchStudio(tmp_path / "batch")
        def log_message(self, *args): pass

    server = SingleInstanceHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    def request(method, path, body=None, headers=None):
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()

    try:
        status, body = request("GET", "/api/batch/tools")
        assert status == 200 and json.loads(body)["tools"][0]["id"] == "image-edit"
        status, body = request("POST", "/api/batch/create", b"{}")
        assert status == 201
        job = json.loads(body)
        status, body = request("POST", f"/api/batch/upload?id={job['id']}&filename={quote('image.png')}", PNG)
        assert status == 201
        uploaded = json.loads(body)
        path = f"/batch-media/{job['id']}/{uploaded['files'][0]['path']}"
        assert request("GET", path) == (200, PNG)
        assert request("GET", path, headers={"Range": "bytes=0-7"}) == (206, PNG[:8])
        assert request("GET", f"/batch-media/{job['id']}/job.json")[0] == 404
        assert request("POST", "/api/batch/create", b"{}", {"Origin": "https://example.com"})[0] == 400
        assert len(json.loads(request("GET", "/api/batch/jobs")[1])["jobs"]) == 1
        assert request("GET", "/static/batch.js")[0] == 200
        # The story API continues to work under the same handler.
        assert request("POST", "/api/project/text", json.dumps({"text": "A test story"}))[0] == 201
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_workspace_markup_is_balanced_and_keeps_story_panels_together():
    class Parser(HTMLParser):
        stack = []
        ids = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                assert attrs["id"] not in self.ids
                self.ids[attrs["id"]] = list(self.stack)
            if tag not in {"meta", "link", "input", "img", "br", "hr"}:
                self.stack.append((tag, attrs.get("id")))
        def handle_endtag(self, tag):
            assert self.stack and self.stack[-1][0] == tag, (tag, self.stack)
            self.stack.pop()
    parser = Parser()
    parser.feed((WEB_ROOT / "index.html").read_text(encoding="utf-8"))
    assert not parser.stack
    assert ("div", "view-story") in parser.ids["results-panel"]
    assert ("div", "view-story") not in parser.ids["batch-start"]
    assert ("div", "view-batch") in parser.ids["batch-start"]
    assert ("div", "view-settings") in parser.ids["services-panel"]
