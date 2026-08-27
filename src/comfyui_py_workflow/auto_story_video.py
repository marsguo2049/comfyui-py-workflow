from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .documents import read_document
from .lmstudio import LMStudioClient
from .story_plan import StoryPlan
from .story_planner import create_story_plan


def _print_plan_summary(plan: StoryPlan, path: Path | None = None) -> None:
    if path is not None:
        print(f"Story plan: {path}")
    print(f"Title: {plan.title}")
    print(f"Duration: {plan.target_duration_seconds:g} seconds")
    print(f"Shots: {len(plan.shots)}")
    print(f"Estimated keyframes: {plan.estimated_frame_count}")
    print(f"Aspect ratio: {plan.aspect_ratio}")


def _plan_destination(output_root: Path) -> Path:
    identifier = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    return output_root / "plans" / identifier / "story-plan.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan and optionally generate a local story video with LM Studio and ComfyUI"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--story", help="Short story text supplied directly on the command line")
    source.add_argument("--input", type=Path, help="TXT, Markdown, DOCX, or text-based PDF source")
    source.add_argument("--plan", type=Path, help="Existing story-plan.json to inspect or execute")
    parser.add_argument("--duration", type=float, help="Target video duration in seconds")
    parser.add_argument("--clip-seconds", type=float, default=5.0)
    parser.add_argument("--style", help="Optional visual style instruction")
    parser.add_argument(
        "--aspect-ratio",
        choices=["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"],
        default="16:9",
    )
    parser.add_argument("--output-language", default="Chinese")
    parser.add_argument("--model", default=os.environ.get("LM_STUDIO_MODEL"))
    parser.add_argument(
        "--lm-studio",
        default=os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234/v1"),
    )
    parser.add_argument("--lm-timeout", type=float, default=300.0)
    parser.add_argument("--allow-remote-lm-studio", action="store_true")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run ComfyUI after planning; without this flag only a reviewable plan is written",
    )
    parser.add_argument(
        "--keep-lm-loaded",
        action="store_true",
        help="Do not unload the LM Studio model before same-command ComfyUI execution",
    )
    parser.add_argument(
        "--comfyui",
        default=os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188"),
    )
    parser.add_argument("--output-root", type=Path, default=Path("outputs/story-video"))
    parser.add_argument("--base-seed", type=int, default=1000)
    parser.add_argument("--image-timeout", type=float, default=900.0)
    parser.add_argument("--video-timeout", type=float, default=1800.0)
    parser.add_argument(
        "--z-workflow",
        type=Path,
        default=Path("workflows/api/z-image-turbo.api.json"),
    )
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
    args = parser.parse_args()

    if args.plan:
        plan = StoryPlan.read(args.plan)
        if not args.execute:
            _print_plan_summary(plan, args.plan)
            return
    else:
        if args.duration is None:
            parser.error("--duration is required when using --story or --input")
        source_text = args.story if args.story is not None else read_document(args.input)
        client = LMStudioClient(
            args.lm_studio,
            api_token=os.environ.get("LM_STUDIO_API_TOKEN"),
            timeout_seconds=args.lm_timeout,
            allow_remote=args.allow_remote_lm_studio,
        )
        model = client.resolve_model(args.model)
        print(f"Planning with local LM Studio model: {model}")
        plan = create_story_plan(
            client,
            model=model,
            source_text=source_text,
            target_duration_seconds=args.duration,
            clip_seconds=args.clip_seconds,
            aspect_ratio=args.aspect_ratio,
            style=args.style,
            output_language=args.output_language,
        )
        if not args.execute:
            destination = plan.write(_plan_destination(args.output_root))
            _print_plan_summary(plan, destination)
            print("Review the plan, then execute it with: cpw-story-video --plan <path> --execute")
            return
        planned_path = plan.write(_plan_destination(args.output_root))
        print(f"Saved story plan before media execution: {planned_path}")
        if not args.keep_lm_loaded:
            unloaded = client.unload_model(model)
            print(f"Unloaded LM Studio model instance(s): {', '.join(unloaded)}")

    from .client import ComfyUIClient
    from .story_video import StoryVideoExecutor

    executor = StoryVideoExecutor(
        ComfyUIClient(args.comfyui),
        z_image_workflow=args.z_workflow,
        qwen_edit_workflow=args.qwen_workflow,
        h3_workflow=args.h3_workflow,
    )
    destination = executor.run(
        plan,
        output_root=args.output_root,
        base_seed=args.base_seed,
        image_timeout_seconds=args.image_timeout,
        video_timeout_seconds=args.video_timeout,
    )
    _print_plan_summary(plan, destination / "story-plan.json")
    print(f"Story video completed: {destination / 'final.mp4'}")


if __name__ == "__main__":
    main()
