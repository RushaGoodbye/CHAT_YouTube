"""Keep SEO tasks bound to the channel selected when they were launched."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_local_seo_uses_explicit_origin_profile_when_ui_switches(tmp_path, monkeypatch):
    import pytest
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)

    class ProfileProbe(Exception):
        pass

    observed = []

    def capture(_conn, _video_id, profile):
        observed.append(profile)
        raise ProfileProbe()

    monkeypatch.setattr(ui, "cached_public_metadata", capture)
    window = ui.MainWindow()
    try:
        window.current_profile = "live"
        with pytest.raises(ProfileProbe):
            window._generate_local_seo_result("RG_VIDEO_ID", profile="main")
        assert observed == ["main"]
    finally:
        window.close()


def test_batch_nas_prioritization_runs_inside_task():
    import ast
    from pathlib import Path

    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    window = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "MainWindow"
    )
    batch = next(
        item for item in window.body
        if isinstance(item, ast.FunctionDef) and item.name == "local_seo_batch"
    )
    nested = next(
        item for item in batch.body
        if isinstance(item, ast.FunctionDef) and item.name == "task"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "is_file"
        for node in ast.walk(nested)
    )
    own_calls = [node for statement in batch.body if statement is not nested
                 for node in ast.walk(statement)]
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "is_file"
        for node in own_calls
    )


def test_async_result_carries_origin_profile_into_savers():
    from pathlib import Path
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    for section in ("_save_local_seo_result", "_save_local_seo_batch"):
        begin = source.index(f"    def {section}(")
        end = source.index("\n    def ", begin + 6)
        body = source[begin:end]
        assert 'origin_profile = str(result.get("profile") or self.current_profile)' in body
        assert 'profile=origin_profile' in body
    assert '"profile": origin_profile' in source
