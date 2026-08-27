from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from comfyui_py_workflow.client import ComfyUIClient
from comfyui_py_workflow.story_plan import StoryPlan
from comfyui_py_workflow.story_video import (
    ASPECT_RATIOS,
    StoryVideoExecutor,
    prepare_h3_prompt,
    resolution_for_aspect,
)
from comfyui_py_workflow.video_sequence import media_duration, remux_segments


ROOT = Path(__file__).resolve().parents[1]


def test_resolution_matches_requested_aspect() -> None:
    width, height = resolution_for_aspect("16:9")
    assert width % 32 == 0
    assert height % 32 == 0
    assert width > height
    assert ASPECT_RATIOS["16:9"] == "16:9 (Widescreen)"


def test_rejects_unknown_aspect() -> None:
    with pytest.raises(ValueError, match="Unsupported aspect ratio"):
        resolution_for_aspect("5:4")


def test_remux_requires_one_duration_per_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="One segment duration"):
        remux_segments(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"],
            tmp_path / "out.mp4",
            segment_seconds=[5],
        )


def test_h3_prompt_uses_official_fl2va_structure_and_suppresses_unscripted_speech() -> None:
    prompt = prepare_h3_prompt(
        "快递员走进车站。音效：远处传来含混的人声。",
        duration_seconds=5,
        dialogue_mode="auto",
    )
    assert prompt.startswith("How the reference pictures align with the target video")
    assert "5.00-second mark" in prompt
    assert "integrated_multimodal_description:" in prompt
    assert "overall_soundscape:" in prompt
    assert "non_diegetic_music:" in prompt
    assert "No dialogue, narration, singing, or intelligible speech" in prompt
    assert "含混的人声" not in prompt


def test_h3_prompt_preserves_exact_tagged_dialogue() -> None:
    raw = (
        "integrated_multimodal_description: [Shot 1] The courier (S1) says softly: "
        "<d>[Chinese] 包裹已送达。</d>\n\n"
        "overall_soundscape: Rain taps against the station windows.\n\n"
        "non_diegetic_music: N/A"
    )
    prompt = prepare_h3_prompt(raw, duration_seconds=5, dialogue_mode="dialogue")
    assert "<d>[Chinese] 包裹已送达。</d>" in prompt
    assert "No dialogue" not in prompt


def test_dynamic_executor_runs_one_shot_with_fake_comfyui(tmp_path: Path) -> None:
    run_calls = []
    qwen_prompts = []

    class FakeClient:
        input_reference = staticmethod(ComfyUIClient.input_reference)
        output_assets = staticmethod(ComfyUIClient.output_assets)

        def check_health(self):
            return {"system": "fake"}

        def upload_image(self, path, *, filename, subfolder):
            assert Path(path).is_file()
            return {"name": filename, "subfolder": subfolder}

        def run(self, workflow, timeout_seconds):
            run_calls.append(set(workflow))
            if "24" in workflow:
                assert workflow["26"]["inputs"]["value"] == 1
                assert workflow["23"]["inputs"]["aspect_ratio"] == "1:1 (Square)"
                h3_prompt = workflow["12"]["inputs"]["prompt"]
                assert h3_prompt.startswith("How the reference pictures align")
                assert "No dialogue, narration, singing, or intelligible speech" in h3_prompt
                return "video-prompt", {
                    "outputs": {
                        "24": {
                            "video": [
                                {"filename": "fake.mp4", "subfolder": "", "type": "output"}
                            ]
                        }
                    }
                }
            node_id = "469" if "469" in workflow else "9"
            if node_id == "469":
                qwen_prompts.append(workflow["433:111"]["inputs"]["prompt"])
            return f"image-{node_id}", {
                "outputs": {
                    node_id: {
                        "images": [
                            {"filename": "fake.png", "subfolder": "", "type": "output"}
                        ]
                    }
                }
            }

        def download_asset(self, asset, destination):
            output = Path(destination)
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.suffix == ".mp4":
                shutil.copyfile(
                    ROOT / "examples" / "bicycle-sequence" / "assets" / "bicycle-final-10s.mp4",
                    output,
                )
            else:
                output.write_bytes(b"fake image")
            return output

    plan = StoryPlan.from_dict({
        "schema_version": 1,
        "title": "测试",
        "summary": "一秒测试镜头",
        "target_duration_seconds": 1,
        "clip_seconds": 5,
        "aspect_ratio": "1:1",
        "visual_bible": {
            "style": "写实",
            "characters": ["骑手"],
            "locations": ["道路"],
            "continuity_rules": ["保持服装"],
            "global_negative_prompt": "水印，重复人物",
        },
        "shots": [{
            "index": 1,
            "duration_seconds": 1,
            "transition_from_previous": "cut",
            "summary": "骑手前进",
            "start_frame_prompt": "骑手位于道路起点",
            "end_frame_edit_prompt": "骑手前进一步",
            "video_prompt": "骑手前进，镜头跟随",
        }],
    })
    executor = StoryVideoExecutor(
        FakeClient(),
        z_image_workflow=ROOT / "workflows" / "api" / "z-image-turbo.api.json",
        qwen_edit_workflow=ROOT / "workflows" / "api" / "qwen-image-edit-2509.api.json",
        h3_workflow=ROOT / "workflows" / "api" / "minimax-h3-first-last-frame.api.json",
    )
    events = []
    render_dir = tmp_path / "render"
    destination = executor.run(
        plan,
        output_root=tmp_path,
        destination=render_dir,
        progress_callback=events.append,
    )
    metadata = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "succeeded"
    assert metadata["estimated_frame_count"] == 2
    assert 0.9 <= media_duration(destination / "final.mp4") <= 1.1
    mp4 = (destination / "final.mp4").read_bytes()
    assert mp4.find(b"moov") < mp4.find(b"mdat")
    assert events[-1]["stage"] == "completed"

    call_count = len(run_calls)
    resumed = executor.run(
        plan,
        output_root=tmp_path,
        destination=render_dir,
        resume=True,
        progress_callback=events.append,
    )
    assert resumed == destination
    assert len(run_calls) == call_count

    run_calls.clear()
    qwen_prompts.clear()
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"fake local reference")
    referenced_destination = executor.run(
        plan,
        output_root=tmp_path,
        destination=tmp_path / "render-with-reference",
        reference_image=reference,
        progress_callback=events.append,
    )
    image_workflows = [nodes for nodes in run_calls if "24" not in nodes]
    assert image_workflows and all("469" in nodes for nodes in image_workflows)
    assert qwen_prompts[0].startswith("Use the uploaded image as the authoritative visual reference")
    referenced_metadata = json.loads(
        (referenced_destination / "run.json").read_text(encoding="utf-8")
    )
    assert referenced_metadata["reference_sha256"]
    assert referenced_metadata["shots"][0]["start_frame_generation"]["model"].endswith(
        "reference-start"
    )
