from __future__ import annotations

from pathlib import Path

import pytest

from comfyui_py_workflow.story_plan import (
    StoryPlan,
    StoryPlanError,
    clip_durations,
    story_plan_schema,
)
from comfyui_py_workflow.story_planner import chunk_text, create_story_plan


ROOT = Path(__file__).resolve().parents[1]


def plan_data() -> dict:
    return {
        "schema_version": 1,
        "title": "雨中信使",
        "summary": "信使穿过街道。",
        "target_duration_seconds": 12,
        "clip_seconds": 5,
        "aspect_ratio": "16:9",
        "visual_bible": {
            "style": "电影写实",
            "characters": ["红衣信使"],
            "locations": ["雨夜街道"],
            "continuity_rules": ["保持红色外套"],
            "global_negative_prompt": "人物重复，水印，文字",
        },
        "shots": [
            {
                "index": 1,
                "duration_seconds": 5,
                "transition_from_previous": "cut",
                "summary": "进入街道",
                "start_frame_prompt": "红衣信使站在雨夜街道入口",
                "end_frame_edit_prompt": "信使向前走到路灯下",
                "video_prompt": "信使向前行走，镜头缓慢跟随，雨声",
            },
            {
                "index": 2,
                "duration_seconds": 5,
                "transition_from_previous": "continuous",
                "summary": "继续前进",
                "start_frame_prompt": "红衣信使位于路灯下",
                "end_frame_edit_prompt": "信使走到街道尽头",
                "video_prompt": "信使继续行走，稳定跟拍，雨声",
            },
            {
                "index": 3,
                "duration_seconds": 2,
                "transition_from_previous": "cut",
                "summary": "抵达门口",
                "start_frame_prompt": "红衣信使站在门外",
                "end_frame_edit_prompt": "信使抬手敲门",
                "video_prompt": "信使敲门，固定镜头，敲门声",
            },
        ],
    }


def test_clip_durations_keeps_exact_target() -> None:
    assert clip_durations(12, 5) == [5.0, 5.0, 2.0]
    assert clip_durations(5, 5) == [5.0]


def test_plan_counts_frames_across_cuts() -> None:
    plan = StoryPlan.from_dict(plan_data())
    assert plan.estimated_frame_count == 5


def test_plan_rejects_wrong_duration() -> None:
    data = plan_data()
    data["shots"][2]["duration_seconds"] = 5
    with pytest.raises(StoryPlanError, match="duration must be 2"):
        StoryPlan.from_dict(data)


def test_schema_requires_exact_shot_count() -> None:
    shots = story_plan_schema(4)["properties"]["shots"]
    assert shots["minItems"] == shots["maxItems"] == 4


def test_chunk_text_preserves_content_order() -> None:
    text = "A" * 900 + "\n\n" + "B" * 900
    chunks = chunk_text(text, max_chars=1000)
    assert len(chunks) == 2
    assert chunks[0].startswith("A")
    assert chunks[1].startswith("B")


def test_planner_accepts_valid_structured_result() -> None:
    class FakeClient:
        def structured_chat(self, **kwargs):
            return plan_data()

    plan = create_story_plan(
        FakeClient(),
        model="local/model",
        source_text="信使穿过雨夜街道。",
        target_duration_seconds=12,
        clip_seconds=5,
        aspect_ratio="16:9",
    )
    assert len(plan.shots) == 3


def test_planner_rejects_model_changing_requested_duration() -> None:
    class FakeClient:
        def structured_chat(self, **kwargs):
            data = plan_data()
            data["target_duration_seconds"] = 13
            data["shots"][2]["duration_seconds"] = 3
            return data

    with pytest.raises(StoryPlanError, match="could not produce a valid story plan"):
        create_story_plan(
            FakeClient(),
            model="local/model",
            source_text="信使穿过雨夜街道。",
            target_duration_seconds=12,
            clip_seconds=5,
            aspect_ratio="16:9",
        )


def test_public_example_plan_is_valid() -> None:
    plan = StoryPlan.read(
        ROOT / "examples" / "auto-story-video" / "story-plan.example.json"
    )
    assert len(plan.shots) == 2
    assert plan.estimated_frame_count == 3
