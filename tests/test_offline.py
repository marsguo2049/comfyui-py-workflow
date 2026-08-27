from __future__ import annotations

from comfyui_py_workflow.offline import check_lm_studio, is_loopback_url


def test_only_loopback_service_urls_are_offline_safe() -> None:
    assert is_loopback_url("http://127.0.0.1:8188")
    assert is_loopback_url("http://localhost:1234/v1")
    assert not is_loopback_url("https://example.com/v1")


def test_remote_lm_studio_is_blocked_before_network_access() -> None:
    result = check_lm_studio("https://example.com/v1")
    assert not result["ok"]
    assert result["state"] == "blocked"
