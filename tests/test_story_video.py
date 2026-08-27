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


def test_dynamic_executor_runs_one_shot_with_fake_comfyui(tmp_path: Path) -> None:
    class FakeClient:
        input_reference = staticmethod(ComfyUIClient.input_reference)
        output_assets = staticmethod(ComfyUIClient.output_assets)

        def check_health(self):
            return {"system": "fake"}

        def upload_image(self, path, *, filename, subfolder):
            assert Path(path).is_file()
            return {"name": filename, "subfolder": subfolder}

        def run(self, workflow, timeout_seconds):
            if "24" in workflow:
                assert workflow["26"]["inputs"]["value"] == 1
                assert workflow["23"]["inputs"]["aspect_ratio"] == "1:1 (Square)"
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
    destination = executor.run(plan, output_root=tmp_path)
    metadata = json.loads((destination / "run.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "succeeded"
    assert metadata["estimated_frame_count"] == 2
    assert 0.9 <= media_duration(destination / "final.mp4") <= 1.1
