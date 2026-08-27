from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import ComfyUIAsset, ComfyUIClient, load_workflow_template


@dataclass(frozen=True)
class GeneratedFrame:
    index: int
    model: str
    prompt_id: str
    seed: int
    local_file: str
    remote_asset: ComfyUIAsset


class TwoFrameImageSequence:
    def __init__(self, client: ComfyUIClient) -> None:
        self.client = client

    def run(
        self,
        *,
        z_image_workflow: str | Path,
        qwen_edit_workflow: str | Path,
        first_prompt: str,
        edit_prompt: str,
        negative_prompt: str,
        output_root: str | Path,
        width: int = 768,
        height: int = 768,
        first_seed: int = 42,
        edit_seed: int = 43,
        timeout_seconds: float = 900.0,
    ) -> Path:
        self.client.check_health()
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        destination = Path(output_root) / run_id
        destination.mkdir(parents=True, exist_ok=False)
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "status": "running",
            "first_prompt": first_prompt,
            "edit_prompt": edit_prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "frames": [],
        }
        self._write_metadata(destination, metadata)

        z_workflow = ComfyUIClient.apply_substitutions(load_workflow_template(z_image_workflow), {
            ("57:27", "text"): first_prompt,
            ("57:3", "seed"): first_seed,
            ("57:13", "width"): width,
            ("57:13", "height"): height,
            ("57:13", "batch_size"): 1,
            ("9", "filename_prefix"): f"cpw_z_{run_id}",
        })
        first_prompt_id, first_history = self.client.run(z_workflow, timeout_seconds=timeout_seconds)
        first_asset = self._single_image(first_history, "9")
        first_path = self.client.download_asset(first_asset, destination / "frame-0001.png")
        first_frame = GeneratedFrame(1, "z-image-turbo", first_prompt_id, first_seed, first_path.name, first_asset)
        metadata["frames"].append(self._frame_dict(first_frame))
        self._write_metadata(destination, metadata)

        upload = self.client.upload_image(
            first_path,
            filename=f"{run_id}-frame-0001.png",
            subfolder="cpw",
        )
        edit_workflow = ComfyUIClient.apply_substitutions(load_workflow_template(qwen_edit_workflow), {
            ("78", "image"): self.client.input_reference(upload),
            ("433:111", "prompt"): edit_prompt,
            ("433:110", "prompt"): negative_prompt,
            ("433:3", "seed"): edit_seed,
            ("433:443", "value"): True,
            ("469", "filename_prefix"): f"cpw_qwen_edit_{run_id}",
        })
        second_prompt_id, second_history = self.client.run(edit_workflow, timeout_seconds=timeout_seconds)
        second_asset = self._single_image(second_history, "469")
        second_path = self.client.download_asset(second_asset, destination / "frame-0002.png")
        second_frame = GeneratedFrame(2, "qwen-image-edit-2509", second_prompt_id, edit_seed, second_path.name, second_asset)
        metadata["frames"].append(self._frame_dict(second_frame))
        metadata["status"] = "succeeded"
        self._write_metadata(destination, metadata)
        return destination

    @staticmethod
    def _single_image(history: dict[str, Any], node_id: str) -> ComfyUIAsset:
        images = [asset for asset in ComfyUIClient.output_assets(history, node_id=node_id) if asset.kind == "images"]
        if len(images) != 1:
            raise RuntimeError(f"Expected one image from node {node_id}, found {len(images)}")
        return images[0]

    @staticmethod
    def _frame_dict(frame: GeneratedFrame) -> dict[str, Any]:
        data = asdict(frame)
        data["remote_asset"] = asdict(frame.remote_asset)
        return data

    @staticmethod
    def _write_metadata(destination: Path, metadata: dict[str, Any]) -> None:
        (destination / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Z-Image frame, then edit it into a second frame with Qwen Image Edit")
    parser.add_argument("--first-prompt", required=True)
    parser.add_argument("--edit-prompt", required=True)
    parser.add_argument("--negative-prompt", default="extra objects, duplicate subject, distorted geometry, text, watermark")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument(
        "--z-workflow",
        type=Path,
        default=Path("workflows/api/z-image-turbo.api.json"),
    )
    parser.add_argument(
        "--edit-workflow",
        type=Path,
        default=Path("workflows/api/qwen-image-edit-2509.api.json"),
    )
    parser.add_argument("--output-root", type=Path, default=Path("outputs/image-sequence"))
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--first-seed", type=int, default=42)
    parser.add_argument("--edit-seed", type=int, default=43)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    destination = TwoFrameImageSequence(ComfyUIClient(args.server)).run(
        z_image_workflow=args.z_workflow,
        qwen_edit_workflow=args.edit_workflow,
        first_prompt=args.first_prompt,
        edit_prompt=args.edit_prompt,
        negative_prompt=args.negative_prompt,
        output_root=args.output_root,
        width=args.width,
        height=args.height,
        first_seed=args.first_seed,
        edit_seed=args.edit_seed,
        timeout_seconds=args.timeout,
    )
    print(f"Two-frame sequence completed: {destination}")


if __name__ == "__main__":
    main()
