"""Contract tests compile actual UI methods in isolation, without test-only mocks of the application."""
import ast
from pathlib import Path
import pytest


def _legacy_methods():
    path = Path(__file__).resolve().parents[1] / "src" / "rg_youtube_control" / "ui.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    window = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
    required = {
        "prepare_zero_quota_batch",
        "_generate_local_seo_result",
        "_save_local_seo_result",
    }
    methods = [node for node in window.body
               if isinstance(node, ast.FunctionDef) and node.name in required]
    assert {node.name for node in methods} == required
    wrapper = ast.ClassDef(
        name="IsolatedWindow", bases=[], keywords=[], body=methods,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    namespace = {}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["IsolatedWindow"]


def test_legacy_zero_quota_button_only_opens_vidiq():
    cls = _legacy_methods()
    class Dummy:
        count = 0
        def review_vidiq_proposals(self):
            self.count += 1
    dummy = Dummy()
    cls.prepare_zero_quota_batch(dummy)
    assert dummy.count == 1


def test_legacy_generator_fails_closed():
    cls = _legacy_methods()
    with pytest.raises(RuntimeError, match="vidIQ"):
        cls._generate_local_seo_result(object(), "abcdefghijk")


def test_legacy_result_saver_fails_closed():
    cls = _legacy_methods()
    with pytest.raises(RuntimeError, match="vidIQ"):
        cls._save_local_seo_result(object(), {})
