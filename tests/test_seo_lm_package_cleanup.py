"""Model lifecycle never unloads pre-existing LM Studio instances."""
import json
import urllib.error
import pytest
from rg_youtube_control import lm_studio_backend as backend


class Reply:
    def __init__(self, value):
        self.value=value
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        return json.dumps(self.value).encode("utf-8")


def fake_client(monkeypatch, preload=False, omit_instance_id=False):
    instances={"qwen3-14b": ["manual"] if preload else []}
    calls=[]
    def request(req,timeout=30):
        body=json.loads(req.data) if req.data else {}
        calls.append((req.full_url,body))
        if req.full_url.endswith("/api/v1/models"):
            return Reply({"models":[{"key":"qwen3-14b","loaded_instances":[
                {"id":x} for x in instances["qwen3-14b"]]}]})
        if req.full_url.endswith("/api/v1/models/load"):
            instances["qwen3-14b"].append("our_instance")
            data={"status":"loaded"}
            if not omit_instance_id:
                data["instance_id"]="our_instance"
            return Reply(data)
        if req.full_url.endswith("/api/v1/models/unload"):
            instance_id=body["instance_id"]
            instances["qwen3-14b"].remove(instance_id)
            return Reply({"status":"unloaded"})
        raise AssertionError(req.full_url)
    monkeypatch.setattr(backend.urllib.request,"urlopen",request)
    return instances,calls


def test_unloads_only_new_instance_after_seo(monkeypatch):
    models,calls=fake_client(monkeypatch)
    with backend.seo_model_lifecycle():
        assert backend.ensure_model_loaded() == "our_instance"
        assert models["qwen3-14b"] == ["our_instance"]
    assert models["qwen3-14b"] == []
    assert [x[1]["instance_id"] for x in calls if x[0].endswith("/unload")] == ["our_instance"]


def test_reuses_existing_model_without_unloading_it(monkeypatch):
    models,calls=fake_client(monkeypatch,preload=True)
    with backend.seo_model_lifecycle():
        assert backend.ensure_model_loaded() == "manual"
    assert models["qwen3-14b"] == ["manual"]
    assert not any(url.endswith("/unload") for url,_ in calls)


def test_exception_does_not_leak_owned_instance(monkeypatch):
    models,calls=fake_client(monkeypatch)
    with pytest.raises(ValueError,match="seo failed"):
        with backend.seo_model_lifecycle():
            backend.ensure_model_loaded()
            raise ValueError("seo failed")
    assert models["qwen3-14b"] == []
    assert any(url.endswith("/unload") for url,_ in calls)


def test_nested_seo_session_only_cleans_up_on_outer_exit(monkeypatch):
    models,calls=fake_client(monkeypatch)
    with backend.seo_model_lifecycle():
        with backend.seo_model_lifecycle():
            backend.ensure_model_loaded()
        assert models["qwen3-14b"] == ["our_instance"]
    assert models["qwen3-14b"] == []


def test_unconfirmed_load_does_not_unload_arbitrary_model(monkeypatch):
    models,calls=fake_client(monkeypatch,omit_instance_id=True)
    with backend.seo_model_lifecycle():
        assert backend.ensure_model_loaded()=="qwen3-14b"
    assert models["qwen3-14b"] == ["our_instance"]
    assert not any(url.endswith("/unload") for url,_ in calls)


def test_without_explicit_seo_session_existing_loading_behavior_is_unchanged(monkeypatch):
    models,calls=fake_client(monkeypatch)
    backend.ensure_model_loaded()
    assert models["qwen3-14b"] == ["our_instance"]
    assert not any(url.endswith("/unload") for url,_ in calls)


def test_decorated_package_cleans_up_and_returns_result(monkeypatch):
    models,calls=fake_client(monkeypatch)
    @backend.auto_release_seo_models
    def package():
        backend.ensure_model_loaded()
        return {"publication_allowed":False}
    assert package()=={"publication_allowed":False}
    assert models["qwen3-14b"] == []
