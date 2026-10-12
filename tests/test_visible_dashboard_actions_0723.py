"""Visual and functional regression for user-visible Today actions (0.7.23)."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from rg_youtube_control.ui import MetricCard


def test_metric_navigation_has_real_button_and_emits_click():
    app = QApplication.instance() or QApplication([])
    card = MetricCard("Перевірити SEO-пакети")
    seen = []
    card.clicked.connect(lambda: seen.append("opened"))
    assert card.action_button.isHidden()

    card.set_action("Відкрити чергу →", "Відкрити SEO-пакети на перевірці")
    card.show()
    try:
        assert card.action_button.isVisible()
        assert isinstance(card.action_button, QPushButton)
        assert card.action_button.text() == "Відкрити чергу →"
        assert card.action_button.accessibleName() == "Відкрити SEO-пакети на перевірці"
        assert card.action_button.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert card.property("interactive") is True
        card.action_button.click()
        assert seen == ["opened"]
        assert card.minimumHeight() == 92  # action is inline, not a huge extra row
    finally:
        card.close()


def test_three_dashboard_cards_have_visible_actions_and_correct_callbacks():
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "rg_youtube_control" / "ui.py"
    ).read_text(encoding="utf-8")
    build_start = source.index("    def _build_task_center_tab")
    build_end = source.index("\n    def _today_scheduled_row", build_start)
    block = source[build_start:build_end]
    assert 'self.center_review.set_action(' in block
    assert '"Відкрити чергу →"' in block
    assert 'self._open_optimization_status("draft")' in block
    assert 'self.center_prepared.set_action(' in block
    assert '"Переглянути →"' in block
    assert 'self.center_comments.set_action(' in block
    assert '"Відкрити →"' in block
    assert 'self.center_review.clicked.connect(' in block
    assert 'self.center_comments.clicked.connect(' in block


def test_hover_state_makes_navigation_cards_visually_distinct():
    css = (
        Path(__file__).resolve().parents[1]
        / "src" / "rg_youtube_control" / "style.py"
    ).read_text(encoding="utf-8")
    assert 'QFrame#MetricCard[interactive="true"]:hover' in css
    assert 'QFrame#MetricCard QPushButton[role="primary"]' in css
