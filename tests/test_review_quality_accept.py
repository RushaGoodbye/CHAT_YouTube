"""Manual confirmation must not bypass semantic SEO review gates."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "rg_youtube_control" / "ui.py"


def test_review_accept_requires_safe_three_options():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    method = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "review_draft_queue"
    )
    body = ast.get_source_segment(code, method)
    assert 'quality_state != "safe" or len(options) != 3' in body
    assert "title_variants_json" in body
    assert body.index('quality_state != "safe" or len(options) != 3') < body.index('set_optimization_draft_status(self.conn, video_id, "ready")')
