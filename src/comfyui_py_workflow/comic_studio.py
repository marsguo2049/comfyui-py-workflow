"""Local comic projects using Studio's persistent job storage and locking."""
from __future__ import annotations

import math
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .batch_studio import BatchStudio, MAX_FILE_BYTES
from .client import ComfyUIClient
from .comic import COMIC_ASPECTS, ComicImageRenderer, create_comic_plan, export_comic, validate_comic_plan
from .documents import read_document
from .lmstudio import LMStudioClient
from .offline import is_loopback_url
from .studio import ALLOWED_SOURCE_SUFFIXES, utc_now


class ComicStudio(BatchStudio):
    """Share job persistence, listing and folder opening with the batch workspace."""
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.workflow_root = Path(__file__).resolve().parents[2] / "workflows" / "api"
        for path in self.root.glob("*/job.json"):
            try:
                job = self._load(path.parent.name)
                if job["status"] in {"planning", "interrupted"}:
                    job.update(status="interrupted", message="服务已重启。已有分格保留，可继续生成；未完成的分镜规划请重新启动。")
                    self._save(job)
            except (OSError, ValueError, KeyError):
                continue

    def create(self, text: str = "", *, filename: str = "story.txt", data: bytes | None = None) -> dict:
        suffix = Path(filename.replace("\\", "/")).suffix.lower()
        if suffix not in ALLOWED_SOURCE_SUFFIXES:
            raise ValueError("支持 TXT、Markdown、DOCX 和 PDF 故事文件")
        content = data if data is not None else text.strip().encode("utf-8")
        if not content or len(content) > 100 * 1024 * 1024:
            raise ValueError("故事不能为空，文件不能超过 100 MB")
        if data is None and len(text) > 120000:
            raise ValueError("故事文字最多 120000 字符")
        with self._lock:
            job = dict(id=uuid.uuid4().hex, kind="comic", status="draft", created_at=utc_now(),
                       title="未命名漫画", source=f"source{suffix}", reference=None, revision=0,
                       files=[], results=[], exports=[], completed=0, succeeded=0, failed=0,
                       plan=None, warnings=[], message="故事已保存，可以生成漫画分镜。")
            directory = self._dir(job["id"])
            directory.mkdir()
            (directory / job["source"]).write_bytes(content)
            self._save(job)
            return deepcopy(job)

    def _idle(self, job: dict) -> None:
        thread = self._threads.get(job["id"])
        if thread and thread.is_alive():
            raise ValueError("当前漫画任务仍在运行，请完成或停止后再操作")

    def list_jobs(self) -> list[dict]:
        with self._lock:
            jobs = super().list_jobs()
            for job in jobs:
                job["title"] = self._load(job["id"]).get("title", "未命名漫画")
            return jobs

    def attach_reference(self, job_id: str, data: bytes) -> dict:
        if not data or len(data) > MAX_FILE_BYTES:
            raise ValueError("参考图须为 1 字节至 25 MB")
        suffix = self._image_suffix(data)
        if suffix not in {".png", ".jpg", ".webp"}:
            raise ValueError("漫画参考图支持 PNG、JPEG 或 WebP")
        with self._lock:
            job = self._load(job_id)
            self._idle(job)
            if job["plan"] or job["results"]:
                raise ValueError("请在生成分镜前添加参考图；更换参考图请新建漫画")
            relative = f"reference{suffix}"
            (self._dir(job_id) / relative).write_bytes(data)
            job["reference"] = relative
            self._save(job)
            return job

    def _launch(self, job: dict, status: str, action: Callable[[str, threading.Event], None]) -> dict:
        self._idle(job)
        self._threads = {key: thread for key, thread in self._threads.items() if thread.is_alive()}
        if self._threads:
            raise ValueError("已有漫画任务运行中，请等待或停止后再开始")
        event = self._cancel[job["id"]] = threading.Event()
        job.update(status=status, failed=0, warnings=[], message="正在规划漫画分镜…" if status == "planning" else "正在准备漫画图片生成…")
        self._save(job)
        def worker() -> None:
            try:
                action(job["id"], event)
            except Exception as exc:
                self._update(job["id"], status="failed", failed=1, message=f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._cancel.pop(job["id"], None)
        thread = threading.Thread(target=worker, daemon=True, name=f"cpw-comic-{job['id']}")
        self._threads[job["id"]] = thread
        thread.start()
        return deepcopy(job)

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            job = self._load(job_id)
            if job["status"] == "stopping" and set(values) == {"message"}:
                return
            job.update(values)
            self._save(job)

    def plan(self, job_id: str, settings: dict) -> dict:
        count = int(settings.get("panel_count", 6))
        aspect = str(settings.get("aspect_ratio", "3:4"))
        style = str(settings.get("style") or "清晰漫画线稿，柔和色彩，人物与服装保持一致").strip()
        url = str(settings.get("lm_studio_url", "http://127.0.0.1:1234/v1"))
        if not 2 <= count <= 16 or aspect not in COMIC_ASPECTS or len(style) > 1000:
            raise ValueError("请检查漫画格数（2–16）、画幅和画风要求")
        if not is_loopback_url(url):
            raise ValueError("仅允许本机 LM Studio 地址")
        with self._lock:
            job = self._load(job_id)
            self._idle(job)
            if job["results"]:
                raise ValueError("漫画已有图片，请编辑现有分镜或新建漫画")
            def action(job_id: str, event: threading.Event) -> None:
                client = LMStudioClient(url, timeout_seconds=900)
                model = client.resolve_model(str(settings.get("model") or "") or None)
                source = read_document(self._dir(job_id) / job["source"])
                if not source.strip():
                    raise ValueError("故事文件没有可读取的文字")
                result = create_comic_plan(client, model=model, source=source, count=count,
                                           aspect=aspect, style=style, has_reference=bool(job["reference"]))
                warnings = []
                if settings.get("unload_model", True):
                    try:
                        client.unload_model(model)
                    except Exception:
                        warnings.append("未能自动卸载文字模型；显存不足时请在生图前手动卸载。")
                self._update(job_id, plan=result, title=result["title"], revision=job["revision"] + 1,
                             exports=[], status="cancelled" if event.is_set() else "ready", warnings=warnings,
                             message="分镜已保存。请审阅每格画面、旁白和对白，再开始生成。")
            return self._launch(job, "planning", action)

    def save_plan(self, job_id: str, data: Any, revision: int) -> dict:
        plan = validate_comic_plan(data)
        with self._lock:
            job = self._load(job_id)
            self._idle(job)
            if revision != job["revision"]:
                raise ValueError("分镜已更新，请重新加载后再保存")
            old = job["plan"]
            keep = 0
            if old and all(old[key] == plan[key] for key in ["style", "character_bible", "aspect_ratio", "negative_prompt"]):
                for previous, current in zip(old["panels"], plan["panels"]):
                    if any(previous[key] != current[key] for key in ["prompt", "reference"]):
                        break
                    keep += 1
            job["results"] = job["results"][:keep]
            job.update(plan=plan, title=plan["title"], revision=revision + 1, exports=[],
                       completed=len(job["results"]), succeeded=len(job["results"]), failed=0,
                       status="ready", message="分镜已保存。画面要求变动的分格及后续图片需要重新生成。")
            if len(job["results"]) == len(plan["panels"]):
                job["exports"] = export_comic(plan, self._dir(job_id), job["results"])
                job.update(status="succeeded", message="文字修改已应用到阅读页与图片包。")
            self._save(job)
            return job

    def start(self, job_id: str, settings: dict) -> dict:
        url = str(settings.get("comfyui_url", "http://127.0.0.1:8188"))
        seed, timeout = int(settings.get("base_seed", 1000)), float(settings.get("timeout_seconds", 900))
        if not is_loopback_url(url) or not 0 <= seed <= 2**53 - 17 or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
            raise ValueError("请检查本机 ComfyUI 地址、种子和超时（1–86400 秒）")
        with self._lock:
            job = self._load(job_id)
            self._idle(job)
            plan = validate_comic_plan(job["plan"])
            if int(settings.get("revision", -1)) != job["revision"]:
                raise ValueError("分镜版本已变化，请刷新后重新确认")
            retry = settings.get("retry_from")
            if retry is not None:
                retry = int(retry)
                if not 1 <= retry <= len(job["results"]) + 1:
                    raise ValueError("重做起始格超出已有分格范围")
                job["results"] = job["results"][:retry - 1]
            if job["results"] and seed != job.get("base_seed"):
                raise ValueError("继续生成时须沿用原种子；修改种子请从第一格重做")
            directory = self._dir(job_id)
            for result in job["results"]:
                if not self.media_path(job_id, result["path"]).is_file():
                    raise ValueError("已有分格图片缺失，请从第一格重做")
            job.update(base_seed=seed, exports=[], completed=len(job["results"]), succeeded=len(job["results"]))
            def action(job_id: str, event: threading.Event) -> None:
                client = ComfyUIClient(url)
                client.check_health()
                renderer = ComicImageRenderer(client, self.workflow_root)
                results = list(job["results"])
                for panel in plan["panels"][len(results):]:
                    if event.is_set():
                        break
                    index = panel["index"]
                    self._update(job_id, message=f"正在生成第 {index}/{len(plan['panels'])} 格…")
                    source = None
                    if panel["reference"] == "previous" and results:
                        source = directory / results[-1]["path"]
                    elif job["reference"]:
                        source = directory / job["reference"]
                    elif results:
                        source = directory / results[0]["path"]
                    relative = f"panel-{index:04d}.png"
                    renderer.render(plan, panel, source=source, destination=directory / relative, seed=seed + index, timeout=timeout)
                    results.append(dict(index=index, path=relative, seed=seed + index))
                    self._update(job_id, results=results, completed=len(results), succeeded=len(results))
                if len(results) == len(plan["panels"]):
                    exports = export_comic(plan, directory, results)
                    self._update(job_id, status="succeeded", exports=exports, message="漫画已完成，可阅读、打印或下载图片包。")
                else:
                    self._update(job_id, status="cancelled", message="已在当前图片完成后停止，可继续生成剩余分格。")
            return self._launch(job, "running", action)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._load(job_id)
            event = self._cancel.get(job_id)
            if event:
                event.set()
                job.update(status="stopping", message="停止请求已记录，将在当前模型调用完成后生效。")
                self._save(job)
            return job

    def media_path(self, job_id: str, relative: str) -> Path:
        job = self.get(job_id)
        allowed = {result["path"] for result in job["results"]} | set(job["exports"])
        if job["reference"]:
            allowed.add(job["reference"])
        directory = self._dir(job_id)
        path = (directory / relative).resolve()
        if relative not in allowed or not path.is_relative_to(directory) or not path.is_file():
            raise FileNotFoundError("找不到漫画文件")
        return path
