from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "workflows" / "api"


def load(name: str) -> dict:
    return json.loads((API / name).read_text(encoding="utf-8"))


def test_z_image_workflow_has_expected_inputs() -> None:
    workflow = load("z-image-turbo.api.json")
    assert workflow["57:27"]["inputs"]["text"] == ""
    assert workflow["57:13"]["inputs"]["width"] == 768
    assert workflow["9"]["class_type"] == "SaveImage"


def test_qwen_workflow_uses_example_input() -> None:
    workflow = load("qwen-image-edit-2509.api.json")
    assert workflow["78"]["inputs"]["image"] == "bicycle-frame-0001.png"
    assert workflow["433:111"]["inputs"]["prompt"] == ""
    assert workflow["433:110"]["inputs"]["prompt"] == ""
    assert workflow["469"]["class_type"] == "SaveImageAdvanced"


def test_h3_workflow_uses_first_and_last_frames() -> None:
    workflow = load("minimax-h3-first-last-frame.api.json")
    assert workflow["22"]["inputs"]["image"] == "bicycle-frame-0001.png"
    assert workflow["20"]["inputs"]["image"] == "bicycle-frame-0002.png"
    assert workflow["23"]["inputs"]["aspect_ratio"] == "1:1 (Square)"
    assert workflow["12"]["inputs"]["prompt"] == ""
    assert workflow["24"]["class_type"] == "SaveVideo"


def test_workflows_contain_no_machine_specific_paths() -> None:
    for workflow in sorted((ROOT / "workflows").rglob("*.json")):
        text = workflow.read_text(encoding="utf-8").lower()
        assert "c:\\users\\" not in text
        assert "c:/users/" not in text
        assert "c:\\local-llm" not in text
        assert "c:/local-llm" not in text


def test_ui_workflows_contain_no_generation_prompts() -> None:
    for workflow_path in sorted((ROOT / "workflows" / "ui").glob("*.json")):
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        node_groups = [workflow.get("nodes", [])]
        node_groups.extend(
            subgraph.get("nodes", [])
            for subgraph in workflow.get("definitions", {}).get("subgraphs", [])
        )
        for nodes in node_groups:
            for node in nodes:
                if node.get("type") == "MarkdownNote":
                    continue
                named = node.get("widgets_values_named", {})
                for field in ("text", "prompt", "prompt_1"):
                    assert not str(named.get(field, "")).strip(), (
                        workflow_path,
                        node.get("id"),
                        field,
                    )
