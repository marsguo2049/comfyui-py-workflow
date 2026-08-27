from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class LMStudioError(RuntimeError):
    """Raised when LM Studio cannot provide a valid local model response."""


class LMStudioClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        *,
        api_token: str | None = None,
        timeout_seconds: float = 300.0,
        allow_remote: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        parsed_url = urlparse(self.base_url)
        self.native_base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/api/v1"
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds
        hostname = (parsed_url.hostname or "").lower()
        if not allow_remote and hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "LM Studio must use a loopback address unless allow_remote=True is explicitly set"
            )

    def list_models(self) -> list[str]:
        result = self._request_json("/models")
        data = result.get("data")
        if not isinstance(data, list):
            raise LMStudioError("LM Studio returned a malformed model list")
        return [str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")]

    def resolve_model(self, requested: str | None) -> str:
        if requested:
            return requested
        models = self.list_models()
        if len(models) == 1:
            return models[0]
        if not models:
            raise LMStudioError("LM Studio reports no available models")
        raise LMStudioError(
            "Multiple LM Studio models are available; select one with --model. "
            f"Choices: {', '.join(models)}"
        )

    def unload_model(self, model: str) -> list[str]:
        result = self._request_json("/models", base_url=self.native_base_url)
        models = result.get("models")
        if not isinstance(models, list):
            raise LMStudioError("LM Studio returned a malformed native model list")
        instance_ids: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            instances = item.get("loaded_instances", [])
            if not isinstance(instances, list):
                continue
            identifiers = {str(item.get("key", "")), str(item.get("selected_variant", ""))}
            loaded_ids = {
                str(instance.get("id"))
                for instance in instances
                if isinstance(instance, dict) and instance.get("id")
            }
            if model in identifiers or model in loaded_ids:
                instance_ids.extend(sorted(loaded_ids))
        if not instance_ids:
            raise LMStudioError(
                f"Could not identify a loaded LM Studio instance for {model!r}; "
                "unload it manually before starting ComfyUI"
            )
        for instance_id in instance_ids:
            self._request_json(
                "/models/unload",
                method="POST",
                payload={"instance_id": instance_id},
                base_url=self.native_base_url,
            )
        return instance_ids

    def structured_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        temperature: float = 0.3,
        max_tokens: int = 8192,
        disable_reasoning: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # Reasoning-capable models can spend the entire output budget in
        # reasoning_content and leave message.content empty. Structured tasks
        # need the JSON itself, so use LM Studio's OpenAI-compatible switch to
        # reserve the budget for the schema-constrained answer.
        if disable_reasoning:
            payload["reasoning_effort"] = "none"
        result = self._request_json("/chat/completions", method="POST", payload=payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LMStudioError("LM Studio returned a malformed chat completion")
        choice = choices[0]
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        finish_reason = str(choice.get("finish_reason") or "unknown")
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        details = (
            usage.get("completion_tokens_details")
            if isinstance(usage.get("completion_tokens_details"), dict)
            else {}
        )
        reasoning_tokens = details.get("reasoning_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if not isinstance(content, str) or not content.strip():
            if finish_reason == "length":
                raise LMStudioError(
                    "LM Studio exhausted the output/context limit before returning JSON "
                    f"(finish_reason=length, completion_tokens={completion_tokens}, "
                    f"reasoning_tokens={reasoning_tokens}). Disable model reasoning or "
                    "reload the model with a larger context length."
                )
            raise LMStudioError(
                "LM Studio returned an empty structured response "
                f"(finish_reason={finish_reason}, reasoning_tokens={reasoning_tokens})"
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            preview = " ".join(content[:160].splitlines())
            raise LMStudioError(
                "LM Studio returned incomplete or invalid structured JSON "
                f"(finish_reason={finish_reason}, preview={preview!r})"
            ) from exc
        if not isinstance(parsed, dict):
            raise LMStudioError("LM Studio structured response must be a JSON object")
        return parsed

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{base_url or self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LMStudioError(
                f"LM Studio request failed ({exc.code} {exc.reason}): {body}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise LMStudioError(f"LM Studio request failed: {exc}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LMStudioError("LM Studio returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise LMStudioError("LM Studio returned an unexpected response")
        return result
