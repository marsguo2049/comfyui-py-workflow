from __future__ import annotations

import argparse
import json
from pathlib import Path

from comfyui_py_workflow import ComfyUIClient, TwoFrameImageSequence
from comfyui_py_workflow.video_sequence import ThreeFrameVideoSequence


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the public bicycle sequence with local ComfyUI")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs" / "bicycle-sequence")
    parser.add_argument("--image-timeout", type=float, default=900.0)
    parser.add_argument("--video-timeout", type=float, default=1800.0)
    args = parser.parse_args()

    config = json.loads((EXAMPLE / "prompts.example.json").read_text(encoding="utf-8"))
    client = ComfyUIClient(args.server)
    api_workflows = ROOT / "workflows" / "api"

    image_run = TwoFrameImageSequence(client).run(
        z_image_workflow=api_workflows / "z-image-turbo.api.json",
        qwen_edit_workflow=api_workflows / "qwen-image-edit-2509.api.json",
        first_prompt=config["first_prompt"],
        edit_prompt=config["second_frame_prompt"],
        negative_prompt=config["negative_prompt"],
        output_root=args.output_root,
        width=config["width"],
        height=config["height"],
        first_seed=config["first_seed"],
        edit_seed=config["second_frame_seed"],
        timeout_seconds=args.image_timeout,
    )

    video_run = ThreeFrameVideoSequence(client).run(
        first_frame=image_run / "frame-0001.png",
        second_frame=image_run / "frame-0002.png",
        qwen_edit_workflow=api_workflows / "qwen-image-edit-2509.api.json",
        h3_workflow=api_workflows / "minimax-h3-first-last-frame.api.json",
        third_frame_prompt=config["third_frame_prompt"],
        negative_prompt=config["negative_prompt"],
        first_clip_prompt=config["first_clip_prompt"],
        second_clip_prompt=config["second_clip_prompt"],
        output_root=image_run / "video-sequence",
        edit_seed=config["third_frame_seed"],
        first_clip_seed=config["first_clip_seed"],
        second_clip_seed=config["second_clip_seed"],
        clip_seconds=config["clip_seconds"],
        timeout_seconds=args.video_timeout,
    )
    print(f"Bicycle sequence completed: {video_run}")


if __name__ == "__main__":
    main()
