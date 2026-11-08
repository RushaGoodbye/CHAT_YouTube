"""Local LM Studio backend for offline, review-only text generation.

Uses the OpenAI-compatible loopback API. It never calls a cloud model,
executes a background job, or updates YouTube.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import urllib.error
import urllib.request
from typing import Any

DEFAULT_LM_STUDIO_MODEL = "qwen3-14b"
DEFAULT_LM_STUDIO_URL = "http://127.0.0.1:1234"

# This context belongs only to the synchronous SEO operation that created it.
# Pre-existing or manually loaded models are never added to the owned list.
_OWNED_SEO_INSTANCES: ContextVar[dict[str, set[str]] | None] = ContextVar(
    "rg_owned_lmstudio_instances", default=None
)


@contextmanager
def seo_model_lifecycle():
    """Release SEO-owned models at the end of a job, even on exceptions.

    Never stop the LM Studio server; never release a model loaded by someone
    else. Nested calls share the same owner and only outermost closes it.
    """
    active = _OWNED_SEO_INSTANCES.get()
    if active is not None:
        yield
        return
    owned: dict[str, set[str]] = {}
    token = _OWNED_SEO_INSTANCES.set(owned)
    try:
        yield
    finally:
        _OWNED_SEO_INSTANCES.reset(token)
        for url, ids in owned.items():
            for instance_id in sorted(ids):
                try:
                    request = urllib.request.Request(
                        url.rstrip("/") + "/api/v1/models/unload",
                        data=json.dumps({"instance_id": instance_id}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=20):
                        pass
                except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                    # Cleanup failure must never mask the actual SEO error.
                    pass




def auto_release_seo_models(func):
    """Wrap a synchronous SEO job, not every individual LM Studio request."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        with seo_model_lifecycle():
            return func(*args, **kwargs)
    return wrapped


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


def ensure_model_loaded(
    *, model: str = DEFAULT_LM_STUDIO_MODEL,
    url: str = DEFAULT_LM_STUDIO_URL,
    timeout: float = 30.0,
    num_ctx: int | None = None,
) -> str:
    """Load an already-downloaded model only when SEO is requested.

    Return the real instance ID; respect models already loaded under an alias.
    Never download models, unload other models, or run in the background.
    """
    request = urllib.request.Request(
        url.rstrip("/") + "/api/v1/models", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=min(timeout, 10.0)) as response:
            inventory = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Не вдалося отримати список моделей LM Studio.") from exc
    matches = [item for item in inventory.get("models", [])
               if isinstance(item, dict) and item.get("key") == model]
    if not matches:
        raise RuntimeError(f"Модель {model} не встановлена у LM Studio.")
    instances = matches[0].get("loaded_instances") or []
    for instance in instances:
        if isinstance(instance, dict) and instance.get("id"):
            return str(instance["id"])
    context_length = max(8192, min(int(num_ctx or 8192), 16384))
    payload = {
        "model": model, "context_length": context_length,
        "flash_attention": True,
    }
    load_request = urllib.request.Request(
        url.rstrip("/") + "/api/v1/models/load",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(load_request, timeout=max(30.0, timeout)) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"LM Studio не змогла завантажити локальну модель {model}: "
            f"{str(exc)[:160]}"
        ) from exc
    if result.get("status") != "loaded":
        raise RuntimeError(f"LM Studio не підтвердила завантаження {model}.")
    confirmed_id = result.get("instance_id") or result.get("model_instance_id")
    # Do not register an inferred model name as a disposable instance ID.
    # Only unload instances whose unique ID the load endpoint explicitly gave.
    owned = _OWNED_SEO_INSTANCES.get()
    if owned is not None and isinstance(confirmed_id, str) and confirmed_id:
        owned.setdefault(url.rstrip("/"), set()).add(confirmed_id)
    return str(confirmed_id or model)


def lm_studio_chat(
    messages: list[dict[str, str]], *, model: str = DEFAULT_LM_STUDIO_MODEL,
    url: str = DEFAULT_LM_STUDIO_URL, timeout: float = 300.0,
    temperature: float = 0.2, json_mode: bool = False,
    num_ctx: int | None = None,
    max_tokens: int | None = None,
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
    if max_tokens is not None and (
            type(max_tokens) is not int or not 100 <= max_tokens <= 4096):
        raise ValueError("INVALID_LOCAL_RESPONSE_TOKEN_LIMIT")
    loaded_id = ensure_model_loaded(
        model=model, url=url, timeout=timeout, num_ctx=num_ctx,
    )
    current = list(messages)
    for attempt in range(2):
        payload: dict[str, Any] = {
            "model": loaded_id, "messages": current, "stream": False,
            "temperature": temperature, "reasoning_effort": "none",
            "max_tokens": max_tokens if max_tokens is not None else (
                1700 if json_mode else 1250),
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