from __future__ import annotations

import argparse
import json
import mimetypes
import re
import socket
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .offline import LOOPBACK_HOSTS
from .studio import OfflineStudio


WEB_ROOT = Path(__file__).with_name("web")


class SingleInstanceHTTPServer(ThreadingHTTPServer):
    """Refuse a second server on the same port, including on Windows."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def parse_byte_range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or (not match.group(1) and not match.group(2)) or size <= 0:
        raise ValueError("Invalid byte range")
    start_text, end_text = match.groups()
    if start_text:
        start = int(start_text)
        end = min(size - 1, int(end_text)) if end_text else size - 1
    else:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Invalid suffix byte range")
        start = max(0, size - suffix_length)
        end = size - 1
    if start >= size or start > end:
        raise ValueError("Byte range is outside the file")
    return start, end


class StudioRequestHandler(BaseHTTPRequestHandler):
    studio: OfflineStudio
    server_version = "CPWOfflineStudio/0.5"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_file(WEB_ROOT / "index.html", cache=False)
                return
            if parsed.path.startswith("/static/"):
                self._send_file(WEB_ROOT / Path(parsed.path).name, cache=False)
                return
            if parsed.path == "/api/projects":
                self._send_json({"projects": self.studio.list_projects()})
                return
            if parsed.path == "/api/project":
                project_id = self._query(parsed, "id")
                self._send_json(self.studio.project_payload(project_id))
                return
            if parsed.path == "/api/status":
                lm_url = self._query(parsed, "lm", "http://127.0.0.1:1234/v1")
                comfy_url = self._query(parsed, "comfy", "http://127.0.0.1:8188")
                self._send_json(self.studio.service_status(lm_url, comfy_url))
                return
            if parsed.path.startswith("/media/"):
                parts = parsed.path.split("/", 3)
                if len(parts) != 4:
                    raise ValueError("Invalid media URL")
                project_id = unquote(parts[2])
                relative = unquote(parts[3])
                self._send_media_file(self.studio.media_path(project_id, relative))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self._check_origin()
            if parsed.path == "/api/project/file":
                filename = self._query(parsed, "filename")
                data = self._read_body(max_bytes=100 * 1024 * 1024)
                self._send_json(self.studio.create_file_project(filename, data), status=201)
                return
            if parsed.path == "/api/project/reference-image":
                project_id = self._query(parsed, "project_id")
                filename = self._query(parsed, "filename")
                data = self._read_body(max_bytes=25 * 1024 * 1024)
                self._send_json(
                    self.studio.attach_reference_image(project_id, filename, data),
                    status=201,
                )
                return

            body = self._read_json()
            if parsed.path == "/api/project/text":
                result = self.studio.create_text_project(
                    str(body.get("text", "")),
                    str(body.get("filename", "story.md")),
                )
                self._send_json(result, status=201)
            elif parsed.path == "/api/analyze":
                self._send_json(self.studio.analyze(
                    str(body["project_id"]),
                    lm_studio_url=str(body.get("lm_studio_url", "http://127.0.0.1:1234/v1")),
                    model=str(body.get("model") or "") or None,
                    output_language=str(body.get("output_language", "Chinese")),
                ))
            elif parsed.path == "/api/plan":
                self._send_json(self.studio.create_plan(
                    str(body["project_id"]),
                    duration_seconds=int(body["duration_seconds"]),
                    aspect_ratio=str(body.get("aspect_ratio", "16:9")),
                    style=str(body.get("style") or "") or None,
                    dialogue_mode=str(body.get("dialogue_mode", "auto")),
                    lm_studio_url=str(body.get("lm_studio_url", "http://127.0.0.1:1234/v1")),
                    model=str(body.get("model") or "") or None,
                    output_language=str(body.get("output_language", "Chinese")),
                ))
            elif parsed.path == "/api/save-plan":
                plan = body.get("plan")
                if not isinstance(plan, dict):
                    raise ValueError("plan must be a JSON object")
                self._send_json(self.studio.save_plan(str(body["project_id"]), plan))
            elif parsed.path == "/api/generate":
                self._send_json(self.studio.start_generation(
                    str(body["project_id"]),
                    comfyui_url=str(body.get("comfyui_url", "http://127.0.0.1:8188")),
                    base_seed=int(body.get("base_seed", 1000)),
                ), status=202)
            elif parsed.path == "/api/cancel":
                self._send_json(self.studio.cancel_generation(str(body["project_id"])))
            elif parsed.path == "/api/open-folder":
                path = self.studio.open_project_folder(str(body["project_id"]))
                self._send_json({"ok": True, "path": path})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error(exc)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/media/"):
                parts = parsed.path.split("/", 3)
                if len(parts) != 4:
                    raise ValueError("Invalid media URL")
                project_id = unquote(parts[2])
                relative = unquote(parts[3])
                self._send_media_file(
                    self.studio.media_path(project_id, relative),
                    head_only=True,
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error(exc)

    def _read_body(self, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Request body is empty")
        if length > max_bytes:
            raise ValueError(f"Request body exceeds {max_bytes} bytes")
        return self.rfile.read(length)

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON request body must be an object")
        return data

    @staticmethod
    def _query(parsed: Any, name: str, default: str | None = None) -> str:
        values = parse_qs(parsed.query).get(name)
        if values:
            return values[0]
        if default is not None:
            return default
        raise ValueError(f"Missing query parameter: {name}")

    def _send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, *, cache: bool = True) -> None:
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_media_file(self, path: Path, *, head_only: bool = False) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            try:
                parsed_range = parse_byte_range(range_header, size)
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parsed_range is not None:
                start, end = parsed_range
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        parsed = urlparse(origin)
        host = self.headers.get("Host", "")
        if (parsed.hostname or "").lower() not in LOOPBACK_HOSTS or parsed.netloc != host:
            raise PermissionError("Cross-origin requests are blocked in offline mode")

    def _send_error(self, exc: Exception) -> None:
        status = HTTPStatus.NOT_FOUND if isinstance(exc, FileNotFoundError) else HTTPStatus.BAD_REQUEST
        self._send_json({
            "error": type(exc).__name__,
            "message": str(exc),
        }, status=status)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fully local Offline Story Studio UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.host.lower() not in LOOPBACK_HOSTS:
        parser.error("Offline mode only permits a loopback --host")

    StudioRequestHandler.studio = OfflineStudio(args.project_root)
    try:
        server = SingleInstanceHTTPServer((args.host, args.port), StudioRequestHandler)
    except OSError as exc:
        parser.exit(
            2,
            f"Offline Story Studio could not start on {args.host}:{args.port}. "
            f"Another instance may already be running ({exc}).\n",
        )
    url = f"http://{args.host}:{args.port}"
    print(f"Offline Story Studio: {url}")
    print(f"Projects: {StudioRequestHandler.studio.project_root.resolve()}")
    print("Only loopback connections are accepted. Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Offline Story Studio...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
