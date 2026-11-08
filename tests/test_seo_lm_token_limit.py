import json
import pytest
from rg_youtube_control import lm_studio_backend as backend


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _size=-1):
        return b'{"choices":[{"message":{"content":"{\\\"ok\\\":true}"}}]}'


def test_json_generation_accepts_safe_token_cap_without_network(monkeypatch):
    requests = []
    monkeypatch.setattr(backend, "ensure_model_loaded", lambda **kwargs: "qwen3-14b")
    def fake_urlopen(request, timeout=0):
        requests.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse()
    monkeypatch.setattr(backend.urllib.request, "urlopen", fake_urlopen)
    output = backend.lm_studio_chat(
        [{"role": "user", "content": "Return JSON"}], model="qwen3-14b",
        json_mode=True, max_tokens=850, num_ctx=4096,
    )
    assert json.loads(output) == {"ok": True}
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 850


@pytest.mark.parametrize("bad", [0, 99, 4097, -1, True, "850"])
def test_local_token_limit_fails_closed(bad):
    with pytest.raises(ValueError, match="INVALID_LOCAL_RESPONSE_TOKEN_LIMIT"):
        backend.lm_studio_chat(
            [{"role": "user", "content": "Return JSON"}], max_tokens=bad)
