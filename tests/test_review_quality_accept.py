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
    assert "title_variants_json" in body
    assert "reviewed_seo_acceptance_issues(" in body
    assert 'original_description=draft["source_description"]' in body
    assert "status != \"safe\"" in body
    assert 'if len(options) != 3:' in body
    assert "if issues:" in body
    assert body.index("reviewed_seo_acceptance_issues(") < body.index('set_optimization_draft_status(self.conn, video_id, "ready")')
    assert body.index("if issues:") < body.index('set_optimization_draft_status(self.conn, video_id, "ready")')


def test_manual_review_can_open_every_verified_dialogue_not_only_preview():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    method = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_review_one_draft_dialog"
    )
    body = ast.get_source_segment(code, method)
    assert "load_local_evidence_report(" in body
    assert "ВІДКРИТИ ВСЮ ДОКАЗОВУ КАРТУ" in body
    assert "setPlainText(proof_text)" in body
    assert "show_full_evidence_map" in body
    assert "full_dialog.exec()" in body
