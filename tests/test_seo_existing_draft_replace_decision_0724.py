"""0.7.24 non-destructive replacement of an existing, richer SEO package."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _setup(monkeypatch, tmp_path, *, approval):
    from PySide6.QtWidgets import QApplication, QMessageBox
    import rg_youtube_control.ui as ui
    app = QApplication.instance() or QApplication([])
    existing = {
        "new_title": "Увольнение ШОЙГУ - коррупция или всё по плану?",
        "description": "Розлогий попередній опис. " * 40,
        "chapters": "00:00 Початок\n02:00 Тема\n03:00 Тема\n04:00 Тема\n05:00 Тема\n06:00 Тема\n08:00 Тема",
        "tags_json": json.dumps(["Шойгу", "РАША ГУДБАЙ"], ensure_ascii=False),
        "status": "ready",
    }
    monkeypatch.setattr(ui, "get_optimization_draft", lambda *_: existing)
    decisions = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args: decisions.append(_args) or approval,
    )
    persisted = []
    monkeypatch.setattr(
        ui, "save_optimization_draft",
        lambda *_args, **_kwargs: persisted.append((_args, _kwargs)),
    )
    monkeypatch.setattr(ui, "log_action", lambda *_args, **_kwargs: None)
    messages = []
    fake = SimpleNamespace(
        conn=object(),
        current_profile="main",
        data_dir=tmp_path,
        _normalize_local_seo_package=lambda _: (
            "MEitKm687xo", "Почему уволили Шойгу?",
            "Український опис причин звільнення та корупції. " * 12,
            ["РАША ГУДБАЙ", "чат рулетка", "Шойгу", "коррупция",
             "Путин", "Белоусов", "Минобороны", "Россия"], "",
            ["Шойгу: причины", "Шойгу и коррупция", "Шойгу и стратегия"],
        ),
        _seo_candidate_regressions=lambda **_: [
            "Розділи збереженого пакета: 7; у кандидата: 0."
        ],
        _preview_deep_content_package=lambda **_: True,
        _package_quality_gate=lambda **_: ("safe", []),
        _set_process_idle=lambda *args: messages.append(args),
        _toast=lambda *_: None,
        reload_optimization_queue=lambda: None,
        reload_action_log=lambda: None,
        _update_optimization_context_card=lambda: None,
    )
    result = {
        "package": {"needs_review": True, "review_reason": "Перевірте факти",
                    "provider": "test"},
        "context": {"title": existing["new_title"], "description": "",
                    "tags": []},
        "evidence_report": None,
    }
    return ui, fake, result, existing, decisions, persisted, messages


def test_declining_replacement_preserves_old_draft_and_saves_recoverable_backup(
    monkeypatch, tmp_path
):
    from PySide6.QtWidgets import QMessageBox
    ui, fake, result, existing, decisions, persisted, _ = _setup(
        monkeypatch, tmp_path, approval=QMessageBox.StandardButton.No
    )
    ui.MainWindow._save_local_seo_result(fake, result)
    assert not persisted
    assert decisions
    assert decisions[-1][-1] == QMessageBox.StandardButton.No
    files = list((tmp_path / "seo_candidates").glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["previous_saved_draft"] == existing
    assert saved["preserved_saved_draft"] is True


def test_explicit_yes_can_replace_only_local_draft_with_previous_package_backed_up(
    monkeypatch, tmp_path
):
    from PySide6.QtWidgets import QMessageBox
    ui, fake, result, existing, decisions, persisted, _ = _setup(
        monkeypatch, tmp_path, approval=QMessageBox.StandardButton.Yes
    )
    ui.MainWindow._save_local_seo_result(fake, result)
    assert persisted
    assert persisted[0][0][6] == "draft"
    assert decisions[-1][-1] == QMessageBox.StandardButton.No
    files = list((tmp_path / "seo_candidates").glob("*.json"))
    assert files
    assert json.loads(files[0].read_text(encoding="utf-8"))[
        "previous_saved_draft"
    ] == existing
