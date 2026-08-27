from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import ComfyUIClient
from .documents import read_document
from .duration_advisor import analyze_story_duration
from .lmstudio import LMStudioClient
from .offline import check_comfyui, check_lm_studio, local_capabilities
from .story_plan import StoryPlan
from .story_planner import create_story_plan
from .story_video import GenerationCancelled, StoryVideoExecutor


PROJECT_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
ALLOWED_SOURCE_SUFFIXES = {".txt", ".md", ".markdown", ".docx", ".pdf"}
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_REFERENCE_IMAGE_BYTES = 25 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OfflineStudio:
    def __init__(self, project_root: str | Path | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        self.repository_root = repository_root
        self.project_root = Path(project_root or repository_root / "outputs" / "offline-studio")
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.workflows = [
            repository_root / "workflows" / "api" / "z-image-turbo.api.json",
            repository_root / "workflows" / "api" / "qwen-image-edit-2509.api.json",
            repository_root / "workflows" / "api" / "minimax-h3-first-last-frame.api.json",
        ]
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        for state_path in sorted(self.project_root.glob("*/project.json"), reverse=True):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            projects.append({
                "project_id": state.get("project_id"),
                "status": state.get("status"),
                "source_name": state.get("source_name"),
                "title": state.get("title"),
                "updated_at": state.get("updated_at"),
            })
        return projects

    def create_text_project(self, text: str, filename: str = "story.md") -> dict[str, Any]:
        if not text.strip():
            raise ValueError("故事内容不能为空")
        safe_name = self._safe_source_name(filename, default="story.md")
        return self._create_project(safe_name, text.encode("utf-8"))

    def create_file_project(self, filename: str, data: bytes) -> dict[str, Any]:
        if not data:
            raise ValueError("上传的文件为空")
        if len(data) > 100 * 1024 * 1024:
            raise ValueError("文件超过 100 MB 本地限制")
        safe_name = self._safe_source_name(filename)
        return self._create_project(safe_name, data)

    def attach_reference_image(
        self,
        project_id: str,
        filename: str,
        data: bytes,
    ) -> dict[str, Any]:
        if not data:
            raise ValueError("上传的参考图片为空")
        if len(data) > MAX_REFERENCE_IMAGE_BYTES:
            raise ValueError("参考图片超过 25 MB 本地限制")
        project_dir, state = self._load(project_id)
        if self._is_running(project_id):
            raise RuntimeError("视频生成期间不能更换参考图片")
        if (project_dir / "render" / "run.json").is_file():
            raise RuntimeError("这个项目已经开始渲染，不能再更换参考图片；请新建项目")
        safe_name, detected_suffix = self._safe_reference_name(filename, data)
        reference_dir = project_dir / "source" / "reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        destination = reference_dir / f"reference-image{detected_suffix}"
        temporary = reference_dir / f"reference-image{detected_suffix}.tmp"
        temporary.write_bytes(data)
        temporary.replace(destination)
        state.update({
            "reference_image_name": safe_name,
            "reference_image_file": str(destination.relative_to(project_dir)).replace("\\", "/"),
            "reference_image_bytes": len(data),
            "updated_at": utc_now(),
            "progress": {
                "stage": state.get("status", "source_ready"),
                "message": "单张参考图片已保存在本机，将作为新场景关键帧的视觉依据。",
            },
        })
        self._write_state(project_dir, state)
        return self.project_payload(project_id)

    def _create_project(self, source_name: str, data: bytes) -> dict[str, Any]:
        project_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        project_dir = self.project_root / project_id
        source_dir = project_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=False)
        source_path = source_dir / source_name
        source_path.write_bytes(data)
        state = {
            "schema_version": 1,
            "project_id": project_id,
            "status": "source_ready",
            "source_name": source_name,
            "source_file": str(source_path.relative_to(project_dir)).replace("\\", "/"),
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "progress": {
                "stage": "source_ready",
                "message": "故事文件已经保存在本机，等待 LM Studio 分析。",
            },
            "warnings": [],
        }
        self._write_state(project_dir, state)
        return self.project_payload(project_id)

    def analyze(
        self,
        project_id: str,
        *,
        lm_studio_url: str,
        model: str | None,
        output_language: str = "Chinese",
    ) -> dict[str, Any]:
        project_dir, state = self._load(project_id)
        self._set_status(
            project_dir,
            state,
            "analyzing",
            "正在使用本地文字模型理解故事并推荐时长。",
        )
        try:
            source_text = read_document(project_dir / state["source_file"])
            client = LMStudioClient(lm_studio_url, timeout_seconds=600)
            selected_model = client.resolve_model(model or None)
            analysis = analyze_story_duration(
                client,
                model=selected_model,
                source_text=source_text,
                output_language=output_language,
            )
            analysis.write(project_dir / "story-analysis.json")
            (project_dir / "duration-options.json").write_text(
                json.dumps(
                    [option.__dict__ for option in analysis.options],
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            state.update({
                "status": "analyzed",
                "title": analysis.title,
                "lm_studio_url": lm_studio_url,
                "lm_model": selected_model,
                "source_characters": len(source_text),
                "updated_at": utc_now(),
                "progress": {
                    "stage": "analyzed",
                    "message": "故事分析完成，请确认视频时长。",
                },
            })
            self._write_state(project_dir, state)
            return self.project_payload(project_id)
        except Exception as exc:
            self._fail(project_dir, state, "analysis_failed", exc)
            raise

    def create_plan(
        self,
        project_id: str,
        *,
        duration_seconds: int,
        aspect_ratio: str,
        style: str | None,
        dialogue_mode: str,
        lm_studio_url: str,
        model: str | None,
        output_language: str = "Chinese",
    ) -> dict[str, Any]:
        if duration_seconds < 15 or duration_seconds > 180 or duration_seconds % 5:
            raise ValueError("第一版视频时长必须是 15-180 秒之间的 5 秒倍数")
        project_dir, state = self._load(project_id)
        self._set_status(
            project_dir,
            state,
            "planning",
            "正在生成模型专用分镜提示词。",
        )
        try:
            source_text = read_document(project_dir / state["source_file"])
            client = LMStudioClient(lm_studio_url, timeout_seconds=900)
            selected_model = client.resolve_model(model or state.get("lm_model") or None)
            plan = create_story_plan(
                client,
                model=selected_model,
                source_text=source_text,
                target_duration_seconds=duration_seconds,
                clip_seconds=5,
                aspect_ratio=aspect_ratio,
                style=style,
                output_language=output_language,
                dialogue_mode=dialogue_mode,
                has_reference_image=bool(state.get("reference_image_file")),
            )
            plan.write(project_dir / "story-plan.json")
            warning = None
            try:
                unloaded = client.unload_model(selected_model)
                unload_message = f"已卸载 LM Studio 模型实例：{', '.join(unloaded)}"
            except Exception as exc:
                warning = f"无法自动卸载 LM Studio 模型，请在启动 ComfyUI 生成前手动卸载：{exc}"
                unload_message = warning
            warnings = list(state.get("warnings", []))
            if warning:
                warnings.append(warning)
            state.update({
                "status": "planned",
                "title": plan.title,
                "selected_duration_seconds": duration_seconds,
                "aspect_ratio": aspect_ratio,
                "dialogue_mode": plan.dialogue_mode,
                "lm_model": selected_model,
                "updated_at": utc_now(),
                "warnings": warnings,
                "progress": {
                    "stage": "planned",
                    "message": f"分镜已生成并通过校验。{unload_message}",
                },
            })
            self._write_state(project_dir, state)
            return self.project_payload(project_id)
        except Exception as exc:
            self._fail(project_dir, state, "planning_failed", exc)
            raise

    def save_plan(self, project_id: str, plan_data: dict[str, Any]) -> dict[str, Any]:
        project_dir, state = self._load(project_id)
        if self._is_running(project_id):
            raise RuntimeError("视频生成期间不能修改分镜")
        plan = StoryPlan.from_dict(plan_data)
        plan.write(project_dir / "story-plan.json")
        state.update({
            "status": "planned",
            "title": plan.title,
            "selected_duration_seconds": plan.target_duration_seconds,
            "aspect_ratio": plan.aspect_ratio,
            "dialogue_mode": plan.dialogue_mode,
            "updated_at": utc_now(),
            "progress": {"stage": "planned", "message": "分镜修改已经保存并通过校验。"},
        })
        self._write_state(project_dir, state)
        return self.project_payload(project_id)

    def service_status(self, lm_studio_url: str, comfyui_url: str) -> dict[str, Any]:
        return {
            "offline_mode": True,
            "lm_studio": check_lm_studio(lm_studio_url),
            "comfyui": check_comfyui(comfyui_url, self.workflows),
            "capabilities": local_capabilities(),
        }

    def start_generation(
        self,
        project_id: str,
        *,
        comfyui_url: str,
        base_seed: int = 1000,
    ) -> dict[str, Any]:
        project_dir, state = self._load(project_id)
        if not (project_dir / "story-plan.json").is_file():
            raise FileNotFoundError("请先生成并确认 story-plan.json")
        if self._is_running(project_id):
            raise RuntimeError("这个项目已经在生成中")
        preflight = check_comfyui(comfyui_url, self.workflows)
        if not preflight["ok"]:
            raise RuntimeError(preflight["message"] + self._preflight_details(preflight))

        cancel_event = threading.Event()
        self._cancel_events[project_id] = cancel_event
        state.update({
            "status": "rendering",
            "comfyui_url": comfyui_url,
            "updated_at": utc_now(),
            "progress": {
                "stage": "queued",
                "message": "ComfyUI 预检通过，准备开始本地生成。",
                "completed_shots": 0,
                "total_shots": len(StoryPlan.read(project_dir / "story-plan.json").shots),
            },
        })
        self._write_state(project_dir, state)
        thread = threading.Thread(
            target=self._render_worker,
            args=(project_id, comfyui_url, base_seed, cancel_event),
            name=f"cpw-render-{project_id}",
            daemon=True,
        )
        self._threads[project_id] = thread
        thread.start()
        return self.project_payload(project_id)

    def _render_worker(
        self,
        project_id: str,
        comfyui_url: str,
        base_seed: int,
        cancel_event: threading.Event,
    ) -> None:
        project_dir, state = self._load(project_id)
        render_dir = project_dir / "render"

        def progress(event: dict[str, Any]) -> None:
            with self._lock:
                _, current = self._load(project_id)
                current["status"] = "rendering"
                current["progress"] = event
                current["updated_at"] = utc_now()
                self._write_state(project_dir, current)

        try:
            executor = StoryVideoExecutor(
                ComfyUIClient(comfyui_url),
                z_image_workflow=self.workflows[0],
                qwen_edit_workflow=self.workflows[1],
                h3_workflow=self.workflows[2],
            )
            destination = executor.run(
                StoryPlan.read(project_dir / "story-plan.json"),
                output_root=project_dir,
                destination=render_dir,
                resume=(render_dir / "run.json").is_file(),
                base_seed=base_seed,
                progress_callback=progress,
                cancel_check=cancel_event.is_set,
                reference_image=(
                    project_dir / state["reference_image_file"]
                    if state.get("reference_image_file")
                    else None
                ),
            )
            _, state = self._load(project_id)
            state.update({
                "status": "succeeded",
                "updated_at": utc_now(),
                "final_video": str((destination / "final.mp4").relative_to(project_dir)).replace("\\", "/"),
                "progress": {
                    "stage": "completed",
                    "message": "最终视频已经生成并保存在本机。",
                },
            })
            self._write_state(project_dir, state)
        except GenerationCancelled as exc:
            _, state = self._load(project_id)
            self._fail(project_dir, state, "cancelled", exc)
        except Exception as exc:
            _, state = self._load(project_id)
            self._fail(project_dir, state, "render_failed", exc)
        finally:
            with self._lock:
                self._threads.pop(project_id, None)
                self._cancel_events.pop(project_id, None)

    def cancel_generation(self, project_id: str) -> dict[str, Any]:
        event = self._cancel_events.get(project_id)
        if event is None:
            raise RuntimeError("当前没有由本页面启动的生成任务")
        event.set()
        project_dir, state = self._load(project_id)
        state["progress"] = {
            "stage": "cancelling",
            "message": "已请求停止；当前 ComfyUI 模型步骤结束后生效。",
        }
        state["updated_at"] = utc_now()
        self._write_state(project_dir, state)
        return self.project_payload(project_id)

    def project_payload(self, project_id: str) -> dict[str, Any]:
        project_dir, state = self._load(project_id)
        payload: dict[str, Any] = {"state": state}
        for name in ("story-analysis.json", "duration-options.json", "story-plan.json"):
            path = project_dir / name
            if path.is_file():
                payload[name.removesuffix(".json").replace("-", "_")] = json.loads(
                    path.read_text(encoding="utf-8")
                )
        render_dir = project_dir / "render"
        payload["keyframes"] = [
            str(path.relative_to(project_dir)).replace("\\", "/")
            for path in sorted(render_dir.glob("frame-*.png"))
        ]
        payload["clips"] = [
            str(path.relative_to(project_dir)).replace("\\", "/")
            for path in sorted(render_dir.glob("clip-*.mp4"))
        ]
        final_path = render_dir / "final.mp4"
        payload["final_video"] = (
            str(final_path.relative_to(project_dir)).replace("\\", "/")
            if final_path.is_file()
            else None
        )
        payload["project_path"] = str(project_dir.resolve())
        payload["running"] = self._is_running(project_id)
        reference_path = project_dir / str(state.get("reference_image_file", ""))
        payload["reference_image"] = (
            str(reference_path.relative_to(project_dir)).replace("\\", "/")
            if state.get("reference_image_file") and reference_path.is_file()
            else None
        )
        return payload

    def media_path(self, project_id: str, relative_path: str) -> Path:
        project_dir, _ = self._load(project_id)
        candidate = (project_dir / relative_path).resolve()
        if project_dir.resolve() not in candidate.parents:
            raise ValueError("Invalid media path")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate

    def open_project_folder(self, project_id: str) -> str:
        project_dir, _ = self._load(project_id)
        if os.name == "nt":
            os.startfile(str(project_dir))
        else:
            raise RuntimeError("打开文件夹按钮当前只支持 Windows")
        return str(project_dir)

    def _load(self, project_id: str) -> tuple[Path, dict[str, Any]]:
        if not PROJECT_ID.fullmatch(project_id):
            raise ValueError("Invalid project id")
        project_dir = self.project_root / project_id
        state_path = project_dir / "project.json"
        if not state_path.is_file():
            raise FileNotFoundError(project_id)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return project_dir, state

    def _write_state(self, project_dir: Path, state: dict[str, Any]) -> None:
        with self._lock:
            destination = project_dir / "project.json"
            temporary = project_dir / "project.json.tmp"
            temporary.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(destination)

    def _set_status(
        self,
        project_dir: Path,
        state: dict[str, Any],
        status: str,
        message: str,
    ) -> None:
        state.pop("error", None)
        state.update({
            "status": status,
            "updated_at": utc_now(),
            "progress": {"stage": status, "message": message},
        })
        self._write_state(project_dir, state)

    def _fail(
        self,
        project_dir: Path,
        state: dict[str, Any],
        status: str,
        exc: Exception,
    ) -> None:
        message = f"{type(exc).__name__}: {exc}"
        state.update({
            "status": status,
            "updated_at": utc_now(),
            "error": message,
            "progress": {"stage": status, "message": message},
        })
        self._write_state(project_dir, state)

    def _is_running(self, project_id: str) -> bool:
        thread = self._threads.get(project_id)
        return thread is not None and thread.is_alive()

    @staticmethod
    def _safe_source_name(filename: str, default: str | None = None) -> str:
        name = Path(filename or default or "").name
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_SOURCE_SUFFIXES:
            raise ValueError("仅支持 TXT、Markdown、DOCX 和 PDF")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip(".-") or "story"
        return f"{stem[:80]}{suffix}"

    @staticmethod
    def _safe_reference_name(filename: str, data: bytes) -> tuple[str, str]:
        name = Path(filename).name
        supplied_suffix = Path(name).suffix.lower()
        if supplied_suffix not in ALLOWED_REFERENCE_SUFFIXES:
            raise ValueError("参考图片仅支持 PNG、JPG/JPEG 和 WebP")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            detected_suffix = ".png"
        elif data.startswith(b"\xff\xd8\xff"):
            detected_suffix = ".jpg"
        elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            detected_suffix = ".webp"
        else:
            raise ValueError("无法识别参考图片内容，文件可能损坏或格式不受支持")
        supplied_family = ".jpg" if supplied_suffix == ".jpeg" else supplied_suffix
        if supplied_family != detected_suffix:
            raise ValueError("参考图片的扩展名与实际内容不一致")
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip(".-") or "reference"
        return f"{stem[:80]}{supplied_suffix}", detected_suffix

    @staticmethod
    def _preflight_details(preflight: dict[str, Any]) -> str:
        details = []
        for key in ("missing_workflows", "missing_nodes", "missing_models"):
            values = preflight.get(key) or []
            if values:
                details.append(f" {key}: {', '.join(values)}")
        return "".join(details)
