"""Guard the real-video acceptance entrypoint used on AlexPC."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "rg_remote_control" / "seo_readonly_acceptance_10.py"


def test_real_video_acceptance_script_present_and_compiles():
    source = SCRIPT.read_text(encoding="utf-8")
    compile(source, str(SCRIPT), "exec")
    assert "mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    assert "production_db_writes" in source
    assert "youtube_writes" in source


def test_real_video_acceptance_duration_formats():
    spec = importlib.util.spec_from_file_location("rg_seo_readonly_acceptance_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._duration_seconds("PT9M53S") == 593
    assert module._duration_seconds("00:09:53") == 593
    assert module._duration_seconds("593") == 593
    assert module._duration_seconds("PT1H1M1S") == 3661


def test_safe_error_codes_never_export_private_model_text():
    spec = importlib.util.spec_from_file_location("rg_seo_readonly_acceptance_codes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._safe_error_code(ValueError(
        "Локальна SEO-генерація не пройшла валідацію після повторів: need at least 8 grounded tags"
    )) == "TAGS_INSUFFICIENT"
    assert module._safe_error_code(ValueError(
        "Untrusted transcript private quoted sentence"
    )) == "LOCAL_SEO_OTHER_ERROR"


def test_batch_accepts_video_ids_that_start_with_dash(tmp_path, monkeypatch):
    import json
    spec = importlib.util.spec_from_file_location("rg_seo_readonly_batch_ids", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = []
    def fake_run_one(video_id, **kwargs):
        seen.append(video_id)
        return {"video_id": video_id, "status": "DRAFT_READY_FOR_HUMAN_REVIEW"}
    monkeypatch.setattr(module, "run_one", fake_run_one)
    out = tmp_path / "summary.json"
    exit_code = module.main([
        "--video-ids", "MEitKm687xo,-Bu_aDIvEs4,fdHXrCyw3Lw",
        "--output", str(out),
    ])
    assert exit_code == 0
    assert seen == ["MEitKm687xo", "-Bu_aDIvEs4", "fdHXrCyw3Lw"]
    assert json.loads(out.read_text(encoding="utf-8"))["video_count"] == 3
