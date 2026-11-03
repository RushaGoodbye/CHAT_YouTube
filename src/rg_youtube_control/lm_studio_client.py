"""Local-only LM Studio OpenAI-compatible inference for RG YouTube Control.

No external API, no OpenAI SDK, no Ollama dependency. Original SRT remains on
localhost. The API client rejects non-loopback endpoints and proxy routing.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:1234"
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _local_api_url(base_url: str, endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
    if (parsed.scheme != "http"
            or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/", "/v1")):
        raise ValueError(
            "LM Studio API must use a loopback HTTP address, "
            "for example http://127.0.0.1:1234"
        )
    if not 1 <= (parsed.port or 1234) <= 65535:
        raise ValueError("Invalid LM Studio port")
    # Normalise host so Windows proxy/DNS rules cannot redirect an API call.
    if parsed.hostname == "::1":
        host = "[::1]"
    else:
        host = "127.0.0.1"
    # Native v1 model listing includes model type, so we can reject
    # embeddings before attempting chat completions.
    prefix = "" if endpoint.startswith("api/v1/") else "v1/"
    return f"http://{host}:{parsed.port or 1234}/{prefix}{endpoint}"


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never follow a redirect which might carry private SRT to a remote URL.
        raise RuntimeError("LM Studio API redirect rejected")


def _local_json(
    endpoint: str,
    *,
    base_url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
    token: str = "",
) -> dict[str, Any]:
    url = _local_api_url(base_url, endpoint)
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        url, headers=headers, data=body,
        method="POST" if body is not None else "GET",
    )
    # Never forward private SRT via HTTP_PROXY/HTTPS_PROXY environment values.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirect(),
    )
    try:
        with opener.open(req, timeout=max(1.0, float(timeout))) as reply:
            parsed = json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"LM Studio returned HTTP {exc.code}; check model/server state"
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise RuntimeError("LM Studio local server is unavailable") from exc
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("LM Studio returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("LM Studio returned an unexpected response")
    return parsed


def _native_llm_models(*, base_url: str | None = None, timeout: float = 4.0) -> list[dict[str, Any]]:
    result = _local_json(
        "api/v1/models",
        base_url=base_url or os.getenv("RG_LMSTUDIO_URL", DEFAULT_BASE_URL),
        timeout=timeout,
        token=os.getenv("RG_LMSTUDIO_TOKEN", ""),
    )
    data = result.get("models")
    if not isinstance(data, list):
        raise RuntimeError("LM Studio native model list is malformed")
    return [
        item for item in data
        if isinstance(item, dict) and item.get("type") == "llm"
        and isinstance(item.get("key"), str) and item["key"].strip()
    ]


def list_models(*, base_url: str | None = None, timeout: float = 4.0) -> list[str]:
    return [str(item["key"]) for item in _native_llm_models(base_url=base_url, timeout=timeout)]


def _choose_model(models: list[dict[str, Any]], preferred: str = "") -> str:
    ids = [str(m["key"]) for m in models]
    if preferred:
        return preferred if preferred in ids else ""
    loaded = [str(m["key"]) for m in models if m.get("loaded_instances")]
    if len(loaded) == 1:
        return loaded[0]
    if len(models) == 1:
        return ids[0]
    return ""


def probe_lm_studio(*, base_url: str | None = None) -> dict[str, Any]:
    try:
        models = _native_llm_models(base_url=base_url)
        preferred = os.getenv("RG_LMSTUDIO_MODEL", "").strip()
        selected = _choose_model(models, preferred)
        return {
            "available": True,
            "model_count": len(models),
            "model_selected": bool(selected),
            "selected_model": selected,
            "status": "READY" if selected else "SELECT_OR_LOAD_MODEL",
        }
    except (RuntimeError, ValueError) as exc:
        return {
            "available": False, "model_count": 0,
            "model_selected": False, "selected_model": "",
            "status": "LOCAL_SERVER_UNAVAILABLE",
            "error_type": type(exc).__name__,
        }


def ensure_local_server() -> dict[str, Any]:
    """Start a stopped local LM Studio server without opening a console window."""
    import subprocess
    from pathlib import Path

    status = probe_lm_studio()
    if status.get("available"):
        return status
    if os.name != "nt":
        return status
    executable = Path.home() / ".lmstudio" / "bin" / "lms.exe"
    if not executable.is_file():
        return status
    try:
        subprocess.run(
            [str(executable), "server", "start"],
            timeout=25, check=False, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return status
    return probe_lm_studio()


def lm_studio_chat(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    base_url: str | None = None,
    timeout: float = 180.0,
    temperature: float = 0.15,
    json_mode: bool = False,
    max_tokens: int = 2500,
    reasoning_effort: str | None = None,
) -> str:
    endpoint = base_url or os.getenv("RG_LMSTUDIO_URL", DEFAULT_BASE_URL)
    configured = (model or os.getenv("RG_LMSTUDIO_MODEL", "")).strip()
    if not configured:
        models = _native_llm_models(base_url=endpoint, timeout=5.0)
        configured = _choose_model(models)
        if not configured:
            raise RuntimeError(
                "LM Studio: load one language model or configure RG_LMSTUDIO_MODEL"
            )
    data: dict[str, Any] = {
        "model": configured,
        "messages": messages,
        "temperature": float(temperature),
        "stream": False,
        "max_tokens": max(128, min(int(max_tokens), 8192)),
    }
    # Gemma 4 reasoning mode can consume the ENTIRE output-token budget,
    # leaving message.content empty. Disable thinking by default for concise
    # SEO JSON; an explicit 'auto' setting omits this field for other models.
    effort = (
        reasoning_effort
        if reasoning_effort is not None
        else os.getenv("RG_LMSTUDIO_REASONING_EFFORT", "none")
    ).strip().lower()
    if effort not in ("none", "auto", "low", "medium", "high"):
        raise ValueError("Unsupported local reasoning setting")
    if effort != "auto":
        data["reasoning_effort"] = effort
    if json_mode:
        # Official OpenAI-compatible structured output format for LM Studio.
        # A generic object schema supports both SEO and comment JSON payloads.
        data["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "rg_local_json",
                "strict": False,
                "schema": {"type": "object", "additionalProperties": True},
            },
        }
    result = _local_json(
        "chat/completions", base_url=endpoint, payload=data,
        timeout=timeout, token=os.getenv("RG_LMSTUDIO_TOKEN", ""),
    )
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LM Studio returned no completion choices")
    message = choices[0].get("message") if isinstance(choices[0],dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("LM Studio returned no assistant message")
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(
            str(x.get("text") or "") for x in content if isinstance(x, dict)
        )
    answer = str(content or "").strip()
    if not answer:
        completion = (result.get("usage") or {}).get("completion_tokens_details") or {}
        if (
            choices[0].get("finish_reason") == "length"
            and int(completion.get("reasoning_tokens") or 0) >= data["max_tokens"] - 4
        ):
            raise RuntimeError(
                "LM Studio consumed output budget on reasoning; "
                "set RG_LMSTUDIO_REASONING_EFFORT=none"
            )
        raise RuntimeError("LM Studio returned empty assistant content")
    return answer
