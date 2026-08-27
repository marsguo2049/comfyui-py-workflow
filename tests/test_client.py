import pytest

from comfyui_py_workflow import ComfyUIClient


def test_substitution_does_not_mutate_template() -> None:
    template = {"1": {"inputs": {"text": "old"}, "class_type": "CLIPTextEncode"}}
    result = ComfyUIClient.apply_substitutions(template, {("1", "text"): "new"})
    assert result["1"]["inputs"]["text"] == "new"
    assert template["1"]["inputs"]["text"] == "old"


def test_substitution_rejects_missing_input() -> None:
    with pytest.raises(KeyError):
        ComfyUIClient.apply_substitutions({}, {("1", "text"): "new"})


def test_extracts_output_assets() -> None:
    history = {
        "outputs": {
            "9": {
                "images": [
                    {"filename": "frame.png", "subfolder": "cpw", "type": "output"}
                ]
            }
        }
    }
    assets = ComfyUIClient.output_assets(history, node_id="9")
    assert len(assets) == 1
    assert assets[0].filename == "frame.png"
    assert assets[0].subfolder == "cpw"


def test_builds_uploaded_input_reference() -> None:
    assert ComfyUIClient.input_reference({"name": "frame.png", "subfolder": "cpw"}) == "cpw/frame.png"


def test_rejects_remote_comfyui_address_by_default() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ComfyUIClient("https://example.com")


def test_accepts_loopback_comfyui_address() -> None:
    client = ComfyUIClient("http://127.0.0.1:8188")
    assert client.base_url == "http://127.0.0.1:8188"
