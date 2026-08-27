from __future__ import annotations

import json
import math
from typing import Any

from .lmstudio import LMStudioClient
from .story_plan import (
    SUPPORTED_DIALOGUE_MODES,
    StoryPlan,
    StoryPlanError,
    clip_durations,
    story_plan_schema,
)


SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "key_events": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "characters": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "locations": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    },
    "required": ["summary", "key_events", "characters", "locations"],
}


def chunk_text(text: str, max_chars: int = 12_000) -> list[str]:
    if max_chars < 1000:
        raise ValueError("max_chars must be at least 1000")
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        pieces = [paragraph[index:index + max_chars] for index in range(0, len(paragraph), max_chars)]
        for piece in pieces:
            extra = len(piece) + (2 if current else 0)
            if current and current_length + extra > max_chars:
                chunks.append("\n\n".join(current))
                current = []
                current_length = 0
            current.append(piece)
            current_length += len(piece) + (2 if current_length else 0)
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def prepare_story_source(
    client: LMStudioClient,
    *,
    model: str,
    source_text: str,
    direct_limit_chars: int = 30_000,
    chunk_chars: int = 12_000,
) -> str:
    if len(source_text) <= direct_limit_chars:
        return source_text
    summaries: list[dict[str, Any]] = []
    chunks = chunk_text(source_text, max_chars=chunk_chars)
    for index, chunk in enumerate(chunks, start=1):
        summary = client.structured_chat(
            model=model,
            schema_name="story_source_summary",
            schema=SUMMARY_SCHEMA,
            temperature=0.1,
            max_tokens=2048,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize source material for later storyboarding. Preserve causal order, "
                        "character identity, locations, visual facts, and the ending. Do not invent events."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Source chunk {index}/{len(chunks)}:\n\n{chunk}",
                },
            ],
        )
        summaries.append(summary)
    return "\n\n".join(
        f"CHUNK {index}\n{json.dumps(summary, ensure_ascii=False)}"
        for index, summary in enumerate(summaries, start=1)
    )


def create_story_plan(
    client: LMStudioClient,
    *,
    model: str,
    source_text: str,
    target_duration_seconds: float,
    clip_seconds: float = 5.0,
    aspect_ratio: str = "16:9",
    style: str | None = None,
    output_language: str = "Chinese",
    dialogue_mode: str = "auto",
    has_reference_image: bool = False,
) -> StoryPlan:
    if dialogue_mode not in SUPPORTED_DIALOGUE_MODES:
        raise ValueError(f"Unsupported dialogue mode: {dialogue_mode}")
    durations = clip_durations(target_duration_seconds, clip_seconds)
    prepared_source = prepare_story_source(client, model=model, source_text=source_text)
    style_instruction = style.strip() if style and style.strip() else "Choose a coherent visual style suited to the story."
    reference_instruction = (
        "A single user-supplied reference image will be passed directly to Qwen Image Edit for "
        "every independently composed start frame. Treat that image as the authoritative source "
        "for visible subject identity, face, clothing, objects, and visual style. Do not invent "
        "specific unseen traits. Write each start_frame_prompt as a complete target composition "
        "that tells the image editor what to preserve from the reference and what scene to create."
        if has_reference_image
        else "No reference image is supplied; start frames will be generated from text with Z-Image."
    )
    system_prompt = """
You are a meticulous storyboard director and prompt engineer for a fully local image-to-video pipeline.
Return only the requested structured data. Preserve the source story; do not add unrelated plot points.

Prompt responsibilities:
- start_frame_prompt: a complete standalone still-image target. Without a reference image it is a Z-Image generation prompt; with a reference image it is a Qwen Image Edit composition instruction. Repeat the identity-preservation, environment, composition, lighting, and style requirements needed for the frame.
- end_frame_edit_prompt: a Qwen Image Edit instruction describing only the controlled visual change from this shot's start frame to its end frame. Preserve identity, wardrobe, object geometry, location, and style unless the story requires a change.
- video_prompt: an English MiniMax H3 FL2VA prompt that follows the official format exactly. Begin with the first/last-frame alignment sentence, then use the three fields integrated_multimodal_description, overall_soundscape, and non_diegetic_music. Use one continuous [Shot 1] that physically travels from Picture 1 at 0.00 seconds to Picture 2 at this shot's exact ending time. Cover subject motion, camera motion, timing, environmental motion, and audio without contradicting either endpoint image.
- global_negative_prompt: reusable defects to avoid, including duplicate subjects, distorted anatomy or geometry, identity drift, unintended text, logos, and watermarks.

Use transition_from_previous='continuous' when this shot begins exactly from the previous shot's end frame. Use 'cut' for a new time, location, viewpoint, or independent shot. The first shot must use 'cut'.

MiniMax H3 audio rules:
- Only exact spoken words inside <d>[Language] ...</d> count as dialogue. Never request vague "talking", "a voice", "speech", or unspecified words.
- Give every speaking character a stable ID such as (S1). Put speaker identity and delivery outside <d>; put only the language tag and exact spoken words inside it.
- A five-second clip may contain at most one short, complete spoken line. Do not let speech run past the end of a clip.
- Keep dialogue out of overall_soundscape. That field contains ambience, physical sounds, and non-verbal sounds only. Put audience-only music in non_diegetic_music, or N/A when absent.
""".strip()
    dialogue_instruction = {
        "auto": (
            "AUTO: Decide per shot whether a short spoken line is narratively necessary. Use dialogue "
            "only for a meaningful source-story line or essential communication; never invent filler. "
            "If a shot has no <d> tag, explicitly state that nobody speaks and no intelligible voice is heard."
        ),
        "none": (
            "NONE: No dialogue, narration, voiceover, whispering, or singing in any shot. Do not use "
            "<d> tags. Explicitly state that nobody speaks, no intelligible voice is heard, and visible "
            "mouths remain closed except for non-verbal reactions. Ambience, foley, and music are allowed."
        ),
        "dialogue": (
            "DIALOGUE: Include concise story-relevant dialogue or voiceover in at least one shot. Every "
            "spoken line must use a stable speaker ID and exact <d>[Language] ...</d> syntax. Keep each "
            "line short enough to finish naturally within its five-second clip."
        ),
    }[dialogue_mode]
    user_prompt = f"""
Create a storyboard in {output_language} from the source below.

Hard constraints:
- target_duration_seconds: {target_duration_seconds:g}
- clip_seconds: {clip_seconds:g}
- exactly {len(durations)} shots
- shot durations in order: {json.dumps(durations)}
- aspect_ratio: {aspect_ratio}
- style instruction: {style_instruction}
- dialogue_mode: {dialogue_mode}
- dialogue policy: {dialogue_instruction}
- indexes must be 1 through {len(durations)}
- every prompt field must be non-empty
- reference image policy: {reference_instruction}

Source:
{prepared_source}
""".strip()
    schema = story_plan_schema(len(durations))
    schema["properties"]["dialogue_mode"] = {"type": "string", "const": dialogue_mode}
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: StoryPlanError | None = None
    for attempt in range(2):
        data = client.structured_chat(
            model=model,
            schema_name="story_video_plan",
            schema=schema,
            messages=messages,
            temperature=0.25 if attempt == 0 else 0.0,
            max_tokens=max(4096, len(durations) * 1200),
        )
        data.setdefault("dialogue_mode", dialogue_mode)
        try:
            plan = StoryPlan.from_dict(data)
            if not math.isclose(
                plan.target_duration_seconds,
                target_duration_seconds,
                abs_tol=0.01,
            ):
                raise StoryPlanError("Top-level target duration changed from the request")
            if not math.isclose(plan.clip_seconds, clip_seconds, abs_tol=0.01):
                raise StoryPlanError("Top-level clip duration changed from the request")
            if plan.aspect_ratio != aspect_ratio:
                raise StoryPlanError("Aspect ratio changed from the request")
            if plan.dialogue_mode != dialogue_mode:
                raise StoryPlanError("Dialogue mode changed from the request")
            return plan
        except StoryPlanError as exc:
            last_error = exc
            messages.extend([
                {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        f"The plan failed semantic validation: {exc}. Regenerate the complete plan "
                        "and obey every hard constraint exactly."
                    ),
                },
            ])
    raise StoryPlanError(f"LM Studio could not produce a valid story plan: {last_error}")
