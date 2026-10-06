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
        'self.center_quota = ProgressMetricCard("Квота YouTube на сьогодні")',
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


def test_today_screen_is_decision_focused() -> None:
    source = _ui_source()
    start = source.index("    def _build_task_center_tab")
    end = source.index("\n    def _today_scheduled_row", start)
    block = source[start:end]
    for marker in (
        'self.today_process_frame = process',
        'process.setVisible(False)',
        'self.center_scheduled.setVisible(False)',
        'self.center_results.setVisible(False)',
        'self.center_vidiq.setVisible(False)',
        'grid.addWidget(self.center_quota, 1, 0, 1, 4)',
        'pipeline.setVisible(False)',
        'archive_card.setVisible(False)',
        'activity_card.setVisible(False)',
        'issues_card.setVisible(False)',
        'ProgressMetricCard("Квота YouTube на сьогодні")',
    ):
        assert marker in block


def test_today_stream_action_matches_state() -> None:
    source = _ui_source()
    start = source.index("    def _refresh_today_stream_card")
    end = source.index("\n    def open_today_stream_optimization", start)
    block = source[start:end]
    assert '"Переглянути"' in block
    assert '"Перевірити"' in block
    assert '"Підготувати"' in block


def test_today_problem_list_ignores_success_summary_words() -> None:
    source = _ui_source()
    start = source.index('if hasattr(self, "issue_list")')
    end = source.index("\n\n\n    def prepare_zero_quota_batch", start)
    block = source[start:end]
    assert 'action_is_error' in block
    assert 'details_is_error' in block
    assert 'for key in ("помил", "error"' not in block


def test_idle_process_strip_is_hidden() -> None:
    source = _ui_source()
    start = source.index("    def _set_process_idle")
    end = source.index("\n    def _toast", start)
    block = source[start:end]
    assert 'self.today_process_frame.setVisible(False)' in block


def test_v060_guided_release_contract() -> None:
    source = _ui_source()
    for marker in (
        'self.next_action_why_btn = QPushButton("Чому?")',
        'def _explain_guided_next_action',
        'def _discard_all_legacy_drafts',
        'def review_draft_queue',
        'QPushButton("Прийняти")',
        'QPushButton("Відхилити")',
        'generation="local-seo-0.6"',
        'generation="safe-metadata-0.6"',
        'def _package_quality_gate',
        '"SEO-опис не українською"',
        '"старий рекламний хвіст у назві"',
    ):
        assert marker in source


def test_v060_normal_mode_hides_technical_ui() -> None:
    source = _ui_source()
    for marker in (
        'self.advanced_mode = get_setting(',
        'self.advanced_mode_box = QCheckBox("Розширений режим")',
        'self.optimization_table.setColumnHidden(7, not advanced)',
        'self.advanced_batch_seo_action.setVisible',
        'self.settings_sections.setTabVisible(index, advanced)',
        'self.optimization_process_frame.setVisible(False)',
    ):
        assert marker in source


def test_v060_smart_workspace_state_and_search() -> None:
    source = _ui_source()
    for marker in (
        'optimization_queue_filter_{self.current_profile}',
        'optimization_status_filter_{self.current_profile}',
        'optimization_density',
        '"готовые": "ready"',
        '"черновики": "draft"',
        '"нужно подготовить": "needs"',
        'def _restore_optimization_view_state',
    ):
        assert marker in source


def test_v060_quota_protection_and_write_verification() -> None:
    source = _ui_source()
    start = source.index("    def apply_content_package")
    end = source.index("\n    @staticmethod\n    def _dedupe_tags", start)
    block = source[start:end]
    assert "_quota_write_available" in source
    assert "_verify_applied_metadata" in block
    assert "Контроль після запису не пройдено" in block
    assert "контроль YouTube OK" in block
    assert "Квота в резерві" in source


def test_v060_batch_verification_reuses_refresh() -> None:
    source = _ui_source()
    start = source.index("    def apply_next_safe_archive_batch")
    end = source.index("\n    def apply_safe_optimization", start)
    block = source[start:end]
    assert "expected_after" in block
    assert "refreshed_rows = sync_specific_videos" in block
    assert "verification_failed" in block
    assert "Контроль batch не пройдено" in block


def test_v060_logs_split_work_and_diagnostics() -> None:
    source = _ui_source()
    start = source.index("    def _build_log_tab")
    end = source.index("\n    def _build_settings_tab", start)
    block = source[start:end]
    assert 'self.log_sections.addTab(work_page, "Робота")' in block
    assert 'self.log_sections.addTab(diagnostic_page, "Діагностика")' in block
    assert "def reload_action_log" in block
    assert "def _diagnostic_family" in source
    assert 'f"×{int(info[\'count\'])}"' in block


def test_v060_background_resume_and_sync() -> None:
    source = _ui_source()
    assert "self.background_sync_timer = QTimer(self)" in source
    assert "def background_metadata_sync" in source
    assert "def _resume_saved_workflow" in source
    assert 'action="Чергу відновлено"' in source


def test_v060_user_facing_status_and_badges() -> None:
    source = _ui_source()
    assert '["Відео", "Назва", "Перегляди", "Стан", "Проблеми"]' in source
    assert '"Потрібно покращити"' in source
    assert '"Критично"' in source
    assert 'def _refresh_tab_badges' in source
    assert 'self._set_tab_badge(3, "Коментарі", comments)' in source


def test_v060_diagnostics_are_in_settings() -> None:
    source = _ui_source()
    assert 'self.settings_sections.addTab(diagnostics_page, "Діагностика")' in source
    assert 'def refresh_diagnostics_panel' in source
    assert 'def _open_diagnostics_log' in source
    assert 'refresh_diagnostics_btn = QPushButton("Оновити діагностику")' in source


def test_v060_guided_action_avoids_useless_extra_prep() -> None:
    source = _ui_source()
    start = source.index("    def _refresh_next_action_card")
    end = source.index("\n    def _run_guided_next_action", start)
    block = source[start:end]
    assert "elif ready_queue and safe_capacity <= 0:" in block
    assert "Нові архівні пакети зараз готувати не потрібно" in block
    assert 'self._guided_next_action = "comments"' in block
