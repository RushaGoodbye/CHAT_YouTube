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
