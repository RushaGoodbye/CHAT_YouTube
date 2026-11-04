"""Local LM Studio backend for offline, review-only text generation.

Uses the OpenAI-compatible loopback API. It never calls a cloud model,
executes a background job, or updates YouTube.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_LM_STUDIO_MODEL = "rg-qwen3-14b"
DEFAULT_LM_STUDIO_URL = "http://127.0.0.1:1234"


def list_models(*, url: str = DEFAULT_LM_STUDIO_URL, timeout: float = 2.0) -> list[str]:
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/models", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return [
        str(item.get("id"))
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]


def lm_studio_chat(
    messages: list[dict[str, str]], *, model: str = DEFAULT_LM_STUDIO_MODEL,
    url: str = DEFAULT_LM_STUDIO_URL, timeout: float = 300.0,
    temperature: float = 0.2, json_mode: bool = False,
    num_ctx: int | None = None,
) -> str:
    """One request, with at most one retry for an empty model message."""
    if not messages or any(
        not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant"}
        for m in messages
    ):
        raise ValueError("INVALID_LOCAL_LLM_MESSAGES")
    # The OpenAI-compatible endpoint cannot alter context length per request.
    # Set it when loading the model, never silently clip source text here.
    if num_ctx is not None and (not isinstance(num_ctx, int) or num_ctx < 1024):
        raise ValueError("INVALID_LM_STUDIO_CONTEXT")
    current = list(messages)
    for attempt in range(2):
        payload: dict[str, Any] = {
            "model": model, "messages": current, "stream": False,
            "temperature": temperature, "reasoning_effort": "none",
            "max_tokens": 1700 if json_mode else 1250,
        }
        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "rg_local_json",
                    "strict": False,
                    "schema": {"type": "object", "additionalProperties": True},
                },
            }
        request = urllib.request.Request(
            url.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                "LM Studio недоступна. Запустіть локальний сервер і "
                f"завантажте модель {model}: {str(exc)[:160]}"
            ) from exc
        choices = result.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError("LM Studio не повернула результат моделі.")
        text = str((choices[0].get("message") or {}).get("content") or "").strip()
        if text:
            return text
        if attempt == 0:
            current = current + [{
                "role": "user",
                "content": "Попередня відповідь була порожня. Поверни відповідь лише у потрібному форматі.",
            }]
    raise RuntimeError("LM Studio двічі повернула порожню відповідь.")