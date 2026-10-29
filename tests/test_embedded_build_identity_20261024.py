"""Windows QA builds must identify exact binaries despite same semver."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_build_info_is_available_without_ci():
    from rg_youtube_control import build_info
    assert isinstance(build_info.BUILD_SHA, str)
    assert isinstance(build_info.BUILD_NUMBER, str)
    assert build_info.BUILD_SHA
    assert build_info.BUILD_NUMBER


def test_settings_show_version_and_build_identity(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import __version__, ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        label = window.version_label.text()
        assert __version__ in label
        assert "збірка #" in label
        assert "local" in label
        assert "development"[:8] in label
    finally:
        window.close()


def test_windows_workflow_stamps_embedded_build_before_pyinstaller():
    workflow = Path(".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )
    assert "Stamp exact build number and commit into Windows EXE" in workflow
    assert 'BUILD_NUMBER = ' in workflow
    assert 'BUILD_SHA = ' in workflow
    assert workflow.index("Stamp exact build number") < workflow.index(
        "- name: Build application"
    )
