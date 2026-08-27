from __future__ import annotations

import json
import mimetypes
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ComfyUIError(RuntimeError):
    """Raised when a ComfyUI request cannot be completed."""


class ComfyUIExecutionError(ComfyUIError):
    """Raised when ComfyUI reports a workflow execution failure."""


@dataclass(frozen=True)
class ComfyUIAsset:
    node_id: str
    kind: str
    filename: str
    subfolder: str
    folder_type: str


def load_workflow_template(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        workflow = json.load(handle)
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow template must be a JSON object")
    return workflow


class ComfyUIClient:
    """Small transport boundary for exported ComfyUI API-format workflows."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def check_health(self) -> dict[str, Any]:
        return self._request_json("/system_stats")

    @staticmethod
    def apply_substitutions(
        workflow: dict[str, Any], substitutions: dict[tuple[str, str], Any]
    ) -> dict[str, Any]:
        updated = deepcopy(workflow)
        for (node_id, input_name), value in substitutions.items():
            try:
                updated[node_id]["inputs"][input_name] = value
            except KeyError as exc:
                raise KeyError(f"Missing workflow input {node_id}.{input_name}") from exc
        return updated

    def submit(self, workflow: dict[str, Any], client_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id
        result = self._request_json("/prompt", method="POST", payload=payload)
        if "prompt_id" not in result:
            raise ComfyUIError(f"ComfyUI did not return a prompt_id: {result}")
        return result

    def get_history(self, prompt_id: str) -> dict[str, Any] | None:
        result = self._request_json(f"/history/{quote(prompt_id, safe='')}")
        history = result.get(prompt_id)
        if history is None:
            return None
        if not isinstance(history, dict):
            raise ComfyUIError("ComfyUI returned malformed history data")
        return history

    def wait_for_completion(
        self,
        prompt_id: str,
        timeout_seconds: float = 900.0,
        poll_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            history = self.get_history(prompt_id)
            if history is not None:
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIExecutionError(self._execution_error_message(history))
                if status.get("completed") is True or "outputs" in history:
                    return history
            sleep(poll_interval_seconds)
        raise TimeoutError(f"ComfyUI prompt {prompt_id} did not finish within {timeout_seconds:g} seconds")

    def run(
        self,
        workflow: dict[str, Any],
        timeout_seconds: float = 900.0,
        client_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        result = self.submit(workflow, client_id=client_id or str(uuid.uuid4()))
        prompt_id = str(result["prompt_id"])
        return prompt_id, self.wait_for_completion(prompt_id, timeout_seconds=timeout_seconds)

    def upload_image(
        self,
        path: str | Path,
        *,
        filename: str | None = None,
        subfolder: str = "cpw",
        overwrite: bool = True,
    ) -> dict[str, Any]:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        upload_name = filename or source.name
        boundary = f"----cpw-{uuid.uuid4().hex}"
        fields = {
            "type": "input",
            "subfolder": subfolder,
            "overwrite": "true" if overwrite else "false",
        }
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
            )
        content_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{upload_name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode("utf-8")
        )
        chunks.append(source.read_bytes())
        chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
        return self._request_json(
            "/upload/image",
            method="POST",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    @staticmethod
    def input_reference(upload_result: dict[str, Any]) -> str:
        name = str(upload_result["name"])
        subfolder = str(upload_result.get("subfolder", "")).strip("/\\")
        return f"{subfolder}/{name}" if subfolder else name

    @staticmethod
    def output_assets(history: dict[str, Any], node_id: str | None = None) -> list[ComfyUIAsset]:
        outputs = history.get("outputs", {})
        selected = {node_id: outputs.get(node_id, {})} if node_id else outputs
        assets: list[ComfyUIAsset] = []
        for current_node_id, output in selected.items():
            if not isinstance(output, dict):
                continue
            for kind, values in output.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    if not isinstance(value, dict) or "filename" not in value:
                        continue
                    assets.append(ComfyUIAsset(
                        node_id=str(current_node_id),
                        kind=str(kind),
                        filename=str(value["filename"]),
                        subfolder=str(value.get("subfolder", "")),
                        folder_type=str(value.get("type", "output")),
                    ))
        return assets

    def download_asset(self, asset: ComfyUIAsset, destination: str | Path) -> Path:
        query = urlencode({
            "filename": asset.filename,
            "subfolder": asset.subfolder,
            "type": asset.folder_type,
        })
        data = self._request_bytes(f"/view?{query}")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = dict(headers or {})
        request_data = data
        if payload is not None:
            request_data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        raw = self._open(path, method=method, data=request_data, headers=request_headers)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComfyUIError("ComfyUI returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ComfyUIError("ComfyUI returned an unexpected response")
        return result

    def _request_bytes(self, path: str) -> bytes:
        return self._open(path, method="GET", data=None, headers={})

    def _open(self, path: str, *, method: str, data: bytes | None, headers: dict[str, str]) -> bytes:
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIError(f"ComfyUI request failed ({exc.code} {exc.reason}): {body}") from exc
        except (URLError, TimeoutError) as exc:
            raise ComfyUIError(f"ComfyUI request failed: {exc}") from exc

    @staticmethod
    def _execution_error_message(history: dict[str, Any]) -> str:
        messages = history.get("status", {}).get("messages", [])
        for message in reversed(messages):
            if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
                return f"ComfyUI execution failed: {message[1]}"
        return "ComfyUI execution failed"
