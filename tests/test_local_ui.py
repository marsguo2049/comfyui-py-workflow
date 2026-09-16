from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from comfyui_py_workflow.batch_studio import BatchStudio
from comfyui_py_workflow.local_ui import (
    SingleInstanceHTTPServer,
    StudioRequestHandler,
    parse_byte_range,
    render_index,
)


def test_local_ui_port_is_single_instance() -> None:
    first = SingleInstanceHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
    host, port = first.server_address
    try:
        with pytest.raises(OSError):
            second = SingleInstanceHTTPServer((host, port), StudioRequestHandler)
            second.server_close()
    finally:
        first.server_close()


def test_status_uses_real_client_constructor(monkeypatch) -> None:
    from comfyui_py_workflow.client import ComfyUIClient
    from comfyui_py_workflow.local_ui import comfyui_status

    def health(client):
        assert client.timeout_seconds == 3
        return {"system": {}}

    monkeypatch.setattr(ComfyUIClient, "check_health", health)
    assert comfyui_status("http://127.0.0.1:8188")["ok"] is True


def test_byte_ranges_include_suffix_and_open_ended_forms() -> None:
    assert parse_byte_range(None, 1000) is None
    assert parse_byte_range("bytes=100-199", 1000) == (100, 199)
    assert parse_byte_range("bytes=900-", 1000) == (900, 999)
    assert parse_byte_range("bytes=-100", 1000) == (900, 999)
    assert parse_byte_range("bytes=-2000", 1000) == (0, 999)


@pytest.mark.parametrize("value", ["bytes=-0", "bytes=1000-", "bytes=9-2", "items=1-2"])
def test_invalid_byte_ranges_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_byte_range(value, 1000)


def test_rendered_workbench_is_comfyui_only_and_uses_shared_batch_fragment() -> None:
    html = render_index()
    assert "ComfyUI Workbench" in html
    assert '<div id="view-batch" class="hidden">' in html
    assert "批量首尾帧视频" in html
    assert "LM Studio" in html
    assert "view-story" in html
    assert "view-comic" in html
    assert "lm-url" in html
    assert "story-text" in html
    assert "translation" not in html.lower()
    assert "/static/app.js" in html
    assert "/static/comic.js" in html


def test_standalone_http_boundary_includes_creative_but_not_translation(tmp_path) -> None:
    from comfyui_py_workflow.studio import OfflineStudio
    from comfyui_py_workflow.comic_studio import ComicStudio
    class Handler(StudioRequestHandler):
        batch = BatchStudio(tmp_path / "batch-jobs")
        studio = OfflineStudio(tmp_path / "stories")
        comic = ComicStudio(tmp_path / "comic-jobs")

        def log_message(self, *args):
            pass

    server = SingleInstanceHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    try:
        connection.request("GET", "/api/batch/tools")
        response = connection.getresponse()
        assert response.status == 200
        assert {tool["id"] for tool in json.loads(response.read())["tools"]} == {
            "image-edit",
            "first-last-video",
        }

        for method, path, body, expected in [
            ("GET", "/api/projects", None, 200),
            ("GET", "/api/comic/jobs", None, 200),
            ("POST", "/api/project/text", b'{"text":"A synthetic story."}', 201),
            ("POST", "/api/comic/create", b'{"text":"A synthetic comic."}', 201),
            ("POST", "/api/translate", b"{}", 404),
        ]:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            assert response.status == expected
            response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join(3)
