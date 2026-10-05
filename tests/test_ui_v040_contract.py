from pathlib import Path


def _ui_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "src" / "rg_youtube_control" / "ui.py").read_text(encoding="utf-8")


def test_v040_dashboard_contract() -> None:
    source = _ui_source()
    required = (
        'self.tabs.addTab(page, "Сьогодні")',
        'self.tabs.addTab(page, "Архів")',
        'self.process_progress = QProgressBar()',
        'self.activity_list = QListWidget()',
        'self.issue_list = QListWidget()',
        'self.center_quota = ProgressMetricCard("YouTube API")',
        'self.center_vidiq = ProgressMetricCard("vidIQ · AIR Boost")',
        'self.optimization_search = QLineEdit()',
        'self.optimization_density = QComboBox()',
        'FrozenColumnsTable(',
        'def rollback_last_optimized_metadata',
    )
    for marker in required:
        assert marker in source


def test_v040_quick_filters_and_context_actions_contract() -> None:
    source = _ui_source()
    for marker in (
        '"Потрібна увага", "needs"',
        '"Готово", "ready"',
        '"Без тегів", "no_tags"',
        '"Низький CTR", "low_ctr"',
        'self.context_primary_btn',
        'self._preview_deep_content_package',
        'THUMBNAIL · VISIBILITY · ДАТА',
    ):
        assert marker in source
