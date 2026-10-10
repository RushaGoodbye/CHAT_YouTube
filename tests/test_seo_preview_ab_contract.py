"""Regression contract for SEO preview: A/B alternatives must be visible before approval."""
import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src" / "rg_youtube_control" / "ui.py"


def _method(name: str) -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing method {name}")


def test_deep_preview_accepts_and_displays_ab_variants():
    node = _method("_preview_deep_content_package")
    assert "title_variants" in {item.arg for item in node.args.kwonlyargs}
    source = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), node)
    assert 'if title_variants is not None:' in source
    assert 'if len(variants) != 3:' in source
    assert 'ab_options.setPlainText(' in source
    assert 'layout.addWidget(ab_options)' in source


def test_local_seo_preview_passes_generated_variants():
    node = _method("_save_local_seo_result")
    calls = [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_preview_deep_content_package"
    ]
    assert len(calls) == 1
    keywords = {item.arg: item.value for item in calls[0].keywords}
    assert "title_variants" in keywords
    assert isinstance(keywords["title_variants"], ast.Name)
    assert keywords["title_variants"].id == "variants"
