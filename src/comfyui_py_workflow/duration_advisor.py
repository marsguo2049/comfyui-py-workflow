from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .lmstudio import LMStudioClient
from .story_planner import prepare_story_source


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "synopsis": {"type": "string", "minLength": 1},
        "genre": {"type": "string", "minLength": 1},
        "key_events": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "visual_complexity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "recommended_duration_seconds": {
            "type": "integer",
            "minimum": 15,
            "maximum": 180,
        },
        "rationale": {"type": "string", "minLength": 1},
    },
    "required": [
        "title",
        "synopsis",
        "genre",
        "key_events",
        "visual_complexity",
        "recommended_duration_seconds",
        "rationale",
    ],
}


@dataclass(frozen=True)
class DurationOption:
    key: str
    label: str
    seconds: int
    shot_count: int
    estimated_keyframes: int
    estimated_render_minutes: int
    description: str


@dataclass(frozen=True)
class StoryAnalysis:
    schema_version: int
    title: str
    synopsis: str
    genre: str
    key_events: list[str]
    visual_complexity: str
    recommended_duration_seconds: int
    rationale: str
    options: list[DurationOption]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination


def _round_to_clip(seconds: float, clip_seconds: int = 5) -> int:
    return max(clip_seconds, int(round(seconds / clip_seconds)) * clip_seconds)


def build_duration_options(
    recommended_seconds: int,
    *,
    clip_seconds: int = 5,
    minutes_per_clip: float = 5.2,
) -> list[DurationOption]:
    recommended = min(120, max(30, _round_to_clip(recommended_seconds, clip_seconds)))
    candidates = [
        (
            "concise",
            "精简版",
            max(15, _round_to_clip(recommended * 2 / 3, clip_seconds)),
            "保留主线和最重要的视觉节点，节奏较快。",
        ),
        (
            "recommended",
            "推荐版",
            recommended,
            "在故事完整度、连续性和本机渲染时间之间取得平衡。",
        ),
        (
            "detailed",
            "完整版",
            min(180, _round_to_clip(recommended * 3 / 2, clip_seconds)),
            "保留更多铺垫、转场和人物反应，渲染时间更长。",
        ),
    ]
    options: list[DurationOption] = []
    seen: set[int] = set()
    for key, label, seconds, description in candidates:
        if seconds in seen:
            continue
        seen.add(seconds)
        shot_count = math.ceil(seconds / clip_seconds)
        estimated_keyframes = shot_count + 1 + round(max(0, shot_count - 1) * 0.25)
        options.append(DurationOption(
            key=key,
            label=label,
            seconds=seconds,
            shot_count=shot_count,
            estimated_keyframes=estimated_keyframes,
            estimated_render_minutes=math.ceil(shot_count * minutes_per_clip),
            description=description,
        ))
    return options


def analyze_story_duration(
    client: LMStudioClient,
    *,
    model: str,
    source_text: str,
    output_language: str = "Chinese",
) -> StoryAnalysis:
    prepared_source = prepare_story_source(client, model=model, source_text=source_text)
    result = client.structured_chat(
        model=model,
        schema_name="offline_story_analysis",
        schema=ANALYSIS_SCHEMA,
        temperature=0.15,
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a story editor planning a fully local AI video. Analyze only the "
                    "provided source. Recommend a practical total duration made from five-second "
                    "shots. Prefer 30-120 seconds for a single short film. For long source material, "
                    "recommend a representative episode rather than attempting to visualize every "
                    "sentence. Preserve causal order and do not invent plot points."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Respond in {output_language}. Estimate the shortest duration that still tells "
                    "a coherent visual story. The local benchmark is about 5.2 render minutes for "
                    f"each five-second clip.\n\nSource:\n{prepared_source}"
                ),
            },
        ],
    )
    recommended = int(result["recommended_duration_seconds"])
    return StoryAnalysis(
        schema_version=1,
        title=str(result["title"]),
        synopsis=str(result["synopsis"]),
        genre=str(result["genre"]),
        key_events=[str(value) for value in result["key_events"]],
        visual_complexity=str(result["visual_complexity"]),
        recommended_duration_seconds=_round_to_clip(recommended),
        rationale=str(result["rationale"]),
        options=build_duration_options(recommended),
    )
