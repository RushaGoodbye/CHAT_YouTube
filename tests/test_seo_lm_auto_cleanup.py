"""No live LLM usage. Verifies ownership-aware automatic model cleanup."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "qa_seo_real_local_llm.py"
spec = importlib.util.spec_from_file_location("rg_seo_test_runtime_cleanup", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_own_instances_unloaded_only_after_seo(monkeypatch):
    loaded = {"qwen3-14b": [], "google/gemma-4-12b": []}
    unload = []
    def fake_api(path, payload=None, timeout=20):
        if path == "/api/v1/models":
            return {"models": [{"key": key, "loaded_instances": [
                {"id": instance_id} for instance_id in values]}
                for key, values in loaded.items()]}
        if path == "/api/v1/models/load":
            key = payload["model"]
            instance_id = "seo_" + key
            loaded[key].append(instance_id)
            return {"status": "loaded", "instance_id": instance_id}
        if path == "/api/v1/models/unload":
            instance_id = payload["instance_id"]
            unload.append(instance_id)
            for values in loaded.values():
                if instance_id in values:
                    values.remove(instance_id)
            return {"status": "unloaded"}
        raise AssertionError(path)
    monkeypatch.setattr(mod, "_api", fake_api)
    mod._record_preexisting_instances()
    mod._model_ready(mod.WRITER)
    assert loaded[mod.WRITER] == ["seo_" + mod.WRITER]
    mod._model_ready(mod.CRITIC)
    assert unload == ["seo_" + mod.WRITER]
    assert loaded[mod.CRITIC] == ["seo_" + mod.CRITIC]
    assert mod._cleanup_our_models() == []
    assert unload == ["seo_" + mod.WRITER, "seo_" + mod.CRITIC]
    assert not mod._OWNED_INSTANCES
    assert mod._cleanup_our_models() == []


def test_preloaded_model_is_never_unloaded_even_during_switch(monkeypatch):
    loaded = {mod.WRITER: ["manual_writer"], mod.CRITIC: []}
    unload = []
    def api(path, payload=None, timeout=20):
        if path == "/api/v1/models":
            return {"models": [{"key": k, "loaded_instances": [{"id": x} for x in v]}
                               for k,v in loaded.items()]}
        if path == "/api/v1/models/unload":
            unload.append(payload["instance_id"])
            raise AssertionError("MUST_NOT_UNLOAD_PRELOADED")
        raise AssertionError(path)
    monkeypatch.setattr(mod, "_api", api)
    mod._record_preexisting_instances()
    mod._model_ready(mod.WRITER)
    with pytest.raises(RuntimeError, match="PREEXISTING_MODEL_IN_USE"):
        mod._model_ready(mod.CRITIC)
    assert mod._cleanup_our_models() == []
    assert loaded[mod.WRITER] == ["manual_writer"]
    assert unload == []


def test_cleanup_retries_errors_without_unloading_any_unknown_model(monkeypatch):
    mod._OWNED_INSTANCES.clear()
    mod._PREEXISTING_INSTANCES.clear()
    mod._OWNED_INSTANCES.add("seo_owned")
    seen = []
    def api(path, payload=None, timeout=20):
        if path == "/api/v1/models/unload":
            seen.append(payload["instance_id"])
            raise OSError("temporary failure")
        raise AssertionError(path)
    monkeypatch.setattr(mod, "_api", api)
    assert mod._cleanup_our_models() == ["OSError:seo_owned"]
    assert seen == ["seo_owned"]
    assert "seo_owned" in mod._OWNED_INSTANCES
    mod._OWNED_INSTANCES.clear()


def test_load_rejects_unverified_ownership(monkeypatch):
    def api(path, payload=None, timeout=20):
        if path == "/api/v1/models":
            return {"models": [
                {"key": mod.WRITER, "loaded_instances": []},
                {"key": mod.CRITIC, "loaded_instances": []},
            ]}
        if path == "/api/v1/models/load":
            return {"status": "loaded", "instance_id": "not_visible"}
        raise AssertionError(path)
    monkeypatch.setattr(mod, "_api", api)
    mod._record_preexisting_instances()
    with pytest.raises(RuntimeError, match="MODEL_INSTANCE_OWNERSHIP_UNPROVEN"):
        mod._model_ready(mod.WRITER)
    assert not mod._OWNED_INSTANCES
