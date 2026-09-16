"""Pair first/last frames and run the bundled MiniMax H3 video workflow."""
from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from typing import Any

from .client import ComfyUIClient, ComfyUIExecutionError, load_workflow_template

ASPECT_RATIOS = ("1:1 (Square)", "16:9 (Widescreen)", "9:16 (Portrait Widescreen)")


class VideoStateUnknown(RuntimeError):
    def __init__(self, prompt_id: str | None, cause: Exception) -> None:
        self.prompt_id = prompt_id
        super().__init__(f"ComfyUI 生成状态未确认，已停止后续提交；当前视频可能仍在生成。"
                         f"请在 ComfyUI 查看队列和输出。任务编号：{prompt_id or '未收到'}。{cause}")


def default_video_workflow_path() -> Path:
    return Path(__file__).resolve().parents[2] / "workflows/api/minimax-h3-first-last-frame.api.json"


def pair_frames(files: list[dict[str, Any]], mode: str = "order") -> list[dict[str, Any]]:
    if mode not in {"order", "name"}:
        raise ValueError("配对方式须为自然排序或同名匹配")
    if any(f.get("role") not in {"first", "last"} for f in files):
        raise ValueError("每张图片必须指定首帧或尾帧")

    def natural(file):
        name = file["name"]
        return ([(1, int(s)) if s.isdigit() else (0, s)
                 for s in re.split(r"([0-9]+)", name.casefold())], name)

    first = sorted((f for f in files if f["role"] == "first"), key=natural)
    last = sorted((f for f in files if f["role"] == "last"), key=natural)
    if not first or not last:
        raise ValueError("请分别添加至少一张首帧和尾帧图片")
    if len(first) == 1:
        pairs = [(first[0], end) for end in last]
    elif len(last) == 1:
        pairs = [(start, last[0]) for start in first]
    elif mode == "order":
        if len(first) != len(last):
            raise ValueError(f"首帧 {len(first)} 张、尾帧 {len(last)} 张，数量须相同，或其中一侧仅选一张")
        pairs = list(zip(first, last))
    else:
        def by_name(items):
            result = {}
            for item in items:
                key = Path(item["name"]).stem.casefold()
                if key in result:
                    raise ValueError(f"同名匹配存在重复文件名：{item['name']}，请移除重复图片或使用自然排序")
                result[key] = item
            return result
        first_map, last_map = by_name(first), by_name(last)
        if first_map.keys() != last_map.keys():
            missing = sorted(first_map.keys() ^ last_map.keys())
            raise ValueError("首尾帧文件名未完全匹配：" + "、".join(missing[:10]))
        pairs = [(item, last_map[Path(item["name"]).stem.casefold()]) for item in first]
    return [dict(first=start, last=end) for start, end in pairs]


def video_settings(settings: dict[str, Any]) -> dict[str, Any]:
    seconds = float(settings.get("duration_seconds", 5))
    megapixels = float(settings.get("megapixels", 0.6))
    steps = float(settings.get("steps", 4))
    ratio = str(settings.get("aspect_ratio", ASPECT_RATIOS[0]))
    mode = str(settings.get("pairing_mode", "order"))
    if not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise ValueError("每段时长须在 1–30 秒之间")
    if not math.isfinite(megapixels) or not 0.1 <= megapixels <= 2:
        raise ValueError("分辨率须在 0.1–2 百万像素之间")
    if not math.isfinite(steps) or not steps.is_integer() or not 1 <= steps <= 100:
        raise ValueError("采样步数须为 1–100 的整数")
    if ratio not in ASPECT_RATIOS or mode not in {"order", "name"}:
        raise ValueError("画面比例或配对方式无效")
    # Matches the bundled expression: H3 requires a frame count of 17n + 5.
    frames = max(5, round(seconds * 24))
    frames += (5 - frames % 17) % 17
    return dict(duration_seconds=seconds, megapixels=megapixels, steps=int(steps),
                aspect_ratio=ratio, pairing_mode=mode, frame_count=frames,
                actual_duration_seconds=frames / 24)


def validate_video_template(workflow: dict[str, Any]) -> None:
    required = {
        "22": ("LoadImage", "image"), "20": ("LoadImage", "image"),
        "12": ("MiniMaxH3ImageToVideo", "prompt"), "3": ("Seed (rgthree)", "seed"),
        "8": ("BasicScheduler", "steps"), "23": ("ResolutionSelector", "aspect_ratio"),
        "26": ("PrimitiveFloat", "value"), "27": ("ComfyMathExpression", "expression"),
        "16": ("CreateVideo", "fps"), "24": ("SaveVideo", "filename_prefix"),
    }
    for node, (kind, field) in required.items():
        entry = workflow.get(node, {})
        if entry.get("class_type") != kind or field not in entry.get("inputs", {}):
            raise ValueError(f"视频工作流不兼容：需要节点 {node} ({kind}) 的 {field} 输入")
    for node, field, expected in (("12", "length", ["27", 1]),
                                   ("27", "values.a", ["26", 0])):
        if workflow[node]["inputs"].get(field) != expected:
            raise ValueError("视频工作流的时长节点连接与内置 H3 工作流不一致")


class FirstLastVideoGenerator:
    def __init__(self, client: ComfyUIClient, workflow_path: str) -> None:
        self.client = client
        self.template = load_workflow_template(workflow_path)
        validate_video_template(self.template)

    def generate(self, first: Path, last: Path, destination: Path,
                 settings: dict[str, Any], seed: int, on_submitted=None) -> dict[str, Any]:
        token = uuid.uuid4().hex
        references = []
        for role, source in (("first", first), ("last", last)):
            upload = self.client.upload_image(source,
                filename=f"{token}-{role}{source.suffix}", subfolder="cpw")
            references.append(self.client.input_reference(upload))
        workflow = ComfyUIClient.apply_substitutions(self.template, {
            ("22", "image"): references[0], ("20", "image"): references[1],
            ("12", "prompt"): settings["prompt"], ("3", "seed"): seed,
            ("8", "steps"): settings["steps"],
            ("23", "aspect_ratio"): settings["aspect_ratio"],
            ("23", "megapixels"): settings["megapixels"], ("23", "multiple"): 32,
            ("26", "value"): settings["duration_seconds"],
            ("27", "expression"): "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17",
            ("16", "fps"): 24, ("24", "format"): "mp4",
            ("24", "filename_prefix"): f"video/cpw_batch_{token}",
        })
        prompt_id = None
        try:
            response = self.client.submit(workflow)
            prompt_id = str(response["prompt_id"])
            if on_submitted:
                on_submitted(prompt_id)
            history = self.client.wait_for_completion(prompt_id, timeout_seconds=settings["timeout_seconds"])
        except ComfyUIExecutionError:
            raise
        except Exception as exc:
            raise VideoStateUnknown(prompt_id, exc) from exc
        assets = [asset for asset in self.client.output_assets(history, node_id="24")
                  if Path(asset.filename).suffix.lower() == ".mp4"]
        if len(assets) != 1:
            raise RuntimeError(f"视频输出应为一个 MP4，实际找到 {len(assets)} 个")
        self.client.download_asset(assets[0], destination)
        return dict(prompt_id=prompt_id, duration_seconds=settings["actual_duration_seconds"])
