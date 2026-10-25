"""Real 0.7.18 editor regression: one Shoigu story, three paraphrases."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control.seo_readiness import ready_for_youtube


SHOIGU_VARIANTS = [
    "Увольнение Шойгу: коррупция или план?",
    "Шойгу уволен: за что и по какому плану?",
    "Увольнение Шойгу: коррупция или стратегия?",
]


def test_shoigu_paraphrases_are_not_three_different_hooks():
    issues = ab_title_issues(SHOIGU_VARIANTS)
    assert any("1 і 2" in item and "повторюють" in item for item in issues)
    allowed, reasons = ready_for_youtube(
        status="ready", generation="local-seo", quality_state="editor_approved",
        variants=SHOIGU_VARIANTS,
    )
    assert not allowed
    assert any("повторюють" in item for item in reasons)


def test_different_real_stories_still_pass():
    assert not ab_title_issues([
        "БЕЛОУСОВ В МИНОБОРОНЫ: ЧЕГО ЖДАТЬ РОССИЯНАМ?",
        "ТИМУР ИВАНОВ И КОРРУПЦИЯ: ЧТО ГОВОРЯТ СОБЕСЕДНИКИ?",
        "ПЕРЕВОД ШОЙГУ В СОВБЕЗ: КАК РЕАГИРУЮТ РОССИЯНЕ?",
    ])


def test_package_review_button_explains_editorial_block(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control.ui import ContentOptimizationDialog

    app = QApplication.instance() or QApplication([])
    alerts = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, _title, message: alerts.append(message),
    )
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda _parent, _title, message: alerts.append(message),
    )
    dialog = ContentOptimizationDialog(
        "Увольнение ШОЙГУ - коррупция или все идет по плану?",
        "У цьому випуску обговорюють зміну посади Шойгу та кадрові рішення. " * 7,
        "00:00 Вступ\n00:43 Версії змін у керівництві",
        ["раша гудбай", "чат рулетка", "шойгу", "иванов", "белоусов",
         "минобороны", "россия", "кадровые решения", "коррупция", "совбез"],
        "ready", SHOIGU_VARIANTS, generation="manual",
    )
    try:
        dialog.validate_package_now()
        assert alerts
        assert "РЕДАКТОРСЬКА ПЕРЕВІРКА:" in alerts[-1]
        assert "повторюють один сюжетний гачок" in alerts[-1]
        assert "НЕ готовий" in alerts[-1]
    finally:
        dialog.close()


def test_editor_does_not_display_unverified_stored_ready(monkeypatch):
    import rg_youtube_control.ui as ui

    inspected = []
    class Row:
        def fetchone(self):
            return None

    class Conn:
        def execute(self, *_args):
            return Row()

    class Editor:
        def __init__(self, *_args, **_kwargs):
            inspected.append(_args[4])

        def exec(self):
            return 0

    monkeypatch.setattr(ui, "ContentOptimizationDialog", Editor)
    monkeypatch.setattr(ui, "get_optimization_draft", lambda *_: {
        "new_title": "Увольнение ШОЙГУ - коррупция или план?",
        "description": "Опис про рішення і кадрову перестановку.",
        "chapters": "",
        "tags_json": '["раша гудбай"]',
        "title_variants_json": __import__("json").dumps(SHOIGU_VARIANTS, ensure_ascii=False),
        "status": "ready",
        "generation": "local-seo",
    })
    fake_window = SimpleNamespace(
        _selected_optimization_video_ids=lambda: ["MiEtkMo87xo"],
        conn=Conn(),
        _current_video_metadata=lambda _id: ("Original", "Before", []),
        _effective_optimization_status=lambda _id: "draft",
        _error=lambda *_: (_ for _ in ()).throw(AssertionError("no UI error expected")),
    )
    ui.MainWindow.edit_content_package(fake_window)
    assert inspected == ["draft"]


def test_real_shoigu_draft_reports_both_status_and_duplicate_topics():
    """Regression from operator screenshot in installed 0.7.19."""
    ready, issues = ready_for_youtube(
        status="draft", generation="local-seo",
        quality_state="review", variants=SHOIGU_VARIANTS,
    )
    assert not ready
    assert "Пакет не має статусу готовності." in issues
    assert any("повторюють один сюжетний гачок" in issue for issue in issues)
    assert any("SEO не підтверджено" in issue for issue in issues)


def test_draft_safe_metadata_does_not_require_ab():
    ready, issues = ready_for_youtube(
        status="draft", generation="safe-metadata-0.7.6",
        quality_state="safe_metadata", variants=[], scheduled=False,
    )
    assert not ready
    assert issues == ("Пакет не має статусу готовності.",)


def test_draft_scheduled_title_update_requires_editorial_review():
    ready, issues = ready_for_youtube(
        status="draft", generation="scheduled-import",
        quality_state="", variants=[], scheduled=True,
    )
    assert not ready
    assert any("A/B" in item for item in issues)
    assert any("SEO не підтверджено" in item for item in issues)


def test_editor_review_button_shows_ab_even_for_draft(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control.ui import ContentOptimizationDialog
    app = QApplication.instance() or QApplication([])
    alerts = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, _title, message: alerts.append(message),
    )
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda _parent, _title, message: alerts.append(message),
    )
    dialog = ContentOptimizationDialog(
        "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ",
        (
            "У цьому випуску чат-рулетки росіяни обговорюють зміну посади "
            "Шойгу та причини кадрових рішень у Міністерстві оборони РФ. "
        ) * 4,
        "00:00 Вступ і головне запитання\\n00:43 Версії причин зміни Шойгу",
        ["РАША ГУДБАЙ", "чат рулетка", "Шойгу", "увольнение Шойгу",
         "Белоусов", "Тимур Иванов", "Совет безопасности России",
         "Министерство обороны России", "коррупция в России", "Россия"],
        "draft", SHOIGU_VARIANTS, generation="local-seo",
    )
    try:
        dialog.validate_package_now()
        assert alerts
        result = alerts[-1]
        assert "Пакет не має статусу готовності." in result
        assert "повторюють один сюжетний гачок" in result
        assert "перефразування однієї події" in result
        assert "Пакет НЕ готовий" in result
    finally:
        dialog.close()
