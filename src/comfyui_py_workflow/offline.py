from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .client import ComfyUIClient, load_workflow_template
from .lmstudio import LMStudioClient


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MODEL_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".bin"}


def is_loopback_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").lower() in LOOPBACK_HOSTS


def check_lm_studio(base_url: str) -> dict[str, Any]:
    if not is_loopback_url(base_url):
        return {
            "ok": False,
            "state": "blocked",
            "message": "离线模式拒绝非本机 LM Studio 地址。",
            "models": [],
        }
    try:
        client = LMStudioClient(base_url, timeout_seconds=5)
        models = client.list_models()
    except Exception as exc:
        return {
            "ok": False,
            "state": "offline",
            "message": f"LM Studio 未连接：{type(exc).__name__}: {exc}",
            "models": [],
        }
    if not models:
        return {
            "ok": False,
            "state": "no_model",
            "message": "LM Studio 已启动，但没有可用的已加载模型。",
            "models": [],
        }
    return {
        "ok": True,
        "state": "ready",
        "message": f"LM Studio 已就绪，检测到 {len(models)} 个模型。",
        "models": models,
    }


def _workflow_requirements(path: Path) -> tuple[set[str], list[tuple[str, str, str]]]:
    workflow = load_workflow_template(path)
    classes: set[str] = set()
    model_inputs: list[tuple[str, str, str]] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        if class_type:
            classes.add(class_type)
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if isinstance(value, str) and Path(value).suffix.lower() in MODEL_SUFFIXES:
                model_inputs.append((str(node_id), str(input_name), value))
    return classes, model_inputs


def _allowed_values(object_info: dict[str, Any], class_type: str, input_name: str) -> list[str] | None:
    node_info = object_info.get(class_type, {})
    inputs = node_info.get("input", {}) if isinstance(node_info, dict) else {}
    for section_name in ("required", "optional"):
        section = inputs.get(section_name, {}) if isinstance(inputs, dict) else {}
        spec = section.get(input_name) if isinstance(section, dict) else None
        if isinstance(spec, list) and spec and isinstance(spec[0], list):
            return [str(value) for value in spec[0]]
    return None


def check_comfyui(base_url: str, workflow_paths: list[str | Path]) -> dict[str, Any]:
    if not is_loopback_url(base_url):
        return {
            "ok": False,
            "state": "blocked",
            "message": "离线模式拒绝非本机 ComfyUI 地址。",
            "missing_workflows": [],
            "missing_nodes": [],
            "missing_models": [],
        }
    paths = [Path(path) for path in workflow_paths]
    missing_workflows = [str(path) for path in paths if not path.is_file()]
    if missing_workflows:
        return {
            "ok": False,
            "state": "missing_workflows",
            "message": "缺少本地 API 工作流文件。",
            "missing_workflows": missing_workflows,
            "missing_nodes": [],
            "missing_models": [],
        }
    try:
        client = ComfyUIClient(base_url, timeout_seconds=8)
        system_stats = client.check_health()
        object_info = client.get_object_info()
    except Exception as exc:
        return {
            "ok": False,
            "state": "offline",
            "message": f"ComfyUI 未连接：{type(exc).__name__}: {exc}",
            "missing_workflows": [],
            "missing_nodes": [],
            "missing_models": [],
        }

    required_classes: set[str] = set()
    model_inputs: list[tuple[str, str, str, str]] = []
    for path in paths:
        classes, models = _workflow_requirements(path)
        required_classes.update(classes)
        for node_id, input_name, value in models:
            workflow = load_workflow_template(path)
            class_type = str(workflow[node_id].get("class_type", ""))
            model_inputs.append((class_type, input_name, value, path.name))
    missing_nodes = sorted(required_classes.difference(object_info))
    missing_models: list[str] = []
    for class_type, input_name, value, workflow_name in model_inputs:
        allowed = _allowed_values(object_info, class_type, input_name)
        if allowed is not None and value not in allowed:
            missing_models.append(f"{workflow_name}: {value}")

    ok = not missing_nodes and not missing_models
    message = "ComfyUI、工作流节点和模型已就绪。" if ok else "ComfyUI 已连接，但工作流依赖不完整。"
    return {
        "ok": ok,
        "state": "ready" if ok else "incomplete",
        "message": message,
        "missing_workflows": [],
        "missing_nodes": missing_nodes,
        "missing_models": sorted(set(missing_models)),
        "system_stats": system_stats,
    }


def local_capabilities() -> dict[str, Any]:
    text_pdf = importlib.util.find_spec("pypdf") is not None
    media = importlib.util.find_spec("av") is not None
    rapidocr_spec = importlib.util.find_spec("rapidocr")
    rapidocr = rapidocr_spec is not None
    onnxruntime = importlib.util.find_spec("onnxruntime") is not None
    pymupdf = importlib.util.find_spec("pymupdf") is not None
    tesseract = shutil.which("tesseract") is not None
    ocr_models = False
    if rapidocr_spec is not None and rapidocr_spec.origin:
        model_dir = Path(rapidocr_spec.origin).resolve().parent / "models"
        ocr_models = all((model_dir / name).is_file() for name in (
            "PP-OCRv6_det_small.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "PP-OCRv6_rec_small.onnx",
        ))
    return {
        "text_pdf": text_pdf,
        "media": media,
        "ocr": (rapidocr and onnxruntime and pymupdf and ocr_models) or tesseract,
        "ocr_backend": (
            "RapidOCR + ONNX Runtime + PyMuPDF"
            if rapidocr and onnxruntime and pymupdf and ocr_models
            else "Tesseract" if tesseract
            else None
        ),
    }
