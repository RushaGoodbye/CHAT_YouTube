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
    assert seen["body"]["think"] is False
    assert seen["body"]["keep_alive"] == "20m"


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



def test_ukrainian_description_repairs_first_russian_language_result_once(monkeypatch):
    calls = []
    ru = "Участники обсуждают события в России и говорят о ситуации. " * 10
    ua = (
        "У відео співрозмовники обговорюють суспільні питання, "
        "відповідальність за війну, а також розповідають про "
        "причини відсутності змін у суспільстві. " * 5
    )
    def fake_open(req, timeout):
        calls.append(json.loads(req.data.decode("utf-8")))
        text = ru if len(calls) == 1 else ua
        return FakeReply({"message": {"content": json.dumps(
            {"description": text}, ensure_ascii=False)}})
    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_open)
    result = adapter.ollama_description_json(
        current_title="27 лет без изменений", selected_title="Против войны",
        transcript="Россиияне обсуждают войну и гражданскую ответственность. " * 80,
        timeout=120,
    )
    assert len(calls) == 2
    assert result["description"] == ua
    assert all(c["model"] == "qwen3:8b" for c in calls)
    assert "ПОВНІСТЮ УКРАЇНСЬКОЮ" in calls[1]["messages"][1]["content"]


def test_ukrainian_repair_never_accepts_two_russian_responses(monkeypatch):
    calls = []
    ru = "Обсуждение ситуации и вопросов власти, которые происходят в России. " * 12
    def fake_open(req, timeout):
        calls.append(timeout)
        return FakeReply({"message": {"content": json.dumps(
            {"description": ru}, ensure_ascii=False)}})
    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_open)
    with pytest.raises(ValueError, match="Description must be Ukrainian"):
        adapter.ollama_description_json(
            current_title="Разговор", transcript="Исходная расшифровка." * 160,
            timeout=100,
        )
    assert len(calls) == 2



def test_every_ollama_qa_call_disables_qwen3_reasoning():
    # The 8B local model may spend >100 seconds generating hidden thinking
    # rather than the tiny JSON response required by SEO.
    from pathlib import Path
    source = Path("src/rg_youtube_control/seo_engine_ollama.py").read_text(
        encoding="utf-8"
    )
    assert source.count('"think": False') == 5
    assert source.count('"keep_alive": "20m"') == 5
