from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .client import ComfyUIAsset, ComfyUIClient, load_workflow_template


SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
)


@dataclass(frozen=True)
class BatchItemResult:
    source: Path
    destination: Path | None
    prompt_id: str | None
    seed: int
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.destination is not None


@dataclass(frozen=True)
class BatchRunResult:
    items: tuple[BatchItemResult, ...]
    cancelled: bool

    @property
    def succeeded_count(self) -> int:
        return sum(item.succeeded for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(not item.succeeded for item in self.items)


def discover_images(paths: Iterable[str | Path], *, recursive: bool = False) -> list[Path]:
    """Return supported image files in stable order, without duplicates."""

    images: list[Path] = []
    seen: set[str] = set()
    for value in paths:
        path = Path(value).expanduser()
        if path.is_dir():
            candidates = path.rglob("*") if recursive else path.glob("*")
            candidates = sorted(
                (candidate for candidate in candidates if candidate.is_file()),
                key=lambda candidate: str(candidate).casefold(),
            )
        elif path.is_file():
            candidates = [path]
        else:
            continue
        for candidate in candidates:
            if candidate.suffix.casefold() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            resolved = candidate.resolve()
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                images.append(resolved)
    return images


def default_qwen_workflow_path() -> Path:
    return Path(__file__).resolve().parents[2] / "workflows" / "api" / "qwen-image-edit-2509.api.json"


class QwenBatchImageEditor:
    """Run one Qwen Image Edit workflow per source image."""

    INPUT_NODE = "78"
    POSITIVE_NODE = "433:111"
    NEGATIVE_NODE = "433:110"
    SAMPLER_NODE = "433:3"
    OUTPUT_NODE = "469"

    def __init__(self, client: ComfyUIClient) -> None:
        self.client = client

    def run(
        self,
        *,
        images: Iterable[str | Path],
        output_dir: str | Path,
        prompt: str,
        negative_prompt: str = "",
        workflow_path: str | Path | None = None,
        base_seed: int = 43,
        increment_seed: bool = True,
        timeout_seconds: float = 900.0,
        overwrite: bool = False,
        continue_on_error: bool = True,
        cancel_event: threading.Event | None = None,
        on_progress: Callable[[int, int, BatchItemResult], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> BatchRunResult:
        sources = discover_images(images)
        if not sources:
            raise ValueError("没有可处理的图片")
        if not prompt.strip():
            raise ValueError("提示词不能为空")
        if base_seed < 0:
            raise ValueError("种子不能为负数")
        if timeout_seconds <= 0:
            raise ValueError("超时时间必须大于 0")

        template = load_workflow_template(workflow_path or default_qwen_workflow_path())
        self._validate_template(template)
        destination_root = Path(output_dir).expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        if on_status:
            on_status("正在连接 ComfyUI…")
        self.client.check_health()

        results: list[BatchItemResult] = []
        total = len(sources)
        for index, source in enumerate(sources):
            if cancel_event is not None and cancel_event.is_set():
                return BatchRunResult(tuple(results), cancelled=True)
            seed = base_seed + index if increment_seed else base_seed
            if on_status:
                on_status(f"正在处理 {index + 1}/{total}：{source.name}")
            try:
                item = self._run_one(
                    source=source,
                    destination_root=destination_root,
                    template=template,
                    prompt=prompt.strip(),
                    negative_prompt=negative_prompt.strip(),
                    seed=seed,
                    timeout_seconds=timeout_seconds,
                    overwrite=overwrite,
                )
            except Exception as exc:
                item = BatchItemResult(source, None, None, seed, f"{type(exc).__name__}: {exc}")
                results.append(item)
                if on_progress:
                    on_progress(index + 1, total, item)
                if not continue_on_error:
                    raise
                continue
            results.append(item)
            if on_progress:
                on_progress(index + 1, total, item)
        return BatchRunResult(tuple(results), cancelled=False)

    def _run_one(
        self,
        *,
        source: Path,
        destination_root: Path,
        template: dict,
        prompt: str,
        negative_prompt: str,
        seed: int,
        timeout_seconds: float,
        overwrite: bool,
    ) -> BatchItemResult:
        token = uuid.uuid4().hex[:12]
        upload = self.client.upload_image(
            source,
            filename=f"{token}-{source.name}",
            subfolder="cpw-batch-edit",
            overwrite=True,
        )
        workflow = ComfyUIClient.apply_substitutions(template, {
            (self.INPUT_NODE, "image"): self.client.input_reference(upload),
            (self.POSITIVE_NODE, "prompt"): prompt,
            (self.NEGATIVE_NODE, "prompt"): negative_prompt,
            (self.SAMPLER_NODE, "seed"): seed,
            (self.OUTPUT_NODE, "filename_prefix"): f"cpw_batch_edit_{token}",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        asset = self._first_output_image(history)
        suffix = Path(asset.filename).suffix.casefold()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            suffix = ".png"
        destination = destination_root / f"{source.stem}_edited{suffix}"
        if not overwrite:
            destination = self._unused_path(destination)
        self.client.download_asset(asset, destination)
        return BatchItemResult(source, destination, prompt_id, seed)

    @classmethod
    def _validate_template(cls, template: dict) -> None:
        required = {
            (cls.INPUT_NODE, "image"),
            (cls.POSITIVE_NODE, "prompt"),
            (cls.NEGATIVE_NODE, "prompt"),
            (cls.SAMPLER_NODE, "seed"),
            (cls.OUTPUT_NODE, "filename_prefix"),
        }
        missing = [
            f"{node_id}.{input_name}"
            for node_id, input_name in required
            if input_name not in template.get(node_id, {}).get("inputs", {})
        ]
        if missing:
            raise ValueError("工作流缺少必要输入节点：" + ", ".join(sorted(missing)))

    @classmethod
    def _first_output_image(cls, history: dict) -> ComfyUIAsset:
        images = [
            asset
            for asset in ComfyUIClient.output_assets(history, node_id=cls.OUTPUT_NODE)
            if asset.kind == "images"
        ]
        if not images:
            raise RuntimeError(f"输出节点 {cls.OUTPUT_NODE} 没有返回图片")
        return images[0]

    @staticmethod
    def _unused_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = re.sub(r"-\d+$", "", path.stem)
        index = 2
        while True:
            candidate = path.with_name(f"{stem}-{index}{path.suffix}")
            if not candidate.exists():
                return candidate
            index += 1
