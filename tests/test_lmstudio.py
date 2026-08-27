from __future__ import annotations

import json

import pytest

from comfyui_py_workflow.lmstudio import LMStudioClient, LMStudioError


def test_rejects_remote_server_by_default() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LMStudioClient("https://example.com/v1")


def test_structured_chat_parses_content(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LMStudioClient()
    captured = {}

    def fake_request(path, *, method="GET", payload=None):
        captured.update(path=path, method=method, payload=payload)
        return {"choices": [{"message": {"content": json.dumps({"answer": 3})}}]}

    monkeypatch.setattr(client, "_request_json", fake_request)
    result = client.structured_chat(
        model="local/model",
        messages=[{"role": "user", "content": "answer"}],
        schema_name="answer",
        schema={"type": "object"},
    )
    assert result == {"answer": 3}
    assert captured["path"] == "/chat/completions"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["payload"]["reasoning_effort"] == "none"


def test_structured_chat_reports_reasoning_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LMStudioClient()

    def fake_request(path, *, method="GET", payload=None):
        return {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "", "reasoning_content": "still thinking"},
            }],
            "usage": {
                "completion_tokens": 256,
                "completion_tokens_details": {"reasoning_tokens": 256},
            },
        }

    monkeypatch.setattr(client, "_request_json", fake_request)
    with pytest.raises(LMStudioError, match="reasoning_tokens=256"):
        client.structured_chat(
            model="local/model",
            messages=[{"role": "user", "content": "answer"}],
            schema_name="answer",
            schema={"type": "object"},
        )


def test_structured_chat_reports_invalid_json_with_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LMStudioClient()

    def fake_request(path, *, method="GET", payload=None):
        return {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": '{"answer":'},
            }]
        }

    monkeypatch.setattr(client, "_request_json", fake_request)
    with pytest.raises(LMStudioError, match="finish_reason=length"):
        client.structured_chat(
            model="local/model",
            messages=[{"role": "user", "content": "answer"}],
            schema_name="answer",
            schema={"type": "object"},
        )


def test_resolve_model_requires_choice_when_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LMStudioClient()
    monkeypatch.setattr(client, "list_models", lambda: ["a", "b"])
    with pytest.raises(LMStudioError, match="--model"):
        client.resolve_model(None)


def test_unloads_matching_native_model_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LMStudioClient()
    calls = []

    def fake_request(path, *, method="GET", payload=None, base_url=None):
        calls.append((path, method, payload, base_url))
        if path == "/models":
            return {
                "models": [{
                    "key": "local/model",
                    "loaded_instances": [{"id": "local/model-instance"}],
                }]
            }
        return {"instance_id": payload["instance_id"]}

    monkeypatch.setattr(client, "_request_json", fake_request)
    assert client.unload_model("local/model") == ["local/model-instance"]
    assert calls[-1][0:3] == (
        "/models/unload",
        "POST",
        {"instance_id": "local/model-instance"},
    )
