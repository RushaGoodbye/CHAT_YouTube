"""Regression: technical metadata cleanup must never appear as full SEO review."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "rg_youtube_control" / "ui.py"


def test_content_review_queue_excludes_technical_metadata():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "review_draft_queue"
    )
    body = ast.get_source_segment(source, method)
    assert "'safe-metadata-0.7.6'" in body
    assert "NOT IN" in body
    assert "Технічні пакети метаданих не є SEO-оптимізацією" in body


def test_zero_quota_metadata_remains_explicitly_technical():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_zero_quota_batch"
    )
    body = ast.get_source_segment(source, method)
    assert 'generation="safe-metadata-0.7.6"' in body
    assert 'quality_state="safe_metadata"' in body
    assert 'title_variants=[]' in body
