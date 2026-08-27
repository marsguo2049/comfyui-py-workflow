from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import ComfyUIAsset, ComfyUIClient, load_workflow_template
from .story_plan import StoryPlan
from .video_sequence import media_duration, remux_segments


ASPECT_RATIOS = {
    "1:1": "1:1 (Square)",
    "2:3": "2:3 (Portrait Photo)",
    "3:2": "3:2 (Photo)",
    "3:4": "3:4 (Portrait Standard)",
    "4:3": "4:3 (Standard)",
    "9:16": "9:16 (Portrait Widescreen)",
    "16:9": "16:9 (Widescreen)",
    "21:9": "21:9 (Ultrawide)",
}


def resolution_for_aspect(
    aspect_ratio: str,
    *,
    megapixels: float = 0.6,
    multiple: int = 32,
) -> tuple[int, int]:
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError(f"Unsupported aspect ratio: {aspect_ratio}")
    width_ratio, height_ratio = (int(value) for value in aspect_ratio.split(":"))
    scale = math.sqrt(megapixels * 1024 * 1024 / (width_ratio * height_ratio))
    width = round(width_ratio * scale / multiple) * multiple
    height = round(height_ratio * scale / multiple) * multiple
    return width, height


class StoryVideoExecutor:
    def __init__(
        self,
        client: ComfyUIClient,
        *,
        z_image_workflow: str | Path,
        qwen_edit_workflow: str | Path,
        h3_workflow: str | Path,
    ) -> None:
        self.client = client
        self.z_image_workflow = Path(z_image_workflow)
        self.qwen_edit_workflow = Path(qwen_edit_workflow)
        self.h3_workflow = Path(h3_workflow)

    def run(
        self,
        plan: StoryPlan,
        *,
        output_root: str | Path,
        base_seed: int = 1000,
        image_timeout_seconds: float = 900.0,
        video_timeout_seconds: float = 1800.0,
    ) -> Path:
        plan.validate()
        self.client.check_health()
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        destination = Path(output_root) / run_id
        destination.mkdir(parents=True, exist_ok=False)
        plan.write(destination / "story-plan.json")
        width, height = resolution_for_aspect(plan.aspect_ratio)
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "status": "running",
            "target_duration_seconds": plan.target_duration_seconds,
            "estimated_frame_count": plan.estimated_frame_count,
            "resolution": {"width": width, "height": height},
            "shots": [],
        }
        self._write_metadata(destination, metadata)

        current_end: Path | None = None
        frame_number = 0
        raw_clips: list[Path] = []
        durations: list[float] = []
        try:
            for shot in plan.shots:
                shot_record: dict[str, Any] = {
                    "index": shot.index,
                    "duration_seconds": shot.duration_seconds,
                    "transition_from_previous": shot.transition_from_previous,
                }
                if current_end is None or shot.transition_from_previous == "cut":
                    frame_number += 1
                    start_frame, start_record = self._generate_start_frame(
                        prompt=shot.start_frame_prompt,
                        seed=base_seed + frame_number,
                        width=width,
                        height=height,
                        frame_number=frame_number,
                        destination=destination,
                        run_id=run_id,
                        timeout_seconds=image_timeout_seconds,
                    )
                    shot_record["start_frame_generation"] = start_record
                else:
                    start_frame = current_end
                    shot_record["start_frame_generation"] = None
                shot_record["start_frame"] = start_frame.name

                frame_number += 1
                end_frame, end_record = self._generate_end_frame(
                    source=start_frame,
                    prompt=shot.end_frame_edit_prompt,
                    negative_prompt=plan.visual_bible.global_negative_prompt,
                    seed=base_seed + frame_number,
                    frame_number=frame_number,
                    destination=destination,
                    run_id=run_id,
                    timeout_seconds=image_timeout_seconds,
                )
                shot_record["end_frame"] = end_frame.name
                shot_record["end_frame_generation"] = end_record

                clip, clip_record = self._generate_clip(
                    shot_index=shot.index,
                    first_frame=start_frame,
                    last_frame=end_frame,
                    prompt=shot.video_prompt,
                    seed=base_seed + 10_000 + shot.index,
                    duration_seconds=shot.duration_seconds,
                    aspect_ratio=plan.aspect_ratio,
                    destination=destination,
                    run_id=run_id,
                    timeout_seconds=video_timeout_seconds,
                )
                shot_record["clip"] = clip_record
                metadata["shots"].append(shot_record)
                self._write_metadata(destination, metadata)
                raw_clips.append(clip)
                durations.append(shot.duration_seconds)
                current_end = end_frame

            final_path = destination / "final.mp4"
            remux_segments(raw_clips, final_path, segment_seconds=durations)
            metadata["final_video"] = {
                "file": final_path.name,
                "duration_seconds": media_duration(final_path),
            }
            metadata["status"] = "succeeded"
            self._write_metadata(destination, metadata)
            return destination
        except Exception as exc:
            metadata["status"] = "failed"
            metadata["error"] = f"{type(exc).__name__}: {exc}"
            self._write_metadata(destination, metadata)
            raise

    def _generate_start_frame(
        self,
        *,
        prompt: str,
        seed: int,
        width: int,
        height: int,
        frame_number: int,
        destination: Path,
        run_id: str,
        timeout_seconds: float,
    ) -> tuple[Path, dict[str, Any]]:
        workflow = ComfyUIClient.apply_substitutions(load_workflow_template(self.z_image_workflow), {
            ("57:27", "text"): prompt,
            ("57:3", "seed"): seed,
            ("57:13", "width"): width,
            ("57:13", "height"): height,
            ("57:13", "batch_size"): 1,
            ("9", "filename_prefix"): f"cpw_story_{run_id}_frame_{frame_number:04d}",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        asset = self._single_asset(history, "9", "images")
        output = self.client.download_asset(asset, destination / f"frame-{frame_number:04d}.png")
        return output, self._generation_record("z-image-turbo", prompt_id, seed, asset)

    def _generate_end_frame(
        self,
        *,
        source: Path,
        prompt: str,
        negative_prompt: str,
        seed: int,
        frame_number: int,
        destination: Path,
        run_id: str,
        timeout_seconds: float,
    ) -> tuple[Path, dict[str, Any]]:
        upload = self.client.upload_image(
            source,
            filename=f"{run_id}-frame-{frame_number - 1:04d}.png",
            subfolder="cpw",
        )
        workflow = ComfyUIClient.apply_substitutions(load_workflow_template(self.qwen_edit_workflow), {
            ("78", "image"): self.client.input_reference(upload),
            ("433:111", "prompt"): prompt,
            ("433:110", "prompt"): negative_prompt,
            ("433:3", "seed"): seed,
            ("433:443", "value"): True,
            ("469", "filename_prefix"): f"cpw_story_{run_id}_frame_{frame_number:04d}",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        asset = self._single_asset(history, "469", "images")
        output = self.client.download_asset(asset, destination / f"frame-{frame_number:04d}.png")
        return output, self._generation_record("qwen-image-edit-2509", prompt_id, seed, asset)

    def _generate_clip(
        self,
        *,
        shot_index: int,
        first_frame: Path,
        last_frame: Path,
        prompt: str,
        seed: int,
        duration_seconds: float,
        aspect_ratio: str,
        destination: Path,
        run_id: str,
        timeout_seconds: float,
    ) -> tuple[Path, dict[str, Any]]:
        first_upload = self.client.upload_image(
            first_frame,
            filename=f"{run_id}-shot-{shot_index:04d}-first.png",
            subfolder="cpw",
        )
        last_upload = self.client.upload_image(
            last_frame,
            filename=f"{run_id}-shot-{shot_index:04d}-last.png",
            subfolder="cpw",
        )
        workflow = ComfyUIClient.apply_substitutions(load_workflow_template(self.h3_workflow), {
            ("22", "image"): self.client.input_reference(first_upload),
            ("20", "image"): self.client.input_reference(last_upload),
            ("12", "prompt"): prompt,
            ("3", "seed"): seed,
            ("23", "aspect_ratio"): ASPECT_RATIOS[aspect_ratio],
            ("23", "megapixels"): 0.6,
            ("23", "multiple"): 32,
            ("26", "value"): duration_seconds,
            ("24", "filename_prefix"): f"video/cpw_story_{run_id}_shot_{shot_index:04d}",
            ("24", "format"): "mp4",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        assets = self.client.output_assets(history, node_id="24")
        videos = [
            asset for asset in assets
            if Path(asset.filename).suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}
        ]
        if len(videos) != 1:
            raise RuntimeError(f"Expected one video from node 24, found {len(videos)}")
        asset = videos[0]
        suffix = Path(asset.filename).suffix or ".mp4"
        output = self.client.download_asset(
            asset,
            destination / f"clip-{shot_index:04d}-raw{suffix}",
        )
        return output, {
            **self._generation_record("minimax-h3-fl2va", prompt_id, seed, asset),
            "file": output.name,
            "requested_duration_seconds": duration_seconds,
            "raw_duration_seconds": media_duration(output),
        }

    @staticmethod
    def _single_asset(history: dict[str, Any], node_id: str, kind: str) -> ComfyUIAsset:
        assets = [
            asset for asset in ComfyUIClient.output_assets(history, node_id=node_id)
            if asset.kind == kind
        ]
        if len(assets) != 1:
            raise RuntimeError(f"Expected one {kind} from node {node_id}, found {len(assets)}")
        return assets[0]

    @staticmethod
    def _generation_record(
        model: str,
        prompt_id: str,
        seed: int,
        asset: ComfyUIAsset,
    ) -> dict[str, Any]:
        return {
            "model": model,
            "prompt_id": prompt_id,
            "seed": seed,
            "remote_asset": asdict(asset),
        }

    @staticmethod
    def _write_metadata(destination: Path, metadata: dict[str, Any]) -> None:
        (destination / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
