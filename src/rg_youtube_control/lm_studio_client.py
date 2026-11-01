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
    return f"http://{host}:{parsed.port or 1234}/v1/{endpoint}"


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


def list_models(
    *,
    base_url: str | None = None,
    timeout: float = 4.0,
) -> list[str]:
    result = _local_json(
        "models",
        base_url=base_url or os.getenv("RG_LMSTUDIO_URL", DEFAULT_BASE_URL),
        timeout=timeout,
        token=os.getenv("RG_LMSTUDIO_TOKEN", ""),
    )
    data = result.get("data")
    if not isinstance(data, list):
        raise RuntimeError("LM Studio model list is malformed")
    return [
        str(item["id"])
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
        and item["id"].strip()
    ]


def probe_lm_studio(*, base_url: str | None = None) -> dict[str, Any]:
    try:
        models = list_models(base_url=base_url)
        preferred = os.getenv("RG_LMSTUDIO_MODEL", "").strip()
        return {
            "available": True,
            "model_count": len(models),
            "model_selected": bool(
                preferred in models or (not preferred and len(models) == 1)
            ),
            "selected_model": preferred if preferred in models else (
                models[0] if not preferred and len(models) == 1 else ""
            ),
            "status": "READY" if (
                preferred in models or (not preferred and len(models) == 1)
            ) else "SELECT_OR_LOAD_MODEL",
        }
    except (RuntimeError, ValueError) as exc:
        return {
            "available": False, "model_count": 0,
            "model_selected": False, "selected_model": "",
            "status": "LOCAL_SERVER_UNAVAILABLE",
            "error_type": type(exc).__name__,
        }


def lm_studio_chat(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    base_url: str | None = None,
    timeout: float = 180.0,
    temperature: float = 0.15,
    json_mode: bool = False,
    max_tokens: int = 2500,
) -> str:
    endpoint = base_url or os.getenv("RG_LMSTUDIO_URL", DEFAULT_BASE_URL)
    configured = (model or os.getenv("RG_LMSTUDIO_MODEL", "")).strip()
    if not configured:
        models = list_models(base_url=endpoint, timeout=5.0)
        if len(models) != 1:
            raise RuntimeError(
                "LM Studio: load exactly one model or configure RG_LMSTUDIO_MODEL"
            )
        configured = models[0]
    data: dict[str, Any] = {
        "model": configured,
        "messages": messages,
        "temperature": float(temperature),
        "stream": False,
        "max_tokens": max(128, min(int(max_tokens), 8192)),
    }
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
        raise RuntimeError("LM Studio returned empty assistant content")
    return answer
