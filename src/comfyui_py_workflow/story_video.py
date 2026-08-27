from __future__ import annotations

import json
import hashlib
import math
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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


def prepare_h3_prompt(
    prompt: str,
    *,
    duration_seconds: float,
    dialogue_mode: str,
) -> str:
    """Normalize a shot into MiniMax H3's official FL2VA prompt structure."""
    raw = prompt.strip()
    raw = re.sub(
        r"^How the reference pictures align with the target video[^\n]*\n+",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    alignment = (
        "How the reference pictures align with the target video — "
        "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
        f"Picture 2 (from Shot 1) aligns with the {duration_seconds:.2f}-second mark "
        "of the target video."
    )

    if "integrated_multimodal_description:" not in raw:
        # Legacy plans mixed visual motion and sound in one free-form sentence.
        # Keep the visual portion, but do not carry vague voice instructions
        # forward because they can cause H3 to invent unintelligible speech.
        visual = re.split(
            r"(?:音效|声音|sound effects?|audio)\s*[:：]",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        raw = (
            f"integrated_multimodal_description: [Shot 1] {visual}\n\n"
            "overall_soundscape: Natural environmental ambience and synchronized "
            "physical action sounds only.\n\n"
            "non_diegetic_music: N/A"
        )

    has_dialogue = "<d>" in raw and "</d>" in raw
    if dialogue_mode == "none" or (dialogue_mode == "auto" and not has_dialogue):
        no_speech = (
            " No character speaks, whispers, sings, or produces intelligible words; "
            "visible mouths remain closed except for explicitly described non-verbal reactions."
        )
        marker = "\noverall_soundscape:"
        if marker in raw:
            raw = raw.replace(marker, no_speech + "\n\noverall_soundscape:", 1)
        else:
            raw += no_speech
        raw = raw.replace(
            "overall_soundscape:",
            "overall_soundscape: No dialogue, narration, singing, or intelligible speech is audible. ",
            1,
        )

    return f"{alignment}\n\n{raw}"


class GenerationCancelled(RuntimeError):
    """Raised between generation stages when a local user requests cancellation."""


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
        destination: str | Path | None = None,
        resume: bool = False,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        reference_image: str | Path | None = None,
    ) -> Path:
        plan.validate()
        self.client.check_health()
        generated_run_id = (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        )
        destination_path = Path(destination) if destination is not None else Path(output_root) / generated_run_id
        metadata_path = destination_path / "run.json"
        plan_payload = json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        plan_sha256 = hashlib.sha256(plan_payload).hexdigest()
        reference_path = Path(reference_image) if reference_image is not None else None
        if reference_path is not None and not reference_path.is_file():
            raise FileNotFoundError(f"Reference image not found: {reference_path}")
        reference_sha256 = (
            hashlib.sha256(reference_path.read_bytes()).hexdigest()
            if reference_path is not None
            else None
        )
        width, height = resolution_for_aspect(plan.aspect_ratio)

        if resume and metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("plan_sha256") not in {None, plan_sha256}:
                raise ValueError("Cannot resume: story-plan.json changed after rendering started")
            if metadata.get("reference_sha256") != reference_sha256:
                raise ValueError("Cannot resume: the reference image changed after rendering started")
            run_id = str(metadata.get("run_id") or destination_path.name)
            if metadata.get("status") == "succeeded" and (destination_path / "final.mp4").is_file():
                self._notify(progress_callback, {
                    "stage": "completed",
                    "message": "任务已经完成，无需重复生成。",
                    "completed_shots": len(plan.shots),
                    "total_shots": len(plan.shots),
                    "completed_seconds": plan.target_duration_seconds,
                })
                return destination_path
        else:
            destination_path.mkdir(parents=True, exist_ok=False)
            run_id = generated_run_id if destination is None else destination_path.name
            metadata = {
                "run_id": run_id,
                "status": "running",
                "plan_sha256": plan_sha256,
                "reference_sha256": reference_sha256,
                "reference_image": reference_path.name if reference_path is not None else None,
                "target_duration_seconds": plan.target_duration_seconds,
                "estimated_frame_count": plan.estimated_frame_count,
                "resolution": {"width": width, "height": height},
                "shots": [],
            }

        destination_path.mkdir(parents=True, exist_ok=True)
        plan.write(destination_path / "story-plan.json")
        metadata["status"] = "running"
        metadata["plan_sha256"] = plan_sha256
        metadata.pop("error", None)
        self._write_metadata(destination_path, metadata)

        current_end: Path | None = None
        frame_number = 0
        raw_clips: list[Path] = []
        durations: list[float] = []
        completed_records = metadata.get("shots", [])
        if not isinstance(completed_records, list):
            raise ValueError("Cannot resume: run.json has malformed shot records")
        if len(completed_records) > len(plan.shots):
            raise ValueError("Cannot resume: run.json contains too many shots")
        for expected_index, record in enumerate(completed_records, start=1):
            if not isinstance(record, dict) or record.get("index") != expected_index:
                raise ValueError("Cannot resume: completed shot records are not sequential")
            start_frame = destination_path / str(record.get("start_frame", ""))
            end_frame = destination_path / str(record.get("end_frame", ""))
            clip_data = record.get("clip", {})
            clip = destination_path / str(clip_data.get("file", ""))
            if not start_frame.is_file() or not end_frame.is_file() or not clip.is_file():
                raise ValueError(f"Cannot resume: files for completed shot {expected_index} are missing")
            current_end = end_frame
            raw_clips.append(clip)
            durations.append(float(record["duration_seconds"]))
            for frame_path in (start_frame, end_frame):
                try:
                    frame_number = max(frame_number, int(frame_path.stem.rsplit("-", 1)[1]))
                except (IndexError, ValueError):
                    raise ValueError(f"Cannot resume: unexpected frame name {frame_path.name}")

        def update_progress(stage: str, message: str, shot_index: int | None = None) -> None:
            completed_seconds = sum(durations)
            event = {
                "stage": stage,
                "message": message,
                "shot_index": shot_index,
                "completed_shots": len(raw_clips),
                "total_shots": len(plan.shots),
                "completed_seconds": completed_seconds,
                "target_seconds": plan.target_duration_seconds,
            }
            metadata["progress"] = event
            self._write_metadata(destination_path, metadata)
            self._notify(progress_callback, event)

        def ensure_not_cancelled() -> None:
            if cancel_check is not None and cancel_check():
                raise GenerationCancelled("Generation cancelled by the local user")

        try:
            update_progress("starting", "正在准备本地生成任务。")
            for shot in plan.shots[len(completed_records):]:
                ensure_not_cancelled()
                shot_record: dict[str, Any] = {
                    "index": shot.index,
                    "duration_seconds": shot.duration_seconds,
                    "transition_from_previous": shot.transition_from_previous,
                }
                if current_end is None or shot.transition_from_previous == "cut":
                    update_progress(
                        "start_frame",
                        f"正在生成第 {shot.index}/{len(plan.shots)} 镜起始帧。",
                        shot.index,
                    )
                    frame_number += 1
                    if reference_path is not None:
                        start_frame, start_record = self._generate_reference_start_frame(
                            source=reference_path,
                            prompt=shot.start_frame_prompt,
                            negative_prompt=plan.visual_bible.global_negative_prompt,
                            aspect_ratio=plan.aspect_ratio,
                            seed=base_seed + frame_number,
                            frame_number=frame_number,
                            destination=destination_path,
                            run_id=run_id,
                            timeout_seconds=image_timeout_seconds,
                        )
                    else:
                        start_frame, start_record = self._generate_start_frame(
                            prompt=shot.start_frame_prompt,
                            seed=base_seed + frame_number,
                            width=width,
                            height=height,
                            frame_number=frame_number,
                            destination=destination_path,
                            run_id=run_id,
                            timeout_seconds=image_timeout_seconds,
                        )
                    shot_record["start_frame_generation"] = start_record
                else:
                    start_frame = current_end
                    shot_record["start_frame_generation"] = None
                shot_record["start_frame"] = start_frame.name

                ensure_not_cancelled()
                update_progress(
                    "end_frame",
                    f"正在生成第 {shot.index}/{len(plan.shots)} 镜结束帧。",
                    shot.index,
                )
                frame_number += 1
                end_frame, end_record = self._generate_end_frame(
                    source=start_frame,
                    prompt=shot.end_frame_edit_prompt,
                    negative_prompt=plan.visual_bible.global_negative_prompt,
                    seed=base_seed + frame_number,
                    frame_number=frame_number,
                    destination=destination_path,
                    run_id=run_id,
                    timeout_seconds=image_timeout_seconds,
                )
                shot_record["end_frame"] = end_frame.name
                shot_record["end_frame_generation"] = end_record

                ensure_not_cancelled()
                update_progress(
                    "video",
                    f"正在生成第 {shot.index}/{len(plan.shots)} 段视频。",
                    shot.index,
                )
                clip, clip_record = self._generate_clip(
                    shot_index=shot.index,
                    first_frame=start_frame,
                    last_frame=end_frame,
                    prompt=prepare_h3_prompt(
                        shot.video_prompt,
                        duration_seconds=shot.duration_seconds,
                        dialogue_mode=plan.dialogue_mode,
                    ),
                    seed=base_seed + 10_000 + shot.index,
                    duration_seconds=shot.duration_seconds,
                    aspect_ratio=plan.aspect_ratio,
                    destination=destination_path,
                    run_id=run_id,
                    timeout_seconds=video_timeout_seconds,
                )
                shot_record["clip"] = clip_record
                metadata["shots"].append(shot_record)
                raw_clips.append(clip)
                durations.append(shot.duration_seconds)
                current_end = end_frame
                update_progress(
                    "shot_completed",
                    f"第 {shot.index}/{len(plan.shots)} 段视频已经完成。",
                    shot.index,
                )

            ensure_not_cancelled()
            update_progress("remux", "正在拼接并校验最终视频。")
            final_path = destination_path / "final.mp4"
            remux_segments(raw_clips, final_path, segment_seconds=durations)
            metadata["final_video"] = {
                "file": final_path.name,
                "duration_seconds": media_duration(final_path),
            }
            metadata["status"] = "succeeded"
            update_progress("completed", "最终视频已经生成。")
            self._write_metadata(destination_path, metadata)
            return destination_path
        except GenerationCancelled as exc:
            metadata["status"] = "cancelled"
            metadata["error"] = str(exc)
            update_progress("cancelled", "任务已在当前模型步骤完成后停止。")
            self._write_metadata(destination_path, metadata)
            raise
        except Exception as exc:
            metadata["status"] = "failed"
            metadata["error"] = f"{type(exc).__name__}: {exc}"
            update_progress("failed", metadata["error"])
            self._write_metadata(destination_path, metadata)
            raise

    @staticmethod
    def _notify(
        callback: Callable[[dict[str, Any]], None] | None,
        event: dict[str, Any],
    ) -> None:
        if callback is None:
            return
        try:
            callback(dict(event))
        except Exception:
            # A broken UI callback must never abort an expensive local render.
            return

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

    def _generate_reference_start_frame(
        self,
        *,
        source: Path,
        prompt: str,
        negative_prompt: str,
        aspect_ratio: str,
        seed: int,
        frame_number: int,
        destination: Path,
        run_id: str,
        timeout_seconds: float,
    ) -> tuple[Path, dict[str, Any]]:
        upload = self.client.upload_image(
            source,
            filename=f"{run_id}-reference{source.suffix.lower()}",
            subfolder="cpw",
        )
        edit_prompt = (
            "Use the uploaded image as the authoritative visual reference. Preserve the visible "
            "subject identity, facial features, clothing, important objects, and visual style unless "
            "the target scene explicitly requires a change. Recompose it as a new storyboard frame "
            f"for a {aspect_ratio} canvas; extend or crop the background naturally. Target scene: {prompt}"
        )
        workflow = ComfyUIClient.apply_substitutions(load_workflow_template(self.qwen_edit_workflow), {
            ("78", "image"): self.client.input_reference(upload),
            ("433:111", "prompt"): edit_prompt,
            ("433:110", "prompt"): negative_prompt,
            ("433:3", "seed"): seed,
            ("433:443", "value"): True,
            ("469", "filename_prefix"): f"cpw_story_{run_id}_frame_{frame_number:04d}",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        asset = self._single_asset(history, "469", "images")
        output = self.client.download_asset(asset, destination / f"frame-{frame_number:04d}.png")
        return output, self._generation_record(
            "qwen-image-edit-2509-reference-start", prompt_id, seed, asset
        )

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
