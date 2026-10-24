"""No more three identical operator-facing SEO errors for one real video.

A model outage, bad JSON or inadequate verified tag diversity produces a
GROUNDed, manual-review-only draft. It cannot become apply-ready or change
YouTube metadata. Missing source evidence is still an error.
"""
import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control import free_tools as seo


REPORT = {
    "blocks_total": 2,
    "blocks_with_evidence": 2,
    "blocks": [
        {"verified": True, "topics": [{
            "topic": "Причини кадрової зміни",
            "evidence": "Шойгу уволили из-за коррупции в армии или нет?"
        }]},
        {"verified": True, "topics": [{
            "topic": "Мотиви та рішення",
            "evidence": "Я думаю это было кадровое решение министерства обороны"
        }]},
    ],
}
TITLE = "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"


def test_two_ollama_failures_return_grounded_draft_not_an_error(monkeypatch):
    attempted = []
    def offline(*args, **kwargs):
        attempted.append(True)
        raise RuntimeError("Ollama не отвечает")
    monkeypatch.setattr(seo, "ollama_chat", offline)
    result = seo.generate_seo_package_local(
        current_title=TITLE,
        transcript=seo.evidence_outline_text(REPORT),
        evidence_report=REPORT,
        is_short=True,
    )
    assert len(attempted) == 2
    assert result["provider"] == "local:evidence-safe-recovery"
    assert result["technical_fallback"] is True
    assert result["needs_review"] is True
    assert result["title"] == TITLE
    assert result["title_variants"] == []
    assert result["chapters"] == ""
    assert "Шойгу" in result["description"]
    assert "Оllama" not in str(result)
    assert result["youtube_data_api_quota"] == 0


def test_no_source_quote_does_not_fabricate_fallback(monkeypatch):
    report = {
        "blocks_total": 1, "blocks_with_evidence": 0,
        "blocks": [{"verified": False, "topics": []}],
    }
    monkeypatch.setattr(
        seo, "ollama_chat",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    with pytest.raises((RuntimeError, ValueError)):
        seo.generate_seo_package_local(
            current_title=TITLE,
            transcript="",
            evidence_report=report,
            is_short=True,
        )


def test_grounded_fallback_with_few_tags_keeps_draft_in_gui(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui
    from rg_youtube_control.db import get_optimization_draft

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    video_id = "MEitKm687xo"
    def fail_modal(*args, **kwargs):
        raise AssertionError("Unexpected modal warning in recovery QA")
    monkeypatch.setattr(ui.QMessageBox, "warning", fail_modal)
    try:
        window.conn.execute(
            "INSERT INTO videos(video_id,profile,title,privacy_status,"
            "last_synced_at) VALUES (?,?,?,?,?)",
            (video_id, "main", TITLE, "public", "2026-10-24")
        )
        window.conn.commit()
        result = {
            "video_id": video_id,
            "profile": "main",
            "context": {"title": TITLE, "description": "", "tags": []},
            "package": {
                "title": TITLE, "title_variants": [],
                "description": seo._deterministic_evidence_description(
                    TITLE, REPORT
                ),
                "tags": ["РАША ГУДБАЙ", "чат рулетка", "Шойгу"],
                "chapters": "",
                "technical_fallback": True,
                "needs_review": True,
                "provider": "local:evidence-safe-recovery",
                "review_reason": "Потребує ручної перевірки",
            },
            "evidence_report": REPORT,
        }
        monkeypatch.setattr(
            window, "_preview_deep_content_package", lambda **kwargs: True
        )
        monkeypatch.setattr(window, "reload_optimization_queue", lambda: None)
        monkeypatch.setattr(window, "reload_action_log", lambda: None)
        monkeypatch.setattr(window, "update_task_center", lambda: None)
        monkeypatch.setattr(
            window, "_update_optimization_context_card", lambda: None
        )
        window._save_local_seo_result(result)
        draft = get_optimization_draft(window.conn, video_id)
        assert draft is not None
        assert draft["status"] == "draft"
        assert draft["quality_state"] == "needs_review"
        assert len(draft["title_variants_json"]) >= 2
    finally:
        window.close()


def test_invalid_non_tag_metadata_remains_blocked(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from rg_youtube_control import ui

    monkeypatch.setattr(ui, "app_data_dir", lambda: tmp_path)
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    try:
        bad = {
            "video_id": "MEitKm687xo",
            "package": {
                "title": "x" * 120,
                "description": "Валідний український текст " * 20,
                "tags": ["РАША ГУДБАЙ", "чат рулетка"],
                "chapters": "",
                "technical_fallback": True,
            },
        }
        with pytest.raises(RuntimeError, match="100"):
            window._normalize_local_seo_package(bad)
    finally:
        window.close()
