"""Regression checks for fail-closed local SEO save-path integration."""
from pathlib import Path


def test_local_seo_only_saves_review_drafts_without_editor_approval():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _save_local_seo_result(")
    end = source.index("    def export_public_comments_zero_api(", start)
    section = source[start:end]
    assert "check_seo_evidence(" in section
    assert "review_titles = [title, *variants]" in section
    assert "expected_title_count=4" in section
    assert "verified_video_mapping=False" in section
    assert "editorial_approval_verified = False" in section
    assert "or not editorial_approval_verified" in section
    assert '"draft" if requires_review else "ready"' in section


def test_batch_drafts_do_not_auto_publish():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def _save_local_seo_batch(")
    end = source.index("    def local_seo_selected(", start)
    section = source[start:end]
    assert 'save_optimization_draft(' in section
    assert '"draft",' in section
    assert '"review",' in section
