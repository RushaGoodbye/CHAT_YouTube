from __future__ import annotations

import io
import urllib.error

import pytest

from rg_youtube_control.free_tools import ollama_chat


def test_ollama_http_500_is_safe_and_preserves_http_cause(monkeypatch):
    def failing_request(_request, timeout=None):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/chat",
            500, "Internal Server Error", hdrs=None, fp=io.BytesIO(b"secret"),
        )

    monkeypatch.setattr("urllib.request.urlopen", failing_request)
    with pytest.raises(RuntimeError, match=r"HTTP 500") as caught:
        ollama_chat(
            [{"role": "user", "content": "Private test subtitle"}],
            timeout=2, json_mode=True,
        )
    assert isinstance(caught.value.__cause__, urllib.error.HTTPError)
    assert "Private test subtitle" not in str(caught.value)
    assert "secret" not in str(caught.value)
