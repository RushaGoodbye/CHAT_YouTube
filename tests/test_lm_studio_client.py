from __future__ import annotations

import json
import urllib.request

import pytest

from rg_youtube_control import lm_studio_client as lm
from rg_youtube_control import free_tools


def test_refuse_external_or_lan_urls_so_srt_stays_on_pc():
    for address in (
        "https://127.0.0.1:1234",
        "http://192.168.50.32:1234",
        "http://lmstudio.local:1234",
        "http://127.0.0.1:1234@evil.com",
        "http://127.0.0.1:1234/v1/../api",
        "http://127.0.0.1:1234?next=https://evil.com",
    ):
        with pytest.raises(ValueError):
            lm._local_api_url(address, "chat/completions")
    assert lm._local_api_url("http://localhost:1234", "models") == (
        "http://127.0.0.1:1234/v1/models"
    )


def test_local_inference_json_and_selected_model(monkeypatch):
    requests = []

    def fake_request(endpoint, **kwargs):
        requests.append((endpoint, kwargs))
        if endpoint == "api/v1/models":
            return {"models": [{"key": "gemma-3-12b-q4", "type": "llm"}]}
        return {"choices": [{"message": {"content": '{"title":"Тест","tags":[]}'}}]}

    monkeypatch.setattr(lm, "_local_json", fake_request)
    monkeypatch.delenv("RG_LMSTUDIO_MODEL", raising=False)
    text = lm.lm_studio_chat(
        [{"role":"user","content":"Приватні субтитри"}], json_mode=True
    )
    assert json.loads(text)["title"] == "Тест"
    sent = requests[-1][1]["payload"]
    assert sent["model"] == "gemma-3-12b-q4"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["reasoning_effort"] == "none"
    assert sent["messages"][0]["content"] == "Приватні субтитри"
    assert requests[-1][0] == "chat/completions"


def test_ambiguous_models_fail_closed(monkeypatch):
    monkeypatch.delenv("RG_LMSTUDIO_MODEL",raising=False)
    monkeypatch.setattr(lm,"_native_llm_models",lambda **_k:[{"key":"model-A"},{"key":"model-B"}])
    with pytest.raises(RuntimeError,match="load one language model"):
        lm.lm_studio_chat([{"role":"user","content":"test"}])


def test_default_production_dispatch_uses_lmstudio_not_ollama(monkeypatch):
    monkeypatch.delenv("RG_LOCAL_AI_PROVIDER", raising=False)
    called = []

    def fake_lm(messages, **kwargs):
        called.append((messages, kwargs))
        return '{"ok":true}'

    monkeypatch.setattr(lm, "lm_studio_chat", fake_lm)
    result = free_tools.ollama_chat(
        [{"role":"user","content":"Локальна українська розмова"}],
        json_mode=True,
    )
    assert json.loads(result)["ok"] is True
    assert called[0][1]["model"] == ""
    assert called[0][1]["json_mode"] is True


def test_probes_lmstudio_with_existing_ui_key_compatibility(monkeypatch):
    monkeypatch.delenv("RG_LOCAL_AI_PROVIDER", raising=False)
    monkeypatch.setattr(lm,"probe_lm_studio",lambda: {
        "available":True, "model_selected":True,
        "selected_model":"gemma-3-12b-q4"
    })
    probes = free_tools.probe_free_tools()
    assert probes["lmstudio"]["available"] is True
    assert probes["lmstudio_model"]["available"] is True
    assert probes["ollama"]["name"] == "LM Studio (local)"


def test_unreachable_server_safely_reports_local_failure(monkeypatch):
    def fail(endpoint, **_kwargs):
        raise RuntimeError("server down")
    monkeypatch.setattr(lm, "_local_json", fail)
    result = lm.probe_lm_studio()
    assert result["status"] == "LOCAL_SERVER_UNAVAILABLE"
    assert not result["model_selected"]

def test_native_model_listing_excludes_embedding_only(monkeypatch):
    monkeypatch.delenv("RG_LMSTUDIO_MODEL", raising=False)
    monkeypatch.setattr(lm, "_local_json", lambda endpoint, **_k: {
        "models": [
            {"key":"text-embedding-nomic-embed-text-v1.5", "type":"embedding"},
            {"key":"gemma-4-12b-q4", "type":"llm"},
        ]
    })
    assert lm.list_models() == ["gemma-4-12b-q4"]
    assert lm.probe_lm_studio()["status"] == "READY"


def test_embedding_only_is_not_a_ready_chat_model(monkeypatch):
    monkeypatch.delenv("RG_LMSTUDIO_MODEL", raising=False)
    monkeypatch.setattr(lm, "_local_json", lambda endpoint, **_k: {
        "models": [{"key":"text-embedding-nomic-embed-text-v1.5", "type":"embedding"}]
    })
    assert lm.list_models() == []
    report=lm.probe_lm_studio()
    assert report["available"] is True
    assert report["model_selected"] is False
    assert report["status"] == "SELECT_OR_LOAD_MODEL"


def test_native_models_api_url_is_still_local_only():
    assert lm._local_api_url("http://127.0.0.1:1234", "api/v1/models") == (
        "http://127.0.0.1:1234/api/v1/models"
    )

def test_reasoning_auto_omits_field_for_non_reasoning_models(monkeypatch):
    calls = []
    monkeypatch.setenv("RG_LMSTUDIO_REASONING_EFFORT", "auto")
    monkeypatch.setenv("RG_LMSTUDIO_MODEL", "local-test-model")
    def fake_request(endpoint, **kwargs):
        calls.append(kwargs)
        return {"choices":[{"message":{"content":"done"},"finish_reason":"stop"}]}
    monkeypatch.setattr(lm, "_local_json", fake_request)
    assert lm.lm_studio_chat([{"role":"user","content":"test"}]) == "done"
    assert "reasoning_effort" not in calls[-1]["payload"]


def test_reasoning_only_exhausted_response_fails_with_actionable_error(monkeypatch):
    monkeypatch.setenv("RG_LMSTUDIO_MODEL", "rg-gemma4-12b")
    monkeypatch.setattr(lm,"_local_json",lambda _endpoint, **_kwargs: {
        "choices":[{"finish_reason":"length","message":{"content":""}}],
        "usage":{"completion_tokens_details":{"reasoning_tokens":2297}},
    })
    with pytest.raises(RuntimeError,match="consumed output budget on reasoning"):
        lm.lm_studio_chat(
            [{"role":"user","content":"test"}], max_tokens=2300
        )


def test_select_only_loaded_llm_from_multiple_installed(monkeypatch):
    monkeypatch.delenv("RG_LMSTUDIO_MODEL", raising=False)
    monkeypatch.setattr(lm, "_native_llm_models", lambda **_k: [
        {"key":"google/gemma-4-12b","loaded_instances":[{"id":"rg-gemma4-12b"}]},
        {"key":"google/gemma-4-e4b","loaded_instances":[]},
    ])
    report = lm.probe_lm_studio()
    assert report["status"] == "READY"
    assert report["selected_model"] == "google/gemma-4-12b"
    assert lm._choose_model([
        {"key":"google/gemma-4-12b","loaded_instances":[{"id":"rg-gemma4-12b"}]},
        {"key":"google/gemma-4-e4b","loaded_instances":[]},
    ]) == "google/gemma-4-12b"


def test_lmstudio_seo_defaults_to_no_reasoning(monkeypatch):
    monkeypatch.delenv("RG_LMSTUDIO_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("RG_LMSTUDIO_MODEL", "rg-gemma4-12b")
    seen = []
    def request(_endpoint, **kwargs):
        seen.append(kwargs["payload"])
        return {"choices":[{"finish_reason":"stop","message":{"content":'{"title":"Страх доносів"}'}}],
                "usage":{"completion_tokens_details":{"reasoning_tokens":0}}}
    monkeypatch.setattr(lm, "_local_json", request)
    answer = lm.lm_studio_chat([{"role":"user","content":"Generate SEO"}], json_mode=True)
    assert answer.startswith('{"title"')
    assert seen[0]["reasoning_effort"] == "none"
    assert seen[0]["response_format"]["type"] == "json_schema"


def test_ensure_local_server_leaves_working_server_untouched(monkeypatch):
    monkeypatch.setattr(lm, "probe_lm_studio", lambda: {
        "available": True, "model_selected": True, "status": "READY"
    })
    assert lm.ensure_local_server()["status"] == "READY"


def test_ensure_local_server_starts_windows_server_when_missing(monkeypatch, tmp_path):
    import pathlib
    import subprocess

    if lm.os.name != "nt":
        pytest.skip("Windows-only LM Studio CLI startup")
    binary = tmp_path / ".lmstudio" / "bin" / "lms.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"placeholder")
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    states = iter([
        {"available": False, "model_selected": False},
        {"available": True, "model_selected": True, "status": "READY"},
    ])
    monkeypatch.setattr(lm, "probe_lm_studio", lambda: next(states))
    invoked = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: invoked.append(cmd))
    assert lm.ensure_local_server()["status"] == "READY"
    assert invoked == [[str(binary), "server", "start", "--bind", "127.0.0.1", "--port", "1234"]]


def test_local_server_recovers_stale_running_without_loopback(monkeypatch, tmp_path):
    import pathlib
    import subprocess
    if lm.os.name != "nt":
        pytest.skip("Windows-only CLI recovery")
    binary = tmp_path / ".lmstudio" / "bin" / "lms.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"placeholder")
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    states = iter([
        {"available": False, "model_selected": False},
        {"available": False, "model_selected": False},
        {"available": True, "model_selected": True, "status": "READY"},
    ])
    monkeypatch.setattr(lm, "probe_lm_studio", lambda: next(states))
    commands = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: commands.append(cmd))
    assert lm.ensure_local_server()["status"] == "READY"
    assert [x[2] for x in commands] == ["start", "stop", "start"]
    assert commands[-1][-2:] == ["--port", "1234"]
