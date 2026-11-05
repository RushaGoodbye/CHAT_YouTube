"""No live audio or system state in unit tests; frozen QA stays opt-in."""
import importlib.util
from pathlib import Path


def test_smoke_requires_explicit_audio_and_destination():
    path=Path(__file__).resolve().parents[1]/"run_app.py"
    spec=importlib.util.spec_from_file_location("rg_entry_qa",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._qa_asr_local([])==2
    assert module._qa_asr_local(["one"])==2


def test_ordinary_startup_preserves_existing_app_entry():
    source=(Path(__file__).resolve().parents[1]/"run_app.py").read_text(encoding="utf-8")
    assert 'if len(sys.argv) > 1 and sys.argv[1] == "--rg-qa-asr-local":' in source
    assert "from rg_youtube_control.main import main" in source
    assert "raise SystemExit(main())" in source