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


def test_today_stream_card_contract() -> None:
    source = _ui_source()
    for marker in (
        'today_stream_caption = QLabel("Сьогоднішній стрім")',
        'self.today_stream_optimize_btn = QPushButton("Оптимізувати")',
        'def _today_scheduled_row',
        'def _refresh_today_stream_card',
        'def open_today_stream_optimization',
        'self._refresh_today_stream_card()',
    ):
        assert marker in source


def test_scheduled_stream_shortcuts_contract() -> None:
    source = _ui_source()
    for marker in (
        'self.scheduled_quick_btn = QPushButton("Заплановані")',
        'today_quick_btn = QPushButton("Сьогоднішній стрім")',
        'scheduled_center_btn = QPushButton("Заплановані стріми")',
        'def _set_optimization_queue_filter',
        'f"Лише заплановані ({scheduled_total})"',
        'elif queue_filter == "scheduled":',
    ):
        assert marker in source


def test_local_seo_batch_resilience_contract() -> None:
    source = _ui_source()
    for marker in (
        'max_attempts = min(len(candidate_ids), max(limit * 3, limit))',
        'if len(prepared) >= limit:',
        'action="SEO-чернетка batch · пропуск"',
        'self.optimization_status_filter.findData("draft")',
        'Фільтр «Чернетки» відкрито автоматично.',
    ):
        assert marker in source


def test_local_seo_worker_uses_thread_local_sqlite_connection() -> None:
    source = _ui_source()
    start = source.index("    def _generate_local_seo_result")
    end = source.index("\n    def _normalize_local_seo_package", start)
    block = source[start:end]
    assert "sqlite3.connect" in block
    assert "self.conn.execute" not in block


def test_local_tool_failures_are_visible() -> None:
    source = _ui_source()
    start = source.index("    def _run_local_tool")
    end = source.index("\n    def refresh_free_tools_status", start)
    block = source[start:end]
    assert "QMessageBox.critical" in block
    assert "self.reload_action_log()" in block
    assert 'QMessageBox.information(self, APP_NAME, message)' in block


def test_local_seo_batch_lifecycle_is_logged() -> None:
    source = _ui_source()
    assert 'action="SEO-чернетка batch · старт"' in source
    assert 'action="SEO-чернетка batch · результат"' in source


def test_local_seo_batch_has_candidate_timeout() -> None:
    source = _ui_source()
    start = source.index("    def local_seo_batch")
    end = source.index("\n    def _save_local_seo_batch", start)
    block = source[start:end]
    assert "candidate_timeout_seconds = 75" in block
    assert "daemon=True" in block
    assert "fast_mode=True" in block
    assert "Кандидат пропущено автоматично." in block
