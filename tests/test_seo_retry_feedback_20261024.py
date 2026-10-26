"""Regression guard: local SEO retries must see the actual validation failure."""
from pathlib import Path


def test_seo_retry_includes_previous_validation_reason():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    start = source.index("def generate_seo_package_local(")
    end = source.index("def _comment_reply_safe_novelty_ok(", start)
    generator = source[start:end]
    assert 'failure_reason = " ".join(str(last_error or "").split())[:350]' in generator
    assert "Причина попередньої відмови: {failure_reason}" in generator
    assert "Не роби заголовком побічну репліку" in generator
    assert "except (ValueError, RuntimeError, TimeoutError) as exc:" in generator
    assert "last_error = exc" in generator

def test_invalid_evidence_titles_cannot_reach_preview():
    source = Path("src/rg_youtube_control/free_tools.py").read_text(encoding="utf-8")
    start = source.index("def generate_seo_package_local(")
    end = source.index("def _comment_reply_safe_novelty_ok(", start)
    generator = source[start:end]
    assert "if title_issues and evidence_report:" in generator
    assert "grounded = _source_quote_ab_titles(evidence_report, current_title)" in generator
    assert "variants = []" in generator
    assert "title_issues = ab_title_issues(variants, evidence_report)" in generator
