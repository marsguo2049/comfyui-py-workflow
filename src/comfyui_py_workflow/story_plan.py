from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class StoryPlanError(ValueError):
    """Raised when a generated story plan is incomplete or inconsistent."""


SUPPORTED_ASPECT_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"}


def clip_durations(target_seconds: float, clip_seconds: float = 5.0) -> list[float]:
    if not math.isfinite(target_seconds) or target_seconds <= 0:
        raise ValueError("Target duration must be a positive finite number")
    if not math.isfinite(clip_seconds) or clip_seconds <= 0:
        raise ValueError("Clip duration must be a positive finite number")
    count = math.ceil(target_seconds / clip_seconds)
    durations = [float(clip_seconds)] * count
    durations[-1] = float(target_seconds - clip_seconds * (count - 1))
    return durations


@dataclass(frozen=True)
class VisualBible:
    style: str
    characters: list[str]
    locations: list[str]
    continuity_rules: list[str]
    global_negative_prompt: str


@dataclass(frozen=True)
class StoryShot:
    index: int
    duration_seconds: float
    transition_from_previous: str
    summary: str
    start_frame_prompt: str
    end_frame_edit_prompt: str
    video_prompt: str


@dataclass(frozen=True)
class StoryPlan:
    schema_version: int
    title: str
    summary: str
    target_duration_seconds: float
    clip_seconds: float
    aspect_ratio: str
    visual_bible: VisualBible
    shots: list[StoryShot]

    @property
    def estimated_frame_count(self) -> int:
        cuts_after_first = sum(
            shot.transition_from_previous == "cut" for shot in self.shots[1:]
        )
        return len(self.shots) + 1 + cuts_after_first

    def validate(self) -> None:
        if self.schema_version != 1:
            raise StoryPlanError("Unsupported story plan schema_version")
        if not self.title.strip() or not self.summary.strip():
            raise StoryPlanError("Story plan title and summary are required")
        if self.aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            raise StoryPlanError(f"Unsupported aspect ratio: {self.aspect_ratio}")
        expected = clip_durations(self.target_duration_seconds, self.clip_seconds)
        if len(self.shots) != len(expected):
            raise StoryPlanError(
                f"Expected {len(expected)} shots for the requested duration, found {len(self.shots)}"
            )
        for position, (shot, duration) in enumerate(zip(self.shots, expected), start=1):
            if shot.index != position:
                raise StoryPlanError(f"Shot indexes must be sequential; expected {position}")
            if not math.isclose(shot.duration_seconds, duration, abs_tol=0.01):
                raise StoryPlanError(
                    f"Shot {position} duration must be {duration:g} seconds"
                )
            if shot.transition_from_previous not in {"continuous", "cut"}:
                raise StoryPlanError(
                    f"Shot {position} transition must be 'continuous' or 'cut'"
                )
            if position == 1 and shot.transition_from_previous != "cut":
                raise StoryPlanError("The first shot transition must be 'cut'")
            required = {
                "summary": shot.summary,
                "start_frame_prompt": shot.start_frame_prompt,
                "end_frame_edit_prompt": shot.end_frame_edit_prompt,
                "video_prompt": shot.video_prompt,
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise StoryPlanError(
                    f"Shot {position} has empty required fields: {', '.join(missing)}"
                )
        if not self.visual_bible.style.strip():
            raise StoryPlanError("Visual bible style is required")
        if not self.visual_bible.global_negative_prompt.strip():
            raise StoryPlanError("A global negative prompt is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: str | Path) -> Path:
        self.validate()
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return destination

    @classmethod
    def read(cls, path: str | Path) -> StoryPlan:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoryPlan:
        try:
            bible_data = data["visual_bible"]
            bible = VisualBible(
                style=str(bible_data["style"]),
                characters=[str(value) for value in bible_data["characters"]],
                locations=[str(value) for value in bible_data["locations"]],
                continuity_rules=[str(value) for value in bible_data["continuity_rules"]],
                global_negative_prompt=str(bible_data["global_negative_prompt"]),
            )
            shots = [
                StoryShot(
                    index=int(shot["index"]),
                    duration_seconds=float(shot["duration_seconds"]),
                    transition_from_previous=str(shot["transition_from_previous"]),
                    summary=str(shot["summary"]),
                    start_frame_prompt=str(shot["start_frame_prompt"]),
                    end_frame_edit_prompt=str(shot["end_frame_edit_prompt"]),
                    video_prompt=str(shot["video_prompt"]),
                )
                for shot in data["shots"]
            ]
            plan = cls(
                schema_version=int(data["schema_version"]),
                title=str(data["title"]),
                summary=str(data["summary"]),
                target_duration_seconds=float(data["target_duration_seconds"]),
                clip_seconds=float(data["clip_seconds"]),
                aspect_ratio=str(data["aspect_ratio"]),
                visual_bible=bible,
                shots=shots,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StoryPlanError(f"Malformed story plan: {exc}") from exc
        plan.validate()
        return plan


def story_plan_schema(shot_count: int) -> dict[str, Any]:
    string = {"type": "string", "minLength": 1}
    string_list = {"type": "array", "items": string}
    shot = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "index": {"type": "integer", "minimum": 1},
            "duration_seconds": {"type": "number", "exclusiveMinimum": 0},
            "transition_from_previous": {
                "type": "string",
                "enum": ["continuous", "cut"],
            },
            "summary": string,
            "start_frame_prompt": string,
            "end_frame_edit_prompt": string,
            "video_prompt": string,
        },
        "required": [
            "index",
            "duration_seconds",
            "transition_from_previous",
            "summary",
            "start_frame_prompt",
            "end_frame_edit_prompt",
            "video_prompt",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "title": string,
            "summary": string,
            "target_duration_seconds": {"type": "number", "exclusiveMinimum": 0},
            "clip_seconds": {"type": "number", "exclusiveMinimum": 0},
            "aspect_ratio": string,
            "visual_bible": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "style": string,
                    "characters": string_list,
                    "locations": string_list,
                    "continuity_rules": string_list,
                    "global_negative_prompt": string,
                },
                "required": [
                    "style",
                    "characters",
                    "locations",
                    "continuity_rules",
                    "global_negative_prompt",
                ],
            },
            "shots": {
                "type": "array",
                "items": shot,
                "minItems": shot_count,
                "maxItems": shot_count,
            },
        },
        "required": [
            "schema_version",
            "title",
            "summary",
            "target_duration_seconds",
            "clip_seconds",
            "aspect_ratio",
            "visual_bible",
            "shots",
        ],
    }
