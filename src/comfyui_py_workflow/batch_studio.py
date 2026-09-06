"""Persistent batch jobs for the local Studio, independent of the HTTP/UI layer."""
from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .batch_image_edit import QwenBatchImageEditor, default_qwen_workflow_path
from .client import ComfyUIClient, load_workflow_template
from .offline import is_loopback_url
from .studio import utc_now


JOB_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_JOB_BYTES = 500 * 1024 * 1024
MAX_FILES = 200
BATCH_TOOLS = [{"id": "image-edit", "name": "批量图片编辑", "description": "用同一段提示词，逐张修改图片。", "model": "Qwen Image Edit 2509"}]


class BatchStudio:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        # A stopped process cannot still own a running job. Keep partial results.
        for path in self.root.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["status"] in {"running", "stopping"}:
                    job.update(status="interrupted", message="服务已重启，已完成的结果仍可下载。请新建任务处理剩余图片。")
                    self._save(job)
            except (OSError, ValueError, KeyError):
                continue

    def _dir(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise ValueError("无效的批量任务编号")
        path = (self.root / job_id).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("任务路径越界")
        return path

    def _load(self, job_id: str) -> dict[str, Any]:
        return json.loads((self._dir(job_id) / "job.json").read_text(encoding="utf-8"))

    def _save(self, job: dict[str, Any]) -> None:
        job["updated_at"] = utc_now()
        path = self._dir(job["id"]) / "job.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)

    def create(self, kind: str = "image-edit") -> dict[str, Any]:
        if kind not in {tool["id"] for tool in BATCH_TOOLS}:
            raise ValueError("不支持的批量工具")
        with self._lock:
            job = dict(id=uuid.uuid4().hex, kind=kind, status="draft", created_at=utc_now(),
                       files=[], results=[], completed=0, succeeded=0, failed=0,
                       message="添加图片并填写修改要求，然后开始处理。")
            (self._dir(job["id"]) / "input").mkdir(parents=True)
            self._save(job)
            return deepcopy(job)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return self._load(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = []
            for path in self.root.glob("*/job.json"):
                try:
                    job = self._load(path.parent.name)
                    jobs.append({key: job[key] for key in ("id", "kind", "status", "updated_at", "succeeded", "failed")})
                except (OSError, ValueError, KeyError):
                    continue
            return sorted(jobs, key=lambda job: job["updated_at"], reverse=True)

    @staticmethod
    def _image_suffix(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
        if data.startswith(b"\xff\xd8\xff"): return ".jpg"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP": return ".webp"
        if data.startswith((b"GIF87a", b"GIF89a")): return ".gif"
        if data.startswith(b"BM"): return ".bmp"
        if data.startswith((b"II\x2a\x00", b"MM\x00\x2a")): return ".tiff"
        raise ValueError("请选择 PNG、JPEG、WebP、GIF、BMP 或 TIFF 图片")

    def upload(self, job_id: str, filename: str, data: bytes) -> dict[str, Any]:
        if not data or len(data) > MAX_FILE_BYTES:
            raise ValueError("单张图片须为 1 字节至 25 MB")
        suffix = self._image_suffix(data)
        name = filename.replace("\\", "/").rsplit("/", 1)[-1][:180]
        with self._lock:
            job = self._load(job_id)
            if job["status"] != "draft":
                raise ValueError("仅待开始的任务可以添加图片")
            if len(job["files"]) >= MAX_FILES or sum(f["bytes"] for f in job["files"]) + len(data) > MAX_JOB_BYTES:
                raise ValueError("每个任务最多 200 张图片、合计 500 MB")
            # Keep meaningful names, but never use a browser-supplied path as a disk path.
            stem = re.sub(r"[^\w\-]", "_", Path(name).stem)[:80] or "image"
            relative = f"input/{len(job['files']) + 1:04d}-{stem}{suffix}"
            (self._dir(job_id) / relative).write_bytes(data)
            job["files"].append(dict(name=name, path=relative, bytes=len(data)))
            self._save(job)
            return deepcopy(job)

    def start(self, job_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        prompt = str(settings.get("prompt", "")).strip()
        url = str(settings.get("comfyui_url", "http://127.0.0.1:8188")).strip()
        seed = int(settings.get("base_seed", 43))
        timeout = float(settings.get("timeout_seconds", 900))
        if not prompt or len(prompt) > 20000:
            raise ValueError("修改要求不能为空，且不能超过 20000 字符")
        if not is_loopback_url(url):
            raise ValueError("离线模式仅允许本机 ComfyUI 地址")
        if not 0 <= seed <= 2**53 - MAX_FILES or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
            raise ValueError("种子或超时参数超出范围（超时 1–86400 秒）")
        workflow = str(settings.get("workflow_path") or default_qwen_workflow_path())
        QwenBatchImageEditor._validate_template(load_workflow_template(workflow))
        with self._lock:
            job = self._load(job_id)
            if job["status"] != "draft" or not job["files"]:
                raise ValueError("任务已开始或尚未添加图片")
            self._threads = {key: thread for key, thread in self._threads.items() if thread.is_alive()}
            if self._threads:
                raise ValueError("已有批量任务运行中，请完成或停止后再开始")
            job.update(status="running", message="准备连接 ComfyUI…", settings=dict(
                prompt=prompt, negative_prompt=str(settings.get("negative_prompt", "")),
                comfyui_url=url, base_seed=seed, timeout_seconds=timeout,
                increment_seed=bool(settings.get("increment_seed", True)), workflow_path=workflow))
            self._save(job)
            event = self._cancel[job_id] = threading.Event()
            thread = self._threads[job_id] = threading.Thread(target=self._run, args=(job_id, event), daemon=True)
            thread.start()
            return deepcopy(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._load(job_id)
            if job["status"] in {"running", "stopping"} and job_id in self._cancel:
                self._cancel[job_id].set()
                job.update(status="stopping", message="将在当前图片完成后停止，已完成的结果会保留。")
                self._save(job)
            return job

    def _run(self, job_id: str, event: threading.Event) -> None:
        def update(**values: Any) -> None:
            with self._lock:
                current = self._load(job_id)
                if current["status"] == "stopping" and set(values) == {"message"}:
                    return
                current.update(values)
                self._save(current)

        def progress(done: int, total: int, item: Any) -> None:
            with self._lock:
                current = self._load(job_id)
                source = item.source.relative_to(directory).as_posix()
                original = next(f["name"] for f in current["files"] if f["path"] == source)
                current["results"].append(dict(name=original, source=source, seed=item.seed,
                    output=item.destination.relative_to(directory).as_posix() if item.destination else None,
                    error=item.error))
                current["completed"] = done
                current["succeeded"] += int(item.succeeded)
                current["failed"] += int(not item.succeeded)
                self._save(current)

        try:
            job = self.get(job_id)
            directory = self._dir(job_id)
            settings = dict(job["settings"])
            client = ComfyUIClient(settings.pop("comfyui_url"))
            result = QwenBatchImageEditor(client).run(
                images=[directory / f["path"] for f in job["files"]], output_dir=directory / "output",
                cancel_event=event, on_progress=progress, on_status=lambda message: update(message=message), **settings)
            status = "cancelled" if result.cancelled else "completed_with_errors" if result.failed_count else "succeeded"
            update(status=status, message=f"{'已停止' if result.cancelled else '处理完成'} · 成功 {result.succeeded_count} 张，失败 {result.failed_count} 张")
        except Exception as exc:
            update(status="failed", message=f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._cancel.pop(job_id, None)

    def media_path(self, job_id: str, relative: str) -> Path:
        job = self.get(job_id)
        allowed = {f["path"] for f in job["files"]} | {r["output"] for r in job["results"] if r["output"]}
        directory = self._dir(job_id)
        path = (directory / relative).resolve()
        if relative not in allowed or not path.is_relative_to(directory) or not path.is_file():
            raise FileNotFoundError("找不到任务图片")
        return path

    def open_folder(self, job_id: str) -> None:
        self.get(job_id)
        if hasattr(os, "startfile"):
            os.startfile(self._dir(job_id))
        else:
            raise ValueError("当前系统不支持从浏览器打开本地文件夹，请下载结果")
