"""Offline contract tests for Ollama transport; no network or YouTube writes."""
import json
import urllib.error

import pytest

from rg_youtube_control import seo_engine_ollama as adapter


class FakeReply:
    def __init__(self, data):
        self._data = data
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self._data).encode("utf-8")


def test_ollama_model_request_uses_valid_schema_and_offline_endpoint(monkeypatch):
    seen = {}
    def fake_open(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeReply({"message": {"content": '{"title":"ok"}'}})
    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_open)
    assert adapter.ollama_json("prompt", timeout=3) == '{"title":"ok"}'
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["timeout"] == 3
    assert seen["body"]["stream"] is False
    assert seen["body"]["format"]["properties"]["tags"]["minItems"] == 8
    assert seen["body"]["model"] == "qwen3:8b"


def test_ollama_connection_failure_is_not_silenced(monkeypatch):
    def failing(req, timeout):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(adapter.urllib.request, "urlopen", failing)
    with pytest.raises(urllib.error.URLError):
        adapter.ollama_json("prompt", timeout=1)


def test_ollama_invalid_payload_is_not_treated_as_success(monkeypatch):
    monkeypatch.setattr(adapter.urllib.request, "urlopen",
                        lambda req, timeout: FakeReply({"error": "model missing"}))
    with pytest.raises((KeyError, ValueError)):
        adapter.ollama_json("prompt")



def test_transient_ollama_disconnect_recovers_once(monkeypatch):
    attempts = []
    def sometimes(req, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise urllib.error.URLError("local server temporarily unavailable")
        return FakeReply({"message": {"content": '{"title":"ok"}'}})
    monkeypatch.setattr(adapter.urllib.request, "urlopen", sometimes)
    assert adapter.ollama_json("prompt", timeout=120) == '{"title":"ok"}'
    assert attempts == [120, 75.0]


def test_non_retryable_http_400_does_not_loop(monkeypatch):
    attempts = []
    def error(req, timeout):
        attempts.append(timeout)
        raise urllib.error.HTTPError(req.full_url, 400, "bad format", {}, None)
    monkeypatch.setattr(adapter.urllib.request, "urlopen", error)
    with pytest.raises(urllib.error.HTTPError):
        adapter.ollama_json("prompt", timeout=120)
    assert len(attempts) == 1
