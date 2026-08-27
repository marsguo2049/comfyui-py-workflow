from __future__ import annotations

from pathlib import Path

import pytest

from comfyui_py_workflow.studio import OfflineStudio


def test_studio_creates_private_local_text_project(tmp_path: Path) -> None:
    studio = OfflineStudio(tmp_path)
    payload = studio.create_text_project("A fully local story")
    state = payload["state"]
    assert state["status"] == "source_ready"
    assert (Path(payload["project_path"]) / state["source_file"]).read_text(
        encoding="utf-8"
    ) == "A fully local story"


def test_studio_rejects_unsupported_upload(tmp_path: Path) -> None:
    studio = OfflineStudio(tmp_path)
    try:
        studio.create_file_project("story.rtf", b"story")
    except ValueError as exc:
        assert "TXT" in str(exc)
    else:
        raise AssertionError("Unsupported upload was accepted")


def test_studio_attaches_one_private_reference_image(tmp_path: Path) -> None:
    studio = OfflineStudio(tmp_path)
    project = studio.create_text_project("A local story")
    project_id = project["state"]["project_id"]
    image_data = b"\x89PNG\r\n\x1a\n" + b"local-image-data"

    payload = studio.attach_reference_image(project_id, "private portrait.png", image_data)

    assert payload["reference_image"] == "source/reference/reference-image.png"
    assert payload["state"]["reference_image_name"] == "private-portrait.png"
    saved = Path(payload["project_path"]) / payload["reference_image"]
    assert saved.read_bytes() == image_data


def test_studio_rejects_reference_with_mismatched_extension(tmp_path: Path) -> None:
    studio = OfflineStudio(tmp_path)
    project_id = studio.create_text_project("A local story")["state"]["project_id"]
    with pytest.raises(ValueError, match="扩展名与实际内容"):
        studio.attach_reference_image(
            project_id,
            "not-really-a-photo.jpg",
            b"\x89PNG\r\n\x1a\ninvalid-but-detected",
        )
