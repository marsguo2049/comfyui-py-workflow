from __future__ import annotations

from comfyui_py_workflow.duration_advisor import (
    analyze_story_duration,
    build_duration_options,
)


def test_duration_options_are_five_second_local_render_estimates() -> None:
    options = build_duration_options(60)
    assert [option.seconds for option in options] == [40, 60, 90]
    assert all(option.seconds % 5 == 0 for option in options)
    assert options[1].shot_count == 12
    assert options[1].estimated_render_minutes == 63


def test_story_analysis_uses_structured_local_result() -> None:
    class FakeClient:
        def structured_chat(self, **kwargs):
            return {
                "title": "Local story",
                "synopsis": "A local-only test.",
                "genre": "drama",
                "key_events": ["beginning", "ending"],
                "visual_complexity": "medium",
                "recommended_duration_seconds": 58,
                "rationale": "Two visual beats need room.",
            }

    result = analyze_story_duration(
        FakeClient(),
        model="local/model",
        source_text="A short story",
    )
    assert result.recommended_duration_seconds == 60
    assert result.options[1].seconds == 60
