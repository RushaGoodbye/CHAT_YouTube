import json
import urllib.error
from types import SimpleNamespace

import pytest

from rg_youtube_control import free_tools
from rg_youtube_control import lm_studio_backend as backend


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_uses_only_local_openai_compatible_endpoint(monkeypatch):
    calls = []
    def handle(req, timeout):
        calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))
        return FakeResponse({"choices": [{"message": {"content": '{"title":"Тест"}'}}]})
    monkeypatch.setattr(backend.urllib.request, "urlopen", handle)
    monkeypatch.setattr(backend, "ensure_model_loaded", lambda **kwargs: "qwen3-14b")
    result = backend.lm_studio_chat(
        [{"role": "user", "content": "Напиши SEO"}], json_mode=True,
        num_ctx=16384,
    )
    assert result == '{"title":"Тест"}'
    assert calls[0][0] == "http://127.0.0.1:1234/v1/chat/completions"
    assert calls[0][1]["model"] == "qwen3-14b"
    assert calls[0][1]["reasoning_effort"] == "none"
    assert calls[0][1]["response_format"]["type"] == "json_schema"
    assert len(calls) == 1


def test_single_retry_on_empty_response_without_hidden_content(monkeypatch):
    calls = []
    def handle(req, timeout):
        calls.append(json.loads(req.data.decode("utf-8")))
        content = "" if len(calls) == 1 else '{"ok":true}'
        return FakeResponse({"choices": [{"message": {
            "content": content, "reasoning_content": "ignore this reasoning",
        }}]})
    monkeypatch.setattr(backend.urllib.request, "urlopen", handle)
    monkeypatch.setattr(backend, "ensure_model_loaded", lambda **kwargs: "qwen3-14b")
    response = backend.lm_studio_chat(
        [{"role": "user", "content": "Check"}], json_mode=True,
    )
    assert response == '{"ok":true}'
    assert len(calls) == 2
    assert len(calls[1]["messages"]) == 2


def test_double_empty_reply_fails_closed(monkeypatch):
    calls = []
    def handle(req, timeout):
        calls.append(1)
        return FakeResponse({"choices": [{"message": {"content": ""}}]})
    monkeypatch.setattr(backend.urllib.request, "urlopen", handle)
    monkeypatch.setattr(backend, "ensure_model_loaded", lambda **kwargs: "qwen3-14b")
    with pytest.raises(RuntimeError, match="двічі"):
        backend.lm_studio_chat([{"role": "user", "content": "Check"}])
    assert len(calls) == 2


def test_local_transport_failure_never_falls_back_to_cloud(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(backend.urllib.request, "urlopen", fail)
    monkeypatch.setattr(backend, "ensure_model_loaded", lambda **kwargs: "qwen3-14b")
    with pytest.raises(RuntimeError, match="LM Studio недоступна"):
        backend.lm_studio_chat([{"role": "user", "content": "Check"}])


def test_existing_seo_call_sites_use_lm_studio_without_ollama(monkeypatch):
    calls = []
    def fake(messages, **kwargs):
        calls.append(kwargs)
        return '{"ok":true}'
    monkeypatch.setattr(free_tools, "lm_studio_chat", fake)
    assert free_tools.ollama_chat([{"role": "user", "content": "Check"}],json_mode=True) == '{"ok":true}'
    assert calls[0]["model"] == "qwen3-14b"
    assert calls[0]["json_mode"] is True


def test_probe_reports_lm_studio_server_and_model(monkeypatch):
    monkeypatch.setattr(free_tools, "list_lm_studio_models",
                        lambda **kwargs: ["qwen3-14b"])
    status = free_tools.probe_free_tools()
    assert status["lm_studio"]["available"]
    assert status["lm_studio_model"]["available"]
    assert status["ollama"]["name"] == "LM Studio"


def test_ensure_model_loads_downloaded_qwen_on_demand(monkeypatch):
    calls = []
    def handle(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse({"models": [{"key": "qwen3-14b", "loaded_instances": []}]})
        assert request.full_url.endswith("/api/v1/models/load")
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "qwen3-14b"
        assert body["context_length"] == 16384
        return FakeResponse({"status": "loaded", "instance_id": "qwen3-14b"})
    monkeypatch.setattr(backend.urllib.request, "urlopen", handle)
    result = backend.ensure_model_loaded(num_ctx=16384)
    assert result == "qwen3-14b"
    assert len(calls) == 2


def test_ensure_model_reuses_existing_alias_no_duplicate_load(monkeypatch):
    calls = []
    def handle(request, timeout):
        calls.append(request.full_url)
        return FakeResponse({"models": [
            {"key": "qwen3-14b", "loaded_instances": [{"id": "rg-qwen3-14b"}]}
        ]})
    monkeypatch.setattr(backend.urllib.request, "urlopen", handle)
    assert backend.ensure_model_loaded() == "rg-qwen3-14b"
    assert len(calls) == 1


def test_ensure_model_never_downloads_missing_model(monkeypatch):
    calls = []
    def handle(request, timeout):
        calls.append(request.full_url)
        return FakeResponse({"models": []})
    monkeypatch.setattr(backend.urllib.request, "urlopen", handle)
    with pytest.raises(RuntimeError, match="не встановлена"):
        backend.ensure_model_loaded()
    assert len(calls) == 1


def test_fast_seo_draft_is_never_marked_editorially_approved(monkeypatch):
    from rg_youtube_control import free_tools
    import json
    response = {
        "title": "Звільнення Шойгу: питання та позиції учасників",
        "title_variants": [
            "Що говорять про звільнення Шойгу?",
            "Розмова про кадрові рішення в Росії",
            "Як співрозмовники пояснюють зміни в уряді?",
        ],
        "description": "У чат-рулетці учасники обговорюють кадрові зміни, рішення щодо Шойгу та позиції співрозмовників. Вони висловлюють різні оцінки політичних подій, а ведучий ставить уточнювальні запитання. Твердження учасників потребують незалежної перевірки перед публікацією.",
        "tags": ["Шойгу", "чат рулетка", "Раша Гудбай", "кадрові рішення",
                 "Росія", "політика РФ", "розмова", "російська влада"],
        "chapters": "",
    }
    monkeypatch.setattr(free_tools, "ollama_chat",
                        lambda *args, **kwargs: json.dumps(response, ensure_ascii=False))
    result = free_tools.generate_seo_package_local(
        current_title="Увольнение Шойгу: що відомо?",
        transcript="Учасники обговорюють звільнення Шойгу і російську владу.",
        fast_mode=True,
    )
    assert result["needs_review"] is True
    assert result["provider"].startswith("lmstudio:")