from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

import av

from .client import ComfyUIAsset, ComfyUIClient, load_workflow_template


class ThreeFrameVideoSequence:
    def __init__(self, client: ComfyUIClient) -> None:
        self.client = client

    def run(
        self,
        *,
        first_frame: str | Path,
        second_frame: str | Path,
        qwen_edit_workflow: str | Path,
        h3_workflow: str | Path,
        third_frame_prompt: str,
        negative_prompt: str,
        first_clip_prompt: str,
        second_clip_prompt: str,
        output_root: str | Path,
        edit_seed: int = 44,
        first_clip_seed: int = 101,
        second_clip_seed: int = 102,
        clip_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
    ) -> Path:
        self.client.check_health()
        first_path = Path(first_frame)
        second_path = Path(second_frame)
        if not first_path.is_file():
            raise FileNotFoundError(first_path)
        if not second_path.is_file():
            raise FileNotFoundError(second_path)

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        destination = Path(output_root) / run_id
        destination.mkdir(parents=True, exist_ok=False)
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "status": "running",
            "clip_seconds": clip_seconds,
            "third_frame_prompt": third_frame_prompt,
            "negative_prompt": negative_prompt,
            "first_clip_prompt": first_clip_prompt,
            "second_clip_prompt": second_clip_prompt,
            "frames": [str(first_path.name), str(second_path.name)],
            "clips": [],
        }
        self._write_metadata(destination, metadata)

        try:
            third_path, edit_record = self._edit_frame(
                second_path,
                qwen_edit_workflow,
                third_frame_prompt,
                negative_prompt,
                edit_seed,
                destination,
                run_id,
                timeout_seconds,
            )
            metadata["frames"].append(third_path.name)
            metadata["third_frame"] = edit_record
            self._write_metadata(destination, metadata)

            raw_clips = [
                self._generate_clip(
                    1, first_path, second_path, first_clip_prompt, first_clip_seed,
                    h3_workflow, destination, run_id, clip_seconds, timeout_seconds,
                ),
                self._generate_clip(
                    2, second_path, third_path, second_clip_prompt, second_clip_seed,
                    h3_workflow, destination, run_id, clip_seconds, timeout_seconds,
                ),
            ]
            normalized: list[Path] = []
            for index, (raw_path, record) in enumerate(raw_clips, start=1):
                clip_path = destination / f"clip-{index:04d}-5s.mp4"
                remux_segments([raw_path], clip_path, segment_seconds=clip_seconds)
                record["normalized_file"] = clip_path.name
                record["duration_seconds"] = media_duration(clip_path)
                metadata["clips"].append(record)
                normalized.append(clip_path)
                self._write_metadata(destination, metadata)

            final_path = destination / "final-10s.mp4"
            remux_segments(normalized, final_path, segment_seconds=clip_seconds)
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

    def _edit_frame(
        self,
        source: Path,
        workflow_path: str | Path,
        prompt: str,
        negative_prompt: str,
        seed: int,
        destination: Path,
        run_id: str,
        timeout_seconds: float,
    ) -> tuple[Path, dict[str, Any]]:
        upload = self.client.upload_image(source, filename=f"{run_id}-frame-0002.png", subfolder="cpw")
        workflow = ComfyUIClient.apply_substitutions(load_workflow_template(workflow_path), {
            ("78", "image"): self.client.input_reference(upload),
            ("433:111", "prompt"): prompt,
            ("433:110", "prompt"): negative_prompt,
            ("433:3", "seed"): seed,
            ("433:443", "value"): True,
            ("469", "filename_prefix"): f"cpw_qwen_edit_{run_id}_frame3",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        asset = self._single_asset(history, "469", "images")
        output = self.client.download_asset(asset, destination / "frame-0003.png")
        return output, {
            "model": "qwen-image-edit-2509",
            "prompt_id": prompt_id,
            "seed": seed,
            "file": output.name,
            "remote_asset": asdict(asset),
        }

    def _generate_clip(
        self,
        index: int,
        first_frame: Path,
        last_frame: Path,
        prompt: str,
        seed: int,
        workflow_path: str | Path,
        destination: Path,
        run_id: str,
        clip_seconds: float,
        timeout_seconds: float,
    ) -> tuple[Path, dict[str, Any]]:
        first_upload = self.client.upload_image(
            first_frame, filename=f"{run_id}-clip-{index}-first.png", subfolder="cpw"
        )
        last_upload = self.client.upload_image(
            last_frame, filename=f"{run_id}-clip-{index}-last.png", subfolder="cpw"
        )
        workflow = ComfyUIClient.apply_substitutions(load_workflow_template(workflow_path), {
            ("22", "image"): self.client.input_reference(first_upload),
            ("20", "image"): self.client.input_reference(last_upload),
            ("12", "prompt"): prompt,
            ("3", "seed"): seed,
            ("23", "aspect_ratio"): "1:1 (Square)",
            ("23", "megapixels"): 0.6,
            ("23", "multiple"): 32,
            ("26", "value"): clip_seconds,
            ("24", "filename_prefix"): f"video/cpw_h3_{run_id}_clip_{index}",
            ("24", "format"): "mp4",
        })
        prompt_id, history = self.client.run(workflow, timeout_seconds=timeout_seconds)
        assets = self.client.output_assets(history, node_id="24")
        video_assets = [asset for asset in assets if Path(asset.filename).suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}]
        if len(video_assets) != 1:
            raise RuntimeError(f"Expected one video from node 24, found {len(video_assets)}")
        asset = video_assets[0]
        suffix = Path(asset.filename).suffix or ".mp4"
        output = self.client.download_asset(asset, destination / f"clip-{index:04d}-raw{suffix}")
        return output, {
            "index": index,
            "model": "minimax-h3-fl2va",
            "prompt_id": prompt_id,
            "seed": seed,
            "raw_file": output.name,
            "raw_duration_seconds": media_duration(output),
            "remote_asset": asdict(asset),
        }

    @staticmethod
    def _single_asset(history: dict[str, Any], node_id: str, kind: str) -> ComfyUIAsset:
        assets = [asset for asset in ComfyUIClient.output_assets(history, node_id=node_id) if asset.kind == kind]
        if len(assets) != 1:
            raise RuntimeError(f"Expected one {kind} asset from node {node_id}, found {len(assets)}")
        return assets[0]

    @staticmethod
    def _write_metadata(destination: Path, metadata: dict[str, Any]) -> None:
        (destination / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _stream_keys(container: av.container.InputContainer) -> list[tuple[str, int, Any]]:
    counts: dict[str, int] = {}
    result: list[tuple[str, int, Any]] = []
    for stream in container.streams:
        if stream.type not in {"video", "audio"}:
            continue
        ordinal = counts.get(stream.type, 0)
        counts[stream.type] = ordinal + 1
        result.append((stream.type, ordinal, stream))
    return result


def remux_segments(
    sources: list[Path],
    destination: Path,
    *,
    segment_seconds: float | list[float],
) -> None:
    if not sources:
        raise ValueError("At least one media source is required")
    if isinstance(segment_seconds, list):
        durations = [Fraction(str(value)) for value in segment_seconds]
        if len(durations) != len(sources):
            raise ValueError("One segment duration is required for each source")
    else:
        durations = [Fraction(str(segment_seconds))] * len(sources)
    if any(value <= 0 for value in durations):
        raise ValueError("Segment durations must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(destination), mode="w") as output:
        with av.open(str(sources[0])) as template:
            output_streams = {
                (kind, ordinal): output.add_stream_from_template(stream)
                for kind, ordinal, stream in _stream_keys(template)
            }
        if not output_streams:
            raise RuntimeError(f"No video or audio streams found in {sources[0]}")

        elapsed = Fraction(0)
        for source, duration in zip(sources, durations):
            with av.open(str(source)) as current:
                input_streams = _stream_keys(current)
                stream_map = {
                    stream.index: output_streams[(kind, ordinal)]
                    for kind, ordinal, stream in input_streams
                }
                origins: dict[int, int] = {}
                offset = elapsed
                for packet in current.demux([stream for _, _, stream in input_streams]):
                    if packet.dts is None:
                        continue
                    origin = origins.setdefault(packet.stream.index, packet.dts)
                    local_pts = packet.pts - origin if packet.pts is not None else None
                    local_dts = packet.dts - origin
                    decode_time = Fraction(local_dts) * packet.time_base
                    if decode_time >= duration:
                        continue
                    offset_ticks = int(offset / packet.time_base)
                    packet.pts = local_pts + offset_ticks if local_pts is not None else None
                    packet.dts = local_dts + offset_ticks
                    packet.stream = stream_map[packet.stream.index]
                    output.mux(packet)
            elapsed += duration


def media_duration(path: str | Path) -> float:
    with av.open(str(path)) as container:
        if container.duration is None:
            raise RuntimeError(f"Media duration is unavailable: {path}")
        return container.duration / av.time_base


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate frame 3, two H3 clips, and one concatenated video")
    parser.add_argument("--first-frame", type=Path, required=True)
    parser.add_argument("--second-frame", type=Path, required=True)
    parser.add_argument("--third-frame-prompt", required=True)
    parser.add_argument("--negative-prompt", required=True)
    parser.add_argument("--first-clip-prompt", required=True)
    parser.add_argument("--second-clip-prompt", required=True)
    parser.add_argument(
        "--qwen-workflow",
        type=Path,
        default=Path("workflows/api/qwen-image-edit-2509.api.json"),
    )
    parser.add_argument(
        "--h3-workflow",
        type=Path,
        default=Path("workflows/api/minimax-h3-first-last-frame.api.json"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    destination = ThreeFrameVideoSequence(ComfyUIClient(args.server)).run(
        first_frame=args.first_frame,
        second_frame=args.second_frame,
        qwen_edit_workflow=args.qwen_workflow,
        h3_workflow=args.h3_workflow,
        third_frame_prompt=args.third_frame_prompt,
        negative_prompt=args.negative_prompt,
        first_clip_prompt=args.first_clip_prompt,
        second_clip_prompt=args.second_clip_prompt,
        output_root=args.output_root,
        timeout_seconds=args.timeout,
    )
    print(f"Three-frame video sequence completed: {destination}")


if __name__ == "__main__":
    main()
