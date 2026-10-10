"""Privacy and structure contracts for an offline genuine-video QA pilot."""
from __future__ import annotations

from pathlib import Path
import sys


def _module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import rg_youtube_real_seo_local_qa as pilot
    return pilot


def test_anonymous_metrics_never_include_user_content(monkeypatch):
    pilot = _module(monkeypatch)
    source = {
        "blocks_total": 6,
        "blocks_with_evidence": 5,
        "source_rows_with_text": 105,
        "source_integrity_verified": True,
    }
    package = {
        "title": "PRIVATE_VIDEO_TITLE_DO_NOT_LOG",
        "description": "PRIVATE_VIDEO_DESCRIPTION_DO_NOT_LOG",
        "title_variants": ["PRIVATE_A", "PRIVATE_B", "PRIVATE_C"],
        "tags": ["PRIVATE_TAG"],
        "timeline_prompt_omitted_count": 1,
    }
    summary = pilot.anonymous_metrics(source, package)
    assert summary["timeline_blocks"] == 6
    assert summary["grounded_blocks"] == 5
    assert summary["semantic_coverage_complete"] is False
    assert summary["ab_titles_count"] == 3
    assert summary["ab_titles_distinct"] is True
    assert "PRIVATE_VIDEO" not in str(summary)
    assert "PRIVATE_TAG" not in str(summary)
    assert "PRIVATE_A" not in str(summary)


def test_missing_local_db_never_contacts_youtube_or_runs_model(tmp_path, monkeypatch):
    pilot = _module(monkeypatch)
    monkeypatch.setattr(pilot, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(pilot, "ollama_chat", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No model call")))
    report = pilot.run()
    assert report["status"] == "NOT_READY"
    assert report["source_text_exported"] is False
    assert report["generated_content_exported"] is False
    assert report["youtube_published"] is False


def test_pilot_has_no_network_or_publish_operations(monkeypatch):
    pilot = _module(monkeypatch)
    source = Path(pilot.__file__).read_text(encoding="utf-8")
    assert 'generate_seo_package_local(' in source
    assert 'analyze_all_timeline_blocks(' in source
    assert "sqlite3.connect" in source
    assert "mode=ro" in source
    assert "SELECT video_id, title" in source
    assert "upload-artifact" not in source
    assert "YouTubeClient" not in source
    assert "upload_video" not in source
    assert "apply_content_package" not in source
    assert "print(title" not in source
    assert "print(video_id" not in source


def test_warning_categories_do_not_expose_private_subjects(monkeypatch):
    pilot = _module(monkeypatch)
    issues = [
        "Частина тем відсутня у згенерованому описі: PRIVATE_PERSON_EVENT",
        "A/B варіант 2 не має підтверджених тематичних слів: PRIVATE_VIDEO",
        "В описі немає жодної дослівної цитати PRIVATE_QUOTE",
    ]
    categories = pilot.anonymous_issue_categories(issues)
    assert "DESCRIPTION_TOPICS" in categories
    assert "AB_TITLES" in categories
    assert "EVIDENCE_QUOTES" in categories
    assert not any("PRIVATE" in category for category in categories)
    assert categories == sorted(set(categories))
