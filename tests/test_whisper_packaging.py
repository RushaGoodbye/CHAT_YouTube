"""Regression: offline SEO transcription runtime must ship with Windows build."""
from pathlib import Path
import tomllib


def test_whisper_in_windows_runtime_requirements():
    req = Path("requirements.txt").read_text(encoding="utf-8")
    meta = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert any(line.startswith("faster-whisper") for line in req.splitlines())
    assert any(dep.startswith("faster-whisper") for dep in meta["project"]["dependencies"])


def test_whisper_import_checked_during_windows_build():
    workflow = Path(".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert "import faster_whisper" in workflow
    assert "Verify packaged offline transcription" in workflow
    assert "ctranslate2 was not included" in workflow
