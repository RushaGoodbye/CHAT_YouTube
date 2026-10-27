"""Run packaged-runtime proof in CI, even before creating the EXE."""
import json

from rg_youtube_control.packaged_smoke import run_packaged_selftest


def test_selftest_writes_pass_report(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    report = tmp_path / "runtime-proof.json"
    assert run_packaged_selftest(report) == 0, report.read_text(encoding="utf-8")
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
    assert "synthetic-whisper-to-srt-to-seo-input" in data["checks"]
    assert "qt-runtime" in data["checks"]
    assert "silero-vad-onnx-real-inference" in data["checks"]
    assert "packaged-pyav-audio-decoding" in data["checks"]


def test_windows_workflow_verifies_installed_binary():
    from pathlib import Path
    workflow = Path(".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert "--packaged-selftest" in workflow
    assert "Installed app selftest timed out" in workflow
    assert 'proof.status -ne "PASS"' in workflow
    assert "--collect-data faster_whisper" in workflow
    assert "VAD ONNX model missing from Windows application" in workflow
    assert "Silero VAD inference proof missing" in workflow
    assert "Packaged PyAV decoding proof missing" in workflow
