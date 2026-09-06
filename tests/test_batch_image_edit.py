from __future__ import annotations

from pathlib import Path

from comfyui_py_workflow.batch_image_edit import (
    QwenBatchImageEditor,
    default_qwen_workflow_path,
    discover_images,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self) -> None:
        self.workflows: list[dict] = []

    def check_health(self) -> dict:
        return {"ok": True}

    def upload_image(self, path, *, filename, subfolder, overwrite):
        assert Path(path).is_file()
        assert overwrite is True
        return {"name": filename, "subfolder": subfolder}

    @staticmethod
    def input_reference(upload):
        return f"{upload['subfolder']}/{upload['name']}"

    def run(self, workflow, timeout_seconds):
        self.workflows.append(workflow)
        return "prompt-1", {
            "outputs": {
                "469": {
                    "images": [
                        {"filename": "result.png", "subfolder": "", "type": "output"}
                    ]
                }
            }
        }

    @staticmethod
    def output_assets(history, node_id=None):
        from comfyui_py_workflow.client import ComfyUIClient

        return ComfyUIClient.output_assets(history, node_id=node_id)

    @staticmethod
    def download_asset(asset, destination):
        path = Path(destination)
        path.write_bytes(b"result")
        return path


def test_discovers_supported_images_without_duplicates(tmp_path: Path) -> None:
    (tmp_path / "a.PNG").write_bytes(b"a")
    (tmp_path / "b.jpg").write_bytes(b"b")
    (tmp_path / "ignore.txt").write_text("no", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.webp").write_bytes(b"c")

    flat = discover_images([tmp_path, tmp_path / "a.PNG"])
    assert [path.name for path in flat] == ["a.PNG", "b.jpg"]
    recursive = discover_images([tmp_path], recursive=True)
    assert [path.name for path in recursive] == ["a.PNG", "b.jpg", "c.webp"]


def test_windows_launcher_is_ascii_safe_for_cmd() -> None:
    launcher = (ROOT / "start-batch-image-edit-ui.bat").read_bytes()
    text = launcher.decode("ascii")
    assert "--diagnose" in text
    assert "python.exe" in text


def test_batch_editor_applies_shared_prompt_and_unique_output_names(tmp_path: Path) -> None:
    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "photo.png"
    second = second_dir / "photo.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    output = tmp_path / "output"
    client = FakeClient()

    result = QwenBatchImageEditor(client).run(
        images=[first, second],
        output_dir=output,
        prompt="turn the sky blue",
        negative_prompt="text",
        workflow_path=default_qwen_workflow_path(),
        base_seed=100,
    )

    assert result.succeeded_count == 2
    assert [item.destination.name for item in result.items] == [
        "photo_edited.png",
        "photo_edited-2.png",
    ]
    assert [workflow["433:111"]["inputs"]["prompt"] for workflow in client.workflows] == [
        "turn the sky blue",
        "turn the sky blue",
    ]
    assert [workflow["433:110"]["inputs"]["prompt"] for workflow in client.workflows] == [
        "text",
        "text",
    ]
    assert [workflow["433:3"]["inputs"]["seed"] for workflow in client.workflows] == [100, 101]
    assert all("cpw-batch-edit/" in workflow["78"]["inputs"]["image"] for workflow in client.workflows)
