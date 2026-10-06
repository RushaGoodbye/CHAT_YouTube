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
        '"Потрібно підготувати", "needs"',
        '"Готово до YouTube", "ready"',
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


def test_batch_seo_requires_transcript_grounding() -> None:
    source = _ui_source()
    start = source.index("    def _generate_local_seo_result")
    end = source.index("\n    def _normalize_local_seo_package", start)
    block = source[start:end]
    assert "if fast_mode and not transcript.strip():" in block
    assert "немає транскрипту для фактчекінгу" in block


def test_batch_seo_uses_transcript_fallback_chain() -> None:
    source = _ui_source()
    start = source.index("    def _generate_local_seo_result")
    end = source.index("\n    def _normalize_local_seo_package", start)
    block = source[start:end]
    assert "load_srt_transcript" in block
    assert "fetch_transcript(video_id)" in block
    assert "fetch_transcript_from_public_metadata" in block
    assert 'context["transcript_source"] = transcript_source' in block


def test_batch_seo_prioritizes_nas_transcripts() -> None:
    source = _ui_source()
    start = source.index("    def local_seo_batch")
    end = source.index("\n    def _save_local_seo_batch", start)
    block = source[start:end]
    assert 'DEFAULT_NAS_TRANSCRIPTS_PATH' in block
    assert 'f"{video_id}.srt"' in block


def test_local_seo_worker_never_uses_gui_nas_path() -> None:
    source = _ui_source()
    start = source.index("    def _generate_local_seo_result")
    end = source.index("\n    def _normalize_local_seo_package", start)
    block = source[start:end]
    assert "self._nas_path(" not in block
    assert 'SELECT value FROM settings WHERE key=?' in block
    assert "normalize_nas_unc_path" in block


def test_optimization_tab_contains_live_process_strip() -> None:
    source = _ui_source()
    start = source.index("    def _build_optimization_tab")
    end = source.index("\n    def ", start + 20)
    block = source[start:end]
    assert 'QLabel("Поточна операція")' in block
    assert "optimization_process_progress" in block
    assert "ProcessStrip" in block


def test_set_process_mirrors_into_optimization_tab() -> None:
    source = _ui_source()
    start = source.index("    def _set_process")
    end = source.index("\n    def _set_process_idle", start)
    block = source[start:end]
    assert "optimization_process_title" in block
    assert "optimization_process_stage" in block
    assert "optimization_process_progress" in block


def test_guided_next_action_contract() -> None:
    source = _ui_source()
    for marker in (
        'next_action_caption = QLabel("Наступна дія")',
        'self.next_action_button = QPushButton("Продовжити")',
        'def _refresh_next_action_card',
        'def _run_guided_next_action',
        'self._refresh_next_action_card(safe_capacity)',
        '"Підготувати сьогоднішній стрім"',
        '"Перевірити підготовлені пакети: {draft_count}"',
        '"Готово до YouTube: {len(ready_queue)} відео"',
    ):
        assert marker in source


def test_guided_optimization_workspace_contract() -> None:
    source = _ui_source()
    start = source.index("    def _build_optimization_tab")
    end = source.index("\n    def _set_optimization_queue_filter", start)
    block = source[start:end]
    for marker in (
        'QPushButton("Підготувати без квоти")',
        'QPushButton("Готово до YouTube")',
        'advanced_btn.setText("Додатково ▾")',
        'archive_campaign_summary.setVisible(False)',
        'free_tools_status_label.setVisible(False)',
        '"Етап"',
        '"Підготовка → Перевірка → Готово → YouTube → Контроль"',
    ):
        assert marker in block


def test_draft_can_be_discarded_without_youtube_mutation() -> None:
    source = _ui_source()
    start = source.index("    def _discard_selected_draft")
    end = source.index("\n    def _run_context_primary_action", start)
    block = source[start:end]
    assert "DELETE FROM optimization_drafts" in block
    assert "YouTube не буде змінено" in block
    assert "_quota_update_video" not in block
    assert "context_discard_btn" in source
