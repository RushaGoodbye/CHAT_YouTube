from __future__ import annotations

import csv
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .config import (
    APP_NAME,
    DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
    DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT,
    DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES,
    DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT,
    DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
    DEFAULT_MAX_AUTO_REPLIES_PER_SCAN,
    DEFAULT_REPLY_TEMPLATES,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_NAS_PACKAGES_PATH,
    DEFAULT_NAS_TRANSCRIPTS_PATH,
    PACKAGE_BRIDGE_URL,
    PROFILE_LABELS,
    PROFILE_TARGETS,
    app_data_dir,
    normalize_nas_unc_path,
)
from .db import (
    commit_video_analytics,
    connect,
    database_integrity_cleanup,
    deep_review_counts,
    deep_review_state_map,
    get_optimization_draft,
    get_setting,
    log_action,
    recent_action_log,
    latest_metadata_snapshot,
    optimization_events,
    record_optimization_event,
    save_metadata_snapshot,
    save_optimization_draft,
    set_comment_status,
    set_deep_review_state,
    set_optimization_draft_status,
    set_setting,
    upsert_video_analytics,
)
from .archive_campaign import (
    archive_profile_stats,
    deep_review_candidates,
    export_deep_review_manifest,
    load_campaign_checkpoint,
    next_campaign_phase,
    reconcile_campaign_checkpoint,
    save_campaign_checkpoint,
)
from .metadata_audit import (
    audit,
    blocks_automatic_title_language_change,
    normalize_links,
    title_script_profile,
)
from .package_bridge import bridge_health, fetch_package, upload_transcript
from .free_tools import (
    DEFAULT_OLLAMA_MODEL,
    fetch_public_metadata,
    fetch_transcript,
    generate_comment_reply_local,
    generate_seo_package_local,
    load_google_trends_csv,
    load_google_trends_summary,
    probe_free_tools,
    transcript_sample_text,
    transcript_text,
)
from .recovery import (
    create_recovery_backup,
    prune_recovery_backups,
    read_recovery_manifest,
    restore_recovery_backup,
)
from .optimization import (
    archive_potential_score,
    compose_description,
    extract_chapters_from_description,
    is_safe_archive_candidate,
    needs_deep_review,
    priority_label,
    safe_description_fix,
    safe_description_needs_content_package,
    sanitize_imported_package_description,
    validate_chapters,
    validate_content_package,
)
from .service import (
    archive_priority_enabled,
    cleanup_stale_scheduled_rows,
    current_quota_day,
    manual_reply,
    quota_budget_status,
    reply_one_queued_safe_comment,
    scan_channel_comments,
    scan_comments,
    sync_specific_videos,
    sync_upcoming_live_broadcasts,
    sync_videos,
    today_auto_reply_count,
    today_reply_count,
    today_quota_units,
    today_quota_breakdown,
    record_quota_units,
    reconcile_local_video_title,
    quota_exhausted,
    mark_quota_exhausted,
    YOUTUBE_DAILY_QUOTA_DEFAULT,
    VIDEO_UPDATE_COST,
    COMMENT_REPLY_COST,
    QUOTA_RESERVE_DEFAULT,
    READ_REQUEST_COST,
    CAPTION_TRANSCRIPT_COST,
    SAFE_METADATA_ITEM_COST,
    reserve_safe_batch_capacity,
    reserve_safe_daily_batch_capacity,
    set_archive_priority_mode,
)
from .youtube_api import YouTubeClient
from .style import APP_STYLESHEET, MUTED, SUCCESS, WARNING, YOUTUBE_RED
from .updater import (
    UpdateInfo,
    check_for_update,
    download_update,
    prune_cached_updates,
)
from .vidiq_budget import (
    VIDIQ_MONTHLY_CREDITS_DEFAULT,
    VIDIQ_RESERVE_CREDITS_DEFAULT,
    budget_status as vidiq_budget_status,
    policy_summary as vidiq_policy_summary,
    set_limits as set_vidiq_limits,
    set_manual_usage as set_vidiq_manual_usage,
)

def _is_quota_exceeded_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return "quotaexceeded" in text or "quota exceeded" in text


def _validate_safe_update_fields(fields: set[str]) -> None:
    forbidden = sorted(set(fields) - {"description", "tags"})
    if forbidden:
        raise RuntimeError(
            "Безпечний режим може змінювати лише опис і теги відео. "
            "Назва та налаштування публікації заблоковані: "
            + ", ".join(forbidden)
        )


ISSUE_LABELS = {
    "old_links": "старі посилання",
    "missing_project_link": "немає посилання проєкту",
    "missing_donate_link": "немає посилання на донат",
    "thin_description": "закороткий опис",
    "no_chapters": "немає розділів",
    "too_many_hashtags": "забагато хештегів",
    "no_tags": "немає тегів",
    "latin_title_review": "англомовна назва - перевірити",
}

PRIVACY_LABELS = {
    "public": "публічне",
    "private": "приватне",
    "unlisted": "за посиланням",
}

COMMENT_CATEGORY_LABELS = {
    "review": "на перевірці",
    "thanks": "подяка",
    "links": "посилання",
    "donate": "донат",
    "schedule": "розклад",
}

COMMENT_STATUS_LABELS = {
    "new": "новий",
    "replied": "відповіли",
    "ignored": "проігноровано",
    "moderation_locked": "модерація YouTube",
}

def _issue_labels(issues: list[str]) -> str:
    return ", ".join(ISSUE_LABELS.get(item, item) for item in issues)


def _standard_hyphen(text: str) -> str:
    return str(text or "").replace("—", "-").replace("–", "-")


def _strip_timestamp_lines(text: str) -> str:
    """Remove chapter/timing lines from YouTube descriptions."""
    import re
    cleaned: list[str] = []
    pattern = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}\s+\S")
    for line in str(text or "").splitlines():
        if pattern.match(line):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned).strip()


class MetadataDialog(QDialog):
    def __init__(self, title: str, description: str, tags: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Метадані відео")
        self.resize(780, 620)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit(_standard_hyphen(title))
        self.description_edit = QPlainTextEdit(_standard_hyphen(description))
        self.tags_edit = QPlainTextEdit(_standard_hyphen(", ".join(tags)))
        form.addRow("Назва:", self.title_edit)
        form.addRow("Опис:", self.description_edit)
        form.addRow("Теги:", self.tags_edit)
        layout.addLayout(form)

        normalize_btn = QPushButton("Замінити старі посилання")
        normalize_btn.clicked.connect(self.normalize_description_links)
        layout.addWidget(normalize_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Зберегти")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def normalize_description_links(self) -> None:
        value = self.description_edit.toPlainText()
        self.description_edit.setPlainText(normalize_links(value))

    def values(self) -> tuple[str, str, list[str]]:
        tags = [
            item.strip()
            for item in self.tags_edit.toPlainText().replace("\n", ",").split(",")
            if item.strip()
        ]
        return (
            _standard_hyphen(self.title_edit.text().strip()),
            _standard_hyphen(self.description_edit.toPlainText().strip()),
            [_standard_hyphen(item) for item in tags],
        )

class ContentOptimizationDialog(QDialog):
    def __init__(
        self,
        title: str,
        description: str,
        chapters: str,
        tags: list[str],
        status: str,
        title_variants: list[str] | None = None,
        scheduled_publish_at: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Пакет оптимізації контенту")
        self.resize(980, 760)
        layout = QVBoxLayout(self)

        self.scheduled_publish_at = scheduled_publish_at
        if scheduled_publish_at:
            scheduled_note = QLabel(
                f"Запланований стрім · {scheduled_publish_at}\n"
                "Назву, опис і теги можна оптимізувати заздалегідь. "
                "Дата, час публікації та видимість не змінюються. "
                "Таймінги в опис не додаються."
            )
            scheduled_note.setWordWrap(True)
            layout.addWidget(scheduled_note)

        description = _strip_timestamp_lines(description)
        chapters = ""

        form = QFormLayout()
        self.title_edit = QLineEdit(_standard_hyphen(title))
        self.description_edit = QPlainTextEdit(_standard_hyphen(description))
        self.chapters_edit = QPlainTextEdit()
        self.chapters_edit.setPlainText("")
        self.chapters_edit.setPlaceholderText(
            "Вимкнено: таймінги в описах не використовуються"
        )
        self.chapters_edit.setEnabled(False)
        self.chapters_edit.setMaximumHeight(54)
        self.tags_edit = QPlainTextEdit(
            _standard_hyphen(", ".join(tags))
        )
        self.title_variants_edit = QPlainTextEdit(
            _standard_hyphen("\n".join(title_variants or []))
        )
        self.title_variants_edit.setPlaceholderText(
            "Варіант A - сильний конфлікт / цитата\n"
            "Варіант B - конфлікт + контекст\n"
            "Варіант C - сильний хук | ЧАТ РУЛЕТКА"
        )
        self.status_combo = QComboBox()
        self.status_combo.addItem("Чернетка", "draft")
        self.status_combo.addItem("Готово до застосування", "ready")
        self.status_combo.addItem("Застосовано", "applied")
        idx = self.status_combo.findData(status)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)

        self.title_edit.textEdited.connect(self._mark_applied_as_draft)
        self.description_edit.textChanged.connect(self._mark_applied_as_draft)
        self.chapters_edit.textChanged.connect(self._mark_applied_as_draft)
        self.tags_edit.textChanged.connect(self._mark_applied_as_draft)
        self.title_variants_edit.textChanged.connect(self._mark_applied_as_draft)

        form.addRow("Нова назва:", self.title_edit)
        form.addRow("Повний опис:", self.description_edit)
        form.addRow("Розділи (вимкнено):", self.chapters_edit)
        form.addRow("Теги:", self.tags_edit)
        form.addRow("A/B варіанти назви:", self.title_variants_edit)
        form.addRow("Статус:", self.status_combo)
        layout.addLayout(form)

        checks = QHBoxLayout()
        validate_btn = QPushButton("Розділи вимкнено")
        validate_btn.setEnabled(False)
        package_check_btn = QPushButton("Перевірити пакет")
        package_check_btn.clicked.connect(self.validate_package_now)
        checks.addWidget(validate_btn)
        checks.addWidget(package_check_btn)
        checks.addStretch()
        layout.addLayout(checks)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Зберегти")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _mark_applied_as_draft(self, *_args) -> None:
        if self.status_combo.currentData() == "applied":
            draft_index = self.status_combo.findData("draft")
            if draft_index >= 0:
                self.status_combo.setCurrentIndex(draft_index)

    def validate_chapters_now(self) -> None:
        ok, message = validate_chapters(self.chapters_edit.toPlainText())
        if ok:
            QMessageBox.information(self, APP_NAME, "Розділи коректні.")
        else:
            QMessageBox.warning(self, APP_NAME, message)

    def validate_package_now(self) -> None:
        (
            title,
            description,
            chapters,
            tags,
            _status,
            title_variants,
        ) = self.values()
        check = validate_content_package(
            title,
            description,
            chapters,
            tags,
            title_variants,
        )

        lines: list[str] = []
        if check.ready:
            lines.append("Технічна перевірка: OK")
        else:
            lines.append("Технічна перевірка: є помилки")

        if check.errors:
            lines.append("\nПОМИЛКИ:")
            lines.extend(f"- {item}" for item in check.errors)
        if check.warnings:
            lines.append("\nРЕКОМЕНДАЦІЇ:")
            lines.extend(f"- {item}" for item in check.warnings)
        if not check.errors and not check.warnings:
            lines.append("\nПакет повністю готовий до застосування.")

        message = "\n".join(lines)
        if check.ready:
            QMessageBox.information(self, "Перевірка пакета", message)
        else:
            QMessageBox.warning(self, "Перевірка пакета", message)

    def _accept_checked(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, "Назва не може бути порожньою.")
            return
        ok, message = validate_chapters(self.chapters_edit.toPlainText())
        if not ok:
            QMessageBox.warning(self, APP_NAME, message)
            return

        if self.status_combo.currentData() == "ready":
            (
                title,
                description,
                chapters,
                tags,
                _status,
                title_variants,
            ) = self.values()
            check = validate_content_package(
                title,
                description,
                chapters,
                tags,
                title_variants,
            )
            if check.errors:
                QMessageBox.warning(
                    self,
                    "Пакет не готовий",
                    "\n".join(f"- {item}" for item in check.errors),
                )
                return

        self.accept()

    def values(self) -> tuple[str, str, str, list[str], str, list[str]]:
        tags = [
            item.strip()
            for item in self.tags_edit.toPlainText().replace("\n", ",").split(",")
            if item.strip()
        ]
        title_variants = [
            item.strip()
            for item in self.title_variants_edit.toPlainText().splitlines()
            if item.strip()
        ][:3]
        return (
            _standard_hyphen(self.title_edit.text().strip()),
            _strip_timestamp_lines(
                _standard_hyphen(self.description_edit.toPlainText().strip())
            ),
            "",
            [_standard_hyphen(item) for item in tags],
            str(self.status_combo.currentData()),
            [_standard_hyphen(item) for item in title_variants],
        )


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(92)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.note_label = QLabel("")
        self.note_label.setProperty("muted", True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.note_label)

    def set_value(self, value: str, note: str = "") -> None:
        self.value_label.setText(value)
        self.note_label.setText(note)


class FrozenColumnsTable(QTableWidget):
    """QTableWidget with a small frozen mirror for key identity columns."""

    def __init__(
        self,
        rows: int,
        columns: int,
        *,
        frozen_columns: tuple[int, ...],
        parent=None,
    ) -> None:
        super().__init__(rows, columns, parent)
        self._frozen_columns = tuple(sorted(set(int(x) for x in frozen_columns)))
        self.frozen_view = QTableView(self)
        self.frozen_view.setModel(self.model())
        self.frozen_view.setSelectionModel(self.selectionModel())
        self.frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.frozen_view.verticalHeader().setVisible(False)
        self.frozen_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.frozen_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.frozen_view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.frozen_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.frozen_view.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        for column in range(columns):
            self.frozen_view.setColumnHidden(
                column,
                column not in self._frozen_columns,
            )
        self.verticalScrollBar().valueChanged.connect(
            self.frozen_view.verticalScrollBar().setValue
        )
        self.frozen_view.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue
        )
        self.horizontalHeader().sectionResized.connect(
            lambda *_args: self.sync_frozen_columns()
        )
        self.frozen_view.show()

    def sync_frozen_columns(self) -> None:
        width = self.frameWidth()
        for column in self._frozen_columns:
            column_width = self.columnWidth(column)
            self.frozen_view.setColumnWidth(column, column_width)
            width += column_width
        self.frozen_view.verticalHeader().setDefaultSectionSize(
            self.verticalHeader().defaultSectionSize()
        )
        self.frozen_view.setGeometry(
            self.frameWidth(),
            self.frameWidth(),
            width,
            self.viewport().height() + self.horizontalHeader().height(),
        )
        self.frozen_view.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.sync_frozen_columns()


class ProgressMetricCard(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("QueueCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(5)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("MetricValue")
        self.note_label = QLabel("")
        self.note_label.setProperty("muted", True)
        self.note_label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.bar)
        layout.addWidget(self.note_label)

    def set_value(
        self,
        value: str,
        *,
        percent: int = 0,
        note: str = "",
        role: str = "",
    ) -> None:
        self.value_label.setText(value)
        self.bar.setValue(max(0, min(100, int(percent))))
        self.bar.setProperty("role", role)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.note_label.setText(note)


class LocalToolWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, func, parent=None) -> None:
        super().__init__(parent)
        self.func = func

    def run(self) -> None:
        try:
            self.succeeded.emit(self.func())
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.data_dir = app_data_dir()
        self.conn = connect(self.data_dir / "rg_youtube_control.db")
        self.current_profile = get_setting(self.conn, "current_profile", "main")
        self.client = YouTubeClient(profile=self.current_profile)
        self.setStyleSheet(APP_STYLESHEET)
        self.resize(1500, 920)
        self.setMinimumSize(1180, 760)

        root = QWidget()
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self._build_top_bar(shell)
        self._build_metrics(shell)

        self.tabs = QTabWidget()
        shell.addWidget(self.tabs, 1)
        self._build_task_center_tab()
        self._build_videos_tab()
        self._build_optimization_tab()
        self._build_comments_tab()
        self._build_analytics_tab()
        self._build_results_tab()
        self._build_log_tab()
        self._build_settings_tab()
        self._build_archive_dashboard_tab()
        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        self._on_main_tab_changed(self.tabs.currentIndex())

        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.background_scan_all_channels)
        self.scan_timer.timeout.connect(self.run_background_maintenance)
        self.scan_timer.start(DEFAULT_SCAN_MINUTES * 60 * 1000)

        self.dashboard_timer = QTimer(self)
        self.dashboard_timer.timeout.connect(self.update_dashboard)
        self.dashboard_timer.start(15 * 1000)

        self.statusBar().showMessage("СИСТЕМА ГОТОВА")
        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()
        self.reload_action_log()
        if hasattr(self, "optimization_density"):
            self._apply_table_density(
                self.optimization_table,
                self.optimization_density,
            )
        self._update_optimization_context_card()
        self.update_dashboard()
        self._refresh_channel_header()
        QTimer.singleShot(1200, self.recover_archive_campaign_state)
        QTimer.singleShot(2000, self.cleanup_cached_updates)
        QTimer.singleShot(3000, self.check_for_updates_silent)
        QTimer.singleShot(4500, self.sync_upcoming_streams_startup)
        QTimer.singleShot(6000, self.ensure_daily_recovery_backup)
        QTimer.singleShot(8000, self.check_quota_plan_ready)
        QTimer.singleShot(10000, self.run_background_maintenance)
        QTimer.singleShot(1500, self.refresh_free_tools_status)

    def _on_main_tab_changed(self, _index: int) -> None:
        if not hasattr(self, "metrics_wrapper"):
            return
        current = self.tabs.currentWidget() if hasattr(self, "tabs") else None
        hide_global_metrics = current in {
            getattr(self, "today_page", None),
            getattr(self, "archive_page", None),
        }
        self.metrics_wrapper.setVisible(not hide_global_metrics)

    def _build_top_bar(self, parent_layout: QVBoxLayout) -> None:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        badge = QLabel("RG")
        badge.setObjectName("AppBadge")
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Керування YouTube")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Сьогодні · відео · оптимізація · архів · результати")
        subtitle.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.header_profile_combo = QComboBox()
        self.header_profile_combo.setMinimumWidth(240)
        for profile_key, label in PROFILE_LABELS.items():
            self.header_profile_combo.addItem(label, profile_key)
        idx = self.header_profile_combo.findData(self.current_profile)
        if idx >= 0:
            self.header_profile_combo.setCurrentIndex(idx)
        self.header_profile_combo.currentIndexChanged.connect(
            self.switch_profile_from_header
        )

        self.header_channel_state = QLabel()
        self.header_channel_state.setObjectName("ChannelState")

        sync_btn = QPushButton("Синхронізувати")
        sync_btn.clicked.connect(self.sync_video_list)

        layout.addWidget(badge)
        layout.addLayout(title_box)
        layout.addStretch()
        layout.addWidget(QLabel("Канал:"))
        layout.addWidget(self.header_profile_combo)
        layout.addWidget(self.header_channel_state)
        layout.addWidget(sync_btn)
        parent_layout.addWidget(bar)

    def _build_metrics(self, parent_layout: QVBoxLayout) -> None:
        wrapper = QWidget()
        self.metrics_wrapper = wrapper
        grid = QGridLayout(wrapper)
        grid.setContentsMargins(18, 12, 18, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.metric_videos = MetricCard("Відео в базі")
        self.metric_scheduled = MetricCard("Заплановано")
        self.metric_attention = MetricCard("Потребує уваги")
        self.metric_comments = MetricCard("Коментарі в черзі")

        grid.addWidget(self.metric_videos, 0, 0)
        grid.addWidget(self.metric_scheduled, 0, 1)
        grid.addWidget(self.metric_attention, 0, 2)
        grid.addWidget(self.metric_comments, 0, 3)
        parent_layout.addWidget(wrapper)

    def _configure_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.setShowGrid(False)

    def _refresh_channel_header(self) -> None:
        title = get_setting(
            self.conn, f"channel_title_{self.current_profile}", ""
        )
        channel_id = get_setting(
            self.conn, f"channel_id_{self.current_profile}", ""
        )
        if title and channel_id:
            short_id = channel_id[:8] + "…" + channel_id[-5:]
            self.header_channel_state.setText(f"● {title} · {short_id}")
            self.header_channel_state.setStyleSheet(
                f"color: {SUCCESS};"
            )
        else:
            self.header_channel_state.setText("○ не підключено")
            self.header_channel_state.setStyleSheet(
                f"color: {WARNING};"
            )

    def update_dashboard(self) -> None:
        if not hasattr(self, "metric_videos"):
            return
        profile = self.current_profile
        total = self.conn.execute(
            "SELECT COUNT(*) AS n FROM videos WHERE profile=?",
            (profile,),
        ).fetchone()["n"]
        scheduled = self.conn.execute(
            """SELECT COUNT(*) AS n FROM videos
               WHERE profile=? AND scheduled_publish_at IS NOT NULL""",
            (profile,),
        ).fetchone()["n"]
        rows = self.conn.execute(
            "SELECT audit_json FROM videos WHERE profile=?",
            (profile,),
        ).fetchall()
        attention = 0
        for row in rows:
            try:
                data = json.loads(row["audit_json"] or "{}")
                if int(data.get("score") or 0) < 100:
                    attention += 1
            except Exception:
                attention += 1
        queued = self.conn.execute(
            """SELECT COUNT(*) AS n
               FROM comments c
               JOIN videos v ON v.video_id=c.video_id
               WHERE v.profile=? AND c.status='new'""",
            (profile,),
        ).fetchone()["n"]

        self.metric_videos.set_value(str(total), PROFILE_LABELS[self.current_profile])
        self.metric_scheduled.set_value(str(scheduled), "майбутні публікації")
        self.metric_attention.set_value(str(attention), "Аудит < 100")
        self.metric_comments.set_value(str(queued), "нові / не оброблені")
        self.refresh_youtube_quota_label()
        self.update_task_center()

    def switch_profile_from_header(self, _index: int) -> None:
        profile = self.header_profile_combo.currentData()
        if not profile:
            return
        self._activate_profile(str(profile))

    def _activate_profile(self, profile: str) -> None:
        if profile not in PROFILE_TARGETS:
            return
        self.current_profile = profile
        set_setting(self.conn, "current_profile", self.current_profile)
        self.client = YouTubeClient(profile=self.current_profile)

        if hasattr(self, "header_profile_combo"):
            self.header_profile_combo.blockSignals(True)
            idx = self.header_profile_combo.findData(profile)
            if idx >= 0:
                self.header_profile_combo.setCurrentIndex(idx)
            self.header_profile_combo.blockSignals(False)

        if hasattr(self, "profile_combo"):
            self.profile_combo.blockSignals(True)
            idx = self.profile_combo.findData(profile)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
            self.profile_combo.blockSignals(False)

        if hasattr(self, "auto_box"):
            default_auto = (
                get_setting(self.conn, "auto_reply_enabled", "0")
                if profile == "main"
                else "0"
            )
            enabled = get_setting(
                self.conn,
                f"auto_reply_enabled_{profile}",
                default_auto,
            ) == "1"
            self.auto_box.blockSignals(True)
            self.auto_box.setChecked(enabled)
            self.auto_box.blockSignals(False)

        if hasattr(self, "safe_autopilot_box"):
            self.safe_autopilot_box.blockSignals(True)
            self.safe_autopilot_box.setChecked(
                get_setting(
                    self.conn,
                    f"safe_metadata_autopilot_{profile}",
                    "0",
                ) == "1"
            )
            self.safe_autopilot_box.blockSignals(False)

        if hasattr(self, "autopilot_interval_spin"):
            for control, key, default_value in (
                (
                    self.autopilot_interval_spin,
                    f"safe_autopilot_interval_minutes_{profile}",
                    DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES,
                ),
                (
                    self.autopilot_daily_spin,
                    f"safe_autopilot_daily_limit_{profile}",
                    DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT,
                ),
            ):
                control.blockSignals(True)
                control.setValue(
                    int(get_setting(self.conn, key, str(default_value)))
                )
                control.blockSignals(False)

        if hasattr(self, "archive_priority_box"):
            self.archive_priority_box.blockSignals(True)
            self.archive_priority_box.setChecked(
                archive_priority_enabled(self.conn)
            )
            self.archive_priority_box.blockSignals(False)
            self._refresh_archive_priority_controls()

        if hasattr(self, "daily_limit_spin"):
            controls = (
                (
                    self.daily_limit_spin,
                    f"auto_reply_daily_limit_{profile}",
                    "auto_reply_daily_limit",
                    DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
                ),
                (
                    self.scan_limit_spin,
                    f"auto_reply_scan_limit_{profile}",
                    "auto_reply_scan_limit",
                    DEFAULT_MAX_AUTO_REPLIES_PER_SCAN,
                ),
                (
                    self.age_limit_spin,
                    f"auto_reply_max_age_hours_{profile}",
                    "auto_reply_max_age_hours",
                    DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
                ),
            )
            for control, profile_key, legacy_key, default_value in controls:
                control.blockSignals(True)
                control.setValue(
                    int(
                        get_setting(
                            self.conn,
                            profile_key,
                            get_setting(self.conn, legacy_key, str(default_value)),
                        )
                    )
                )
                control.blockSignals(False)

        if hasattr(self, "reply_template_edits"):
            for category, (_label, edit) in self.reply_template_edits.items():
                edit.blockSignals(True)
                edit.setText(
                    get_setting(
                        self.conn,
                        f"reply_template_{profile}_{category}",
                        get_setting(
                            self.conn,
                            f"reply_template_{category}",
                            DEFAULT_REPLY_TEMPLATES[category],
                        ),
                    )
                )
                edit.setCursorPosition(0)
                edit.blockSignals(False)

        if hasattr(self, "channel_label"):
            title = get_setting(self.conn, f"channel_title_{profile}", "")
            channel_id = get_setting(self.conn, f"channel_id_{profile}", "")
            self.channel_label.setText(
                f"YouTube: {title} · {channel_id}"
                if title and channel_id
                else "YouTube: не підключено"
            )

        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()
        self.reload_action_log()
        self.update_dashboard()
        self._refresh_channel_header()
        self.statusBar().showMessage(
            f"Активний канал: {PROFILE_LABELS[self.current_profile]}"
        )

    def _build_task_center_tab(self) -> None:
        page = QWidget()
        self.today_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Сьогодні")
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            "Один екран: що відбувається зараз, що потребує рішення і що буде далі."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("muted", True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        zero_quota_btn = QPushButton("Підготувати · 0 квоти")
        zero_quota_btn.clicked.connect(self.prepare_zero_quota_batch)
        planner_btn = QPushButton("План квоти")
        planner_btn.clicked.connect(self.show_quota_planner)
        scheduled_btn = QPushButton("Заплановані")
        scheduled_btn.clicked.connect(self.show_scheduled_center)
        archive_btn = QPushButton("Архів")
        archive_btn.clicked.connect(self._open_archive_mode)
        for button in (zero_quota_btn, planner_btn, scheduled_btn, archive_btn):
            header.addWidget(button)
        layout.addLayout(header)

        health = QFrame()
        health.setObjectName("HealthStrip")
        health_layout = QHBoxLayout(health)
        health_layout.setContentsMargins(12, 8, 12, 8)
        health_layout.setSpacing(8)
        self.health_labels = {}
        for key, label in (
            ("youtube", "YouTube"),
            ("nas", "NAS"),
            ("ollama", "Ollama"),
            ("transcript", "Transcript"),
            ("vidiq", "vidIQ"),
            ("api", "API"),
        ):
            pill = QLabel(f"{label} · —")
            pill.setObjectName("StatusWork")
            self.health_labels[key] = pill
            health_layout.addWidget(pill)
        health_layout.addStretch()
        layout.addWidget(health)

        process = QFrame()
        process.setObjectName("ProcessStrip")
        process_layout = QVBoxLayout(process)
        process_layout.setContentsMargins(14, 10, 14, 10)
        process_top = QHBoxLayout()
        self.process_title = QLabel("Система готова")
        self.process_title.setObjectName("SectionTitle")
        self.process_stage = QLabel("очікування")
        self.process_stage.setObjectName("StatusGood")
        self.process_eta = QLabel("")
        self.process_eta.setProperty("muted", True)
        process_top.addWidget(self.process_title)
        process_top.addWidget(self.process_stage)
        process_top.addStretch()
        process_top.addWidget(self.process_eta)
        self.process_progress = QProgressBar()
        self.process_progress.setRange(0, 100)
        self.process_progress.setValue(0)
        self.process_progress.setTextVisible(False)
        process_layout.addLayout(process_top)
        process_layout.addWidget(self.process_progress)
        layout.addWidget(process)

        today_stream = QFrame()
        today_stream.setObjectName("QueueCard")
        today_stream_layout = QVBoxLayout(today_stream)
        today_stream_layout.setContentsMargins(14, 11, 14, 11)
        today_stream_layout.setSpacing(7)

        today_stream_head = QHBoxLayout()
        today_stream_caption = QLabel("Сьогоднішній стрім")
        today_stream_caption.setObjectName("SectionTitle")
        self.today_stream_state = QLabel("пошук...")
        self.today_stream_state.setObjectName("StatusWork")
        today_stream_head.addWidget(today_stream_caption)
        today_stream_head.addWidget(self.today_stream_state)
        today_stream_head.addStretch()
        today_stream_layout.addLayout(today_stream_head)

        self.today_stream_title = QLabel("Перевіряю заплановані ефіри...")
        self.today_stream_title.setWordWrap(True)
        self.today_stream_title.setObjectName("MetricValue")
        self.today_stream_meta = QLabel("")
        self.today_stream_meta.setWordWrap(True)
        self.today_stream_meta.setProperty("muted", True)
        today_stream_layout.addWidget(self.today_stream_title)
        today_stream_layout.addWidget(self.today_stream_meta)

        today_stream_actions = QHBoxLayout()
        self.today_stream_optimize_btn = QPushButton("Оптимізувати")
        self.today_stream_optimize_btn.setProperty("role", "primary")
        self.today_stream_optimize_btn.clicked.connect(
            self.open_today_stream_optimization
        )
        today_stream_sync_btn = QPushButton("Синхронізувати")
        today_stream_sync_btn.clicked.connect(self.sync_upcoming_streams_startup)
        today_stream_all_btn = QPushButton("Усі заплановані")
        today_stream_all_btn.clicked.connect(self.show_scheduled_center)
        today_stream_actions.addWidget(self.today_stream_optimize_btn)
        today_stream_actions.addWidget(today_stream_sync_btn)
        today_stream_actions.addWidget(today_stream_all_btn)
        today_stream_actions.addStretch()
        today_stream_layout.addLayout(today_stream_actions)
        layout.addWidget(today_stream)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.center_scheduled = MetricCard("Заплановані")
        self.center_prepared = MetricCard("Готові пакети")
        self.center_comments = MetricCard("Коментарі")
        self.center_results = MetricCard("Контроль 7/28/90")
        self.center_quota = ProgressMetricCard("YouTube API")
        self.center_vidiq = ProgressMetricCard("vidIQ · AIR Boost")
        grid.addWidget(self.center_scheduled, 0, 0)
        grid.addWidget(self.center_prepared, 0, 1)
        grid.addWidget(self.center_comments, 0, 2)
        grid.addWidget(self.center_results, 0, 3)
        grid.addWidget(self.center_quota, 1, 0, 1, 2)
        grid.addWidget(self.center_vidiq, 1, 2, 1, 2)
        layout.addLayout(grid)

        pipeline = QFrame()
        pipeline.setObjectName("QueueCard")
        pipeline_layout = QVBoxLayout(pipeline)
        pipeline_title = QLabel("Конвеєр вибраного відео")
        pipeline_title.setObjectName("SectionTitle")
        self.pipeline_label = QLabel(
            "Аналіз  →  Транскрипт  →  SEO  →  Перевірка  →  Готово  →  YouTube  →  Контроль"
        )
        self.pipeline_label.setWordWrap(True)
        self.pipeline_label.setProperty("muted", True)
        pipeline_layout.addWidget(pipeline_title)
        pipeline_layout.addWidget(self.pipeline_label)
        layout.addWidget(pipeline)

        lower = QHBoxLayout()

        archive_card = QFrame()
        archive_card.setObjectName("ArchiveCard")
        archive_layout = QVBoxLayout(archive_card)
        archive_title = QLabel("Архівна кампанія")
        archive_title.setObjectName("SectionTitle")
        self.archive_today_value = QLabel("—")
        self.archive_today_value.setObjectName("MetricValue")
        self.archive_today_bar = QProgressBar()
        self.archive_today_bar.setRange(0, 100)
        self.archive_today_bar.setValue(0)
        self.archive_today_bar.setProperty("role", "success")
        self.archive_today_note = QLabel("")
        self.archive_today_note.setWordWrap(True)
        self.archive_today_note.setProperty("muted", True)
        archive_layout.addWidget(archive_title)
        archive_layout.addWidget(self.archive_today_value)
        archive_layout.addWidget(self.archive_today_bar)
        archive_layout.addWidget(self.archive_today_note)
        open_archive = QPushButton("Відкрити кампанію")
        open_archive.clicked.connect(self.show_archive_campaign_center)
        archive_layout.addWidget(open_archive)
        lower.addWidget(archive_card, 1)

        activity_card = QFrame()
        activity_card.setObjectName("ActivityCard")
        activity_layout = QVBoxLayout(activity_card)
        activity_title = QHBoxLayout()
        activity_label = QLabel("Активність")
        activity_label.setObjectName("SectionTitle")
        activity_title.addWidget(activity_label)
        activity_title.addStretch()
        undo_btn = QPushButton("Відкотити останнє")
        undo_btn.clicked.connect(self.rollback_last_optimized_metadata)
        retry_btn = QPushButton("Повторити останню помилку")
        retry_btn.clicked.connect(self.retry_last_local_task)
        activity_title.addWidget(undo_btn)
        activity_title.addWidget(retry_btn)
        activity_layout.addLayout(activity_title)
        self.activity_list = QListWidget()
        self.activity_list.setObjectName("ActivityList")
        self.activity_list.setMaximumHeight(165)
        activity_layout.addWidget(self.activity_list)
        lower.addWidget(activity_card, 2)

        issues_card = QFrame()
        issues_card.setObjectName("ActivityCard")
        issues_layout = QVBoxLayout(issues_card)
        issues_title = QLabel("Проблеми")
        issues_title.setObjectName("SectionTitle")
        self.issue_list = QListWidget()
        self.issue_list.setObjectName("ActivityList")
        self.issue_list.setMaximumHeight(165)
        issues_layout.addWidget(issues_title)
        issues_layout.addWidget(self.issue_list)
        lower.addWidget(issues_card, 1)
        layout.addLayout(lower)

        self.tabs.addTab(page, "Сьогодні")


    def _today_scheduled_row(self):
        rows = self.conn.execute(
            """SELECT v.video_id,v.title,v.scheduled_publish_at,v.privacy_status,
                      d.status AS draft_status
               FROM videos v
               LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.profile=?
                 AND v.scheduled_publish_at IS NOT NULL
               ORDER BY v.scheduled_publish_at ASC""",
            (self.current_profile,),
        ).fetchall()
        local_today = datetime.now().astimezone().date()
        today_rows = []
        for row in rows:
            raw = str(row["scheduled_publish_at"] or "").strip()
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                if dt.date() == local_today:
                    today_rows.append((dt, row))
            except Exception:
                if raw[:10] == local_today.isoformat():
                    today_rows.append((datetime.max.replace(tzinfo=None), row))
        if not today_rows:
            return None
        today_rows.sort(key=lambda item: item[0].replace(tzinfo=None))
        return today_rows[0][1]

    def _refresh_today_stream_card(self) -> None:
        if not hasattr(self, "today_stream_title"):
            return
        row = self._today_scheduled_row()
        if row is None:
            self.today_stream_state.setText("НЕ ЗНАЙДЕНО")
            self.today_stream_state.setObjectName("StatusWarn")
            self.today_stream_title.setText("На сьогодні запланований стрім не знайдено")
            self.today_stream_meta.setText(
                "Натисніть «Синхронізувати», якщо ефір уже створений у YouTube Studio."
            )
            self.today_stream_optimize_btn.setEnabled(False)
        else:
            status = str(row["draft_status"] or "")
            status_text = {
                "ready": "ГОТОВО",
                "applied": "ЗАСТОСОВАНО",
                "draft": "ЧЕРНЕТКА",
            }.get(status, "ПОТРІБЕН ПАКЕТ")
            self.today_stream_state.setText(status_text)
            self.today_stream_state.setObjectName(
                "StatusGood" if status in {"ready", "applied"} else "StatusWarn"
            )
            self.today_stream_title.setText(str(row["title"] or "(без назви)"))
            when = str(row["scheduled_publish_at"] or "")[:16].replace("T", " ")
            privacy = PRIVACY_LABELS.get(
                str(row["privacy_status"] or ""),
                str(row["privacy_status"] or ""),
            )
            self.today_stream_meta.setText(
                f"{when} · {privacy} · ID {row['video_id']}"
            )
            self.today_stream_optimize_btn.setEnabled(True)
        self.today_stream_state.style().unpolish(self.today_stream_state)
        self.today_stream_state.style().polish(self.today_stream_state)

    def open_today_stream_optimization(self) -> None:
        row = self._today_scheduled_row()
        if row is None:
            QMessageBox.information(
                self,
                APP_NAME,
                "На сьогодні запланований стрім не знайдено. "
                "Синхронізуйте заплановані ефіри та повторіть.",
            )
            return

        video_id = str(row["video_id"])
        if hasattr(self, "optimization_filter"):
            index = self.optimization_filter.findData("scheduled")
            if index >= 0:
                self.optimization_filter.setCurrentIndex(index)
        self.reload_optimization_queue()
        self.tabs.setCurrentIndex(2)

        target_row = -1
        for table_row in range(self.optimization_table.rowCount()):
            item = self.optimization_table.item(table_row, 3)
            if item is None:
                continue
            item_video_id = (
                item.data(Qt.ItemDataRole.UserRole)
                or item.data(Qt.ItemDataRole.DisplayRole)
            )
            if str(item_video_id or "") == video_id:
                target_row = table_row
                break

        if target_row >= 0:
            self.optimization_table.selectRow(target_row)
            self.optimization_table.scrollToItem(
                self.optimization_table.item(target_row, 3)
            )
            self.edit_content_package()
            return

        QMessageBox.warning(
            self,
            APP_NAME,
            "Стрім знайдено, але його рядок не відображається в оптимізації. "
            "Відкрийте «Усі заплановані» та оновіть список.",
        )


    def update_task_center(self) -> None:
        if not hasattr(self, "center_scheduled"):
            return
        profile = self.current_profile
        scheduled = int(self.conn.execute(
            """SELECT COUNT(*) FROM videos
               WHERE profile=? AND scheduled_publish_at IS NOT NULL""",
            (profile,),
        ).fetchone()[0])
        queued = int(self.conn.execute(
            """SELECT COUNT(*) FROM comments c
               JOIN videos v ON v.video_id=c.video_id
               WHERE v.profile=? AND c.status='new'""",
            (profile,),
        ).fetchone()[0])
        ready = int(self.conn.execute(
            """SELECT COUNT(*) FROM optimization_drafts d
               JOIN videos v ON v.video_id=d.video_id
               WHERE v.profile=? AND d.status='ready'""",
            (profile,),
        ).fetchone()[0])

        events = optimization_events(self.conn, profile, limit=100)
        today = datetime.now(timezone.utc).date()
        waiting = 0
        for event in events:
            try:
                optimized = datetime.fromisoformat(
                    str(event["optimized_at"]).replace("Z", "+00:00")
                ).date()
            except Exception:
                continue
            if (today - optimized).days < 90:
                waiting += 1

        budget = quota_budget_status(self.conn)
        used = int(budget["used"])
        remaining = int(budget["remaining"])
        reserve = int(budget["reserve"])
        quota_percent = round(used / max(1, YOUTUBE_DAILY_QUOTA_DEFAULT) * 100)
        safe_capacity = max(0, (remaining - reserve) // max(1, SAFE_METADATA_ITEM_COST))
        self.center_quota.set_value(
            f"{remaining:,} / {YOUTUBE_DAILY_QUOTA_DEFAULT:,}",
            percent=quota_percent,
            note=(
                f"використано {used:,} · резерв {reserve:,} · "
                f"≈{safe_capacity} безпечних оновлень"
            ),
            role="danger" if bool(budget["exhausted"]) else "warning" if quota_percent >= 75 else "",
        )

        vidiq = vidiq_budget_status(self.conn)
        vidiq_used_pct = round(
            int(vidiq.used) / max(1, int(vidiq.limit)) * 100
        )
        self.center_vidiq.set_value(
            f"{vidiq.remaining:,} / {vidiq.limit:,}",
            percent=vidiq_used_pct,
            note=(
                f"використано {vidiq.used:,} · резерв {vidiq.reserve:,} · "
                f"поповнення {vidiq.reset_at or '—'}"
            ),
            role="warning" if vidiq_used_pct >= 75 else "",
        )

        self._refresh_today_stream_card()
        self.center_scheduled.set_value(str(scheduled), "майбутні публікації")
        self.center_prepared.set_value(str(ready), "перевірені та готові")
        self.center_comments.set_value(str(queued), "нові / не оброблені")
        self.center_results.set_value(str(waiting), "очікують контрольних точок")

        stats = self._archive_campaign_stats_cached()
        total_archive = sum(
            int(item.get("archive_total", 0)) for item in stats.values()
        )
        safe_remaining = sum(
            int(item.get("safe_remaining", 0)) for item in stats.values()
        )
        deep_remaining = sum(
            int(item.get("deep_remaining", 0)) for item in stats.values()
        )
        applied = sum(
            int(item.get("applied_packages", 0)) for item in stats.values()
        )
        completed = max(0, total_archive - safe_remaining - deep_remaining)
        archive_pct = round(completed / max(1, total_archive) * 100)
        self.archive_today_value.setText(
            f"{completed:,} / {total_archive:,} · {archive_pct}%"
        )
        self.archive_today_bar.setValue(archive_pct)
        daily_capacity = max(1, safe_capacity)
        remaining_total = safe_remaining + deep_remaining
        days = math.ceil(remaining_total / daily_capacity) if remaining_total else 0
        self.archive_today_note.setText(
            f"safe: {safe_remaining:,} · deep: {deep_remaining:,} · "
            f"застосовано: {applied:,} · прогноз ≈{days} дн."
        )

        channel_id = get_setting(self.conn, f"channel_id_{profile}", "")
        self._set_health_state("youtube", bool(channel_id), "YouTube")
        try:
            nas_ok = self._nas_path(
                "nas_transcripts_path",
                DEFAULT_NAS_TRANSCRIPTS_PATH,
            ).parent.exists()
        except Exception:
            nas_ok = False
        self._set_health_state("nas", nas_ok, "NAS")

        probes = getattr(self, "_free_tools_last_probe", {}) or {}
        self._set_health_state(
            "ollama",
            bool(probes.get("ollama", {}).get("available")),
            "Ollama",
        )
        self._set_health_state(
            "transcript",
            bool(probes.get("transcript", {}).get("available")),
            "Transcript",
        )
        self._set_health_state(
            "vidiq",
            vidiq.remaining > 0,
            "vidIQ",
            warning=vidiq.remaining <= vidiq.reserve,
        )
        self._set_health_state(
            "api",
            not bool(budget["exhausted"]),
            "API",
            warning=quota_percent >= 75 and not bool(budget["exhausted"]),
        )

        if hasattr(self, "activity_list"):
            self.activity_list.clear()
            rows = recent_action_log(self.conn, profile=profile, limit=8)
            if not rows:
                self.activity_list.addItem("Поки немає подій")
            else:
                for row in rows:
                    created = str(row["created_at"] or "")[11:16]
                    action = str(row["action"] or "")
                    details = str(row["details"] or "")
                    text = f"{created}  {action}"
                    if details:
                        text += f" · {details[:90]}"
                    self.activity_list.addItem(text)

        if hasattr(self, "issue_list"):
            self.issue_list.clear()
            rows = recent_action_log(self.conn, profile=profile, limit=80)
            bad = []
            for row in rows:
                hay = (
                    str(row["action"] or "") + " " + str(row["details"] or "")
                ).casefold()
                if any(key in hay for key in ("помил", "error", "failed", "403", "timeout")):
                    bad.append(row)
                if len(bad) >= 5:
                    break
            if not bad:
                self.issue_list.addItem("✓ Критичних проблем немає")
            else:
                for row in bad:
                    self.issue_list.addItem(
                        "⚠ " + str(row["action"] or "")[:55]
                    )


    def prepare_zero_quota_batch(self) -> None:
        """Prepare up to 10 metadata drafts without YouTube Data API calls."""
        profile = self.current_profile
        metadata_issues = {
            "thin_description",
            "no_tags",
            "old_links",
            "missing_project_link",
            "missing_donate_link",
        }
        rows = self.conn.execute(
            """SELECT v.video_id,v.title,v.views,v.audit_json,
                      d.status AS draft_status
               FROM videos v
               LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.profile=? AND v.privacy_status='public'
               ORDER BY v.views DESC""",
            (profile,),
        ).fetchall()

        candidates = []
        for row in rows:
            if str(row["draft_status"] or "") in {"ready", "applied"}:
                continue
            try:
                issues = set(
                    json.loads(row["audit_json"] or "{}").get("issues", [])
                )
            except Exception:
                issues = set()
            if metadata_issues.intersection(issues):
                candidates.append(str(row["video_id"]))
            if len(candidates) >= 10:
                break

        if not candidates:
            QMessageBox.information(
                self,
                APP_NAME,
                "Для 0-quota підготовки немає нових відео з безпечними "
                "проблемами опису, тегів або посилань.",
            )
            return

        self._set_process(
            "0-quota підготовка",
            "аналіз метаданих",
            percent=0,
            eta=f"{len(candidates)} відео · 0 квоти",
        )
        progress = QProgressDialog(
            "0-quota підготовка метаданих...",
            "Зупинити",
            0,
            len(candidates),
            self,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        prepared: list[str] = []
        blocked: list[str] = []
        for index, video_id in enumerate(candidates, start=1):
            if progress.wasCanceled():
                break
            progress.setLabelText(
                f"0-quota: {index}/{len(candidates)} · {video_id}"
            )
            self._set_process(
                "0-quota підготовка",
                f"{index}/{len(candidates)} · {video_id}",
                percent=round((index - 1) / max(1, len(candidates)) * 100),
                eta="локально · 0 квоти",
            )
            QApplication.processEvents()
            try:
                meta = fetch_public_metadata(video_id)
                title = _standard_hyphen(str(meta.get("title") or "").strip())
                description = _standard_hyphen(
                    str(meta.get("description") or "").strip()
                )
                current_tags = [
                    _standard_hyphen(str(item).strip()).lstrip("#")
                    for item in (meta.get("tags") or [])
                    if str(item).strip()
                ]

                safe_fix = safe_description_fix(description, title)
                description = safe_fix.after.strip()
                if len(description) < 250:
                    description = (
                        description.rstrip()
                        + "\n\nРАША ГУДБАЙ - розмови у форматі чат-рулетки. "
                        "У цьому відео обговорюємо тему, зазначену в назві, "
                        "та фіксуємо реальні діалоги без вигадування контексту."
                    ).strip()

                tags: list[str] = []
                seen: set[str] = set()

                def add_tag(value: str) -> None:
                    clean = _standard_hyphen(value).strip().lstrip("#")
                    key = clean.casefold()
                    if clean and key not in seen and len(clean) <= 60:
                        tags.append(clean)
                        seen.add(key)

                for item in current_tags:
                    add_tag(item)
                for item in (
                    "РАША ГУДБАЙ",
                    "чат рулетка",
                    "Россия",
                    "Украина",
                    "россияне",
                    "мнение россиян",
                    "опрос россиян",
                    "разговор с россиянами",
                ):
                    add_tag(item)
                stopwords = {
                    "чат", "рулетка", "раша", "гудбай", "russia",
                    "goodbye", "video", "стрим", "стрима", "стримов",
                    "shorts",
                }
                for token in re.findall(
                    r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ0-9]+",
                    title,
                ):
                    if len(token) >= 4 and token.casefold() not in stopwords:
                        add_tag(token)
                tags = tags[:15]

                check = validate_content_package(
                    title,
                    description,
                    "",
                    tags,
                    [],
                )
                hard_errors = list(check.errors)
                if len(tags) < 8:
                    hard_errors.append("Потрібно щонайменше 8 тегів.")

                status = "ready" if not hard_errors else "draft"
                save_optimization_draft(
                    self.conn,
                    video_id,
                    title,
                    description,
                    "",
                    tags,
                    status=status,
                    title_variants=[],
                )
                if status == "ready":
                    prepared.append(video_id)
                else:
                    blocked.append(video_id)
            except Exception as exc:
                blocked.append(video_id)
                log_action(
                    self.conn,
                    profile=profile,
                    category="0-quota",
                    action="Помилка підготовки",
                    details=f"{video_id}: {exc}",
                )
            progress.setValue(index)

        progress.close()

        raw_queue = get_setting(
            self.conn,
            f"prepared_safe_queue_{profile}",
            "[]",
        )
        try:
            queue_ids = [
                str(item) for item in (json.loads(raw_queue) or [])
                if str(item).strip()
            ]
        except Exception:
            queue_ids = []
        for video_id in prepared:
            if video_id not in queue_ids:
                queue_ids.append(video_id)
        set_setting(
            self.conn,
            f"prepared_safe_queue_{profile}",
            json.dumps(queue_ids, ensure_ascii=False),
        )
        log_action(
            self.conn,
            profile=profile,
            category="0-quota",
            action="Підготовлено пакет",
            details=(
                f"готово {len(prepared)}; чернеток/помилок {len(blocked)}; "
                "YouTube Data API: 0"
            ),
        )
        self.reload_optimization_queue()
        self.update_dashboard()
        self._set_process_idle("0-quota підготовка завершена")
        self._toast(
            f"✓ 0-quota: готово {len(prepared)} · "
            f"чернеток/помилок {len(blocked)} · API 0",
            7000,
        )

    def show_quota_planner(self) -> None:
        profile = self.current_profile
        prepared_count = len(self._prepared_queue_ids())
        scheduled_ready = int(
            self.conn.execute(
                """SELECT COUNT(*)
                   FROM videos v
                   JOIN optimization_drafts d ON d.video_id=v.video_id
                   WHERE v.profile=?
                     AND v.scheduled_publish_at IS NOT NULL
                     AND d.status='ready'""",
                (profile,),
            ).fetchone()[0]
        )
        budget = quota_budget_status(self.conn)

        dialog = QDialog(self)
        dialog.setWindowTitle("Планувальник квоти")
        dialog.resize(620, 430)
        layout = QVBoxLayout(dialog)

        summary = QLabel(
            f"Канал: {PROFILE_LABELS[profile]}\n"
            f"Квота: використано {budget['used']} / 10000 · "
            f"залишилось ≈{budget['remaining']} од. · "
            f"резерв: {budget['reserve']} од.\n"
            f"Підготовлена безпечна черга: {prepared_count}\n"
            f"Готових запланованих стрімів: {scheduled_ready}\n\n"
            "План зберігається локально. Після початку наступного квотного "
            "дня програма запропонує продовжити роботу. Коментарі з "
            "увімкненими автовідповідями відновляться автоматично."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        safe_spin = QSpinBox()
        safe_spin.setRange(0, min(50, max(0, prepared_count)))
        existing_safe = int(
            get_setting(
                self.conn,
                f"quota_plan_safe_count_{profile}",
                str(min(50, prepared_count)),
            )
            or 0
        )
        safe_spin.setValue(min(safe_spin.maximum(), existing_safe))
        layout.addWidget(QLabel("Безпечних відео на наступний квотний день"))
        layout.addWidget(safe_spin)

        scheduled_box = QCheckBox(
            "Нагадати про застосування готових запланованих стрімів"
        )
        scheduled_box.setChecked(
            get_setting(
                self.conn,
                f"quota_plan_scheduled_{profile}",
                "1" if scheduled_ready else "0",
            ) == "1"
        )
        layout.addWidget(scheduled_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Зберегти план")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        next_day = (
            datetime.fromisoformat(current_quota_day()) + timedelta(days=1)
        ).date().isoformat()
        safe_count = int(safe_spin.value())
        scheduled_flag = scheduled_box.isChecked() and scheduled_ready > 0
        set_setting(
            self.conn,
            f"quota_plan_safe_count_{profile}",
            str(safe_count),
        )
        set_setting(
            self.conn,
            f"quota_plan_scheduled_{profile}",
            "1" if scheduled_flag else "0",
        )
        set_setting(
            self.conn,
            f"quota_plan_target_day_{profile}",
            next_day,
        )
        set_setting(
            self.conn,
            f"quota_plan_armed_{profile}",
            "1" if safe_count > 0 or scheduled_flag else "0",
        )
        log_action(
            self.conn,
            profile=profile,
            category="квота",
            action="План на наступний день",
            details=(
                f"безпечних відео {safe_count}; "
                f"заплановані {'так' if scheduled_flag else 'ні'}; "
                f"ціль {next_day}"
            ),
        )
        self.reload_action_log()
        QMessageBox.information(
            self,
            "План збережено",
            f"План для {PROFILE_LABELS[profile]} збережено на квотний день "
            f"{next_day}.",
        )

    def check_quota_plan_ready(self) -> None:
        if quota_exhausted(self.conn):
            return
        current_day = current_quota_day()
        for profile in PROFILE_TARGETS:
            if get_setting(
                self.conn, f"quota_plan_armed_{profile}", "0"
            ) != "1":
                continue
            target_day = get_setting(
                self.conn, f"quota_plan_target_day_{profile}", ""
            )
            if target_day and current_day < target_day:
                continue
            prompted_key = f"quota_plan_prompted_{profile}_{current_day}"
            if get_setting(self.conn, prompted_key, "0") == "1":
                continue

            safe_count = int(
                get_setting(
                    self.conn,
                    f"quota_plan_safe_count_{profile}",
                    "0",
                )
                or 0
            )
            scheduled_flag = get_setting(
                self.conn,
                f"quota_plan_scheduled_{profile}",
                "0",
            ) == "1"
            set_setting(self.conn, prompted_key, "1")

            answer = QMessageBox.question(
                self,
                "Квота відновлена",
                f"{PROFILE_LABELS[profile]}\n\n"
                f"План готовий до продовження:\n"
                f"- безпечних відео: {safe_count}\n"
                f"- заплановані стріми: {'так' if scheduled_flag else 'ні'}\n\n"
                "Відкрити підготовлену роботу зараз?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                continue

            self._activate_profile(profile)
            set_setting(
                self.conn,
                f"quota_plan_armed_{profile}",
                "0",
            )
            if safe_count > 0 and hasattr(self, "optimization_filter"):
                index = self.optimization_filter.findData("prepared")
                if index >= 0:
                    self.optimization_filter.setCurrentIndex(index)
                self.tabs.setCurrentIndex(2)
            elif scheduled_flag:
                self.show_scheduled_center()
            break

    def _set_health_state(
        self,
        key: str,
        ok: bool,
        label: str,
        *,
        working: bool = False,
        warning: bool = False,
    ) -> None:
        if not hasattr(self, "health_labels") or key not in self.health_labels:
            return
        widget = self.health_labels[key]
        state_text = (
            "BUSY"
            if working
            else "LOW"
            if warning
            else "OK"
            if ok
            else "—"
        )
        widget.setText(f"{label} · {state_text}")
        widget.setObjectName(
            "StatusWork"
            if working
            else "StatusWarn"
            if warning
            else "StatusGood"
            if ok
            else "StatusBad"
        )
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _set_process(
        self,
        title: str,
        stage: str = "",
        *,
        percent: int | None = None,
        eta: str = "",
        error: bool = False,
    ) -> None:
        if not hasattr(self, "process_title"):
            return
        self.process_title.setText(title)
        self.process_stage.setText(stage or "очікування")
        self.process_stage.setObjectName(
            "StatusBad" if error else "StatusWork" if stage else "StatusGood"
        )
        self.process_stage.style().unpolish(self.process_stage)
        self.process_stage.style().polish(self.process_stage)
        self.process_eta.setText(eta)
        if percent is None:
            self.process_progress.setRange(0, 0)
        else:
            self.process_progress.setRange(0, 100)
            self.process_progress.setValue(max(0, min(100, int(percent))))

    def _set_process_idle(self, message: str = "Система готова") -> None:
        if not hasattr(self, "process_progress"):
            return
        self.process_progress.setRange(0, 100)
        self.process_progress.setValue(0)
        self._set_process(message, "", percent=0)

    def _toast(self, message: str, timeout_ms: int = 5500) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    def retry_last_local_task(self) -> None:
        task = getattr(self, "_last_failed_local_task", None)
        if not task:
            self._toast("Немає локальної помилки для повтору")
            return
        label, func, on_success = task
        self._run_local_tool(label, func, on_success)

    def _open_archive_mode(self) -> None:
        if hasattr(self, "archive_page"):
            self.tabs.setCurrentWidget(self.archive_page)
            self.refresh_archive_dashboard()
            return
        if hasattr(self, "optimization_filter"):
            idx = self.optimization_filter.findData("archive_top")
            if idx >= 0:
                self.optimization_filter.setCurrentIndex(idx)
        self.tabs.setCurrentIndex(2)

    def _build_archive_dashboard_tab(self) -> None:
        page = QWidget()
        self.archive_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Архів")
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            "Пріоритетна кампанія старих опублікованих відео. "
            "Спочатку локальна підготовка, потім контрольований запис у YouTube."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("muted", True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        head.addLayout(title_box)
        head.addStretch()
        campaign_btn = QPushButton("Центр кампанії")
        campaign_btn.setProperty("role", "primary")
        campaign_btn.clicked.connect(self.show_archive_campaign_center)
        top_btn = QPushButton("ТОП потенціал")
        top_btn.clicked.connect(self.refresh_archive_potential)
        head.addWidget(campaign_btn)
        head.addWidget(top_btn)
        layout.addLayout(head)

        grid = QGridLayout()
        self.archive_total_card = MetricCard("Всього в архіві")
        self.archive_done_card = MetricCard("Опрацьовано")
        self.archive_safe_card = MetricCard("Safe залишилось")
        self.archive_deep_card = MetricCard("Deep залишилось")
        self.archive_ready_card = MetricCard("Готові пакети")
        self.archive_eta_card = MetricCard("Прогноз")
        for idx, card in enumerate((
            self.archive_total_card,
            self.archive_done_card,
            self.archive_safe_card,
            self.archive_deep_card,
            self.archive_ready_card,
            self.archive_eta_card,
        )):
            grid.addWidget(card, idx // 3, idx % 3)
        layout.addLayout(grid)

        progress_card = QFrame()
        progress_card.setObjectName("ArchiveCard")
        pc = QVBoxLayout(progress_card)
        self.archive_main_progress = QProgressBar()
        self.archive_main_progress.setRange(0, 100)
        self.archive_main_progress.setProperty("role", "success")
        self.archive_main_progress_label = QLabel("")
        self.archive_main_progress_label.setObjectName("SectionTitle")
        self.archive_phase_label = QLabel("")
        self.archive_phase_label.setWordWrap(True)
        self.archive_phase_label.setProperty("muted", True)
        pc.addWidget(self.archive_main_progress_label)
        pc.addWidget(self.archive_main_progress)
        pc.addWidget(self.archive_phase_label)
        layout.addWidget(progress_card)

        priority_card = QFrame()
        priority_card.setObjectName("QueueCard")
        pl = QVBoxLayout(priority_card)
        pt = QLabel("Пріоритети")
        pt.setObjectName("SectionTitle")
        pl.addWidget(pt)
        pl.addWidget(QLabel(
            "A · високий потенціал - перші в черзі   |   "
            "B · середній - після A   |   C · низький - тільки коли є запас квоти"
        ))
        buttons = QHBoxLayout()
        for label, minimum in (("A · високий", 80), ("B · середній", 55), ("C · низький", 0)):
            btn = QPushButton(label)
            btn.clicked.connect(
                lambda _checked=False, m=minimum: self._open_archive_priority(m)
            )
            buttons.addWidget(btn)
        buttons.addStretch()
        pl.addLayout(buttons)
        layout.addWidget(priority_card)
        layout.addStretch()
        self.tabs.addTab(page, "Архів")
        self.refresh_archive_dashboard()

    def _open_archive_priority(self, minimum: int) -> None:
        set_setting(self.conn, "archive_ui_min_potential", str(int(minimum)))
        idx = self.optimization_filter.findData("archive_top")
        if idx >= 0:
            self.optimization_filter.setCurrentIndex(idx)
        self.tabs.setCurrentIndex(2)
        self.reload_optimization_queue()

    def refresh_archive_dashboard(self) -> None:
        if not hasattr(self, "archive_total_card"):
            return
        stats = self._archive_campaign_stats_cached()
        total = sum(int(v.get("archive_total", 0)) for v in stats.values())
        safe = sum(int(v.get("safe_remaining", 0)) for v in stats.values())
        deep = sum(int(v.get("deep_remaining", 0)) for v in stats.values())
        ready = sum(int(v.get("ready_packages", 0)) for v in stats.values())
        applied = sum(int(v.get("applied_packages", 0)) for v in stats.values())
        done = max(0, total - safe - deep)
        pct = round(done / max(1, total) * 100)
        budget = quota_budget_status(self.conn)
        capacity = reserve_safe_daily_batch_capacity(
            int(budget["spendable"]),
            max(0, safe + deep),
        )
        days = math.ceil((safe + deep) / max(1, capacity)) if safe + deep else 0
        phase, target = next_campaign_phase(stats)
        self.archive_total_card.set_value(f"{total:,}", "обидва канали")
        self.archive_done_card.set_value(f"{done:,}", f"{pct}% каталогу")
        self.archive_safe_card.set_value(f"{safe:,}", "лише безпечні зміни")
        self.archive_deep_card.set_value(f"{deep:,}", "ручний перегляд")
        self.archive_ready_card.set_value(f"{ready:,}", f"застосовано {applied:,}")
        self.archive_eta_card.set_value(
            f"≈{days} дн.",
            f"сьогодні ≈{capacity} відео без резерву",
        )
        self.archive_main_progress.setValue(pct)
        self.archive_main_progress_label.setText(
            f"Прогрес архівної кампанії · {pct}%"
        )
        phase_names = {
            "safe": "SAFE",
            "deep": "DEEP",
            "complete": "ЗАВЕРШЕНО",
        }
        self.archive_phase_label.setText(
            f"Поточний етап: {phase_names.get(phase, phase)} · "
            f"{PROFILE_LABELS.get(target, 'обидва канали') if target else 'обидва канали'}"
        )

    def _build_videos_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        connect_btn = QPushButton("Підключити YouTube")
        connect_btn.clicked.connect(self.connect_youtube)
        sync_btn = QPushButton("Синхронізувати")
        sync_btn.setProperty("role", "primary")
        sync_btn.clicked.connect(self.sync_video_list)
        sync_both_btn = QPushButton("Обидва канали")
        sync_both_btn.clicked.connect(self.sync_both_channels)
        edit_btn = QPushButton("Редагувати")
        edit_btn.clicked.connect(self.edit_selected_video)

        self.video_search = QLineEdit()
        self.video_search.setPlaceholderText("Пошук за назвою або Video ID")
        self.video_search.setClearButtonEnabled(True)
        self.video_search.setMinimumWidth(280)
        self.video_search.textChanged.connect(self.reload_videos)

        self.video_density = QComboBox()
        self.video_density.addItem("Компактно", 28)
        self.video_density.addItem("Комфортно", 34)
        self.video_density.addItem("Крупно", 42)
        self.video_density.setCurrentIndex(1)
        self.video_density.currentIndexChanged.connect(
            lambda _i: self._apply_table_density(self.video_table, self.video_density)
        )

        for button in (connect_btn, sync_btn, sync_both_btn, edit_btn):
            controls.addWidget(button)
        controls.addSpacing(12)
        controls.addWidget(self.video_search, 1)
        controls.addWidget(QLabel("Щільність:"))
        controls.addWidget(self.video_density)

        self.video_table = FrozenColumnsTable(
            0,
            5,
            frozen_columns=(0, 1),
        )
        self.video_table.setHorizontalHeaderLabels(
            ["Відео", "Назва", "Перегляди", "Аудит", "Проблеми"]
        )
        self.video_table.horizontalHeader().setStretchLastSection(True)
        for column, width in {0: 120, 1: 420, 2: 105, 3: 80, 4: 320}.items():
            self.video_table.setColumnWidth(column, width)
        self.video_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._configure_table(self.video_table)
        self.video_table.itemSelectionChanged.connect(
            self._update_video_context_card
        )

        context = QFrame()
        context.setObjectName("ContextCard")
        cx = QHBoxLayout(context)
        cx.setContentsMargins(14, 10, 14, 10)
        title_box = QVBoxLayout()
        self.video_context_title = QLabel("Виберіть відео")
        self.video_context_title.setObjectName("StickyVideoTitle")
        self.video_context_title.setWordWrap(True)
        self.video_context_note = QLabel(
            "Назва та Video ID залишаються тут видимими навіть при горизонтальній прокрутці."
        )
        self.video_context_note.setProperty("muted", True)
        self.video_context_note.setWordWrap(True)
        title_box.addWidget(self.video_context_title)
        title_box.addWidget(self.video_context_note)
        cx.addLayout(title_box, 1)
        open_opt = QPushButton("До оптимізації")
        open_opt.clicked.connect(self._open_selected_video_in_optimization)
        cx.addWidget(open_opt)

        layout.addLayout(controls)
        layout.addWidget(self.video_table, 1)
        layout.addWidget(context)
        self.tabs.addTab(page, "Відео")


    def _apply_table_density(
        self,
        table: QTableWidget,
        combo: QComboBox,
    ) -> None:
        value = int(combo.currentData() or 34)
        table.verticalHeader().setDefaultSectionSize(value)
        for row in range(table.rowCount()):
            table.setRowHeight(row, value)
        sync_frozen = getattr(table, "sync_frozen_columns", None)
        if callable(sync_frozen):
            sync_frozen()

    def _selected_video_row_id(self) -> str:
        if not hasattr(self, "video_table"):
            return ""
        rows = self.video_table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.video_table.item(rows[0].row(), 0)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "")

    def _update_video_context_card(self) -> None:
        if not hasattr(self, "video_context_title"):
            return
        video_id = self._selected_video_row_id()
        if not video_id:
            self.video_context_title.setText("Виберіть відео")
            self.video_context_note.setText(
                "Назва та Video ID залишаються тут видимими навіть при горизонтальній прокрутці."
            )
            return
        row = self.conn.execute(
            """SELECT title,views,audit_json,published_at
               FROM videos WHERE video_id=?""",
            (video_id,),
        ).fetchone()
        if row is None:
            return
        try:
            audit_data = json.loads(row["audit_json"] or "{}")
        except Exception:
            audit_data = {}
        score = int(audit_data.get("score") or 0)
        issues = _issue_labels(list(audit_data.get("issues", []))) or "критичних проблем немає"
        self.video_context_title.setText(str(row["title"] or video_id))
        self.video_context_note.setText(
            f"{video_id} · {int(row['views'] or 0):,} переглядів · "
            f"аудит {score} · {issues}"
        )

    def _open_selected_video_in_optimization(self) -> None:
        video_id = self._selected_video_row_id()
        self.tabs.setCurrentIndex(2)
        if hasattr(self, "optimization_search"):
            self.optimization_search.setText(video_id)
        self.reload_optimization_queue()

    def _build_optimization_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        toolbar = QHBoxLayout()
        sync_all_btn = QPushButton("Синхронізувати")
        sync_all_btn.clicked.connect(self.sync_full_archive)
        refresh_btn = QPushButton("Оновити")
        refresh_btn.clicked.connect(self.reload_optimization_queue)

        self.optimization_search = QLineEdit()
        self.optimization_search.setPlaceholderText("Пошук: назва, Video ID, проблема")
        self.optimization_search.setClearButtonEnabled(True)
        self.optimization_search.setMinimumWidth(260)
        self.optimization_search.textChanged.connect(self.reload_optimization_queue)

        self.optimization_filter = QComboBox()
        self.optimization_filter.addItem("Усі відео", "all")
        self.optimization_filter.addItem("Лише заплановані", "scheduled")
        self.optimization_filter.addItem("Архів", "archive")
        self.optimization_filter.addItem("Архів: ТОП потенціал", "archive_top")
        self.optimization_filter.addItem("Підготовлена черга", "prepared")
        self.optimization_filter.addItem("Англомовні назви", "latin_titles")
        self.optimization_filter.addItem("Глибока оптимізація", "deep_review")
        self.optimization_filter.currentIndexChanged.connect(
            self.reload_optimization_queue
        )

        self.optimization_status_filter = QComboBox()
        self.optimization_status_filter.addItem("Усі статуси", "all")
        self.optimization_status_filter.addItem("Потрібна увага", "needs")
        self.optimization_status_filter.addItem("Чернетки", "draft")
        self.optimization_status_filter.addItem("Готово", "ready")
        self.optimization_status_filter.addItem("Застосовано", "applied")
        self.optimization_status_filter.addItem("Без тегів", "no_tags")
        self.optimization_status_filter.addItem("Низький CTR", "low_ctr")
        self.optimization_status_filter.currentIndexChanged.connect(
            self.reload_optimization_queue
        )

        self.optimization_density = QComboBox()
        self.optimization_density.addItem("Компактно", 28)
        self.optimization_density.addItem("Комфортно", 34)
        self.optimization_density.addItem("Крупно", 42)
        self.optimization_density.setCurrentIndex(1)
        self.optimization_density.currentIndexChanged.connect(
            lambda _i: self._apply_table_density(
                self.optimization_table,
                self.optimization_density,
            )
        )

        toolbar.addWidget(sync_all_btn)
        toolbar.addWidget(refresh_btn)
        toolbar.addSpacing(8)
        toolbar.addWidget(self.optimization_search, 1)
        toolbar.addWidget(self.optimization_filter)
        toolbar.addWidget(self.optimization_status_filter)
        toolbar.addWidget(self.optimization_density)
        layout.addLayout(toolbar)

        quick_filters = QHBoxLayout()
        quick_filters.setSpacing(6)
        quick_label = QLabel("Швидкі фільтри:")
        quick_label.setProperty("muted", True)
        quick_filters.addWidget(quick_label)

        self.scheduled_quick_btn = QPushButton("Заплановані")
        self.scheduled_quick_btn.setProperty("role", "primary")
        self.scheduled_quick_btn.clicked.connect(
            lambda: self._set_optimization_queue_filter("scheduled")
        )
        quick_filters.addWidget(self.scheduled_quick_btn)

        today_quick_btn = QPushButton("Сьогоднішній стрім")
        today_quick_btn.setProperty("role", "chip")
        today_quick_btn.clicked.connect(self.open_today_stream_optimization)
        quick_filters.addWidget(today_quick_btn)

        for label, key in (
            ("Потрібна увага", "needs"),
            ("Чернетки", "draft"),
            ("Готово", "ready"),
            ("Без тегів", "no_tags"),
            ("Низький CTR", "low_ctr"),
            ("Застосовано", "applied"),
        ):
            chip = QPushButton(label)
            chip.setCheckable(False)
            chip.setProperty("role", "chip")
            chip.clicked.connect(
                lambda _checked=False, k=key:
                self._set_optimization_status_filter(k)
            )
            quick_filters.addWidget(chip)
        quick_filters.addStretch()
        layout.addLayout(quick_filters)

        actions = QHBoxLayout()
        scheduled_center_btn = QPushButton("Заплановані стріми")
        scheduled_center_btn.setProperty("role", "primary")
        scheduled_center_btn.clicked.connect(self.show_scheduled_center)
        local_seo_btn = QPushButton("Локальний SEO · 0 квоти")
        local_seo_btn.setProperty("role", "success")
        local_seo_btn.clicked.connect(self.local_seo_selected)
        apply_package_btn = QPushButton("Застосувати пакет")
        apply_package_btn.setProperty("role", "primary")
        apply_package_btn.clicked.connect(self.apply_content_package)
        package_btn = QPushButton("Редагувати пакет")
        package_btn.clicked.connect(self.edit_content_package)
        rollback_btn = QPushButton("Відкотити")
        rollback_btn.clicked.connect(self.rollback_selected_metadata)

        def make_menu_button(label: str, items: list[tuple[str, object]]) -> QToolButton:
            button = QToolButton()
            button.setText(label)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            for text_value, callback in items:
                action = QAction(text_value, menu)
                action.triggered.connect(
                    lambda _checked=False, cb=callback: cb()
                )
                menu.addAction(action)
            button.setMenu(menu)
            return button

        archive_menu = make_menu_button(
            "Архів ▾",
            [
                ("Центр кампанії", self.show_archive_campaign_center),
                ("ТОП потенціал", self.refresh_archive_potential),
                (
                    f"Підготувати {DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT}",
                    self.prepare_safe_queue,
                ),
                ("Перегляд безпечних правок", self.preview_safe_optimization),
                ("Застосувати безпечні", self.apply_safe_optimization),
                (
                    f"Наступні safe {DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT}",
                    self.apply_next_safe_archive_batch,
                ),
                ("Архів: денний пакет", lambda: self.apply_next_safe_archive_batch(daily=True)),
            ],
        )

        content_menu = make_menu_button(
            "Інструменти ▾",
            [
                ("Google Trends CSV", self.import_google_trends_file),
                ("0-quota статус", self.refresh_free_tools_status),
                ("Транскрипт → NAS", self.export_selected_transcript_to_nas),
                (
                    "Транскрипти запланованих → NAS",
                    self.export_scheduled_transcripts_to_nas,
                ),
                ("Перевірити сховища", self.test_nas_transcript_path),
                ("Імпорт пакета", self.import_selected_package_from_nas),
                ("Центр запланованих", self.show_scheduled_center),
            ],
        )

        titles_menu = make_menu_button(
            "Назви ▾",
            [
                ("Англомовні назви → NAS", self.export_latin_title_review_to_nas),
                ("Перегляд виправлень назв", self.preview_title_corrections),
                ("Застосувати назви (до 20)", self.apply_title_corrections),
            ],
        )

        self.daily_archive_btn = QPushButton("Архів: денний пакет")
        self.daily_archive_btn.setVisible(False)
        self.daily_archive_btn.setEnabled(archive_priority_enabled(self.conn))
        self.daily_archive_btn.clicked.connect(
            lambda: self.apply_next_safe_archive_batch(daily=True)
        )

        for button in (
            scheduled_center_btn,
            local_seo_btn,
            apply_package_btn,
            package_btn,
            rollback_btn,
            archive_menu,
            content_menu,
            titles_menu,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        self.archive_campaign_summary = QLabel()
        self.archive_campaign_summary.setObjectName("ArchiveCampaignSummary")
        self.archive_campaign_summary.setProperty("muted", True)
        self.archive_campaign_summary.setWordWrap(True)
        self._refresh_archive_campaign_summary()

        self.free_tools_status_label = QLabel(
            "0-quota: перевірка локальних інструментів..."
        )
        self.free_tools_status_label.setProperty("muted", True)
        self.free_tools_status_label.setWordWrap(True)

        self.optimization_table = FrozenColumnsTable(
            0,
            12,
            frozen_columns=(3, 4),
        )
        self.optimization_table.setHorizontalHeaderLabels(
            [
                "Пріоритет",
                "Публікація",
                "Статус",
                "Відео",
                "Назва",
                "Перегляди",
                "Аудит",
                "Транскрипт",
                "Пакет",
                "Остання оптимізація",
                "Контроль 7/28/90",
                "Проблеми",
            ]
        )
        self.optimization_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.optimization_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        opt_header = self.optimization_table.horizontalHeader()
        opt_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        opt_header.setStretchLastSection(True)
        opt_header.setMinimumSectionSize(72)
        for column, width in {
            0: 105, 1: 105, 2: 90, 3: 115, 4: 300, 5: 95,
            6: 75, 7: 105, 8: 100, 9: 135, 10: 190, 11: 280,
        }.items():
            self.optimization_table.setColumnWidth(column, width)
        self.optimization_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._configure_table(self.optimization_table)
        self.optimization_table.doubleClicked.connect(
            lambda _index: self.edit_content_package()
        )
        self.optimization_table.itemSelectionChanged.connect(
            self._update_optimization_context_card
        )

        context = QFrame()
        context.setObjectName("ContextCard")
        cx = QHBoxLayout(context)
        cx.setContentsMargins(14, 10, 14, 10)
        text_box = QVBoxLayout()
        self.optimization_context_title = QLabel("Виберіть відео")
        self.optimization_context_title.setObjectName("StickyVideoTitle")
        self.optimization_context_title.setWordWrap(True)
        self.optimization_context_pipeline = QLabel(
            "Аналіз → Транскрипт → SEO → Перевірка → Готово → YouTube → Контроль"
        )
        self.optimization_context_pipeline.setWordWrap(True)
        self.optimization_context_pipeline.setProperty("muted", True)
        self.optimization_context_note = QLabel("")
        self.optimization_context_note.setWordWrap(True)
        self.optimization_context_note.setProperty("muted", True)
        text_box.addWidget(self.optimization_context_title)
        text_box.addWidget(self.optimization_context_pipeline)
        text_box.addWidget(self.optimization_context_note)
        cx.addLayout(text_box, 1)
        self.context_primary_btn = QPushButton("Локальний SEO")
        self.context_primary_btn.setProperty("role", "primary")
        self.context_primary_btn.clicked.connect(self._run_context_primary_action)
        context_rollback = QPushButton("Відкотити")
        context_rollback.clicked.connect(self.rollback_selected_metadata)
        cx.addWidget(self.context_primary_btn)
        cx.addWidget(context_rollback)

        layout.addWidget(self.archive_campaign_summary)
        layout.addWidget(self.free_tools_status_label)
        layout.addWidget(self.optimization_table, 1)
        layout.addWidget(context)
        self.tabs.addTab(page, "Оптимізація")


    def _set_optimization_queue_filter(self, key: str) -> None:
        if not hasattr(self, "optimization_filter"):
            return
        index = self.optimization_filter.findData(str(key))
        if index >= 0:
            self.optimization_filter.setCurrentIndex(index)
        self.reload_optimization_queue()

    def _set_optimization_status_filter(self, key: str) -> None:
        if not hasattr(self, "optimization_status_filter"):
            return
        index = self.optimization_status_filter.findData(str(key))
        if index >= 0:
            self.optimization_status_filter.setCurrentIndex(index)
        self.reload_optimization_queue()

    def _selected_optimization_video_id(self) -> str:
        if not hasattr(self, "optimization_table"):
            return ""
        rows = self.optimization_table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.optimization_table.item(rows[0].row(), 3)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "")

    def _update_optimization_context_card(self) -> None:
        if not hasattr(self, "optimization_context_title"):
            return
        video_id = self._selected_optimization_video_id()
        if not video_id:
            self.optimization_context_title.setText("Виберіть відео")
            self.optimization_context_pipeline.setText(
                "Аналіз → Транскрипт → SEO → Перевірка → Готово → YouTube → Контроль"
            )
            self.optimization_context_note.setText("")
            self.context_primary_btn.setText("Локальний SEO")
            return

        row = self.conn.execute(
            """SELECT v.title,v.audit_json,v.views,d.status AS draft_status,
                      oe.optimized_at AS last_optimized
               FROM videos v
               LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
               LEFT JOIN optimization_events oe ON oe.event_id=(
                   SELECT e.event_id FROM optimization_events e
                   WHERE e.video_id=v.video_id AND e.profile=v.profile
                   ORDER BY e.optimized_at DESC,e.event_id DESC LIMIT 1
               )
               WHERE v.video_id=?""",
            (video_id,),
        ).fetchone()
        if row is None:
            return
        try:
            audit_data = json.loads(row["audit_json"] or "{}")
        except Exception:
            audit_data = {}
        score = int(audit_data.get("score") or 0)
        draft = str(row["draft_status"] or "")
        try:
            transcript_dir = self._nas_path(
                "nas_transcripts_path",
                DEFAULT_NAS_TRANSCRIPTS_PATH,
            )
            transcript_ready = (transcript_dir / f"{video_id}.srt").exists()
        except Exception:
            transcript_ready = False

        stages = [
            ("Аналіз", True),
            ("Транскрипт", transcript_ready),
            ("SEO", draft in {"draft", "ready", "applied"}),
            ("Перевірка", draft in {"ready", "applied"}),
            ("Готово", draft in {"ready", "applied"}),
            ("YouTube", draft == "applied"),
            ("Контроль", bool(row["last_optimized"])),
        ]
        pipeline = "  →  ".join(
            f"{'✓' if done else '○'} {label}" for label, done in stages
        )
        self.optimization_context_title.setText(str(row["title"] or video_id))
        self.optimization_context_pipeline.setText(pipeline)

        history = self.conn.execute(
            """SELECT optimized_at,changed_fields
               FROM optimization_events
               WHERE video_id=? AND profile=?
               ORDER BY optimized_at DESC,event_id DESC LIMIT 3""",
            (video_id, self.current_profile),
        ).fetchall()
        history_text = " · ".join(
            f"{str(item['optimized_at'] or '')[:10]} {str(item['changed_fields'] or '')}"
            for item in history
        )
        note = (
            f"{video_id} · аудит {score} · пакет {draft or 'немає'}"
            + (f" · історія: {history_text}" if history_text else "")
        )
        self.optimization_context_note.setText(note)

        if draft == "ready":
            self.context_primary_btn.setText("Застосувати пакет")
        elif draft == "applied":
            self.context_primary_btn.setText("Переглянути результат")
        elif draft == "draft":
            self.context_primary_btn.setText("Перевірити пакет")
        else:
            self.context_primary_btn.setText("Локальний SEO · 0 квоти")

        if hasattr(self, "pipeline_label"):
            self.pipeline_label.setText(pipeline)

    def _run_context_primary_action(self) -> None:
        video_id = self._selected_optimization_video_id()
        if not video_id:
            self._toast("Виберіть відео")
            return
        draft = get_optimization_draft(self.conn, video_id)
        status = str(draft["status"] or "") if draft is not None else ""
        if status == "ready":
            self.apply_content_package()
        elif status == "applied":
            self.tabs.setCurrentIndex(5)
            self.load_optimization_results()
        elif status == "draft":
            self.edit_content_package()
        else:
            self.local_seo_selected()

    def _build_comments_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        scan_btn = QPushButton("Перевірити коментарі")
        scan_btn.clicked.connect(lambda: self.scan_comment_queue(silent=False))
        test_auto_btn = QPushButton("Тест: 1 автовідповідь")
        test_auto_btn.clicked.connect(self.test_one_auto_reply)
        reply_btn = QPushButton("Відповісти на вибраний")
        reply_btn.clicked.connect(self.reply_selected)
        local_reply_btn = QPushButton("Локальна чернетка · 0 квоти")
        local_reply_btn.setProperty("role", "success")
        local_reply_btn.clicked.connect(self.local_comment_reply_selected)
        local_reply_batch_btn = QPushButton("Чернетки нових x20 · 0 квоти")
        local_reply_batch_btn.clicked.connect(self.local_comment_reply_batch)
        ignore_btn = QPushButton("Ігнорувати")
        ignore_btn.clicked.connect(lambda: self.set_selected_comment_status("ignored"))
        queue_btn = QPushButton("Повернути в чергу")
        queue_btn.clicked.connect(lambda: self.set_selected_comment_status("new"))

        self.comment_status_filter = QComboBox()
        self.comment_status_filter.addItem("Усі статуси", "")
        self.comment_status_filter.addItem("Нові", "new")
        self.comment_status_filter.addItem("З відповіддю", "replied")
        self.comment_status_filter.addItem("Проігноровані", "ignored")
        self.comment_status_filter.currentIndexChanged.connect(self.reload_comments)

        self.comment_category_filter = QComboBox()
        self.comment_category_filter.addItem("Усі категорії", "")
        self.comment_category_filter.addItem("На перевірці", "review")
        self.comment_category_filter.addItem("Подяки", "thanks")
        self.comment_category_filter.addItem("Посилання", "links")
        self.comment_category_filter.addItem("Донати", "donate")
        self.comment_category_filter.addItem("Розклад", "schedule")
        self.comment_category_filter.currentIndexChanged.connect(self.reload_comments)

        self.auto_quota_label = QLabel()

        controls.addWidget(scan_btn)
        controls.addWidget(test_auto_btn)
        controls.addWidget(reply_btn)
        controls.addWidget(local_reply_btn)
        controls.addWidget(local_reply_batch_btn)
        controls.addWidget(ignore_btn)
        controls.addWidget(queue_btn)
        controls.addWidget(self.comment_status_filter)
        controls.addWidget(self.comment_category_filter)
        controls.addStretch()
        controls.addWidget(self.auto_quota_label)

        self.comment_table = QTableWidget(0, 7)
        self.comment_table.setHorizontalHeaderLabels(
            ["Дата", "Відео", "Автор", "Коментар", "Категорія", "Статус", "Чернетка"]
        )
        self.comment_table.horizontalHeader().setStretchLastSection(True)
        self._configure_table(self.comment_table)
        layout.addLayout(controls)
        layout.addWidget(self.comment_table)
        self.tabs.addTab(page, "Коментарі")

    def _build_analytics_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        self.analytics_period_combo = QComboBox()
        self.analytics_period_combo.addItem("28 днів", 28)
        self.analytics_period_combo.addItem("90 днів", 90)
        self.analytics_period_combo.addItem("180 днів", 180)
        self.analytics_period_combo.setCurrentIndex(1)

        refresh_btn = QPushButton("Оновити аналітику")
        refresh_btn.setProperty("role", "primary")
        refresh_btn.clicked.connect(self.load_channel_analytics)

        reauth_btn = QPushButton("Перепідключити YouTube")
        reauth_btn.clicked.connect(self.connect_youtube)

        reach_btn = QPushButton("Увімкнути CTR / покази")
        reach_btn.clicked.connect(self.setup_reach_reporting)

        controls.addWidget(QLabel("Період:"))
        controls.addWidget(self.analytics_period_combo)
        controls.addWidget(refresh_btn)
        controls.addWidget(reach_btn)
        controls.addWidget(reauth_btn)
        controls.addStretch()

        hint = QLabel(
            "Дані надходять безпосередньо з YouTube Analytics API. "
            "vidIQ та його AI-кредити для цієї вкладки не використовуються."
        )
        hint.setWordWrap(True)

        self.analytics_text = QPlainTextEdit()
        self.analytics_text.setReadOnly(True)
        self.analytics_text.setPlaceholderText(
            "Натисніть «Оновити аналітику». "
            "Після встановлення версії з аналітикою потрібно один раз "
            "перепідключити кожен YouTube-канал, щоб дозволити читання Analytics."
        )

        layout.addLayout(controls)
        layout.addWidget(hint)
        layout.addWidget(self.analytics_text, 1)
        self.tabs.addTab(page, "Аналітика")

    def _build_results_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        self.results_period_combo = QComboBox()
        self.results_period_combo.addItem("7 днів", 7)
        self.results_period_combo.addItem("28 днів", 28)
        self.results_period_combo.addItem("90 днів", 90)
        self.results_period_combo.setCurrentIndex(0)

        self.results_change_filter = QComboBox()
        self.results_change_filter.addItem("Усі результати", "all")
        self.results_change_filter.addItem("Покращились", "improved")
        self.results_change_filter.addItem("Погіршились", "declined")
        self.results_change_filter.addItem("Готові до аналізу", "ready")
        self.results_change_filter.addItem("Очікування даних", "waiting")
        self.results_change_filter.currentIndexChanged.connect(
            self._filter_results_table
        )

        self.results_type_filter = QComboBox()
        self.results_type_filter.addItem("Усі типи", "all")
        self.results_type_filter.addItem("Безпечні правки", "safe")
        self.results_type_filter.addItem("Пакет контенту", "content")
        self.results_type_filter.addItem("Заплановані стріми", "scheduled")
        self.results_type_filter.currentIndexChanged.connect(
            self._filter_results_table
        )

        refresh_btn = QPushButton("Оновити результати")
        refresh_btn.setProperty("role", "primary")
        refresh_btn.clicked.connect(self.load_optimization_results)
        export_btn = QPushButton("Експорт CSV")
        export_btn.clicked.connect(self.export_optimization_results_csv)

        controls.addWidget(QLabel("Порівняння:"))
        controls.addWidget(self.results_period_combo)
        controls.addWidget(self.results_change_filter)
        controls.addWidget(self.results_type_filter)
        controls.addWidget(refresh_btn)
        controls.addWidget(export_btn)
        controls.addStretch()

        hint = QLabel(
            "Порівнюються однакові періоди ДО і ПІСЛЯ оптимізації. "
            "День зміни не входить у жодне вікно. Якщо повний період ще "
            "не минув, результат не оцінюється."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)

        self.results_table = QTableWidget(0, 19)
        self.results_table.setHorizontalHeaderLabels([
            "Дата", "Відео", "Зміни", "Статус",
            "Перегляди ДО", "ПІСЛЯ", "Δ",
            "Покази ДО", "ПІСЛЯ",
            "CTR ДО", "ПІСЛЯ",
            "Час перегляду ДО, год", "ПІСЛЯ",
            "Сер. тривалість ДО", "ПІСЛЯ",
            "Підписники ДО", "ПІСЛЯ", "Період", "Висновок",
        ])
        results_header = self.results_table.horizontalHeader()
        results_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        results_header.setStretchLastSection(True)
        results_header.setMinimumSectionSize(72)
        for column, width in {
            0: 95, 1: 260, 2: 170, 3: 105, 4: 105, 5: 95, 6: 75,
            7: 105, 8: 95, 9: 85, 10: 85, 11: 145, 12: 95,
            13: 145, 14: 95, 15: 110, 16: 95, 17: 85, 18: 210,
        }.items():
            self.results_table.setColumnWidth(column, width)
        self.results_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._configure_table(self.results_table)

        layout.addLayout(controls)

        summary_grid = QGridLayout()
        self.results_total_card = MetricCard("Оптимізації")
        self.results_improved_card = MetricCard("Покращились")
        self.results_declined_card = MetricCard("Погіршились")
        self.results_waiting_card = MetricCard("Очікують даних")
        summary_grid.addWidget(self.results_total_card, 0, 0)
        summary_grid.addWidget(self.results_improved_card, 0, 1)
        summary_grid.addWidget(self.results_declined_card, 0, 2)
        summary_grid.addWidget(self.results_waiting_card, 0, 3)
        layout.addLayout(summary_grid)

        layout.addWidget(hint)
        layout.addWidget(self.results_table)
        self.tabs.addTab(page, "Результати")

    @staticmethod
    def _optimization_reason_label(reason: str) -> str:
        return {
            "safe_archive_batch": "посилання + хештеги",
            "safe_optimization": "посилання + хештеги",
            "content_package": "назва + опис + теги",
            "scheduled_package_batch": "запланований стрім",
            "metadata_edit": "ручні метадані",
        }.get(reason, reason.replace("_", " "))

    def _update_results_summary_cards(self) -> None:
        if not hasattr(self, "results_total_card"):
            return
        total = self.results_table.rowCount()
        improved = 0
        declined = 0
        waiting = 0
        for row in range(total):
            result_item = self.results_table.item(row, 18)
            status_item = self.results_table.item(row, 3)
            result_key = (
                str(result_item.data(Qt.ItemDataRole.UserRole) or "")
                if result_item is not None else ""
            )
            status_key = (
                str(status_item.data(Qt.ItemDataRole.UserRole) or "")
                if status_item is not None else ""
            )
            if result_key == "improved":
                improved += 1
            elif result_key == "declined":
                declined += 1
            if status_key == "waiting":
                waiting += 1
        self.results_total_card.set_value(str(total), "7 / 28 / 90 днів")
        self.results_improved_card.set_value(str(improved), "позитивна динаміка")
        self.results_declined_card.set_value(str(declined), "потребують аналізу")
        self.results_waiting_card.set_value(str(waiting), "ще немає повного вікна")

    @staticmethod
    def _pct_change(before: float, after: float) -> str:
        if before <= 0:
            return "—" if after <= 0 else "+∞"
        value = (after - before) / before * 100.0
        return f"{value:+.1f}%"

    @staticmethod
    def _result_summary(
        before: dict[str, float] | None,
        after: dict[str, float] | None,
        reach_before: dict[str, float] | None,
        reach_after: dict[str, float] | None,
    ) -> tuple[str, str, str]:
        if before is None or after is None:
            return "—", "", ""

        metrics: list[tuple[str, float, float]] = [
            ("перегляди", float(before["views"]), float(after["views"])),
            (
                "час перегляду",
                float(before["watch_minutes"]),
                float(after["watch_minutes"]),
            ),
            (
                "сер. тривалість",
                float(before["avd_seconds"]),
                float(after["avd_seconds"]),
            ),
            ("підписники", float(before["subs"]), float(after["subs"])),
        ]
        if reach_before is not None and reach_after is not None:
            metrics.extend([
                (
                    "покази",
                    float(reach_before["impressions"]),
                    float(reach_after["impressions"]),
                ),
                ("CTR", float(reach_before["ctr"]), float(reach_after["ctr"])),
            ])

        improved: list[str] = []
        declined: list[str] = []
        neutral: list[str] = []
        for name, before_value, after_value in metrics:
            tolerance = max(abs(before_value) * 0.005, 0.01)
            if after_value > before_value + tolerance:
                improved.append(name)
            elif after_value < before_value - tolerance:
                declined.append(name)
            else:
                neutral.append(name)

        if len(improved) > len(declined):
            key = "improved"
            label = f"Краще: {len(improved)}/{len(metrics)}"
        elif len(declined) > len(improved):
            key = "declined"
            label = f"Гірше: {len(declined)}/{len(metrics)}"
        else:
            key = "mixed"
            label = "Змішаний результат"

        detail_parts = []
        if improved:
            detail_parts.append("зросли: " + ", ".join(improved))
        if declined:
            detail_parts.append("знизились: " + ", ".join(declined))
        if neutral:
            detail_parts.append("без суттєвої зміни: " + ", ".join(neutral))
        return label, key, "; ".join(detail_parts)

    def _video_window_metrics(
        self, video_id: str, start_date: str, end_date: str
    ) -> dict[str, float]:
        report = self.client.analytics_report(
            start_date=start_date,
            end_date=end_date,
            metrics=(
                "views,estimatedMinutesWatched,averageViewDuration,"
                "subscribersGained"
            ),
            filters=f"video=={video_id}",
        )
        rows = self._analytics_result_rows(report)
        row = rows[0] if rows else [0, 0, 0, 0]
        return {
            "views": float(row[0] or 0),
            "watch_minutes": float(row[1] or 0),
            "avd_seconds": float(row[2] or 0),
            "subs": float(row[3] or 0),
        }

    @staticmethod
    def _reach_window_metrics(
        rows: list[dict[str, str]],
        video_id: str,
        start_date: str,
        end_date: str,
        coverage_start: str | None,
        coverage_end: str | None,
    ) -> dict[str, float] | None:
        if not coverage_start or not coverage_end:
            return None
        if coverage_start > start_date or coverage_end < end_date:
            return None

        impressions = 0.0
        clicks = 0.0
        for row in rows:
            if str(row.get("video_id") or "") != video_id:
                continue
            day = str(row.get("date") or "")
            if not day or day < start_date or day > end_date:
                continue
            try:
                current_impressions = float(
                    row.get("video_thumbnail_impressions") or 0
                )
                ctr_raw = float(
                    row.get("video_thumbnail_impressions_ctr") or 0
                )
            except (TypeError, ValueError):
                continue
            ctr_ratio = ctr_raw if ctr_raw <= 1 else ctr_raw / 100
            impressions += current_impressions
            clicks += current_impressions * ctr_ratio

        ctr = clicks / impressions * 100 if impressions else 0.0
        return {"impressions": impressions, "ctr": ctr}

    def _filter_results_table(self, _index: int = -1) -> None:
        if not hasattr(self, "results_table"):
            return
        change_filter = (
            self.results_change_filter.currentData()
            if hasattr(self, "results_change_filter")
            else "all"
        )
        type_filter = (
            self.results_type_filter.currentData()
            if hasattr(self, "results_type_filter")
            else "all"
        )

        for row in range(self.results_table.rowCount()):
            status_item = self.results_table.item(row, 3)
            summary_item = self.results_table.item(row, 18)
            type_item = self.results_table.item(row, 2)
            status_key = (
                status_item.data(Qt.ItemDataRole.UserRole)
                if status_item else ""
            )
            result_key = (
                summary_item.data(Qt.ItemDataRole.UserRole)
                if summary_item else ""
            )
            reason = (
                type_item.data(Qt.ItemDataRole.UserRole)
                if type_item else ""
            )

            show = True
            if change_filter == "improved":
                show = status_key == "ready" and result_key == "improved"
            elif change_filter == "declined":
                show = status_key == "ready" and result_key == "declined"
            elif change_filter == "ready":
                show = status_key == "ready"
            elif change_filter == "waiting":
                show = status_key == "waiting"

            if show and type_filter != "all":
                if type_filter == "safe":
                    show = reason in {"safe_archive_batch", "safe_optimization"}
                elif type_filter == "content":
                    show = reason == "content_package"
                elif type_filter == "scheduled":
                    show = reason == "scheduled_package_batch"

            self.results_table.setRowHidden(row, not show)

    def export_optimization_results_csv(self) -> None:
        if not hasattr(self, "results_table") or self.results_table.rowCount() == 0:
            QMessageBox.information(
                self, APP_NAME, "Спочатку завантажте результати оптимізації."
            )
            return

        suggested = (
            f"RG_YouTube_Results_{self.current_profile}_"
            f"{datetime.now().date().isoformat()}.csv"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Експорт результатів",
            str(Path.home() / suggested),
            "CSV для Excel (*.csv)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"

        headers = [
            self.results_table.horizontalHeaderItem(col).text()
            for col in range(self.results_table.columnCount())
        ]
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(headers)
            for row in range(self.results_table.rowCount()):
                if self.results_table.isRowHidden(row):
                    continue
                writer.writerow([
                    self.results_table.item(row, col).text()
                    if self.results_table.item(row, col) else ""
                    for col in range(self.results_table.columnCount())
                ])

        QMessageBox.information(
            self,
            "Експорт завершено",
            f"Звіт збережено:\n{path}",
        )

    def _import_historical_optimization_events(self) -> int:
        setting_key = f"optimization_history_backfill_done_{self.current_profile}"
        if get_setting(self.conn, setting_key, "0") == "1":
            return 0

        rows = self.conn.execute(
            """SELECT h.history_id,h.video_id,h.title,h.description,h.tags_json,
                      h.reason,h.created_at
               FROM metadata_history h
               JOIN videos v ON v.video_id=h.video_id
               WHERE v.profile=?
                 AND h.reason IN (
                   'before_safe_archive_batch',
                   'before_safe_optimization',
                   'before_content_package',
                   'before_scheduled_package_batch'
                 )
               ORDER BY h.history_id DESC
               LIMIT 300""",
            (self.current_profile,),
        ).fetchall()
        if not rows:
            set_setting(self.conn, setting_key, "1")
            return 0

        unique_rows = []
        seen_snapshots = set()
        for row in rows:
            key = (
                str(row["video_id"]), str(row["reason"]),
                str(row["title"]), str(row["description"]), str(row["tags_json"]),
            )
            if key in seen_snapshots:
                continue
            seen_snapshots.add(key)
            unique_rows.append(row)

        video_ids = sorted({str(row["video_id"]) for row in unique_rows})
        if video_ids:
            counted = getattr(
                self.client,
                "video_details_with_request_count",
                None,
            )
            if callable(counted):
                current_items, requests = counted(video_ids)
                record_quota_units(
                    self.conn,
                    int(requests) * READ_REQUEST_COST,
                purpose="video",
                )
            else:
                current_items = self.client.video_details(video_ids)
                requests = (len(video_ids) + 49) // 50
                record_quota_units(
                    self.conn,
                    requests * READ_REQUEST_COST,
                purpose="video",
                )
            self.refresh_youtube_quota_label()
        else:
            current_items = []
        current_by_id = {str(item.get("id")): item for item in current_items}
        imported = 0
        reason_map = {
            "before_safe_archive_batch": ("safe_archive_batch", "посилання + хештеги"),
            "before_safe_optimization": ("safe_optimization", "посилання + хештеги"),
            "before_content_package": ("content_package", "назва + опис + теги"),
            "before_scheduled_package_batch": ("scheduled_package_batch", "назва + опис + теги"),
        }
        for row in unique_rows:
            item = current_by_id.get(str(row["video_id"]))
            if not item:
                continue
            snippet = item.get("snippet", {})
            current_title = str(snippet.get("title") or "")
            current_description = str(snippet.get("description") or "")
            current_tags = list(snippet.get("tags") or [])
            try:
                old_tags = json.loads(row["tags_json"] or "[]")
            except Exception:
                old_tags = []
            changed = (
                current_title != str(row["title"] or "")
                or current_description != str(row["description"] or "")
                or current_tags != list(old_tags)
            )
            if not changed:
                continue
            reason, fields = reason_map[str(row["reason"])]
            event_id = record_optimization_event(
                self.conn,
                history_id=int(row["history_id"]),
                video_id=str(row["video_id"]),
                profile=self.current_profile,
                reason=reason,
                changed_fields=fields + " · історія",
                optimized_at=str(row["created_at"] or ""),
            )
            if event_id:
                imported += 1

        set_setting(self.conn, setting_key, "1")
        return imported

    def load_optimization_results(self) -> None:
        if quota_exhausted(self.conn):
            imported = 0
            self.statusBar().showMessage(
                "YouTube API вичерпано. Показуємо лише локально збережені "
                "результати без мережевого імпорту."
            )
        else:
            try:
                imported = self._import_historical_optimization_events()
            except Exception as exc:
                imported = 0
                error_text = str(exc)
                if "403" in error_text or "quota" in error_text.casefold():
                    self.statusBar().showMessage(
                        "Імпорт історії: YouTube API тимчасово недоступний "
                        "(квота або доступ). Локальні дані не пошкоджені."
                    )
                else:
                    self.statusBar().showMessage(
                        "Імпорт історії не виконано. Локальні дані не пошкоджені."
                    )

        days = int(self.results_period_combo.currentData() or 7)
        events = optimization_events(self.conn, self.current_profile, limit=100)
        self.results_table.setRowCount(0)
        if not events:
            QMessageBox.information(
                self,
                APP_NAME,
                "Ще немає зафіксованих успішних оптимізацій для аналізу. "
                "Наступні застосовані зміни будуть записуватися автоматично.",
            )
            return

        today = datetime.now(timezone.utc).date()
        event_windows = []
        for event in events:
            raw_dt = str(event["optimized_at"] or "")
            try:
                optimized_dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                optimized_date = optimized_dt.date()
            except Exception:
                continue
            before_start = optimized_date - timedelta(days=days)
            before_end = optimized_date - timedelta(days=1)
            after_start = optimized_date + timedelta(days=1)
            after_end = optimized_date + timedelta(days=days)
            remaining_days = max(0, (after_end - today).days)
            event_windows.append((
                event,
                before_start,
                before_end,
                after_start,
                after_end,
                remaining_days,
            ))

        reach_rows: list[dict[str, str]] = []
        coverage_start = None
        coverage_end = None
        complete_windows = [item for item in event_windows if item[5] == 0]
        local_only_results = quota_exhausted(self.conn)
        if complete_windows and not local_only_results:
            reach_start = min(item[1] for item in complete_windows).isoformat()
            reach_end = max(item[4] for item in complete_windows).isoformat()
            try:
                reach_rows, _job = self.client.reach_report_rows(
                    start_date=reach_start,
                    end_date=reach_end,
                )
                dates = sorted({
                    str(row.get("date") or "")
                    for row in reach_rows
                    if str(row.get("date") or "")
                })
                if dates:
                    coverage_start = dates[0]
                    coverage_end = dates[-1]
            except Exception:
                reach_rows = []

        prepared = []
        complete_events = 0
        self.statusBar().showMessage("Аналіз результатів оптимізації…")
        QApplication.processEvents()

        for (
            event,
            before_start,
            before_end,
            after_start,
            after_end,
            remaining_days,
        ) in event_windows:
            before = None
            after = None
            reach_before = None
            reach_after = None
            error_text = ""
            if remaining_days == 0 and not local_only_results:
                try:
                    video_id = str(event["video_id"])
                    before = self._video_window_metrics(
                        video_id,
                        before_start.isoformat(),
                        before_end.isoformat(),
                    )
                    after = self._video_window_metrics(
                        video_id,
                        after_start.isoformat(),
                        after_end.isoformat(),
                    )
                    reach_before = self._reach_window_metrics(
                        reach_rows,
                        video_id,
                        before_start.isoformat(),
                        before_end.isoformat(),
                        coverage_start,
                        coverage_end,
                    )
                    reach_after = self._reach_window_metrics(
                        reach_rows,
                        video_id,
                        after_start.isoformat(),
                        after_end.isoformat(),
                        coverage_start,
                        coverage_end,
                    )
                    complete_events += 1
                except Exception as exc:
                    error_text = str(exc)

            prepared.append((
                event,
                before,
                after,
                reach_before,
                reach_after,
                remaining_days,
                error_text,
            ))

        self.results_table.setRowCount(len(prepared))
        for row_index, (
            event,
            before,
            after,
            reach_before,
            reach_after,
            remaining_days,
            error_text,
        ) in enumerate(prepared):
            if error_text:
                status = "помилка Analytics"
                status_key = "error"
            elif local_only_results and remaining_days == 0:
                status = "локально"
                status_key = "waiting"
            elif remaining_days > 0:
                status = f"ще {remaining_days} дн."
                status_key = "waiting"
            else:
                status = "готово"
                status_key = "ready"

            delta_value = None
            if before is not None and after is not None:
                if before["views"] > 0:
                    delta_value = (
                        (after["views"] - before["views"])
                        / before["views"] * 100.0
                    )
                delta = self._pct_change(before["views"], after["views"])
                before_impressions = (
                    f"{int(reach_before['impressions']):,}"
                    if reach_before is not None else "—"
                )
                after_impressions = (
                    f"{int(reach_after['impressions']):,}"
                    if reach_after is not None else "—"
                )
                before_ctr = (
                    f"{reach_before['ctr']:.2f}%"
                    if reach_before is not None else "—"
                )
                after_ctr = (
                    f"{reach_after['ctr']:.2f}%"
                    if reach_after is not None else "—"
                )
                summary_text, result_key, summary_detail = self._result_summary(
                    before,
                    after,
                    reach_before,
                    reach_after,
                )
                values = [
                    str(event["optimized_at"] or "")[:10],
                    str(event["title"] or event["video_id"]),
                    str(event["changed_fields"] or self._optimization_reason_label(
                        str(event["reason"] or "")
                    )),
                    status,
                    f"{int(before['views']):,}",
                    f"{int(after['views']):,}",
                    delta,
                    before_impressions,
                    after_impressions,
                    before_ctr,
                    after_ctr,
                    f"{before['watch_minutes'] / 60:.1f}",
                    f"{after['watch_minutes'] / 60:.1f}",
                    f"{before['avd_seconds']:.0f} с",
                    f"{after['avd_seconds']:.0f} с",
                    f"{int(before['subs']):,}",
                    f"{int(after['subs']):,}",
                    f"{days} днів",
                    summary_text,
                ]
            else:
                values = [
                    str(event["optimized_at"] or "")[:10],
                    str(event["title"] or event["video_id"]),
                    str(event["changed_fields"] or self._optimization_reason_label(
                        str(event["reason"] or "")
                    )),
                    status,
                    "—", "—", "—",
                    "—", "—", "—", "—",
                    "—", "—", "—", "—", "—", "—",
                    f"{days} днів",
                    "—",
                ]
                result_key = ""
                summary_detail = ""

            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 2:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        str(event["reason"] or ""),
                    )
                elif column == 3:
                    item.setData(Qt.ItemDataRole.UserRole, status_key)
                    item.setForeground(
                        QColor(SUCCESS if status_key == "ready" else WARNING)
                    )
                    if error_text:
                        item.setToolTip(error_text)
                elif column == 6:
                    item.setData(Qt.ItemDataRole.UserRole, delta_value)
                    if delta_value is not None:
                        item.setForeground(
                            QColor(SUCCESS if delta_value >= 0 else YOUTUBE_RED)
                        )
                elif column == 18:
                    item.setData(Qt.ItemDataRole.UserRole, result_key)
                    if result_key == "improved":
                        item.setForeground(QColor(SUCCESS))
                    elif result_key == "declined":
                        item.setForeground(QColor(YOUTUBE_RED))
                    elif result_key == "mixed":
                        item.setForeground(QColor(WARNING))
                    if summary_detail:
                        item.setToolTip(summary_detail)
                self.results_table.setItem(row_index, column, item)

        self._filter_results_table()
        self._update_results_summary_cards()
        suffix = f" · імпортовано з історії {imported}" if imported else ""
        reach_note = (
            f" · CTR/покази {coverage_start}–{coverage_end}"
            if coverage_start and coverage_end else
            " · CTR/покази недоступні для цього періоду"
        )
        self.statusBar().showMessage(
            f"Результати: {len(prepared)} подій · "
            f"готово до порівняння {complete_events}{suffix}{reach_note}"
        )

    @staticmethod
    def _analytics_result_rows(report: dict) -> list[list]:
        return list(report.get("rows") or [])

    def setup_reach_reporting(self) -> None:
        try:
            job, created = self.client.ensure_reach_job()
            if created:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Завдання CTR / показів створено. YouTube Reporting API "
                    "почне формувати щоденні звіти про охоплення. Історичні "
                    "дані приблизно за 30 днів з’являться не одразу, зазвичай протягом "
                    "кількох годин або до доби.",
                )
            else:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "CTR / покази вже підключені для цього каналу. "
                    f"ID завдання: {job.get('id', '—')}",
                )
        except Exception as exc:
            message = str(exc)
            if "accessNotConfigured" in message or "SERVICE_DISABLED" in message:
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "YouTube Reporting API ще не увімкнено в Google Cloud. "
                    "Увімкніть його для проєкту RG YouTube Control і повторіть.",
                )
                return
            if "invalid_scope" in message.lower():
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Для цього каналу потрібна повторна авторизація. "
                    "Натисніть «Перепідключити YouTube», дозвольте доступ "
                    "і знову увімкніть CTR / покази.",
                )
                return
            self._error("Помилка підключення CTR / показів", exc)

    def refresh_archive_potential(self) -> None:
        if hasattr(self, "analytics_period_combo"):
            index = self.analytics_period_combo.findData(90)
            if index >= 0:
                self.analytics_period_combo.setCurrentIndex(index)
        self.load_channel_analytics()

    def load_channel_analytics(self) -> None:
        days = int(self.analytics_period_combo.currentData() or 90)
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=max(days - 1, 0))
        start_s = start.isoformat()
        end_s = end.isoformat()

        try:
            self.statusBar().showMessage("Завантаження YouTube Analytics…")
            QApplication.processEvents()

            totals = self.client.analytics_report(
                start_date=start_s,
                end_date=end_s,
                metrics="views,engagedViews,estimatedMinutesWatched,subscribersGained",
            )
            traffic = self.client.analytics_report(
                start_date=start_s,
                end_date=end_s,
                metrics="views,estimatedMinutesWatched",
                dimensions="insightTrafficSourceType",
                sort="-views",
            )
            search = self.client.analytics_report(
                start_date=start_s,
                end_date=end_s,
                metrics="views,estimatedMinutesWatched",
                dimensions="insightTrafficSourceDetail",
                filters="insightTrafficSourceType==YT_SEARCH",
                sort="-views",
                max_results=25,
            )
            geography = self.client.analytics_report(
                start_date=start_s,
                end_date=end_s,
                metrics="views,estimatedMinutesWatched",
                dimensions="country",
                sort="-views",
                max_results=20,
            )
            top_videos = self.client.analytics_report(
                start_date=start_s,
                end_date=end_s,
                metrics=(
                    "views,engagedViews,estimatedMinutesWatched,"
                    "averageViewDuration,subscribersGained"
                ),
                dimensions="video",
                sort="-views",
                max_results=200,
            )

            reach_rows: list[dict[str, str]] = []
            reach_job = None
            reach_error = ""
            try:
                reach_rows, reach_job = self.client.reach_report_rows(
                    start_date=start_s,
                    end_date=end_s,
                )
            except Exception as exc:
                reach_error = str(exc)

            traffic_names = {
                "ADVERTISING": "Реклама",
                "ANNOTATION": "Анотації / картки",
                "END_SCREEN": "Кінцеві заставки",
                "EXT_URL": "Зовнішні сайти / Google",
                "HASHTAGS": "Хештеги",
                "LIVE_REDIRECT": "Перенаправлення трансляції",
                "NO_LINK_EMBEDDED": "Вбудовані плеєри",
                "NO_LINK_OTHER": "Прямі / невідомі",
                "NOTIFICATION": "Сповіщення",
                "PLAYLIST": "Плейлисти",
                "RELATED_VIDEO": "Рекомендовані відео",
                "SHORTS": "Стрічка Shorts",
                "SOUND_PAGE": "Сторінки звуку",
                "SUBSCRIBER": "Головна / підписки",
                "YT_CHANNEL": "Сторінки каналів",
                "YT_OTHER_PAGE": "Інші сторінки YouTube",
                "YT_SEARCH": "Пошук YouTube",
                "VIDEO_REMIXES": "Ремікси",
            }

            lines: list[str] = []
            lines.append(
                f"{PROFILE_LABELS[self.current_profile]} · "
                f"{start_s} — {end_s} · {days} днів"
            )
            lines.append("=" * 72)

            total_rows = self._analytics_result_rows(totals)
            if total_rows:
                row = total_rows[0]
                views = int(row[0] or 0)
                engaged = int(row[1] or 0)
                minutes = float(row[2] or 0)
                subs = int(row[3] or 0)
                lines.append(
                    f"Перегляди: {views:,} · Залучені перегляди: {engaged:,} · "
                    f"Години перегляду: {minutes / 60:,.1f} · "
                    f"Підписники: +{subs:,}"
                )
                lines.append("")

            lines.append("ДЖЕРЕЛА ТРАФІКУ")
            traffic_rows = self._analytics_result_rows(traffic)
            traffic_total = sum(float(r[1] or 0) for r in traffic_rows) or 1.0
            for row in traffic_rows[:15]:
                source = traffic_names.get(str(row[0]), str(row[0]))
                views = float(row[1] or 0)
                pct = views / traffic_total * 100
                hours = float(row[2] or 0) / 60
                lines.append(
                    f"• {source}: {int(views):,} переглядів "
                    f"({pct:.1f}%), {hours:,.1f} ч"
                )
            lines.append("")

            lines.append("ПОШУКОВІ ЗАПИТИ YOUTUBE")
            search_rows = self._analytics_result_rows(search)
            if not search_rows:
                lines.append("• Немає даних за вибраний період")
            else:
                for row in search_rows:
                    term = str(row[0] or "—")
                    views = int(row[1] or 0)
                    hours = float(row[2] or 0) / 60
                    lines.append(f"• {term}: {views:,} переглядів, {hours:,.1f} ч")
            lines.append("")

            lines.append("ГЕОГРАФІЯ")
            for row in self._analytics_result_rows(geography)[:15]:
                country = str(row[0] or "—")
                views = int(row[1] or 0)
                hours = float(row[2] or 0) / 60
                lines.append(f"• {country}: {views:,} переглядів, {hours:,.1f} ч")
            lines.append("")

            reach_by_video: dict[str, dict[str, float]] = {}
            reach_dates: list[str] = []
            for reach_row in reach_rows:
                video_id = str(reach_row.get("video_id") or "")
                if not video_id:
                    continue
                try:
                    impressions = float(
                        reach_row.get("video_thumbnail_impressions") or 0
                    )
                    ctr_raw = float(
                        reach_row.get("video_thumbnail_impressions_ctr") or 0
                    )
                except (TypeError, ValueError):
                    continue
                ctr_ratio = ctr_raw if ctr_raw <= 1 else ctr_raw / 100
                bucket = reach_by_video.setdefault(
                    video_id,
                    {"impressions": 0.0, "clicks": 0.0},
                )
                bucket["impressions"] += impressions
                bucket["clicks"] += impressions * ctr_ratio
                day = str(reach_row.get("date") or "")
                if day:
                    reach_dates.append(day)

            top_video_rows = self._analytics_result_rows(top_videos)
            analytics_by_video: dict[str, dict[str, float]] = {}
            for top_row in top_video_rows:
                video_id = str(top_row[0] or "")
                if not video_id:
                    continue
                analytics_by_video[video_id] = {
                    "views": float(top_row[1] or 0),
                    "engaged": float(top_row[2] or 0),
                    "watch_minutes": float(top_row[3] or 0),
                    "avd_seconds": float(top_row[4] or 0),
                    "subs": float(top_row[5] or 0),
                }

            self.conn.execute(
                "DELETE FROM video_analytics_cache WHERE profile=?",
                (self.current_profile,),
            )
            for video_id in set(analytics_by_video) | set(reach_by_video):
                stats = analytics_by_video.get(video_id, {})
                reach_values = reach_by_video.get(video_id, {})
                impressions = int(reach_values.get("impressions") or 0)
                ctr_percent = (
                    float(reach_values.get("clicks") or 0)
                    / float(reach_values.get("impressions") or 1)
                    * 100
                    if impressions
                    else 0.0
                )
                upsert_video_analytics(
                    self.conn,
                    video_id=video_id,
                    profile=self.current_profile,
                    period_days=days,
                    analytics_views=int(stats.get("views") or 0),
                    engaged_views=int(stats.get("engaged") or 0),
                    watch_minutes=float(stats.get("watch_minutes") or 0),
                    avd_seconds=float(stats.get("avd_seconds") or 0),
                    subs_gained=int(stats.get("subs") or 0),
                    impressions=impressions,
                    ctr_percent=ctr_percent,
                    start_date=start_s,
                    end_date=end_s,
                )
            commit_video_analytics(self.conn)

            title_by_id = {
                row["video_id"]: row["title"]
                for row in self.conn.execute(
                    "SELECT video_id,title FROM videos WHERE profile=?",
                    (self.current_profile,),
                ).fetchall()
            }

            lines.append("ПОКАЗИ ТА CTR")
            if reach_by_video:
                if reach_dates:
                    lines.append(
                        f"Доступний період охоплення: {min(reach_dates)} — {max(reach_dates)}"
                    )
                reach_ranked = sorted(
                    reach_by_video.items(),
                    key=lambda item: item[1]["impressions"],
                    reverse=True,
                )
                for video_id, values in reach_ranked[:15]:
                    impressions = int(values["impressions"])
                    ctr = (
                        values["clicks"] / values["impressions"] * 100
                        if values["impressions"]
                        else 0.0
                    )
                    title = title_by_id.get(video_id, video_id)
                    lines.append(
                        f"• {title}\n"
                        f"  {impressions:,} показів · CTR {ctr:.2f}%"
                    )
            elif reach_job is None and not reach_error:
                lines.append(
                    "• CTR/покази ще не підключені. "
                    "Натисніть «Увімкнути CTR / покази»."
                )
            elif reach_job is not None:
                lines.append(
                    "• Завдання охоплення активне, але звіти ще не готові. "
                    "YouTube формує їх окремо."
                )
            elif reach_error:
                if "accessNotConfigured" in reach_error:
                    lines.append(
                        "• YouTube Reporting API не увімкнено в Google Cloud."
                    )
                else:
                    lines.append("• CTR/покази тимчасово недоступні.")
            lines.append("")

            lines.append("ТОП ВІДЕО")
            for row in top_video_rows:
                video_id = str(row[0])
                views = int(row[1] or 0)
                engaged = int(row[2] or 0)
                hours = float(row[3] or 0) / 60
                avd = int(float(row[4] or 0))
                subs = int(row[5] or 0)
                title = title_by_id.get(video_id, video_id)
                reach_text = ""
                if video_id in reach_by_video:
                    values = reach_by_video[video_id]
                    impressions = int(values["impressions"])
                    ctr = (
                        values["clicks"] / values["impressions"] * 100
                        if values["impressions"]
                        else 0.0
                    )
                    reach_text = f" · {impressions:,} показів · CTR {ctr:.2f}%"
                lines.append(
                    f"• {title}\n"
                    f"  {views:,} переглядів · {engaged:,} залучених · "
                    f"{hours:,.1f} ч · AVD {avd // 60}:{avd % 60:02d} · "
                    f"+{subs} підписників{reach_text}"
                )

            self.analytics_text.setPlainText("\n".join(lines))
            self.reload_optimization_queue()
            self.statusBar().showMessage(
                "YouTube Analytics оновлено · ТОП потенціал перераховано"
            )
        except Exception as exc:
            message = str(exc)
            if (
                "insufficientPermissions" in message
                or "insufficient authentication scopes" in message.lower()
                or "invalid_scope" in message.lower()
            ):
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Для YouTube Analytics потрібна нова авторизація. "
                    "Натисніть «Перепідключити YouTube» на цій вкладці та "
                    "дозвольте доступ, потім повторіть завантаження.",
                )
                return
            self._error("Помилка YouTube Analytics", exc)

    def _build_log_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        refresh_btn = QPushButton("Оновити журнал")
        refresh_btn.clicked.connect(self.reload_action_log)
        controls.addWidget(refresh_btn)
        controls.addWidget(
            QLabel("Показуються останні дії для активного каналу.")
        )
        controls.addStretch()

        self.action_log_table = QTableWidget(0, 4)
        self.action_log_table.setHorizontalHeaderLabels(
            ["Час", "Категорія", "Дія", "Деталі"]
        )
        header = self.action_log_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.action_log_table.setColumnWidth(0, 180)
        self.action_log_table.setColumnWidth(1, 130)
        self.action_log_table.setColumnWidth(2, 220)
        self._configure_table(self.action_log_table)

        layout.addLayout(controls)
        layout.addWidget(self.action_log_table)
        self.tabs.addTab(page, "Журнал")

    def reload_action_log(self) -> None:
        if not hasattr(self, "action_log_table"):
            return
        rows = recent_action_log(
            self.conn,
            profile=self.current_profile,
            limit=250,
        )
        self.action_log_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            created = str(row["created_at"] or "")
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created = dt.astimezone().strftime("%d.%m.%Y %H:%M:%S")
            except Exception:
                pass
            values = [
                created,
                str(row["category"] or ""),
                str(row["action"] or ""),
                str(row["details"] or ""),
            ]
            for column, value in enumerate(values):
                self.action_log_table.setItem(
                    index, column, QTableWidgetItem(value)
                )

    def _build_settings_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.profile_combo = QComboBox()
        for profile_key, label in PROFILE_LABELS.items():
            self.profile_combo.addItem(label, profile_key)
        current_index = self.profile_combo.findData(self.current_profile)
        if current_index >= 0:
            self.profile_combo.setCurrentIndex(current_index)
        self.profile_combo.currentIndexChanged.connect(self.switch_profile)

        saved_title = get_setting(
            self.conn, f"channel_title_{self.current_profile}", ""
        )
        saved_id = get_setting(
            self.conn, f"channel_id_{self.current_profile}", ""
        )
        if saved_title and saved_id:
            self.channel_label = QLabel(f"YouTube: {saved_title} · {saved_id}")
        else:
            self.channel_label = QLabel("YouTube: не підключено")

        self.background_box = QCheckBox(
            f"Фонова перевірка коментарів кожні {DEFAULT_SCAN_MINUTES} хвилин"
        )
        self.background_box.setChecked(
            get_setting(self.conn, "background_scan_enabled", "1") == "1"
        )
        self.background_box.stateChanged.connect(self.save_background_setting)

        self.auto_box = QCheckBox(
            "Автовідповіді лише на безпечні службові коментарі"
        )
        default_auto = (
            get_setting(self.conn, "auto_reply_enabled", "0")
            if self.current_profile == "main"
            else "0"
        )
        self.auto_box.setChecked(
            get_setting(
                self.conn,
                f"auto_reply_enabled_{self.current_profile}",
                default_auto,
            ) == "1"
        )
        self.auto_box.stateChanged.connect(self.save_auto_setting)

        self.archive_priority_box = QCheckBox(
            "Пріоритет архіву - призупинити автопілот безпечних метаданих"
        )
        self.archive_priority_box.setChecked(
            archive_priority_enabled(self.conn)
        )
        self.archive_priority_box.stateChanged.connect(
            self.save_archive_priority_setting
        )

        self.safe_autopilot_box = QCheckBox(
            "Автопілот безпечних метаданих "
            "(лише посилання + рядок хештегів)"
        )
        self.safe_autopilot_box.setChecked(
            get_setting(
                self.conn,
                f"safe_metadata_autopilot_{self.current_profile}",
                "0",
            ) == "1"
        )
        self.safe_autopilot_box.stateChanged.connect(
            self.save_safe_autopilot_setting
        )

        self.autopilot_interval_spin = QSpinBox()
        self.autopilot_interval_spin.setRange(15, 1440)
        self.autopilot_interval_spin.setSuffix(" хв")
        self.autopilot_interval_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    f"safe_autopilot_interval_minutes_{self.current_profile}",
                    str(DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES),
                )
            )
        )
        self.autopilot_interval_spin.valueChanged.connect(
            self.save_safe_autopilot_limits
        )

        self.autopilot_daily_spin = QSpinBox()
        self.autopilot_daily_spin.setRange(1, 100)
        self.autopilot_daily_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    f"safe_autopilot_daily_limit_{self.current_profile}",
                    str(DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT),
                )
            )
        )
        self.autopilot_daily_spin.valueChanged.connect(
            self.save_safe_autopilot_limits
        )

        for profile_key in PROFILE_TARGETS:
            for suffix, legacy_key, default_value in (
                ("daily_limit", "auto_reply_daily_limit", DEFAULT_MAX_AUTO_REPLIES_PER_DAY),
                ("scan_limit", "auto_reply_scan_limit", DEFAULT_MAX_AUTO_REPLIES_PER_SCAN),
                ("max_age_hours", "auto_reply_max_age_hours", DEFAULT_AUTO_REPLY_MAX_AGE_HOURS),
            ):
                target_key = f"auto_reply_{suffix}_{profile_key}"
                if get_setting(self.conn, target_key, "__missing__") == "__missing__":
                    set_setting(
                        self.conn,
                        target_key,
                        get_setting(self.conn, legacy_key, str(default_value)),
                    )
            for category in DEFAULT_REPLY_TEMPLATES:
                target_key = f"reply_template_{profile_key}_{category}"
                if get_setting(self.conn, target_key, "__missing__") == "__missing__":
                    set_setting(
                        self.conn,
                        target_key,
                        get_setting(
                            self.conn,
                            f"reply_template_{category}",
                            DEFAULT_REPLY_TEMPLATES[category],
                        ),
                    )

        if get_setting(self.conn, "auto_reply_daily_limit", "5") == "5":
            set_setting(self.conn, "auto_reply_daily_limit", "30")
        if get_setting(self.conn, "auto_reply_scan_limit", "5") == "5":
            set_setting(self.conn, "auto_reply_scan_limit", "5")
        if get_setting(self.conn, "auto_reply_max_age_hours", "24") == "24":
            set_setting(self.conn, "auto_reply_max_age_hours", "24")

        template_migrations = {
            "thanks": {
                "Дякуємо за підтримку! 💙💛": DEFAULT_REPLY_TEMPLATES["thanks"],
            },
            "links": {
                "Усі актуальні посилання проєкту: https://links.rginfoua.pp.ua/": DEFAULT_REPLY_TEMPLATES["links"],
            },
            "donate": {
                "Дякуємо за підтримку! Усі варіанти відправити донейт для ЗСУ: https://donate.rginfoua.pp.ua/": DEFAULT_REPLY_TEMPLATES["donate"],
                "Дякуємо за підтримку! Усі варіанти донейту: https://donate.rginfoua.pp.ua/": DEFAULT_REPLY_TEMPLATES["donate"],
            },
            "schedule": {
                "Дивіться стріми Пн., Ср., Пт., Сб. з 21:00 до 00:00": DEFAULT_REPLY_TEMPLATES["schedule"],
                "Актуальний розклад і всі посилання проєкту: https://links.rginfoua.pp.ua/": DEFAULT_REPLY_TEMPLATES["schedule"],
            },
        }
        for category, replacements in template_migrations.items():
            key = f"reply_template_{category}"
            current = get_setting(self.conn, key, DEFAULT_REPLY_TEMPLATES[category])
            if current in replacements:
                set_setting(self.conn, key, replacements[current])

        self.daily_limit_spin = QSpinBox()
        self.daily_limit_spin.setRange(1, 100)
        self.daily_limit_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    f"auto_reply_daily_limit_{self.current_profile}",
                    get_setting(
                        self.conn,
                        "auto_reply_daily_limit",
                        str(DEFAULT_MAX_AUTO_REPLIES_PER_DAY),
                    ),
                )
            )
        )
        self.daily_limit_spin.valueChanged.connect(self.save_auto_limits)

        self.scan_limit_spin = QSpinBox()
        self.scan_limit_spin.setRange(1, 20)
        self.scan_limit_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    f"auto_reply_scan_limit_{self.current_profile}",
                    get_setting(
                        self.conn,
                        "auto_reply_scan_limit",
                        str(DEFAULT_MAX_AUTO_REPLIES_PER_SCAN),
                    ),
                )
            )
        )
        self.scan_limit_spin.valueChanged.connect(self.save_auto_limits)

        self.age_limit_spin = QSpinBox()
        self.age_limit_spin.setRange(1, 720)
        self.age_limit_spin.setSuffix(" ч")
        self.age_limit_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    f"auto_reply_max_age_hours_{self.current_profile}",
                    get_setting(
                        self.conn,
                        "auto_reply_max_age_hours",
                        str(DEFAULT_AUTO_REPLY_MAX_AGE_HOURS),
                    ),
                )
            )
        )
        self.age_limit_spin.valueChanged.connect(self.save_auto_limits)

        self.reply_template_edits = {}
        template_labels = {
            "thanks": "Відповідь на подяку",
            "links": "Відповідь із посиланнями",
            "donate": "Відповідь про донат",
            "schedule": "Відповідь про розклад",
        }
        for category, label in template_labels.items():
            edit = QLineEdit(
                get_setting(
                    self.conn,
                    f"reply_template_{self.current_profile}_{category}",
                    get_setting(
                        self.conn,
                        f"reply_template_{category}",
                        DEFAULT_REPLY_TEMPLATES[category],
                    ),
                )
            )
            edit.setPlaceholderText(label)
            edit.setCursorPosition(0)
            edit.editingFinished.connect(
                lambda c=category, e=edit: self.save_reply_template(c, e.text())
            )
            self.reply_template_edits[category] = (label, edit)

        transcript_path = normalize_nas_unc_path(
            get_setting(
                self.conn,
                "nas_transcripts_path",
                DEFAULT_NAS_TRANSCRIPTS_PATH,
            ),
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        set_setting(self.conn, "nas_transcripts_path", transcript_path)
        self.nas_transcripts_edit = QLineEdit(transcript_path)
        self.nas_transcripts_edit.editingFinished.connect(
            lambda: self._save_nas_path_setting(
                "nas_transcripts_path",
                self.nas_transcripts_edit,
                DEFAULT_NAS_TRANSCRIPTS_PATH,
            )
        )

        packages_path = normalize_nas_unc_path(
            get_setting(
                self.conn,
                "nas_packages_path",
                DEFAULT_NAS_PACKAGES_PATH,
            ),
            DEFAULT_NAS_PACKAGES_PATH,
        )
        set_setting(self.conn, "nas_packages_path", packages_path)
        self.nas_packages_edit = QLineEdit(packages_path)
        self.nas_packages_edit.editingFinished.connect(
            lambda: self._save_nas_path_setting(
                "nas_packages_path",
                self.nas_packages_edit,
                DEFAULT_NAS_PACKAGES_PATH,
            )
        )

        oauth_btn = QPushButton("Вибрати JSON клієнта OAuth")
        oauth_btn.clicked.connect(self.choose_oauth_file)

        self.quota_reserve_spin = QSpinBox()
        self.quota_reserve_spin.setRange(0, 9000)
        self.quota_reserve_spin.setSingleStep(250)
        self.quota_reserve_spin.setSuffix(" од.")
        self.quota_reserve_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    "youtube_quota_reserve_units",
                    str(QUOTA_RESERVE_DEFAULT),
                )
            )
        )
        self.quota_reserve_spin.valueChanged.connect(self.save_quota_reserve)

        vidiq_status = vidiq_budget_status(self.conn)
        self.vidiq_monthly_limit_spin = QSpinBox()
        self.vidiq_monthly_limit_spin.setRange(100, 100000)
        self.vidiq_monthly_limit_spin.setSingleStep(100)
        self.vidiq_monthly_limit_spin.setSuffix(" кредитів")
        self.vidiq_monthly_limit_spin.setValue(vidiq_status.limit)
        self.vidiq_monthly_limit_spin.valueChanged.connect(self.save_vidiq_budget)

        self.vidiq_reserve_spin = QSpinBox()
        self.vidiq_reserve_spin.setRange(0, 100000)
        self.vidiq_reserve_spin.setSingleStep(50)
        self.vidiq_reserve_spin.setSuffix(" кредитів")
        self.vidiq_reserve_spin.setValue(vidiq_status.reserve)
        self.vidiq_reserve_spin.valueChanged.connect(self.save_vidiq_budget)

        self.vidiq_used_spin = QSpinBox()
        self.vidiq_used_spin.setRange(0, vidiq_status.limit)
        self.vidiq_used_spin.setSingleStep(10)
        self.vidiq_used_spin.setSuffix(" кредитів")
        self.vidiq_used_spin.setValue(vidiq_status.used)
        self.vidiq_used_spin.valueChanged.connect(self.save_vidiq_usage)

        for spin in (
            self.daily_limit_spin,
            self.scan_limit_spin,
            self.age_limit_spin,
            self.autopilot_interval_spin,
            self.autopilot_daily_spin,
            self.quota_reserve_spin,
            self.vidiq_monthly_limit_spin,
            self.vidiq_reserve_spin,
            self.vidiq_used_spin,
        ):
            spin.setMinimumWidth(120)
            spin.setMaximumWidth(180)

        self.youtube_quota_label = QLabel()
        self.refresh_youtube_quota_label()
        self.vidiq_quota_label = QLabel()
        self.refresh_vidiq_quota_label()
        self.version_label = QLabel(f"Версія: {__version__}")
        update_btn = QPushButton("Перевірити оновлення")
        update_btn.clicked.connect(self.check_for_updates_manual)
        backup_btn = QPushButton("Зберегти робочу версію на NAS")
        backup_btn.clicked.connect(self.create_recovery_backup_now)
        restore_btn = QPushButton("Відновити робочу версію")
        restore_btn.clicked.connect(self.restore_recovery_backup_now)
        db_check_btn = QPushButton("Перевірити локальну базу")
        db_check_btn.clicked.connect(self.check_local_database)

        def settings_hint(text: str) -> QLabel:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setProperty("muted", True)
            label.setObjectName("SettingsHint")
            return label

        def settings_card(
            parent_layout: QVBoxLayout,
            title: str,
            note: str = "",
        ) -> QVBoxLayout:
            card = QFrame()
            card.setObjectName("SettingsCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(10)

            heading = QLabel(title)
            heading.setObjectName("SettingsSectionTitle")
            card_layout.addWidget(heading)
            if note:
                card_layout.addWidget(settings_hint(note))

            parent_layout.addWidget(card)
            return card_layout

        def settings_scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(12, 12, 12, 12)
            content_layout.setSpacing(12)
            scroll = QScrollArea()
            scroll.setObjectName("SettingsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            scroll.setWidget(content)
            return scroll, content_layout

        def compact_form() -> QFormLayout:
            form = QFormLayout()
            form.setLabelAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            form.setHorizontalSpacing(22)
            form.setVerticalSpacing(10)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
            )
            return form

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Канал перемикається у верхній панелі програми.
        # Прихований combo лишається для сумісності зі старою логікою профілів.
        self.profile_combo.setVisible(False)
        self.channel_label.setVisible(False)

        self.settings_sections = QTabWidget()
        self.settings_sections.setObjectName("SettingsSections")
        layout.addWidget(self.settings_sections, 1)

        # Коментарі
        comments_page, comments_layout = settings_scroll_page()

        comments_columns = QHBoxLayout()
        comments_columns.setSpacing(12)
        comments_left = QVBoxLayout()
        comments_left.setSpacing(12)
        comments_right = QVBoxLayout()
        comments_right.setSpacing(12)
        comments_columns.addLayout(comments_left, 1)
        comments_columns.addLayout(comments_right, 1)
        comments_layout.addLayout(comments_columns)

        comments_card = settings_card(
            comments_left,
            "Фонова робота з коментарями",
            "Працюємо лише з уже опублікованими коментарями. "
            "«Очікує на розгляд» програма не читає і не модерує.",
        )
        comments_card.addWidget(self.background_box)
        comments_card.addWidget(self.auto_box)

        reply_limits = compact_form()
        reply_limits.addRow("Денний ліміт", self.daily_limit_spin)
        reply_limits.addRow("За одне сканування", self.scan_limit_spin)
        reply_limits.addRow("Максимальний вік", self.age_limit_spin)
        comments_card.addLayout(reply_limits)
        comments_left.addStretch()

        templates_card = settings_card(
            comments_right,
            "Шаблони автовідповідей",
            "Тексти можна редагувати. Зміни зберігаються автоматично.",
        )
        templates_form = compact_form()
        templates_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        for label, edit in self.reply_template_edits.values():
            templates_form.addRow(label, edit)
        templates_card.addLayout(templates_form)
        comments_right.addStretch()
        comments_layout.addStretch()

        self.settings_sections.addTab(comments_page, "Коментарі")

        # Архів і квота
        archive_page, archive_layout = settings_scroll_page()

        priority_card = settings_card(
            archive_layout,
            "Пріоритет архіву",
            "Зберігає квоту для масової обробки архіву. "
            "Фоновий автопілот метаданих призупиняється, але коментарі "
            "та інші функції продовжують працювати.",
        )
        priority_card.addWidget(self.archive_priority_box)

        autopilot_card = settings_card(
            archive_layout,
            "Автопілот безпечних метаданих",
            "Змінює тільки посилання та рядок хештегів. "
            "Назви, YouTube-теги і основний текст не чіпає.",
        )
        autopilot_card.addWidget(self.safe_autopilot_box)
        autopilot_form = compact_form()
        autopilot_form.addRow("Інтервал", self.autopilot_interval_spin)
        autopilot_form.addRow("Денний ліміт відео", self.autopilot_daily_spin)
        autopilot_card.addLayout(autopilot_form)

        quota_card = settings_card(
            archive_layout,
            "YouTube API",
            "Резерв захищає квоту для важливих операцій.",
        )
        self.youtube_quota_label.setWordWrap(True)
        self.youtube_quota_label.setObjectName("QuotaSummary")
        quota_card.addWidget(self.youtube_quota_label)

        quota_form = compact_form()
        quota_form.addRow("Резерв квоти", self.quota_reserve_spin)
        quota_card.addLayout(quota_form)

        planner_settings_btn = QPushButton("Відкрити планувальник квоти")
        planner_settings_btn.clicked.connect(self.show_quota_planner)
        quota_card.addWidget(planner_settings_btn)

        vidiq_card = settings_card(
            archive_layout,
            "vidIQ · AIR Boost",
            "Один спільний ліміт для обох каналів: 2000 кредитів на акаунт "
            "щомісяця. Enterprise у vidIQ був лише помилковою назвою тарифу. "
            "Пріоритет: заплановані та нові публікації, ТОП архіву і фінальна "
            "перевірка назв. Масові описи, теги, коментарі та архів - локально.",
        )
        self.vidiq_quota_label.setWordWrap(True)
        self.vidiq_quota_label.setObjectName("QuotaSummary")
        vidiq_card.addWidget(self.vidiq_quota_label)
        vidiq_form = compact_form()
        vidiq_form.addRow("Місячний ліміт", self.vidiq_monthly_limit_spin)
        vidiq_form.addRow("Захищений резерв", self.vidiq_reserve_spin)
        vidiq_form.addRow("Використано цього місяця", self.vidiq_used_spin)
        vidiq_card.addLayout(vidiq_form)
        vidiq_card.addWidget(settings_hint(vidiq_policy_summary()))

        self._refresh_archive_priority_controls()
        archive_layout.addStretch()
        self.settings_sections.addTab(archive_page, "Архів і квота")

        # Сховища та API
        storage_page, storage_layout = settings_scroll_page()

        nas_card = settings_card(
            storage_layout,
            "NAS",
            "Шляхи до транскриптів і пакетів оптимізації.",
        )
        nas_form = compact_form()
        nas_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        nas_form.addRow("Транскрипти", self.nas_transcripts_edit)
        nas_form.addRow("Пакети оптимізації", self.nas_packages_edit)
        nas_card.addLayout(nas_form)

        oauth_card = settings_card(
            storage_layout,
            "YouTube OAuth",
            "Файл OAuth використовується для авторизації YouTube Data API.",
        )
        oauth_card.addWidget(oauth_btn)

        storage_layout.addStretch()
        self.settings_sections.addTab(storage_page, "Сховища / API")

        # Система
        system_page, system_layout = settings_scroll_page()

        update_card = settings_card(system_layout, "Версія та оновлення")
        version_row = QHBoxLayout()
        self.version_label.setObjectName("SettingsVersion")
        version_row.addWidget(self.version_label)
        version_row.addStretch()
        version_row.addWidget(update_btn)
        update_card.addLayout(version_row)

        backup_card = settings_card(
            system_layout,
            "Резервні копії",
            "Одна щоденна копія та копія перед масовими змінами. "
            "На NAS зберігаються останні 20 автоматичних копій.",
        )
        backup_row = QHBoxLayout()
        backup_row.addWidget(backup_btn)
        backup_row.addWidget(restore_btn)
        backup_row.addStretch()
        backup_card.addLayout(backup_row)

        database_card = settings_card(
            system_layout,
            "Локальна база",
            "Перевірка цілісності SQLite та безпечне очищення сирітських записів.",
        )
        database_card.addWidget(db_check_btn)

        system_layout.addStretch()
        self.settings_sections.addTab(system_page, "Система")

        self.tabs.addTab(page, "Налаштування")

    def check_local_database(self) -> None:
        try:
            report = database_integrity_cleanup(self.conn)
        except Exception as exc:
            self._error("Помилка перевірки бази", exc)
            return

        orphan_total = sum(report["orphans"].values())
        deleted_total = sum(report["deleted"].values())
        duplicate_snapshots = int(report["duplicate_snapshots"] or 0)
        lines = [
            f"SQLite integrity: {report['integrity']}",
            f"Сирітських записів знайдено: {orphan_total}",
            f"Безпечно очищено: {deleted_total}",
            f"Точних повторів snapshots: {duplicate_snapshots}",
        ]
        if duplicate_snapshots:
            lines.append(
                "Повтори snapshots не видалялись автоматично, "
                "щоб не пошкодити історію відкату."
            )
        QMessageBox.information(
            self,
            "Перевірка локальної бази",
            "\n".join(lines),
        )
        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()

    def _recovery_backup_root(self) -> Path:
        packages = self._nas_path("nas_packages_path", DEFAULT_NAS_PACKAGES_PATH)
        return packages.parent / "BACKUPS"

    def _create_automatic_recovery_backup(
        self,
        reason: str,
        *,
        force: bool = False,
        profile: str | None = None,
    ) -> Path | None:
        today = datetime.now(timezone.utc).date().isoformat()
        daily_key = "automatic_recovery_backup_day"
        if not force and get_setting(self.conn, daily_key, "") == today:
            return None

        root = self._recovery_backup_root()
        archive = create_recovery_backup(
            conn=self.conn,
            data_dir=self.data_dir,
            backup_root=root,
            version=__version__,
            include_installer=False,
            label="RG_YOUTUBE_CONTROL_AUTO",
        )
        removed = prune_recovery_backups(
            root,
            keep=20,
            prefix="RG_YOUTUBE_CONTROL_AUTO_",
        )
        set_setting(self.conn, daily_key, today)
        log_action(
            self.conn,
            profile=profile or self.current_profile,
            category="резервна копія",
            action="Автоматична копія",
            details=f"{reason} · {archive.name} · очищено старих: {removed}",
        )
        self.reload_action_log()
        return archive

    def ensure_daily_recovery_backup(self) -> None:
        try:
            self._create_automatic_recovery_backup(
                "щоденна копія",
                force=False,
            )
        except Exception as exc:
            try:
                log_action(
                    self.conn,
                    profile=self.current_profile,
                    category="резервна копія",
                    action="Помилка щоденної копії",
                    details=str(exc),
                )
            except Exception:
                pass

    def _prechange_backup_or_warn(
        self,
        reason: str,
        *,
        notify: bool = True,
    ) -> bool:
        try:
            self._create_automatic_recovery_backup(reason, force=True)
            return True
        except Exception as exc:
            log_action(
                self.conn,
                profile=self.current_profile,
                category="резервна копія",
                action="Масову зміну заблоковано",
                details=f"{reason} · {exc}",
            )
            if notify:
                QMessageBox.warning(
                    self,
                    "Резервна копія не створена",
                    "Масову зміну зупинено, тому що перед нею не вдалося "
                    "створити резервну копію на NAS.\n\n"
                    f"{exc}",
                )
            return False

    def create_recovery_backup_now(self) -> None:
        root = self._recovery_backup_root()
        answer = QMessageBox.question(
            self,
            "Резервна копія робочої версії",
            f"Створити повну резервну копію версії {__version__}?\n\n"
            f"Місце: {root}\n\n"
            "Буде збережено базу, налаштування, історію оптимізацій, "
            "службові дані та інсталятор цієї ж версії. "
            "Авторизація YouTube не копіюється; після чистої Windows "
            "потрібно буде повторно підключити два канали.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.statusBar().showMessage("Створюю резервну копію на NAS...")
        QApplication.processEvents()
        try:
            archive = create_recovery_backup(
                conn=self.conn,
                data_dir=self.data_dir,
                backup_root=root,
                version=__version__,
            )
        except Exception as exc:
            self._error("Помилка резервного копіювання", exc)
            return

        QMessageBox.information(
            self,
            "Резервну копію створено",
            "Робочу версію збережено.\n\n"
            f"Архів відновлення:\n{archive}\n\n"
            "Після перевстановлення Windows встановіть збережений "
            "інсталятор, відновіть цей архів і повторно підключіть два "
            "YouTube-канали.",
        )
        self.statusBar().showMessage("Резервну копію робочої версії створено")

    def restore_recovery_backup_now(self) -> None:
        root = self._recovery_backup_root()
        archive_name, _filter = QFileDialog.getOpenFileName(
            self,
            "Виберіть recovery.zip",
            str(root),
            "RG YouTube Control recovery (recovery.zip);;ZIP (*.zip)",
        )
        if not archive_name:
            return

        archive = Path(archive_name)
        try:
            manifest = read_recovery_manifest(archive)
        except Exception as exc:
            self._error("Некоректна резервна копія", exc)
            return

        version = str(manifest.get("version") or "?")
        created = str(manifest.get("created_at_utc") or "?")
        answer = QMessageBox.question(
            self,
            "Відновити робочу версію",
            f"Версія копії: {version}\n"
            f"Створено: {created}\n\n"
            "Поточну локальну базу й налаштування буде замінено. "
            "Після відновлення програма закриється. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.scan_timer.stop()
            self.conn.close()
            restore_recovery_backup(data_dir=self.data_dir, archive=archive)
        except Exception as exc:
            QMessageBox.critical(self, "Помилка відновлення", str(exc))
            return

        QMessageBox.information(
            self,
            "Відновлення завершено",
            "Базу та налаштування відновлено. Програма зараз закриється.\n\n"
            "Після запуску повторно підключіть YouTube-канали, якщо Windows "
            "було перевстановлено.",
        )
        QTimer.singleShot(300, QApplication.quit)


    def _save_nas_path_setting(
        self,
        key: str,
        edit: QLineEdit,
        default: str,
    ) -> None:
        normalized = normalize_nas_unc_path(edit.text(), default)
        edit.setText(normalized)
        set_setting(self.conn, key, normalized)

    def _nas_path(self, key: str, default: str) -> Path:
        raw = get_setting(self.conn, key, default)
        normalized = normalize_nas_unc_path(raw, default)
        if normalized != raw:
            set_setting(self.conn, key, normalized)
        return Path(normalized)

    def refresh_youtube_quota_label(self) -> None:
        if not hasattr(self, "youtube_quota_label"):
            return
        budget = quota_budget_status(self.conn)
        breakdown = today_quota_breakdown(self.conn)
        purpose_text = (
            f"відео {breakdown['video']} · "
            f"коментарі {breakdown['comments']} · "
            f"службове {breakdown['service']}"
        )
        if breakdown["legacy"]:
            purpose_text += f" · до обліку {breakdown['legacy']}"
        if bool(budget["exhausted"]):
            text = (
                f"ВИЧЕРПАНО · враховано ≈{budget['used']}/"
                f"{YOUTUBE_DAILY_QUOTA_DEFAULT} · {purpose_text} · "
                f"скидання {budget['reset']}"
            )
        else:
            text = (
                f"Враховано ≈{budget['used']}/{YOUTUBE_DAILY_QUOTA_DEFAULT} · "
                f"{purpose_text} · залишок ≈{budget['remaining']} · "
                f"резерв {budget['reserve']}"
            )
        self.youtube_quota_label.setText(text)

    def refresh_vidiq_quota_label(self) -> None:
        if not hasattr(self, "vidiq_quota_label"):
            return
        status = vidiq_budget_status(self.conn)
        reset_text = status.reset_at or "не синхронізовано"
        self.vidiq_quota_label.setText(
            f"{status.plan} · {status.period} · "
            f"зафіксовано {status.used}/{status.limit} · "
            f"залишок {status.remaining} · резерв {status.reserve} · "
            f"доступно поза пріоритетом {status.spendable} · "
            f"наступне поповнення {reset_text}"
        )

    def _quota_update_video_with_client(
        self,
        client: YouTubeClient,
        video_id: str,
        *,
        respect_reserve: bool = False,
        safe_mode: bool = False,
        **kwargs,
    ) -> None:
        if safe_mode:
            _validate_safe_update_fields(set(kwargs))

        budget = quota_budget_status(self.conn)
        if bool(budget["exhausted"]):
            raise RuntimeError(
                "Денну квоту YouTube Data API вже вичерпано. "
                "Продовжіть після її відновлення."
            )
        if respect_reserve and int(budget["spendable"]) < VIDEO_UPDATE_COST:
            raise RuntimeError(
                "Досягнуто резерву квоти. Автоматичні безпечні зміни "
                "призупинено до наступного квотного дня."
            )
        try:
            client.update_video(video_id, **kwargs)
        except Exception as exc:
            if _is_quota_exceeded_error(exc):
                mark_quota_exhausted(self.conn)
                self.refresh_youtube_quota_label()
            raise
        record_quota_units(self.conn, VIDEO_UPDATE_COST, purpose="video")
        log_action(
            self.conn,
            profile=getattr(client, "profile", self.current_profile),
            category="YouTube",
            action="Оновлено відео",
            details=f"{video_id}: {', '.join(sorted(kwargs.keys()))}",
        )
        self.refresh_youtube_quota_label()

    def _quota_update_video(self, video_id: str, **kwargs) -> None:
        self._quota_update_video_with_client(
            self.client,
            video_id,
            **kwargs,
        )

    def switch_profile(self, _index: int) -> None:
        profile = self.profile_combo.currentData()
        if not profile:
            return
        self._activate_profile(str(profile))

    def choose_oauth_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "JSON клієнта OAuth", str(Path.home()), "JSON (*.json)"
        )
        if path:
            set_setting(self.conn, "client_secret_path", path)
            self.statusBar().showMessage("OAuth JSON вибрано")

    def connect_youtube(self) -> None:
        path = get_setting(self.conn, "client_secret_path")
        if not path:
            self.choose_oauth_file()
            path = get_setting(self.conn, "client_secret_path")
        if not path:
            return
        try:
            profile = self.client.authorize(path)
            expected = PROFILE_TARGETS[self.current_profile]
            if profile.channel_id != expected:
                self.client.clear_credentials()
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "Авторизовано інший канал. Виберіть потрібний канал YouTube "
                    f"для профілю {PROFILE_LABELS[self.current_profile]}.",
                )
                return
            self.channel_label.setText(
                f"YouTube: {profile.channel_title} · {profile.channel_id}"
            )
            set_setting(
                self.conn, f"channel_id_{self.current_profile}", profile.channel_id
            )
            set_setting(
                self.conn, f"channel_title_{self.current_profile}", profile.channel_title
            )
            self._refresh_channel_header()
            self.update_dashboard()
            self.statusBar().showMessage("YouTube підключено")
        except Exception as exc:
            self._error("Помилка авторизації", exc)

    def sync_upcoming_streams_startup(self) -> None:
        """Refresh upcoming broadcasts on both channels once after startup."""
        cleaned = cleanup_stale_scheduled_rows(self.conn)
        if cleaned:
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
        if quota_exhausted(self.conn):
            return

        before_units = today_quota_units(self.conn)
        synced = 0
        for profile in PROFILE_TARGETS:
            client = YouTubeClient(profile=profile)
            try:
                client.credentials()
                rows = sync_upcoming_live_broadcasts(
                    client,
                    self.conn,
                )
                synced += len(rows)
            except Exception as exc:
                if _is_quota_exceeded_error(exc):
                    mark_quota_exhausted(self.conn)
                    break
                continue

        if synced:
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            consumed = max(
                0,
                today_quota_units(self.conn) - before_units,
            )
            self.statusBar().showMessage(
                f"Заплановані ефіри оновлено: {synced} · "
                f"квота читання: {consumed}"
            )

    def sync_video_list(self) -> None:
        try:
            if quota_exhausted(self.conn):
                QMessageBox.information(
                    self,
                    "Квоту YouTube вичерпано",
                    "Синхронізацію через YouTube Data API заблоковано до "
                    "наступного квотного дня. Локальна 0-quota підготовка "
                    "залишається доступною.",
                )
                return
            before_units = today_quota_units(self.conn)
            rows = sync_videos(self.client, self.conn, limit=50)
            upcoming = sync_upcoming_live_broadcasts(
                self.client,
                self.conn,
            )
            consumed = max(0, today_quota_units(self.conn) - before_units)
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            self.statusBar().showMessage(
                f"Відео синхронізовано: {len(rows)} · "
                f"майбутніх ефірів: {len(upcoming)} · "
                f"квота читання: {consumed}"
            )
        except Exception as exc:
            self._error("Помилка синхронізації", exc)

    def sync_both_channels(self) -> None:
        if quota_exhausted(self.conn):
            QMessageBox.information(
                self,
                "Квоту YouTube вичерпано",
                "Синхронізацію двох каналів через YouTube Data API "
                "заблоковано до наступного квотного дня.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Синхронізація двох каналів",
            "Синхронізувати архіви РАША ГУДБАЙ і РАША ГУДБАЙ LIVE? "
            "Це лише читання метаданих.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        before_units = today_quota_units(self.conn)
        results: list[str] = []
        errors: list[str] = []
        for profile in PROFILE_TARGETS:
            client = YouTubeClient(profile=profile)
            try:
                client.credentials()
            except Exception:
                errors.append(f"{PROFILE_LABELS[profile]}: не підключено")
                continue
            try:
                rows = sync_videos(client, self.conn, limit=1000)
                results.append(f"{PROFILE_LABELS[profile]}: {len(rows)}")
            except Exception as exc:
                errors.append(f"{PROFILE_LABELS[profile]}: {exc}")

        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()
        self.update_dashboard()
        consumed = max(0, today_quota_units(self.conn) - before_units)
        message = (
            "Синхронізовано:\n" + ("\n".join(results) or "—")
            + f"\n\nКвота читання YouTube Data API: {consumed} од."
        )
        if errors:
            message += "\n\nНе виконано:\n" + "\n".join(errors)
        QMessageBox.information(self, APP_NAME, message)

    def edit_selected_video(self) -> None:
        row = self.video_table.currentRow()
        if row < 0:
            return
        video_id = self.video_table.item(row, 0).text()
        try:
            current_title, current_description, current_tags = (
                self._current_video_metadata(video_id)
            )
            dialog = MetadataDialog(
                current_title,
                current_description,
                current_tags,
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            title, description, tags = dialog.values()
            if not title:
                QMessageBox.warning(self, APP_NAME, "Назва не може бути порожньою.")
                return
            save_metadata_snapshot(
                self.conn,
                video_id,
                current_title,
                current_description,
                current_tags,
                "before_manual_edit",
            )
            self._quota_update_video(
                video_id, title=title, description=description, tags=tags
            )
            self.sync_video_list()
            self.statusBar().showMessage("Метадані відео оновлено")
        except Exception as exc:
            self._error("Помилка оновлення відео", exc)

    def sync_full_archive(self) -> None:
        answer = QMessageBox.question(
            self,
            "Повна синхронізація архіву",
            "Синхронізувати весь архів каналу? Це лише читання метаданих "
            "і не змінить відео.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            before_units = today_quota_units(self.conn)
            self.statusBar().showMessage("Синхронізую весь архів...")
            QApplication.processEvents()
            rows = sync_videos(self.client, self.conn, limit=1000)
            consumed = max(0, today_quota_units(self.conn) - before_units)
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            stored = self.conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE profile=?",
                (self.current_profile,),
            ).fetchone()["n"]
            latin_titles = self._latin_title_review_count()
            self.statusBar().showMessage(
                f"Архів синхронізовано: {len(rows)} унікальних відео · "
                f"у базі профілю: {stored} · англомовних назв: {latin_titles} · "
                f"квота читання: {consumed}"
            )
        except Exception as exc:
            self._error("Помилка повної синхронізації", exc)

    def _selected_optimization_video_ids(self) -> list[str]:
        if not hasattr(self, "optimization_table"):
            return []
        rows = self.optimization_table.selectionModel().selectedRows(3)
        result: list[str] = []
        for index in rows:
            value = index.data(Qt.ItemDataRole.UserRole) or index.data(
                Qt.ItemDataRole.DisplayRole
            )
            if value:
                result.append(str(value))
        return result

    @staticmethod
    def _optimization_checkpoint_text(raw_date: str | None) -> tuple[str, str]:
        if not raw_date:
            return "—", "—"
        try:
            optimized = datetime.fromisoformat(
                str(raw_date).replace("Z", "+00:00")
            ).date()
        except Exception:
            return str(raw_date)[:10], "—"

        today = datetime.now(timezone.utc).date()
        parts: list[str] = []
        next_date = ""
        for days in (7, 28, 90):
            due = optimized + timedelta(days=days)
            if today >= due:
                parts.append(f"{days} ✓")
            else:
                parts.append(f"{days}: {due.strftime('%d.%m.%Y')}")
                if not next_date:
                    next_date = due.isoformat()
        if not next_date:
            next_date = "усі готові"
        return optimized.isoformat(), " · ".join(parts)

    def _latin_title_review_count(self, profile: str | None = None) -> int:
        target_profile = profile or self.current_profile
        rows = self.conn.execute(
            "SELECT audit_json FROM videos WHERE profile=?",
            (target_profile,),
        ).fetchall()
        count = 0
        for row in rows:
            try:
                issues = json.loads(row["audit_json"] or "{}").get("issues", [])
            except Exception:
                issues = []
            if "latin_title_review" in issues:
                count += 1
        return count

    def _title_review_path(self) -> Path:
        package_dir = self._nas_path(
            "nas_packages_path",
            DEFAULT_NAS_PACKAGES_PATH,
        )
        return package_dir / f"title_review_{self.current_profile}.json"

    def _load_title_review_payload(self) -> tuple[Path, dict]:
        path = self._title_review_path()
        if not path.exists():
            raise RuntimeError(
                "Файл перевірки назв ще не створено. "
                "Натисніть «Англомовні назви → NAS»."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("Некоректний формат файлу перевірки назв.")
        if str(payload.get("profile") or "") != self.current_profile:
            raise RuntimeError(
                "Файл виправлень належить іншому профілю каналу."
            )
        if not isinstance(payload.get("items"), list):
            raise RuntimeError("У файлі немає списку items.")
        return path, payload

    def _validated_title_corrections(
        self,
        payload: dict,
    ) -> tuple[list[dict[str, str]], list[str], int]:
        current_rows = self.conn.execute(
            "SELECT video_id,title,audit_json FROM videos WHERE profile=?",
            (self.current_profile,),
        ).fetchall()
        current = {
            str(row["video_id"]): row
            for row in current_rows
        }
        valid: list[dict[str, str]] = []
        blocked: list[str] = []
        missing = 0

        for raw in payload.get("items", []):
            if not isinstance(raw, dict):
                continue
            video_id = str(raw.get("video_id") or "").strip()
            exported_title = str(raw.get("title") or "").strip()
            new_title = _standard_hyphen(
                str(raw.get("new_title") or "").strip()
            )
            if not video_id or not exported_title:
                blocked.append(f"{video_id or '?'}: немає вихідної назви")
                continue
            if not new_title:
                missing += 1
                continue
            if len(new_title) > 100:
                blocked.append(f"{video_id}: нова назва довша за 100 символів")
                continue
            if title_script_profile(new_title) == "latin":
                blocked.append(
                    f"{video_id}: нова назва досі англомовна"
                )
                continue

            row = current.get(video_id)
            if row is None:
                blocked.append(f"{video_id}: відео немає у локальній базі")
                continue
            current_title = str(row["title"] or "").strip()
            if current_title != exported_title:
                blocked.append(
                    f"{video_id}: поточна назва вже відрізняється від експортованої"
                )
                continue
            try:
                issues = json.loads(row["audit_json"] or "{}").get("issues", [])
            except Exception:
                issues = []
            if "latin_title_review" not in issues:
                blocked.append(
                    f"{video_id}: відео вже не потребує мовного виправлення"
                )
                continue
            if new_title == current_title:
                blocked.append(f"{video_id}: назва не змінюється")
                continue

            valid.append(
                {
                    "video_id": video_id,
                    "old_title": current_title,
                    "new_title": new_title,
                }
            )

        return valid, blocked, missing

    def export_latin_title_review_to_nas(self) -> None:
        try:
            path = self._title_review_path()
            path.parent.mkdir(parents=True, exist_ok=True)

            previous_titles: dict[str, str] = {}
            if path.exists():
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                    for item in previous.get("items", []):
                        if isinstance(item, dict):
                            video_id = str(item.get("video_id") or "")
                            new_title = str(item.get("new_title") or "").strip()
                            if video_id and new_title:
                                previous_titles[video_id] = new_title
                except Exception:
                    previous_titles = {}

            rows = self.conn.execute(
                """SELECT video_id,title,published_at,views,audit_json
                   FROM videos
                   WHERE profile=?
                   ORDER BY views DESC,published_at DESC""",
                (self.current_profile,),
            ).fetchall()

            items = []
            for row in rows:
                try:
                    issues = json.loads(row["audit_json"] or "{}").get(
                        "issues", []
                    )
                except Exception:
                    issues = []
                if "latin_title_review" not in issues:
                    continue
                video_id = str(row["video_id"])
                items.append(
                    {
                        "video_id": video_id,
                        "title": str(row["title"] or ""),
                        "new_title": previous_titles.get(video_id, ""),
                        "published_at": str(row["published_at"] or ""),
                        "views": int(row["views"] or 0),
                    }
                )

            payload = {
                "schema_version": 1,
                "profile": self.current_profile,
                "channel_id": PROFILE_TARGETS[self.current_profile],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(items),
                "instructions": (
                    "Заповніть new_title кирилицею. video_id та title не змінювати."
                ),
                "items": items,
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            QMessageBox.information(
                self,
                "Англомовні назви",
                f"Експортовано: {len(items)}.\n"
                f"Квота YouTube не витрачалась.\n\n{path}",
            )
            self.statusBar().showMessage(
                f"Англомовні назви експортовано: {len(items)} · квота: 0"
            )
        except Exception as exc:
            self._error("Помилка експорту назв", exc)

    def preview_title_corrections(self) -> None:
        try:
            path, payload = self._load_title_review_payload()
            valid, blocked, missing = self._validated_title_corrections(payload)

            lines = [
                f"Файл: {path}",
                f"Готово до застосування: {len(valid)}",
                f"Без new_title: {missing}",
                f"Заблоковано перевіркою: {len(blocked)}",
                "",
            ]
            for index, item in enumerate(valid, start=1):
                lines.extend(
                    [
                        f"{index}. {item['video_id']}",
                        f"ДО: {item['old_title']}",
                        f"ПІСЛЯ: {item['new_title']}",
                        "",
                    ]
                )
            if blocked:
                lines.append("ЗАБЛОКОВАНО:")
                lines.extend(f"- {value}" for value in blocked)

            dialog = QDialog(self)
            dialog.setWindowTitle("Перегляд виправлень назв")
            dialog.resize(980, 720)
            layout = QVBoxLayout(dialog)
            editor = QPlainTextEdit("\n".join(lines))
            editor.setReadOnly(True)
            layout.addWidget(editor)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрити")
            buttons.rejected.connect(dialog.reject)
            buttons.accepted.connect(dialog.accept)
            layout.addWidget(buttons)
            dialog.exec()
        except Exception as exc:
            self._error("Помилка перегляду назв", exc)

    def apply_title_corrections(self) -> None:
        try:
            path, payload = self._load_title_review_payload()
            valid, blocked, missing = self._validated_title_corrections(payload)
            batch = valid[:DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT]
            if not batch:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    f"Немає готових виправлень назв. "
                    f"Без new_title: {missing}. Заблоковано: {len(blocked)}.",
                )
                return

            estimated = len(batch) * (VIDEO_UPDATE_COST + READ_REQUEST_COST)
            answer = QMessageBox.question(
                self,
                "Застосувати виправлення назв",
                f"Готово виправлень: {len(valid)}.\n"
                f"Зараз буде застосовано: {len(batch)}.\n"
                f"Орієнтовна квота: ≈{estimated} од.\n\n"
                "Змінюється лише назва відео. Опис, теги YouTube, "
                "прев'ю та налаштування публікації не змінюються. "
                "Продовжити?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

            if not self._prechange_backup_or_warn(
                f"перед виправленням мови назв · {self.current_profile}"
            ):
                return

            item_by_id = {
                str(item.get("video_id") or ""): item
                for item in payload.get("items", [])
                if isinstance(item, dict)
            }
            changed_ids: list[str] = []
            reconciled_ids: list[str] = []
            errors: list[str] = []

            for index, correction in enumerate(batch, start=1):
                video_id = correction["video_id"]
                self.statusBar().showMessage(
                    f"Виправлення назв: {index}/{len(batch)} · {video_id}"
                )
                QApplication.processEvents()
                try:
                    current_title, description, tags = (
                        self._current_video_metadata(video_id)
                    )
                    new_title = correction["new_title"]
                    if current_title == new_title:
                        reconcile_local_video_title(
                            self.conn,
                            video_id=video_id,
                            title=new_title,
                            description=description,
                            tags=tags,
                        )
                        reconciled_ids.append(video_id)
                        item = item_by_id.get(video_id)
                        if item is not None:
                            item["applied_at"] = (
                                item.get("applied_at")
                                or datetime.now(timezone.utc).isoformat()
                            )
                            item["applied_title"] = new_title
                        continue
                    if current_title != correction["old_title"]:
                        raise RuntimeError(
                            "Назва змінилася після експорту і не збігається "
                            "з підготовленим виправленням. Пропущено."
                        )
                    if title_script_profile(new_title) == "latin":
                        raise RuntimeError(
                            "Нова назва визначена як англомовна."
                        )

                    history_id = save_metadata_snapshot(
                        self.conn,
                        video_id,
                        current_title,
                        description,
                        tags,
                        "before_title_language_correction",
                    )
                    self._quota_update_video(video_id, title=new_title)
                    reconcile_local_video_title(
                        self.conn,
                        video_id=video_id,
                        title=new_title,
                        description=description,
                        tags=tags,
                    )
                    record_optimization_event(
                        self.conn,
                        history_id=history_id,
                        video_id=video_id,
                        profile=self.current_profile,
                        reason="title_language_correction",
                        changed_fields="назва · виправлення мови",
                    )
                    changed_ids.append(video_id)
                    item = item_by_id.get(video_id)
                    if item is not None:
                        item["applied_at"] = datetime.now(timezone.utc).isoformat()
                        item["applied_title"] = new_title
                except Exception as exc:
                    errors.append(f"{video_id}: {exc}")
                    if _is_quota_exceeded_error(exc):
                        mark_quota_exhausted(self.conn)
                        break

            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # YouTube's immediate videos.list may briefly return stale title
            # data after a successful videos.update. The update response was
            # already verified, so keep the confirmed local state and let the
            # next normal synchronization re-check it later.
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()

            completed = len(changed_ids) + len(reconciled_ids)
            message = (
                f"Виправлено назв: {len(changed_ids)}.\n"
                f"Вже було застосовано на YouTube: {len(reconciled_ids)}.\n"
                f"Залишилось готових до наступного пакета: "
                f"{max(0, len(valid) - completed)}."
            )
            if errors:
                message += (
                    f"\nПомилок: {len(errors)}.\n\n"
                    + "\n".join(errors[:6])
                )
            QMessageBox.information(self, APP_NAME, message)
        except Exception as exc:
            self._error("Помилка виправлення назв", exc)

    def cleanup_cached_updates(self) -> None:
        try:
            removed = prune_cached_updates(keep=3)
            if removed:
                log_action(
                    self.conn,
                    profile=self.current_profile,
                    category="система",
                    action="Очищення оновлень",
                    details=f"видалено старих файлів: {len(removed)}",
                )
        except Exception:
            pass

    def recover_archive_campaign_state(self) -> None:
        if not archive_priority_enabled(self.conn):
            return
        try:
            stats = self._archive_campaign_stats()
            checkpoint, interrupted = reconcile_campaign_checkpoint(
                self.conn,
                stats,
            )
            if interrupted:
                log_action(
                    self.conn,
                    profile=checkpoint.get("target") or self.current_profile,
                    category="кампанія архіву",
                    action="Відновлено після переривання",
                    details=(
                        f"етап {checkpoint.get('phase', '')} · "
                        f"{checkpoint.get('target', '')}; "
                        "продовження з поточного стану бази"
                    ),
                )
            self._advance_archive_campaign()
        except Exception as exc:
            log_action(
                self.conn,
                profile=self.current_profile,
                category="кампанія архіву",
                action="Відновлення відкладено",
                details=str(exc),
            )

    def _archive_campaign_stats(self) -> dict[str, dict[str, int]]:
        transcript_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        return {
            profile: archive_profile_stats(
                self.conn,
                profile,
                transcript_dir=transcript_dir,
            )
            for profile in PROFILE_TARGETS
        }

    def _archive_campaign_stats_cached(
        self,
        *,
        max_age_seconds: float = 300.0,
    ) -> dict[str, dict[str, int]]:
        now = time.monotonic()
        cached = getattr(self, "_dashboard_archive_stats_cache", None)
        cached_at = float(
            getattr(self, "_dashboard_archive_stats_cache_at", 0.0) or 0.0
        )
        if cached is not None and now - cached_at < max_age_seconds:
            return cached
        value = self._archive_campaign_stats()
        self._dashboard_archive_stats_cache = value
        self._dashboard_archive_stats_cache_at = now
        return value

    def _archive_campaign_budget(self) -> dict[str, int | str | bool]:
        budget = quota_budget_status(self.conn)
        fresh_spendable = max(
            0,
            YOUTUBE_DAILY_QUOTA_DEFAULT - int(budget["reserve"]),
        )
        current_capacity = reserve_safe_daily_batch_capacity(
            int(budget["spendable"]),
            500,
        )
        fresh_capacity = reserve_safe_daily_batch_capacity(
            fresh_spendable,
            500,
        )
        return {
            **budget,
            "current_capacity": current_capacity,
            "fresh_capacity": fresh_capacity,
        }

    def _refresh_archive_campaign_summary(self) -> None:
        if not hasattr(self, "archive_campaign_summary"):
            return
        stats = self._archive_campaign_stats()
        budget = self._archive_campaign_budget()
        phase, target = next_campaign_phase(stats)
        total_safe = sum(
            int(item["safe_remaining"])
            for item in stats.values()
        )
        fresh_capacity = int(budget["fresh_capacity"])
        days = (
            math.ceil(total_safe / fresh_capacity)
            if total_safe > 0 and fresh_capacity > 0
            else 0
        )
        phase_text = {
            ("safe", "main"): "основний канал · безпечний архів",
            ("safe", "live"): "LIVE · безпечний архів",
            ("deep", "main"): "основний канал · глибока оптимізація",
            ("deep", "live"): "LIVE · глибока оптимізація",
            ("complete", ""): "кампанію завершено",
        }.get((phase, target), "—")
        main = stats.get("main", {})
        live = stats.get("live", {})
        self.archive_campaign_summary.setText(
            "Кампанія архіву · "
            f"етап: {phase_text} · "
            f"безпечних: основний {main.get('safe_remaining', 0)}, "
            f"LIVE {live.get('safe_remaining', 0)} · "
            f"глибока черга: {main.get('deep_remaining', 0)} + "
            f"{live.get('deep_remaining', 0)} · "
            f"сьогодні можна ≈{budget['current_capacity']} · "
            f"свіжий день ≈{fresh_capacity}"
            + (f" · до завершення безпечного архіву ≈{days} дн." if days else "")
            + f" · скидання {budget['reset']}"
        )

    def _advance_archive_campaign(self, *, notify: bool = False) -> None:
        stats = self._archive_campaign_stats()
        self._dashboard_archive_stats_cache = stats
        self._dashboard_archive_stats_cache_at = time.monotonic()
        phase, target = next_campaign_phase(stats)
        save_campaign_checkpoint(
            self.conn,
            phase=phase,
            target=target,
            status="complete" if phase == "complete" else "ready",
            note="",
        )
        if phase == "complete":
            if archive_priority_enabled(self.conn):
                set_archive_priority_mode(
                    self.conn,
                    False,
                    tuple(PROFILE_TARGETS.keys()),
                )
                if hasattr(self, "archive_priority_box"):
                    self.archive_priority_box.blockSignals(True)
                    self.archive_priority_box.setChecked(False)
                    self.archive_priority_box.blockSignals(False)
                    self._refresh_archive_priority_controls()
                if hasattr(self, "safe_autopilot_box"):
                    restored = (
                        get_setting(
                            self.conn,
                            f"safe_metadata_autopilot_{self.current_profile}",
                            "0",
                        )
                        == "1"
                    )
                    self.safe_autopilot_box.blockSignals(True)
                    self.safe_autopilot_box.setChecked(restored)
                    self.safe_autopilot_box.blockSignals(False)
                log_action(
                    self.conn,
                    profile=self.current_profile,
                    category="кампанія архіву",
                    action="Завершено",
                    details=(
                        "обидва канали пройдено; попередній стан "
                        "автопілота метаданих відновлено"
                    ),
                )
                if notify:
                    QMessageBox.information(
                        self,
                        "Кампанію архіву завершено",
                        "Основний канал і LIVE завершили безпечний та "
                        "глибокий етапи. Пріоритет архіву вимкнено, "
                        "попередній стан автопілота метаданих відновлено. "
                        "Коментарі весь час продовжували працювати.",
                    )
            self._refresh_archive_campaign_summary()
            return

        if target and target != self.current_profile:
            self._activate_profile(target)
            self.statusBar().showMessage(
                "Кампанія архіву: наступний етап · "
                f"{PROFILE_LABELS[target]}"
            )
        self._refresh_archive_campaign_summary()

    def export_deep_review_queue_to_nas(
        self,
        profile: str | None = None,
        *,
        notify: bool = True,
    ) -> None:
        target = profile or self.current_profile
        stats = self._archive_campaign_stats()
        if int(stats.get(target, {}).get("safe_remaining", 0)) > 0:
            if notify:
                QMessageBox.information(
                    self,
                    "Глибока оптимізація",
                    f"Спочатку завершіть безпечний архів каналу "
                    f"{PROFILE_LABELS[target]}. Залишилося: "
                    f"{stats[target]['safe_remaining']}.",
                )
            return

        transcript_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        package_dir = self._nas_path(
            "nas_packages_path",
            DEFAULT_NAS_PACKAGES_PATH,
        )
        path, exported, total = export_deep_review_manifest(
            self.conn,
            target,
            transcript_dir=transcript_dir,
            package_dir=package_dir,
            limit=20,
        )
        items, _ = deep_review_candidates(
            self.conn,
            target,
            limit=20,
        )
        transcript_ready = sum(
            1
            for item in items
            if (transcript_dir / f"{item['video_id']}.srt").exists()
        )
        self.reload_optimization_queue()
        self._refresh_archive_campaign_summary()
        if notify:
            QMessageBox.information(
                self,
                "Глибока черга",
                f"Канал: {PROFILE_LABELS[target]}\n"
                f"Експортовано: {exported} з {total}.\n"
                f"Транскрипт уже є: {transcript_ready}/{exported}.\n"
                "Квота YouTube: 0.\n\n"
                f"{path}\n\n"
                "Усі майбутні пакети з цієї черги імпортуються тільки "
                "як чернетки. Автоматичне застосування заборонено.",
            )

    def import_deep_review_packages(
        self,
        profile: str | None = None,
        *,
        notify: bool = True,
    ) -> int:
        target = profile or self.current_profile
        package_dir = self._nas_path(
            "nas_packages_path",
            DEFAULT_NAS_PACKAGES_PATH,
        )
        manifest_path = package_dir / f"deep_review_{target}.json"
        if not manifest_path.exists():
            if notify:
                QMessageBox.information(
                    self,
                    "Глибока черга",
                    "Спочатку експортуйте глибоку чергу на NAS.",
                )
            return 0

        try:
            payload = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            items = payload.get("items") or []
            imported = 0
            missing = 0
            failed: list[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                video_id = str(item.get("video_id") or "").strip()
                if not video_id:
                    continue
                package_path = Path(
                    str(item.get("package_path") or package_dir / f"{video_id}.json")
                )
                if not package_path.exists():
                    missing += 1
                    continue
                try:
                    deep_payload = json.loads(
                        package_path.read_text(encoding="utf-8")
                    )
                    self._save_package_payload(
                        video_id,
                        deep_payload,
                        force_draft=True,
                    )
                    set_deep_review_state(
                        self.conn,
                        video_id=video_id,
                        profile=target,
                        status="review",
                        note="package_imported_as_draft",
                    )
                    imported += 1
                except Exception as exc:
                    failed.append(f"{video_id}: {exc}")

            self.reload_optimization_queue()
            self._refresh_archive_campaign_summary()
            message = (
                f"Імпортовано чернеток: {imported}.\n"
                f"Пакетів ще немає: {missing}.\n"
                "Квота YouTube: 0.\n\n"
                "Перед застосуванням кожен пакет потрібно відкрити, "
                "переглянути зміни та вручну перевести у «Готово»."
            )
            if failed:
                message += (
                    f"\nПомилок: {len(failed)}.\n"
                    + "\n".join(failed[:5])
                )
            if notify:
                QMessageBox.information(
                    self,
                    "Глибокі пакети",
                    message,
                )
            return imported
        except Exception as exc:
            if notify:
                self._error("Помилка імпорту глибоких пакетів", exc)
            else:
                log_action(
                    self.conn,
                    profile=target,
                    category="кампанія архіву",
                    action="Імпорт deep-пакетів відкладено",
                    details=str(exc),
                )
            return 0

    def export_deep_review_transcripts(
        self,
        profile: str | None = None,
        *,
        confirm: bool = True,
        notify: bool = True,
    ) -> None:
        target = profile or self.current_profile
        if target != self.current_profile:
            self._activate_profile(target)

        package_dir = self._nas_path(
            "nas_packages_path",
            DEFAULT_NAS_PACKAGES_PATH,
        )
        transcript_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        manifest_path = package_dir / f"deep_review_{target}.json"
        if not manifest_path.exists():
            if notify:
                QMessageBox.information(
                    self,
                    "Транскрипти глибокої черги",
                    "Спочатку експортуйте глибоку чергу на NAS.",
                )
            return

        try:
            payload = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            items = [
                item
                for item in (payload.get("items") or [])
                if isinstance(item, dict)
            ]
            pending = [
                item
                for item in items
                if item.get("video_id")
                and not (
                    transcript_dir / f"{item['video_id']}.srt"
                ).exists()
            ]
            if not pending:
                if notify:
                    QMessageBox.information(
                        self,
                        "Транскрипти глибокої черги",
                        "Усі транскрипти поточної глибокої черги вже є на NAS.",
                    )
                return

            budget = quota_budget_status(self.conn)
            capacity = max(
                0,
                int(budget["spendable"]) // CAPTION_TRANSCRIPT_COST,
            )
            batch = pending[: min(20, capacity)]
            if not batch:
                if notify:
                    QMessageBox.information(
                        self,
                        "Резерв квоти",
                        "Над захищеним резервом недостатньо квоти "
                        "для нового транскрипту.",
                    )
                return

            estimated = len(batch) * CAPTION_TRANSCRIPT_COST
            if confirm:
                answer = QMessageBox.question(
                    self,
                    "Транскрипти глибокої черги",
                    f"Канал: {PROFILE_LABELS[target]}\n"
                    f"Без транскрипту: {len(pending)}.\n"
                    f"Зараз буде отримано: до {len(batch)}.\n"
                    f"Максимальна витрата: ≈{estimated} од. квоти.\n"
                    f"Резерв {budget['reserve']} од. не буде використано.\n\n"
                    "Продовжити?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

            saved = 0
            failed: list[str] = []
            for index, item in enumerate(batch, start=1):
                video_id = str(item["video_id"])
                self.statusBar().showMessage(
                    f"Глибокі транскрипти: {index}/{len(batch)} · {video_id}"
                )
                QApplication.processEvents()
                try:
                    path, _downloaded = self._export_transcript_video_to_nas(
                        video_id,
                        respect_reserve=True,
                    )
                    item["transcript_ready"] = True
                    item["transcript_path"] = str(path)
                    saved += 1
                except Exception as exc:
                    failed.append(f"{video_id}: {exc}")

            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            manifest_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.reload_optimization_queue()
            self._refresh_archive_campaign_summary()

            message = (
                f"Збережено транскриптів: {saved}.\n"
                f"Помилок: {len(failed)}."
            )
            if failed:
                message += "\n\n" + "\n".join(failed[:5])
            if notify:
                QMessageBox.information(
                    self,
                    "Транскрипти глибокої черги",
                    message,
                )
        except Exception as exc:
            self._error("Помилка транскриптів глибокої черги", exc)

    def run_archive_campaign_step(self, *, automatic: bool = False) -> bool:
        stats = self._archive_campaign_stats()
        phase, target = next_campaign_phase(stats)
        if phase == "complete":
            save_campaign_checkpoint(
                self.conn,
                phase="complete",
                target="",
                status="complete",
                note="campaign_complete",
            )
            self._advance_archive_campaign(notify=not automatic)
            return True

        if target:
            self._activate_profile(target)

        budget = self._archive_campaign_budget()
        if phase == "safe" and int(budget["current_capacity"]) <= 0:
            save_campaign_checkpoint(
                self.conn,
                phase=phase,
                target=target,
                status="paused_quota",
                note="protected_comment_reserve",
            )
            self.statusBar().showMessage(
                "Кампанія архіву: пауза до нового квотного дня - "
                "резерв коментарів не використовується"
            )
            return False

        save_campaign_checkpoint(
            self.conn,
            phase=phase,
            target=target,
            status="running",
            note="automatic" if automatic else "manual",
        )

        if phase == "safe":
            self.apply_next_safe_archive_batch(
                daily=True,
                confirm=not automatic,
                notify=not automatic,
            )
        elif phase == "deep":
            self.export_deep_review_queue_to_nas(
                target,
                notify=not automatic,
            )
            if int(budget.get("deep_transcript_capacity", 0)) > 0:
                self.export_deep_review_transcripts(
                    target,
                    confirm=False,
                    notify=not automatic,
                )
            self.import_deep_review_packages(
                target,
                notify=False,
            )

        self._advance_archive_campaign()
        refreshed = self._archive_campaign_stats()
        next_phase, next_target = next_campaign_phase(refreshed)
        save_campaign_checkpoint(
            self.conn,
            phase=next_phase,
            target=next_target,
            status="complete" if next_phase == "complete" else "ready",
            note="",
        )
        return True


    def _apply_scheduled_before_archive_for_quota_day(
        self,
        current_day: str,
    ) -> bool:
        """Apply ready scheduled packages before archive spends the daily budget."""
        done_key = f"archive_campaign_scheduled_done_{current_day}"
        if get_setting(self.conn, done_key, "0") == "1":
            return True

        total_ready = int(
            self.conn.execute(
                """SELECT COUNT(*)
                   FROM videos v
                   JOIN optimization_drafts d ON d.video_id=v.video_id
                   WHERE v.scheduled_publish_at IS NOT NULL
                     AND d.status='ready'"""
            ).fetchone()[0]
        )
        if total_ready <= 0:
            set_setting(self.conn, done_key, "1")
            return True

        changed_total = 0
        for profile in PROFILE_TARGETS:
            ready_before = int(
                self.conn.execute(
                    """SELECT COUNT(*)
                       FROM videos v
                       JOIN optimization_drafts d ON d.video_id=v.video_id
                       WHERE v.profile=?
                         AND v.scheduled_publish_at IS NOT NULL
                         AND d.status='ready'""",
                    (profile,),
                ).fetchone()[0]
            )
            if ready_before <= 0:
                continue

            client = YouTubeClient(profile=profile)
            client.credentials()
            self.client = client
            self.current_profile = profile

            changed_total += self.apply_ready_scheduled_packages(
                confirm=False,
                notify=False,
            )
            ready_after = int(
                self.conn.execute(
                    """SELECT COUNT(*)
                       FROM videos v
                       JOIN optimization_drafts d ON d.video_id=v.video_id
                       WHERE v.profile=?
                         AND v.scheduled_publish_at IS NOT NULL
                         AND d.status='ready'""",
                    (profile,),
                ).fetchone()[0]
            )
            if ready_after > 0:
                log_action(
                    self.conn,
                    profile=profile,
                    category="кампанія архіву",
                    action="Архів чекає заплановані",
                    details=(
                        f"квотний день {current_day}; "
                        f"залишилось запланованих {ready_after}; "
                        "архівний бюджет не витрачаємо"
                    ),
                )
                self.reload_action_log()
                return False

            if quota_exhausted(self.conn):
                return False

        set_setting(self.conn, done_key, "1")
        log_action(
            self.conn,
            profile=self.current_profile,
            category="заплановані",
            action="Пріоритет перед архівом виконано",
            details=(
                f"квотний день {current_day}; "
                f"оновлено запланованих {changed_total}"
            ),
        )
        self.reload_action_log()
        return True

    def _run_archive_campaign_autorun(self) -> None:
        if not archive_priority_enabled(self.conn):
            return
        if get_setting(
            self.conn,
            "archive_campaign_autorun",
            "1",
        ) != "1":
            return
        if getattr(self, "_archive_campaign_autorun_running", False):
            return

        self._archive_campaign_autorun_running = True
        try:
            current_day = current_quota_day()
            done_key = f"archive_campaign_autorun_done_{current_day}"
            if get_setting(self.conn, done_key, "0") == "1":
                return

            if not self._apply_scheduled_before_archive_for_quota_day(
                current_day
            ):
                return

            stats = self._archive_campaign_stats()
            phase, target = next_campaign_phase(stats)
            if phase == "complete":
                self._advance_archive_campaign()
                set_setting(self.conn, done_key, "1")
                return

            budget = self._archive_campaign_budget()
            if phase == "safe" and int(budget["current_capacity"]) <= 0:
                save_campaign_checkpoint(
                    self.conn,
                    phase=phase,
                    target=target,
                    status="paused_quota",
                    note="protected_comment_reserve",
                )
                return

            try:
                if target:
                    client = YouTubeClient(profile=target)
                    client.credentials()
                    self.client = client
                    self.current_profile = target
                if phase == "safe":
                    backup_root = self._recovery_backup_root()
                    if not backup_root.parent.exists():
                        save_campaign_checkpoint(
                            self.conn,
                            phase=phase,
                            target=target,
                            status="paused_storage",
                            note="nas_unavailable",
                        )
                        return
                completed = self.run_archive_campaign_step(automatic=True)
                if completed:
                    set_setting(self.conn, done_key, "1")
                    log_action(
                        self.conn,
                        profile=target or self.current_profile,
                        category="кампанія архіву",
                        action="Автозапуск квотного дня",
                        details=(
                            f"{phase}:{target} · "
                            f"бюджет кампанії {budget['campaign_spendable']} · "
                            f"резерв коментарів {budget['reserve']}"
                        ),
                    )
                    self.reload_action_log()
            except Exception as exc:
                save_campaign_checkpoint(
                    self.conn,
                    phase=phase,
                    target=target,
                    status="interrupted",
                    note=str(exc),
                )
                log_action(
                    self.conn,
                    profile=target or self.current_profile,
                    category="кампанія архіву",
                    action="Автозапуск відкладено",
                    details=str(exc),
                )
        finally:
            self._archive_campaign_autorun_running = False

    def show_archive_campaign_center(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Центр кампанії архіву")
        dialog.resize(860, 430)
        layout = QVBoxLayout(dialog)

        phase_label = QLabel()
        phase_label.setObjectName("SettingsSectionTitle")
        next_label = QLabel()
        next_label.setWordWrap(True)
        quota_label = QLabel()
        quota_label.setWordWrap(True)
        quota_label.setProperty("muted", True)
        layout.addWidget(phase_label)
        layout.addWidget(next_label)
        layout.addWidget(quota_label)

        table = QTableWidget(2, 5)
        table.setHorizontalHeaderLabels([
            "Канал",
            "Безпечні",
            "Глибока",
            "Транскрипти",
            "Готові пакети",
        ])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

        hint = QLabel(
            "Кампанія проходить автоматично: спочатку готові заплановані "
            "відео, потім основний safe -> LIVE safe -> основний deep -> "
            "LIVE deep. Deep-пакети лишаються чернетками "
            "до ручного перегляду. Резерв коментарів архів не використовує."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        run_btn = QPushButton("Запустити зараз")
        run_btn.setProperty("role", "primary")
        open_btn = QPushButton("Відкрити поточний етап")
        refresh_btn = QPushButton("Оновити")
        close_btn = QPushButton("Закрити")
        for button in (
            run_btn,
            open_btn,
            refresh_btn,
            close_btn,
        ):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        def refresh() -> None:
            stats = self._archive_campaign_stats()
            budget = self._archive_campaign_budget()
            phase, target = next_campaign_phase(stats)
            phase_name = {
                "safe": "БЕЗПЕЧНИЙ АРХІВ",
                "deep": "ГЛИБОКА ОПТИМІЗАЦІЯ",
                "complete": "ЗАВЕРШЕНО",
            }.get(phase, phase)
            target_name = (
                PROFILE_LABELS.get(target, "")
                if target
                else "обидва канали"
            )
            phase_label.setText(
                f"Поточний етап: {phase_name} - {target_name}"
            )

            if phase == "safe":
                remaining = int(
                    stats.get(target, {}).get("safe_remaining", 0)
                )
                next_text = (
                    f"Наступна дія: автоматичний safe-пакет для "
                    f"{target_name}. Залишилось: {remaining}."
                )
            elif phase == "deep":
                remaining = int(
                    stats.get(target, {}).get("deep_remaining", 0)
                )
                next_text = (
                    f"Наступна дія: deep-черга, транскрипти та імпорт "
                    f"чернеток для {target_name}. Залишилось: {remaining}."
                )
            else:
                next_text = (
                    "Наступна дія: кампанію завершено. Попередній стан "
                    "автопілота метаданих відновлюється автоматично."
                )
            next_label.setText(next_text)

            total_safe = sum(
                int(value["safe_remaining"])
                for value in stats.values()
            )
            fresh_capacity = int(budget["fresh_capacity"])
            days = (
                math.ceil(total_safe / fresh_capacity)
                if total_safe and fresh_capacity
                else 0
            )
            quota_label.setText(
                f"Квота: {budget['used']}/{YOUTUBE_DAILY_QUOTA_DEFAULT} - "
                f"для кампанії зараз ≈{budget['current_capacity']} відео - "
                f"резерв коментарів {budget['reserve']} - "
                f"скидання {budget['reset']}"
                + (f" - safe-етап ≈{days} дн." if days else "")
            )

            for row_index, profile in enumerate(("main", "live")):
                item = stats.get(profile, {})
                values = [
                    PROFILE_LABELS[profile],
                    str(item.get("safe_remaining", 0)),
                    str(item.get("deep_remaining", 0)),
                    str(item.get("transcripts", 0)),
                    str(item.get("ready_packages", 0)),
                ]
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column == 0:
                        cell.setFont(
                            QFont("Segoe UI", 9, QFont.Weight.Bold)
                        )
                    table.setItem(row_index, column, cell)

            run_btn.setEnabled(phase != "complete")

        def run_current() -> None:
            self.run_archive_campaign_step(automatic=False)
            refresh()

        def open_current() -> None:
            stats = self._archive_campaign_stats()
            phase, target = next_campaign_phase(stats)
            if target:
                self._activate_profile(target)
            if phase == "deep":
                index = self.optimization_filter.findData("deep_review")
                if index >= 0:
                    self.optimization_filter.setCurrentIndex(index)
            elif phase == "safe":
                index = self.optimization_filter.findData("archive_top")
                if index >= 0:
                    self.optimization_filter.setCurrentIndex(index)
            self.tabs.setCurrentIndex(2)
            dialog.accept()

        run_btn.clicked.connect(run_current)
        open_btn.clicked.connect(open_current)
        refresh_btn.clicked.connect(refresh)
        close_btn.clicked.connect(dialog.accept)

        refresh()
        dialog.exec()

    def _prepared_queue_ids(self) -> list[str]:
        raw = get_setting(
            self.conn,
            f"prepared_safe_queue_{self.current_profile}",
            "[]",
        )
        try:
            value = json.loads(raw)
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        requested = [str(item) for item in value if str(item)]
        if not requested:
            return []
        ready_rows = self.conn.execute(
            """SELECT d.video_id
               FROM optimization_drafts d
               JOIN videos v ON v.video_id=d.video_id
               WHERE v.profile=? AND d.status='ready'""",
            (self.current_profile,),
        ).fetchall()
        ready = {str(row["video_id"]) for row in ready_rows}
        return [video_id for video_id in requested if video_id in ready]

    def prepare_safe_queue(self) -> None:
        rows = self.conn.execute(
            """SELECT v.video_id,v.views,v.audit_json,
                      a.analytics_views,a.impressions,a.ctr_percent
               FROM videos v
               LEFT JOIN video_analytics_cache a
                 ON a.video_id=v.video_id AND a.profile=v.profile
               WHERE v.profile=?
                 AND v.privacy_status='public'
                 AND v.scheduled_publish_at IS NULL""",
            (self.current_profile,),
        ).fetchall()

        ctr_values = [
            float(row["ctr_percent"] or 0)
            for row in rows
            if int(row["impressions"] or 0) >= 1000
            and float(row["ctr_percent"] or 0) > 0
        ]
        channel_median_ctr = median(ctr_values) if ctr_values else 0.0

        ranked = []
        for row in rows:
            try:
                audit_data = json.loads(row["audit_json"] or "{}")
                issues = list(audit_data.get("issues", []))
            except Exception:
                issues = []
            if not is_safe_archive_candidate(issues):
                continue
            potential = archive_potential_score(
                lifetime_views=int(row["views"] or 0),
                analytics_views=int(row["analytics_views"] or 0),
                impressions=int(row["impressions"] or 0),
                ctr_percent=float(row["ctr_percent"] or 0),
                median_ctr_percent=float(channel_median_ctr),
                issues=issues,
            )
            ranked.append((
                potential,
                int(row["impressions"] or 0),
                int(row["analytics_views"] or 0),
                int(row["views"] or 0),
                str(row["video_id"]),
            ))

        ranked.sort(reverse=True)

        ready_rows = self.conn.execute(
            """SELECT d.video_id,v.views
               FROM optimization_drafts d
               JOIN videos v ON v.video_id=d.video_id
               WHERE v.profile=? AND v.privacy_status='public'
                 AND v.scheduled_publish_at IS NULL
                 AND d.status='ready'
               ORDER BY v.views DESC""",
            (self.current_profile,),
        ).fetchall()
        queue = [str(row["video_id"]) for row in ready_rows]
        for item in ranked:
            video_id = item[-1]
            if video_id not in queue:
                queue.append(video_id)

        set_setting(
            self.conn,
            f"prepared_safe_queue_{self.current_profile}",
            json.dumps(queue, ensure_ascii=False),
        )
        set_setting(
            self.conn,
            f"prepared_safe_queue_created_{self.current_profile}",
            datetime.now(timezone.utc).isoformat(),
        )

        if hasattr(self, "optimization_filter"):
            index = self.optimization_filter.findData("prepared")
            if index >= 0:
                self.optimization_filter.setCurrentIndex(index)
        self.reload_optimization_queue()

        QMessageBox.information(
            self,
            "Підготовлена черга",
            f"Підготовлено відео: {len(queue)}.\n"
            "Черга збережена локально та готова до наступного квотного дня.",
        )

    def reload_optimization_queue(self) -> None:
        if not hasattr(self, "optimization_table"):
            return
        import json

        profile = self.current_profile
        self._refresh_archive_campaign_summary()
        scheduled_total = int(
            self.conn.execute(
                """SELECT COUNT(*) FROM videos
                   WHERE profile=? AND scheduled_publish_at IS NOT NULL""",
                (profile,),
            ).fetchone()[0]
        )
        scheduled_index = self.optimization_filter.findData("scheduled")
        if scheduled_index >= 0:
            self.optimization_filter.setItemText(
                scheduled_index,
                f"Лише заплановані ({scheduled_total})",
            )
        if hasattr(self, "scheduled_quick_btn"):
            self.scheduled_quick_btn.setText(
                f"Заплановані · {scheduled_total}"
            )
        latin_index = self.optimization_filter.findData("latin_titles")
        if latin_index >= 0:
            self.optimization_filter.setItemText(
                latin_index,
                f"Англомовні назви ({self._latin_title_review_count(profile)})",
            )
        deep_index = self.optimization_filter.findData("deep_review")
        if deep_index >= 0:
            _deep_items, deep_total = deep_review_candidates(
                self.conn,
                profile,
                limit=1,
            )
            self.optimization_filter.setItemText(
                deep_index,
                f"Глибока оптимізація ({deep_total})",
            )
        queue_filter = (
            self.optimization_filter.currentData()
            if hasattr(self, "optimization_filter")
            else "all"
        )
        extra_where = ""
        if queue_filter == "scheduled":
            extra_where = " AND v.scheduled_publish_at IS NOT NULL"
        elif queue_filter == "archive":
            extra_where = " AND v.scheduled_publish_at IS NULL"
        elif queue_filter == "archive_top":
            extra_where = (
                " AND v.scheduled_publish_at IS NULL"
                " AND v.privacy_status='public'"
            )
        elif queue_filter == "prepared":
            extra_where = (
                " AND v.scheduled_publish_at IS NULL"
                " AND v.privacy_status='public'"
            )
        elif queue_filter == "latin_titles":
            extra_where = (
                " AND v.scheduled_publish_at IS NULL"
                " AND v.privacy_status='public'"
            )
        elif queue_filter == "deep_review":
            extra_where = (
                " AND v.scheduled_publish_at IS NULL"
                " AND v.privacy_status='public'"
            )

        rows = self.conn.execute(
            f"""SELECT v.video_id,v.title,v.published_at,v.scheduled_publish_at,
                       v.privacy_status,v.views,v.audit_json,
                       d.status AS draft_status,
                       a.analytics_views,a.impressions,a.ctr_percent,
                       a.avd_seconds,a.subs_gained,
                       a.updated_at AS analytics_updated_at,
                       oe.optimized_at AS last_optimized_at
                FROM videos v
                LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
                LEFT JOIN video_analytics_cache a
                  ON a.video_id=v.video_id AND a.profile=v.profile
                LEFT JOIN optimization_events oe
                  ON oe.event_id=(
                    SELECT e.event_id
                    FROM optimization_events e
                    WHERE e.video_id=v.video_id AND e.profile=v.profile
                    ORDER BY e.optimized_at DESC,e.event_id DESC
                    LIMIT 1
                  )
                WHERE v.profile=?{extra_where}""",
            (profile,),
        ).fetchall()

        prepared_order = {}
        if queue_filter == "prepared":
            queue_ids = self._prepared_queue_ids()
            prepared_order = {
                video_id: index for index, video_id in enumerate(queue_ids)
            }
            rows = [
                row for row in rows
                if str(row["video_id"]) in prepared_order
            ]
        elif queue_filter == "latin_titles":
            latin_rows = []
            for row in rows:
                try:
                    row_issues = json.loads(
                        row["audit_json"] or "{}"
                    ).get("issues", [])
                except Exception:
                    row_issues = []
                if "latin_title_review" in row_issues:
                    latin_rows.append(row)
            rows = latin_rows
        elif queue_filter == "deep_review":
            state_map = deep_review_state_map(self.conn, profile)
            deep_rows = []
            for row in rows:
                try:
                    row_issues = json.loads(
                        row["audit_json"] or "{}"
                    ).get("issues", [])
                except Exception:
                    row_issues = []
                video_id = str(row["video_id"])
                if (
                    needs_deep_review(row_issues)
                    and state_map.get(video_id) not in {"applied", "skipped"}
                ):
                    deep_rows.append(row)
            rows = deep_rows


        ctr_values = [
            float(row["ctr_percent"] or 0)
            for row in rows
            if int(row["impressions"] or 0) >= 1000
            and float(row["ctr_percent"] or 0) > 0
        ]
        channel_median_ctr = median(ctr_values) if ctr_values else 0.0

        prepared = []
        for row in rows:
            audit_data = json.loads(row["audit_json"] or "{}")
            score = int(audit_data.get("score") or 0)
            issues = list(audit_data.get("issues", []))
            if queue_filter in {"archive_top", "prepared", "deep_review"}:
                priority_value = archive_potential_score(
                    lifetime_views=int(row["views"] or 0),
                    analytics_views=int(row["analytics_views"] or 0),
                    impressions=int(row["impressions"] or 0),
                    ctr_percent=float(row["ctr_percent"] or 0),
                    median_ctr_percent=float(channel_median_ctr),
                    issues=issues,
                )
                grade = (
                    "A" if priority_value >= 80
                    else "B" if priority_value >= 55
                    else "C"
                )
                priority_text = (
                    f"DEEP {grade} · {priority_value}"
                    if queue_filter == "deep_review"
                    else f"{grade} · {priority_value}"
                )
            else:
                priority_value, priority_text = priority_label(
                    score,
                    row["privacy_status"],
                    row["scheduled_publish_at"],
                    issues,
                )
            publish_text = (
                row["scheduled_publish_at"]
                or row["published_at"]
                or ""
            )
            prepared.append(
                (
                    priority_value,
                    publish_text,
                    priority_text,
                    row,
                    score,
                    issues,
                )
            )

        search_text = (
            self.optimization_search.text().strip().casefold()
            if hasattr(self, "optimization_search")
            else ""
        )
        status_filter = (
            self.optimization_status_filter.currentData()
            if hasattr(self, "optimization_status_filter")
            else "all"
        )
        min_archive_potential = int(
            get_setting(self.conn, "archive_ui_min_potential", "0") or 0
        )
        filtered_prepared = []
        for item in prepared:
            priority_value, _publish, _priority_text, row, score, issues = item
            title_text = str(row["title"] or "")
            video_id = str(row["video_id"] or "")
            issue_text = _issue_labels(issues)
            if search_text and not any(
                search_text in value.casefold()
                for value in (title_text, video_id, issue_text)
            ):
                continue
            draft_key = str(row["draft_status"] or "")
            ctr = float(row["ctr_percent"] or 0)
            impressions = int(row["impressions"] or 0)
            matches_status = (
                status_filter == "all"
                or (
                    status_filter == "needs"
                    and (
                        score < 100
                        or bool(issues)
                        or draft_key in {"", "draft"}
                    )
                )
                or (status_filter == "draft" and draft_key == "draft")
                or (status_filter == "ready" and draft_key == "ready")
                or (status_filter == "applied" and draft_key == "applied")
                or (status_filter == "no_tags" and "no_tags" in issues)
                or (
                    status_filter == "low_ctr"
                    and impressions >= 1000
                    and ctr > 0
                    and channel_median_ctr > 0
                    and ctr < channel_median_ctr
                )
            )
            if not matches_status:
                continue
            if (
                queue_filter == "archive_top"
                and priority_value < min_archive_potential
            ):
                continue
            filtered_prepared.append(item)
        prepared = filtered_prepared

        if queue_filter == "prepared":
            prepared.sort(
                key=lambda item: prepared_order.get(
                    str(item[3]["video_id"]), 10**9
                )
            )
        elif queue_filter == "scheduled":
            prepared.sort(
                key=lambda item: (
                    item[1] or "9999",
                    str(item[3]["title"] or "").casefold(),
                )
            )
        elif queue_filter in {"archive_top", "deep_review"}:
            prepared.sort(
                key=lambda item: (
                    -item[0],
                    -(int(item[3]["impressions"] or 0)),
                    -(int(item[3]["analytics_views"] or 0)),
                    -(int(item[3]["views"] or 0)),
                )
            )
        else:
            prepared.sort(
                key=lambda item: (
                    -item[0],
                    item[1] or "9999",
                    -(int(item[3]["views"] or 0)),
                )
            )

        self.optimization_table.setRowCount(len(prepared))
        for index, (_, publish_text, priority_text, row, score, issues) in enumerate(
            prepared
        ):
            transcript_dir = self._nas_path(
                "nas_transcripts_path",
                DEFAULT_NAS_TRANSCRIPTS_PATH,
            )
            transcript_status = (
                "NAS"
                if (transcript_dir / f"{row['video_id']}.srt").exists()
                else ""
            )
            draft_status = {
                "draft": "ЧЕРНЕТКА",
                "ready": "ГОТОВО",
                "applied": "ЗАСТОСОВАНО",
            }.get(row["draft_status"] or "", "")
            last_optimized, checkpoint_text = (
                self._optimization_checkpoint_text(row["last_optimized_at"])
            )
            values = [
                priority_text,
                publish_text,
                PRIVACY_LABELS.get(
                    str(row["privacy_status"] or ""),
                    str(row["privacy_status"] or ""),
                ),
                row["video_id"],
                row["title"],
                str(row["views"] or 0),
                str(score),
                transcript_status,
                draft_status,
                last_optimized,
                checkpoint_text,
                _issue_labels(issues),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setData(Qt.ItemDataRole.UserRole, row["video_id"])
                if column == 0:
                    if priority_text == "ЗАПЛАНОВАНО":
                        item.setForeground(QColor("#5aa7ff"))
                        item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                    elif (
                        priority_text.startswith(("A ·", "B ·", "C ·", "DEEP "))
                    ):
                        potential = int(priority_text.rsplit(" ", 1)[-1])
                        item.setForeground(
                            QColor(
                                "#5aa7ff"
                                if potential >= 80
                                else WARNING
                                if potential >= 55
                                else MUTED
                            )
                        )
                        item.setFont(
                            QFont("Segoe UI", 9, QFont.Weight.Bold)
                        )
                        item.setToolTip(
                            "90 днів: "
                            f"{int(row['analytics_views'] or 0):,} переглядів · "
                            f"{int(row['impressions'] or 0):,} показів · "
                            f"CTR {float(row['ctr_percent'] or 0):.2f}% · "
                            f"медіана каналу {channel_median_ctr:.2f}%"
                        )
                    elif priority_text == "НАЗВА":
                        item.setForeground(QColor(WARNING))
                        item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                    elif priority_text == "ВИСОКИЙ":
                        item.setForeground(QColor(WARNING))
                    elif priority_text == "ГОТОВО":
                        item.setForeground(QColor(SUCCESS))
                elif column == 6:
                    item.setForeground(
                        QColor(SUCCESS if score >= 100 else WARNING if score >= 70 else YOUTUBE_RED)
                    )
                elif column == 7 and transcript_status:
                    item.setForeground(QColor(SUCCESS))
                    item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                elif column == 8 and draft_status:
                    if draft_status == "ЗАСТОСОВАНО":
                        fg = QColor(SUCCESS)
                        bg = QColor("#16371f")
                    elif draft_status == "ГОТОВО":
                        fg = QColor("#8ecbff")
                        bg = QColor("#142b3c")
                    else:
                        fg = QColor(WARNING)
                        bg = QColor("#3b3012")
                    item.setForeground(fg)
                    item.setBackground(bg)
                    item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                elif column == 10 and checkpoint_text != "—":
                    item.setForeground(
                        QColor(
                            SUCCESS
                            if "90 ✓" in checkpoint_text
                            else WARNING
                        )
                    )
                    item.setToolTip(
                        "Контрольні точки аналізу після останньої оптимізації"
                    )
                self.optimization_table.setItem(index, column, item)
        if hasattr(self, "optimization_density"):
            self._apply_table_density(
                self.optimization_table,
                self.optimization_density,
            )
        self._update_optimization_context_card()
        self.update_dashboard()
        self.refresh_archive_dashboard()

    def _current_video_metadata(self, video_id: str) -> tuple[str, str, list[str]]:
        counted = getattr(self.client, "video_details_with_request_count", None)
        if callable(counted):
            items, requests = counted([video_id])
            record_quota_units(
                self.conn,
                int(requests) * READ_REQUEST_COST,
            purpose="video",
            )
        else:
            items = self.client.video_details([video_id])
            record_quota_units(self.conn, READ_REQUEST_COST, purpose="video")
        if not items:
            raise RuntimeError(f"Відео не знайдено: {video_id}")
        snippet = items[0].get("snippet", {})
        self.refresh_youtube_quota_label()
        return (
            snippet.get("title", ""),
            snippet.get("description", ""),
            snippet.get("tags", []) or [],
        )

    def preview_safe_optimization(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if not video_ids:
            QMessageBox.information(
                self, APP_NAME, "Виберіть одне відео в черзі оптимізації."
            )
            return
        video_id = video_ids[0]
        try:
            title, description, _tags = self._current_video_metadata(video_id)
            fix = safe_description_fix(description, title)
            needs_content = safe_description_needs_content_package(
                fix.after,
                title,
            )

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Попередній перегляд · {title}")
            dialog.resize(1050, 720)
            layout = QVBoxLayout(dialog)
            changes = ", ".join(fix.changes) if fix.changes else "змін немає"
            layout.addWidget(QLabel(f"Безпечні зміни: {changes}"))
            if needs_content:
                warning = QLabel(
                    "УВАГА: після очищення старого службового блоку змістовного "
                    "опису недостатньо. Це відео не можна застосовувати через "
                    "безпечний пакет. Потрібен контент-пакет/транскрипт."
                )
                warning.setWordWrap(True)
                warning.setObjectName("warningLabel")
                layout.addWidget(warning)

            columns = QHBoxLayout()
            before = QPlainTextEdit(fix.before)
            before.setReadOnly(True)
            after = QPlainTextEdit(fix.after)
            after.setReadOnly(True)
            left = QVBoxLayout()
            left.addWidget(QLabel("ДО"))
            left.addWidget(before)
            right = QVBoxLayout()
            right.addWidget(QLabel("ПІСЛЯ"))
            right.addWidget(after)
            columns.addLayout(left)
            columns.addLayout(right)
            layout.addLayout(columns)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрити")
            buttons.rejected.connect(dialog.reject)
            buttons.accepted.connect(dialog.accept)
            buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
                dialog.accept
            )
            layout.addWidget(buttons)
            dialog.exec()
        except Exception as exc:
            self._error("Помилка попереднього перегляду", exc)

    def test_nas_transcript_path(self) -> None:
        target_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        nas_ok = False
        bridge_ok = False
        details: list[str] = []

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            probe = target_dir / "_rg_youtube_control_write_test.txt"
            payload = (
                "RG YouTube Control NAS write test\n"
                + datetime.now(timezone.utc).isoformat()
                + "\n"
            )
            probe.write_text(payload, encoding="utf-8")
            check = probe.read_text(encoding="utf-8")
            if check != payload:
                raise RuntimeError("Контрольне читання не збіглося із записом.")
            probe.unlink(missing_ok=True)
            nas_ok = True
            details.append(f"NAS: OK\n{target_dir}")
        except Exception as exc:
            details.append(f"NAS: ПОМИЛКА\n{target_dir}\n{exc}")

        try:
            health = bridge_health(PACKAGE_BRIDGE_URL)
            bridge_ok = bool(health.get("ok"))
            if bridge_ok:
                details.append(
                    f"Package Bridge: OK\n{PACKAGE_BRIDGE_URL}"
                )
            else:
                details.append(
                    f"Package Bridge: некоректна відповідь\n{PACKAGE_BRIDGE_URL}"
                )
        except Exception as exc:
            details.append(
                f"Package Bridge: ПОМИЛКА\n{PACKAGE_BRIDGE_URL}\n{exc}"
            )

        message = "\n\n".join(details)
        if nas_ok or bridge_ok:
            QMessageBox.information(
                self,
                "Перевірка сховищ",
                message,
            )
            self.statusBar().showMessage(
                "Сховища: " + (
                    "NAS + Bridge OK"
                    if nas_ok and bridge_ok
                    else "резервний канал доступний"
                )
            )
        else:
            QMessageBox.critical(
                self,
                "Помилка доступу до сховищ",
                message,
            )
            self.statusBar().showMessage(
                "Сховища: NAS і Package Bridge недоступні"
            )

    def _export_transcript_video_to_nas(
        self,
        video_id: str,
        *,
        respect_reserve: bool = False,
    ) -> tuple[Path, bool]:
        target_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        srt_path = target_dir / f"{video_id}.srt"
        meta_path = target_dir / f"{video_id}.json"

        row = self.conn.execute(
            "SELECT title FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()

        if srt_path.exists() and srt_path.stat().st_size > 0:
            srt = srt_path.read_text(encoding="utf-8")
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            else:
                meta = {}
            meta.update(
                {
                    "video_id": video_id,
                    "channel_profile": self.current_profile,
                    "channel_id": PROFILE_TARGETS[self.current_profile],
                    "title": row["title"] if row else "",
                    "srt_path": str(srt_path),
                }
            )
            try:
                upload_transcript(
                    PACKAGE_BRIDGE_URL,
                    video_id,
                    srt,
                    meta,
                )
            except Exception:
                pass
            return srt_path, False

        if respect_reserve:
            budget = quota_budget_status(self.conn)
            if int(budget["spendable"]) < CAPTION_TRANSCRIPT_COST:
                raise RuntimeError(
                    "Недостатньо квоти вище захищеного резерву "
                    "для отримання транскрипту."
                )

        try:
            track, srt = self.client.download_best_caption_srt(video_id)
        except Exception as exc:
            # captions.list is still a quota-bearing read even when no usable
            # track exists. Count the known list cost conservatively.
            if "не знайдено доступних субтитрів" in str(exc):
                record_quota_units(self.conn, 50, purpose="video")
                self.refresh_youtube_quota_label()
            raise
        record_quota_units(self.conn, CAPTION_TRANSCRIPT_COST, purpose="video")
        self.refresh_youtube_quota_label()

        snippet = track.get("snippet", {})
        srt_path.write_text(srt, encoding="utf-8")

        meta = {
            "video_id": video_id,
            "channel_profile": self.current_profile,
            "channel_id": PROFILE_TARGETS[self.current_profile],
            "title": row["title"] if row else "",
            "language": snippet.get("language"),
            "name": snippet.get("name"),
            "track_kind": snippet.get("trackKind"),
            "status": snippet.get("status"),
            "srt_path": str(srt_path),
        }
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            upload_transcript(
                PACKAGE_BRIDGE_URL,
                video_id,
                srt,
                meta,
            )
        except Exception:
            pass
        return srt_path, True

    def export_scheduled_transcripts_to_nas(self) -> None:
        rows = self.conn.execute(
            """SELECT video_id,title,scheduled_publish_at
               FROM videos
               WHERE profile=? AND scheduled_publish_at IS NOT NULL
               ORDER BY scheduled_publish_at ASC""",
            (self.current_profile,),
        ).fetchall()
        if not rows:
            QMessageBox.information(
                self,
                APP_NAME,
                "На активному каналі немає запланованих відео.",
            )
            return

        target_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
        pending = [
            row
            for row in rows
            if not (target_dir / f"{row['video_id']}.srt").exists()
        ]
        already = len(rows) - len(pending)

        # Existing NAS transcripts are mirrored to Package Bridge without
        # consuming YouTube Captions API quota.
        for row in rows:
            existing_path = target_dir / f"{row['video_id']}.srt"
            if not existing_path.exists():
                continue
            try:
                self._export_transcript_video_to_nas(str(row["video_id"]))
            except Exception:
                pass

        if not pending:
            QMessageBox.information(
                self,
                APP_NAME,
                f"Усі {len(rows)} запланованих транскриптів уже є на NAS.",
            )
            self.reload_optimization_queue()
            return

        if len(pending) > 20:
            QMessageBox.warning(
                self,
                APP_NAME,
                "За один пакет можна отримати не більше 20 транскриптів.",
            )
            return

        estimated = len(pending) * 250
        answer = QMessageBox.question(
            self,
            "Транскрипти запланованих відео",
            f"Знайдено запланованих: {len(rows)}.\n"
            f"Уже на NAS: {already}.\n"
            f"Потрібно отримати: {len(pending)}.\n"
            f"Оцінка квоти Captions API: до ≈{estimated} од.\n\n"
            "Отримати транскрипти зараз?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        saved = 0
        skipped = already
        errors: list[str] = []
        report_items: list[dict[str, str | bool]] = []
        for index, row in enumerate(pending, start=1):
            video_id = row["video_id"]
            self.statusBar().showMessage(
                f"Транскрипти: {index}/{len(pending)} · {video_id}"
            )
            QApplication.processEvents()
            try:
                path, downloaded = self._export_transcript_video_to_nas(video_id)
                if downloaded:
                    saved += 1
                else:
                    skipped += 1
                report_items.append(
                    {
                        "video_id": video_id,
                        "title": str(row["title"] or ""),
                        "scheduled_publish_at": str(
                            row["scheduled_publish_at"] or ""
                        ),
                        "ok": True,
                        "downloaded": downloaded,
                        "path": str(path),
                        "error": "",
                    }
                )
            except Exception as exc:
                error_text = str(exc)
                errors.append(f"{video_id}: {error_text}")
                report_items.append(
                    {
                        "video_id": video_id,
                        "title": str(row["title"] or ""),
                        "scheduled_publish_at": str(
                            row["scheduled_publish_at"] or ""
                        ),
                        "ok": False,
                        "downloaded": False,
                        "path": "",
                        "error": error_text,
                    }
                )

        report_payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "profile": self.current_profile,
            "channel_id": PROFILE_TARGETS[self.current_profile],
            "total_scheduled": len(rows),
            "already_existing": already,
            "downloaded": saved,
            "failed": len(errors),
            "items": report_items,
        }
        report_path = target_dir / "_last_transcript_report.json"
        report_write_error = ""
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            report_write_error = str(exc)

        self.reload_optimization_queue()
        message = (
            f"Готово. Збережено нових транскриптів: {saved}.\n"
            f"Уже існувало: {skipped}."
        )
        if errors:
            preview = "\n".join(errors[:8])
            message += f"\n\nНе вдалося отримати: {len(errors)}\n{preview}"
            if len(errors) > 8:
                message += "\n…"
        if report_write_error:
            message += (
                "\n\nЗвіт на NAS записати не вдалося:\n"
                + report_write_error
            )
        else:
            message += f"\n\nДіагностичний звіт:\n{report_path}"
        QMessageBox.information(self, APP_NAME, message)
        self.statusBar().showMessage("Пакет транскриптів оброблено")

    def export_selected_transcript_to_nas(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для транскрипту виберіть рівно одне відео."
            )
            return

        video_id = video_ids[0]
        answer = QMessageBox.question(
            self,
            "Отримати транскрипт",
            "Буде використано офіційний YouTube Captions API. "
            "Операція читання доріжки субтитрів витрачає квоту API. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            srt_path, downloaded = self._export_transcript_video_to_nas(video_id)
            action = "збережено" if downloaded else "уже був на NAS"
            QMessageBox.information(
                self,
                APP_NAME,
                f"Транскрипт {action}:\n{srt_path}",
            )
            self.reload_optimization_queue()
            self.statusBar().showMessage(
                f"Транскрипт {video_id}: {action}"
            )
        except Exception as exc:
            self._error("Помилка отримання транскрипту", exc)

    def _save_package_payload(
        self,
        video_id: str,
        payload: dict,
        *,
        force_draft: bool = False,
    ) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        package_video_id = str(payload.get("video_id") or video_id)
        if package_video_id != video_id:
            raise RuntimeError(
                "video_id у пакеті не збігається з вибраним відео."
            )

        title = _standard_hyphen(
            str(
                payload.get("new_title")
                or payload.get("title")
                or ""
            ).strip()
        )
        description = _standard_hyphen(
            str(payload.get("description") or "").strip()
        )
        package_description_fix = sanitize_imported_package_description(
            description,
            title,
        )
        description = package_description_fix.after
        chapters = _standard_hyphen(
            str(payload.get("chapters") or "").strip()
        )
        if not chapters:
            description, detected_chapters = (
                extract_chapters_from_description(description)
            )
            if detected_chapters:
                chapters = detected_chapters

        tags_value = payload.get("tags") or []
        title_variants_value = payload.get("title_variants") or []
        if isinstance(title_variants_value, str):
            title_variants = [
                _standard_hyphen(item.strip())
                for item in title_variants_value.splitlines()
                if item.strip()
            ][:3]
        else:
            title_variants = [
                _standard_hyphen(str(item).strip())
                for item in title_variants_value
                if str(item).strip()
            ][:3]

        if isinstance(tags_value, str):
            tags = [
                _standard_hyphen(item.strip())
                for item in tags_value.replace("\n", ",").split(",")
                if item.strip()
            ]
        else:
            tags = [
                _standard_hyphen(str(item).strip())
                for item in tags_value
                if str(item).strip()
            ]

        if not title:
            raise RuntimeError("У пакеті немає назви.")

        check = validate_content_package(
            title,
            description,
            chapters,
            tags,
            title_variants,
        )
        errors = list(check.errors)
        warnings = list(check.warnings)

        current_row = self.conn.execute(
            "SELECT title FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
        current_title = str(current_row["title"] or "") if current_row else ""
        if blocks_automatic_title_language_change(current_title, title):
            errors.append(
                "Автоматичну зміну назви з кирилиці на англійську заблоковано. "
                "Назва має відповідати мові відео; змініть її вручну."
            )

        requested_status = str(payload.get("status") or "ready")
        if requested_status not in {"draft", "ready"}:
            requested_status = "ready"
        if force_draft:
            requested_status = "draft"
        status = (
            "draft"
            if errors and requested_status == "ready"
            else requested_status
        )

        save_optimization_draft(
            self.conn,
            video_id,
            title,
            description,
            chapters,
            tags,
            status,
            title_variants,
        )
        return status, tuple(errors), tuple(warnings)

    def import_selected_package_from_nas(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для імпорту виберіть рівно одне відео."
            )
            return

        video_id = video_ids[0]
        try:
            package_dir = self._nas_path(
                "nas_packages_path",
                DEFAULT_NAS_PACKAGES_PATH,
            )
            package_path = package_dir / f"{video_id}.json"
            source = "NAS"
            if package_path.exists():
                payload = json.loads(
                    package_path.read_text(encoding="utf-8")
                )
            else:
                payload = fetch_package(
                    PACKAGE_BRIDGE_URL,
                    video_id,
                )
                source = "Package Bridge"
                if payload is None:
                    QMessageBox.information(
                        self,
                        APP_NAME,
                        "Пакет поки не знайдено.\n\n"
                        f"NAS: {package_path}\n"
                        f"Bridge: {PACKAGE_BRIDGE_URL}",
                    )
                    return

            status, errors, warnings = self._save_package_payload(
                video_id,
                payload,
            )
            self.reload_optimization_queue()

            details = [
                f"Пакет імпортовано з {source}.",
                f"Статус: {'Готово' if status == 'ready' else 'Чернетка'}.",
            ]
            if errors:
                details.append(
                    f"Критичних помилок: {len(errors)}."
                )
            if warnings:
                details.append(
                    f"Рекомендацій: {len(warnings)}."
                )
            QMessageBox.information(
                self,
                APP_NAME,
                "\n".join(details),
            )
        except Exception as exc:
            self._error("Помилка імпорту пакета", exc)

    def fetch_scheduled_packages(self) -> None:
        rows = self.conn.execute(
            """SELECT v.video_id,v.scheduled_publish_at,
                      d.status,d.new_title
               FROM videos v
               LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.profile=?
                 AND v.scheduled_publish_at IS NOT NULL
               ORDER BY v.scheduled_publish_at ASC""",
            (self.current_profile,),
        ).fetchall()
        if not rows:
            QMessageBox.information(
                self,
                APP_NAME,
                "На активному каналі немає запланованих стрімів.",
            )
            return

        package_dir = self._nas_path(
            "nas_packages_path",
            DEFAULT_NAS_PACKAGES_PATH,
        )
        imported = 0
        ready = 0
        draft = 0
        skipped = 0
        missing = 0
        failed: list[str] = []

        for index, row in enumerate(rows, start=1):
            video_id = str(row["video_id"])
            existing_status = str(row["status"] or "")
            existing_title = _standard_hyphen(
                str(row["new_title"] or "").strip()
            )

            self.statusBar().showMessage(
                f"Пакети запланованих: {index}/{len(rows)} · {video_id}"
            )
            QApplication.processEvents()

            try:
                package_path = package_dir / f"{video_id}.json"
                if package_path.exists():
                    payload = json.loads(
                        package_path.read_text(encoding="utf-8")
                    )
                else:
                    payload = fetch_package(
                        PACKAGE_BRIDGE_URL,
                        video_id,
                    )
                if payload is None:
                    missing += 1
                    continue

                remote_title = _standard_hyphen(
                    str(
                        payload.get("new_title")
                        or payload.get("title")
                        or ""
                    ).strip()
                )
                if (
                    existing_status in {"ready", "applied"}
                    and existing_title
                    and existing_title == remote_title
                ):
                    skipped += 1
                    continue

                status, errors, _warnings = self._save_package_payload(
                    video_id,
                    payload,
                )
                imported += 1
                if status == "ready" and not errors:
                    ready += 1
                else:
                    draft += 1
            except Exception as exc:
                failed.append(f"{video_id}: {exc}")

        self.reload_optimization_queue()
        message = (
            f"Запланованих: {len(rows)}.\n"
            f"Імпортовано пакетів: {imported}.\n"
            f"Готово до застосування: {ready}.\n"
            f"Чернеток після перевірки: {draft}.\n"
            f"Без змін: {skipped}.\n"
            f"Пакетів поки немає: {missing}."
        )
        if failed:
            message += (
                f"\nПомилок: {len(failed)}.\n\n"
                + "\n".join(failed[:5])
            )
        QMessageBox.information(
            self,
            "Пакети запланованих стрімів",
            message,
        )
        self.statusBar().showMessage("Пакети запланованих перевірено")

    def edit_content_package(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для пакета контенту виберіть рівно одне відео."
            )
            return

        video_id = video_ids[0]
        try:
            video_row = self.conn.execute(
                "SELECT scheduled_publish_at FROM videos WHERE video_id=?",
                (video_id,),
            ).fetchone()
            scheduled_publish_at = (
                str(video_row["scheduled_publish_at"])
                if video_row and video_row["scheduled_publish_at"]
                else None
            )
            current_title, current_description, current_tags = (
                self._current_video_metadata(video_id)
            )
            draft = get_optimization_draft(self.conn, video_id)
            if draft is None:
                title = current_title
                description = current_description
                chapters = ""
                tags = current_tags
                status = "draft"
                title_variants = []
            else:
                import json
                title = draft["new_title"]
                description = draft["description"]
                chapters = draft["chapters"]
                tags = json.loads(draft["tags_json"] or "[]")
                title_variants = json.loads(
                    draft["title_variants_json"] or "[]"
                )
                status = draft["status"]

            dialog = ContentOptimizationDialog(
                title,
                description,
                chapters,
                tags,
                status,
                title_variants,
                scheduled_publish_at,
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            (
                new_title,
                description,
                chapters,
                tags,
                status,
                title_variants,
            ) = dialog.values()
            save_optimization_draft(
                self.conn,
                video_id,
                new_title,
                description,
                chapters,
                tags,
                status,
                title_variants,
            )
            self.reload_optimization_queue()
            self.statusBar().showMessage("Пакет оптимізації збережено")
        except Exception as exc:
            self._error("Помилка пакета оптимізації", exc)

    def _preview_deep_content_package(
        self,
        *,
        video_id: str,
        current_title: str,
        current_description: str,
        current_tags: list[str],
        new_title: str,
        new_description: str,
        new_tags: list[str],
    ) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Глибока оптимізація · перегляд · {video_id}")
        dialog.resize(1180, 760)
        layout = QVBoxLayout(dialog)

        note = QLabel(
            "Це повний перегляд небезпечних змін. Thumbnail, видимість, "
            "дата публікації та інші налаштування не змінюються."
        )
        note.setWordWrap(True)
        note.setProperty("muted", True)
        layout.addWidget(note)

        change_map = QFrame()
        change_map.setObjectName("QueueCard")
        map_layout = QHBoxLayout(change_map)
        map_layout.setContentsMargins(12, 8, 12, 8)
        title_changed = current_title.strip() != new_title.strip()
        desc_delta = len(new_description) - len(current_description)
        tags_delta = len(new_tags) - len(current_tags)
        title_state = QLabel(
            "НАЗВА · " + ("ЗМІНА" if title_changed else "БЕЗ ЗМІН")
        )
        title_state.setObjectName("StatusWarn" if title_changed else "StatusGood")
        desc_state = QLabel(
            f"ОПИС · {len(current_description)} → {len(new_description)} "
            f"({desc_delta:+d})"
        )
        desc_state.setObjectName("StatusWork")
        tags_state = QLabel(
            f"ТЕГИ · {len(current_tags)} → {len(new_tags)} ({tags_delta:+d})"
        )
        tags_state.setObjectName("StatusWork")
        locked = QLabel("THUMBNAIL · VISIBILITY · ДАТА · 🔒")
        locked.setObjectName("StatusGood")
        for widget in (title_state, desc_state, tags_state, locked):
            map_layout.addWidget(widget)
        map_layout.addStretch()
        layout.addWidget(change_map)

        columns = QHBoxLayout()
        before_box = QVBoxLayout()
        after_box = QVBoxLayout()
        before_box.addWidget(QLabel("ДО"))
        after_box.addWidget(QLabel("ПІСЛЯ"))

        before_title = QLabel(f"НАЗВА\n{current_title}")
        before_title.setWordWrap(True)
        after_title = QLabel(f"НАЗВА\n{new_title}")
        after_title.setWordWrap(True)

        before_description = QPlainTextEdit()
        before_description.setReadOnly(True)
        before_description.setPlainText(current_description)
        after_description = QPlainTextEdit()
        after_description.setReadOnly(True)
        after_description.setPlainText(new_description)

        before_tags = QPlainTextEdit()
        before_tags.setReadOnly(True)
        before_tags.setMaximumHeight(105)
        before_tags.setPlainText(", ".join(current_tags) if current_tags else "—")
        after_tags = QPlainTextEdit()
        after_tags.setReadOnly(True)
        after_tags.setMaximumHeight(105)
        after_tags.setPlainText(", ".join(new_tags) if new_tags else "—")

        before_box.addWidget(before_title)
        before_box.addWidget(QLabel("ОПИС"))
        before_box.addWidget(before_description, 1)
        before_box.addWidget(QLabel("ТЕГИ YOUTUBE · окреме поле, не частина опису"))
        before_box.addWidget(before_tags)

        after_box.addWidget(after_title)
        after_box.addWidget(QLabel("ОПИС"))
        after_box.addWidget(after_description, 1)
        after_box.addWidget(QLabel("ТЕГИ YOUTUBE · окреме поле, не частина опису"))
        after_box.addWidget(after_tags)
        columns.addLayout(before_box, 1)
        columns.addLayout(after_box, 1)
        layout.addLayout(columns, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText("Перевірено · продовжити")
        buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        ).setText("Скасувати")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def apply_content_package(self) -> None:
        if quota_exhausted(self.conn):
            QMessageBox.information(
                self,
                "Квоту YouTube вичерпано",
                "Застосування пакета заблоковано до наступного квотного дня.",
            )
            return
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для застосування виберіть рівно одне відео."
            )
            return

        video_id = video_ids[0]
        draft = get_optimization_draft(self.conn, video_id)
        if draft is None:
            QMessageBox.information(
                self, APP_NAME, "Для цього відео ще немає пакета оптимізації."
            )
            return
        if draft["status"] != "ready":
            QMessageBox.warning(
                self,
                APP_NAME,
                "Пакет повинен мати статус «Готово до застосування».",
            )
            return

        import json
        try:
            final_description = _strip_timestamp_lines(
                draft["description"]
            )
            current_title, current_description, current_tags = (
                self._current_video_metadata(video_id)
            )
            new_tags = json.loads(draft["tags_json"] or "[]")
            new_title = draft["new_title"]

            deep_state_before = deep_review_state_map(
                self.conn,
                self.current_profile,
            )
            if video_id in deep_state_before:
                if not self._preview_deep_content_package(
                    video_id=video_id,
                    current_title=current_title,
                    current_description=current_description,
                    current_tags=current_tags,
                    new_title=new_title,
                    new_description=final_description,
                    new_tags=new_tags,
                ):
                    return
                answer = QMessageBox.question(
                    self,
                    "Підтвердити глибоку оптимізацію",
                    f"Перегляд завершено. Буде змінено назву, опис і теги "
                    f"одного відео (≈{VIDEO_UPDATE_COST} од. квоти).\n\n"
                    "Застосувати перевірений пакет?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
            else:
                answer = QMessageBox.question(
                    self,
                    "Застосувати пакет оптимізації",
                    f"Відео: {video_id}\n\n"
                    f"Назва:\n{current_title}\n→\n{new_title}\n\n"
                    f"Опис: {len(current_description)} → "
                    f"{len(final_description)} символів\n"
                    f"Теги: {len(current_tags)} → {len(new_tags)}\n\n"
                    "Усі поля буде надіслано одним videos.update "
                    f"(≈{VIDEO_UPDATE_COST} од. квоти). Продовжити?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
            if answer != QMessageBox.StandardButton.Yes:
                return

            history_id = save_metadata_snapshot(
                self.conn,
                video_id,
                current_title,
                current_description,
                current_tags,
                "before_content_package",
            )
            self._set_process(
                f"Запис у YouTube · {video_id}",
                "videos.update",
                percent=None,
                eta=f"≈{VIDEO_UPDATE_COST + READ_REQUEST_COST} од. квоти",
            )
            self._quota_update_video(
                video_id,
                title=new_title,
                description=final_description,
                tags=new_tags,
            )
            record_optimization_event(
                self.conn, history_id=history_id, video_id=video_id,
                profile=self.current_profile, reason="content_package",
                changed_fields="назва + опис + теги",
            )
            set_optimization_draft_status(self.conn, video_id, "applied")
            deep_state = deep_review_state_map(
                self.conn,
                self.current_profile,
            )
            if video_id in deep_state:
                set_deep_review_state(
                    self.conn,
                    video_id=video_id,
                    profile=self.current_profile,
                    status="applied",
                    note="content_package_applied_after_preview",
                )
            sync_specific_videos(self.client, self.conn, [video_id])
            self.reload_videos()
            self.reload_optimization_queue()
            self._advance_archive_campaign()
            self._set_process_idle("YouTube оновлено · точка відкату збережена")
            self._toast(
                "✓ Пакет застосовано · точка відкату збережена · "
                "кнопка «Відкотити» доступна для вибраного відео",
                7000,
            )
        except Exception as exc:
            self._error("Помилка застосування пакета", exc)

    @staticmethod
    def _dedupe_tags(tags: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in tags:
            value = str(item).strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    def show_scheduled_center(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Центр запланованих стрімів")
        dialog.resize(1450, 720)
        layout = QVBoxLayout(dialog)

        hint = QLabel(
            "В одному вікні: дата, видимість, пакет, назва, опис, теги та "
            "передпублікаційна перевірка. Запис у YouTube виконується лише "
            "кнопкою «Застосувати готові»."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        table = QTableWidget(0, 9)
        table.setHorizontalHeaderLabels([
            "Дата",
            "Видимість",
            "Відео",
            "Поточна назва",
            "Пакет",
            "Назва",
            "Опис",
            "Теги",
            "Перевірка",
        ])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in {
            0: 155, 1: 100, 2: 120, 3: 290, 4: 110,
            5: 100, 6: 100, 7: 90, 8: 330,
        }.items():
            table.setColumnWidth(column, width)
        layout.addWidget(table, 1)

        def refresh() -> None:
            rows = self.conn.execute(
                """SELECT v.video_id,v.title,v.scheduled_publish_at,
                          v.privacy_status,
                          d.new_title,d.description,d.chapters,d.tags_json,
                          d.title_variants_json,d.status
                   FROM videos v
                   LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
                   WHERE v.profile=?
                     AND v.scheduled_publish_at IS NOT NULL
                   ORDER BY v.scheduled_publish_at ASC""",
                (self.current_profile,),
            ).fetchall()
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                if row["new_title"] is None:
                    package_text = "НЕМАЄ"
                    title_state = "—"
                    description_state = "—"
                    tags_state = "—"
                    check_text = "Потрібен пакет контенту"
                    check_color = WARNING
                else:
                    (
                        new_title,
                        description,
                        chapters,
                        tags,
                        check,
                        changes,
                    ) = self._prepare_scheduled_package(row)
                    package_text = {
                        "draft": "ЧЕРНЕТКА",
                        "ready": "ГОТОВО",
                        "applied": "ЗАСТОСОВАНО",
                    }.get(str(row["status"] or "draft"), "ЧЕРНЕТКА")
                    title_state = f"{len(new_title)}/100"
                    try:
                        final_description = compose_description(
                            description, chapters
                        )
                    except Exception:
                        final_description = description
                    description_state = f"{len(final_description)}/5000"
                    tags_state = f"{len(tags)} шт."
                    parts = []
                    if check.errors:
                        parts.append("помилки: " + "; ".join(check.errors))
                    if check.warnings:
                        parts.append("рекомендації: " + "; ".join(check.warnings))
                    if changes:
                        parts.append("авто: " + "; ".join(changes))
                    check_text = "OK" if not parts else " | ".join(parts)
                    check_color = YOUTUBE_RED if check.errors else WARNING if check.warnings else SUCCESS

                values = [
                    str(row["scheduled_publish_at"] or "")[:16],
                    PRIVACY_LABELS.get(
                        str(row["privacy_status"] or ""),
                        str(row["privacy_status"] or ""),
                    ),
                    str(row["video_id"]),
                    str(row["title"] or ""),
                    package_text,
                    title_state,
                    description_state,
                    tags_state,
                    check_text,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 4:
                        item.setForeground(
                            QColor(
                                SUCCESS if package_text in {"ГОТОВО", "ЗАСТОСОВАНО"}
                                else WARNING
                            )
                        )
                    elif column == 8:
                        item.setForeground(QColor(check_color))
                        item.setToolTip(check_text)
                    table.setItem(row_index, column, item)

        buttons = QHBoxLayout()
        prepare_btn = QPushButton("Підготувати всі")
        check_btn = QPushButton("Перевірити все")
        apply_btn = QPushButton("Застосувати готові")
        apply_btn.setProperty("role", "primary")
        refresh_btn = QPushButton("Оновити")
        close_btn = QPushButton("Закрити")

        def prepare_all() -> None:
            self.fetch_scheduled_packages()
            self.audit_scheduled_packages()
            refresh()

        def audit_all() -> None:
            self.audit_scheduled_packages()
            refresh()

        def apply_all() -> None:
            self.apply_ready_scheduled_packages()
            refresh()

        prepare_btn.clicked.connect(prepare_all)
        check_btn.clicked.connect(audit_all)
        apply_btn.clicked.connect(apply_all)
        refresh_btn.clicked.connect(refresh)
        close_btn.clicked.connect(dialog.accept)
        for button in (
            prepare_btn, check_btn, apply_btn, refresh_btn, close_btn
        ):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        refresh()
        dialog.exec()

    def _prepare_scheduled_package(
        self, row
    ) -> tuple[str, str, list[str], list[str], object, list[str]]:
        new_title = str(row["new_title"] or "").strip()
        description = str(row["description"] or "")
        chapters = str(row["chapters"] or "")
        tags = self._dedupe_tags(json.loads(row["tags_json"] or "[]"))
        title_variants = json.loads(row["title_variants_json"] or "[]")

        clean_description, detected_chapters = extract_chapters_from_description(
            description
        )
        changes: list[str] = []
        if detected_chapters:
            description = clean_description
            if not chapters.strip():
                chapters = detected_chapters
            changes.append("прибрано дубль розділів з опису")

        safe_fix = sanitize_imported_package_description(
            description,
            new_title,
        )
        if safe_fix.after != description:
            description = safe_fix.after
            changes.extend(safe_fix.changes)

        original_tags = [
            str(item).strip()
            for item in json.loads(row["tags_json"] or "[]")
            if str(item).strip()
        ]
        if tags != original_tags:
            changes.append("прибрано дублікати тегів")

        check = validate_content_package(
            new_title, description, chapters, tags, title_variants
        )
        return new_title, description, chapters, tags, check, changes

    def audit_scheduled_packages(self) -> None:
        rows = self.conn.execute(
            """SELECT v.video_id,v.title,v.scheduled_publish_at,
                      d.new_title,d.description,d.chapters,d.tags_json,
                      d.title_variants_json,d.status
               FROM videos v
               LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.profile=?
                 AND v.scheduled_publish_at IS NOT NULL
               ORDER BY v.scheduled_publish_at ASC""",
            (self.current_profile,),
        ).fetchall()

        if not rows:
            QMessageBox.information(
                self,
                APP_NAME,
                "На активному каналі немає запланованих стрімів.",
            )
            return

        missing = 0
        applied = 0
        ready = 0
        draft = 0
        errors_total = 0
        warnings_total = 0
        chapters_fixed = 0
        normalized_packages = 0
        details: list[str] = []

        for row in rows:
            video_id = str(row["video_id"])
            scheduled_at = str(row["scheduled_publish_at"] or "")
            if row["new_title"] is None:
                missing += 1
                details.append(f"{scheduled_at} · {video_id}: немає пакета")
                continue

            status = str(row["status"] or "draft")
            if status == "applied":
                applied += 1
            elif status == "ready":
                ready += 1
            else:
                draft += 1

            (
                prepared_title, description, chapters, tags, check, prep_changes
            ) = self._prepare_scheduled_package(row)
            title_variants = json.loads(row["title_variants_json"] or "[]")

            if prep_changes:
                normalized_packages += 1
                if any("розділ" in item for item in prep_changes):
                    chapters_fixed += 1
                if status == "applied":
                    status = "ready"
                    applied -= 1
                    ready += 1
                save_optimization_draft(
                    self.conn,
                    video_id,
                    prepared_title,
                    description,
                    chapters,
                    tags,
                    status,
                    title_variants,
                )
            errors_total += len(check.errors)
            warnings_total += len(check.warnings)
            if check.errors or check.warnings or prep_changes:
                title = str(row["title"] or video_id).strip()
                short_title = title if len(title) <= 54 else title[:51] + "..."
                parts: list[str] = []
                if prep_changes:
                    parts.append("авто: " + "; ".join(prep_changes))
                if check.errors:
                    parts.append("помилки: " + "; ".join(check.errors))
                if check.warnings:
                    parts.append("рекомендації: " + "; ".join(check.warnings))
                details.append(
                    f"{scheduled_at} · {short_title} [{video_id}]: "
                    + " | ".join(parts)
                )

        self.reload_optimization_queue()

        lines = [
            f"Запланованих стрімів: {len(rows)}",
            f"Застосовано: {applied}",
            f"Готово до застосування: {ready}",
            f"Чернеток: {draft}",
            f"Без пакета: {missing}",
            f"Автоматично нормалізовано пакетів: {normalized_packages}",
            f"Очищено дублікати таймінгів в описі: {chapters_fixed}",
            f"Критичних помилок: {errors_total}",
            f"Рекомендацій: {warnings_total}",
        ]
        if details:
            lines.append("\nДеталі:")
            lines.extend(details[:12])
            if len(details) > 12:
                lines.append(f"...ще {len(details) - 12}")

        QMessageBox.information(
            self,
            "Перевірка запланованих стрімів",
            "\n".join(lines),
        )


    def apply_ready_scheduled_packages(
        self,
        *,
        confirm: bool = True,
        notify: bool = True,
    ) -> int:
        if quota_exhausted(self.conn):
            if notify:
                QMessageBox.information(
                    self,
                    "Квоту YouTube вичерпано",
                    "Застосування пакетів запланованих стрімів заблоковано "
                    "до наступного квотного дня.",
                )
            return 0

        rows = self.conn.execute(
            """SELECT v.video_id,v.title,v.scheduled_publish_at,
                      d.new_title,d.description,d.chapters,d.tags_json,
                      d.title_variants_json
               FROM videos v
               JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.profile=?
                 AND v.scheduled_publish_at IS NOT NULL
                 AND d.status='ready'
               ORDER BY v.scheduled_publish_at ASC
               LIMIT 20""",
            (self.current_profile,),
        ).fetchall()

        if not rows:
            if notify:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Немає запланованих стрімів із пакетом «Готово до застосування».",
                )
            return 0

        budget = quota_budget_status(self.conn)
        batch_limit = reserve_safe_batch_capacity(
            int(budget["spendable"]),
            len(rows),
            final_refresh_reads=1,
        )
        if batch_limit <= 0:
            if notify:
                QMessageBox.information(
                    self,
                    "Резерв квоти",
                    "Для запланованих стрімів недостатньо квоти вище "
                    f"захищеного резерву {budget['reserve']} од.",
                )
            return 0

        rows = rows[:batch_limit]
        prepared_rows = []
        blocked: list[str] = []
        for row in rows:
            prepared = self._prepare_scheduled_package(row)
            new_title, description, chapters, tags, check, prep_changes = prepared
            if check.errors:
                blocked.append(
                    f"{row['video_id']}: " + "; ".join(check.errors)
                )
                continue
            prepared_rows.append((row, prepared))

        if blocked:
            if notify:
                QMessageBox.warning(
                    self,
                    "Заплановані стріми потребують виправлення",
                    "Критичні помилки знайдено до запису в YouTube. "
                    "Нічого не змінено.\n\n" + "\n".join(blocked[:10]),
                )
            return 0

        if not prepared_rows:
            return 0

        estimated = (
            len(prepared_rows) * SAFE_METADATA_ITEM_COST
            + READ_REQUEST_COST
        )
        preview_lines = []
        for row, prepared in prepared_rows[:10]:
            new_title, description, chapters, tags, check, prep_changes = prepared
            suffix = (
                " · авто: " + ", ".join(prep_changes)
                if prep_changes else ""
            )
            preview_lines.append(
                f"• {str(row['scheduled_publish_at'] or '')[:16]} · "
                f"{str(row['title'] or row['video_id'])[:55]}{suffix}"
            )
        if len(prepared_rows) > 10:
            preview_lines.append(f"...ще {len(prepared_rows) - 10}")

        if confirm:
            answer = QMessageBox.question(
                self,
                "Оптимізація запланованих стрімів",
                f"Перевірено й готово: {len(prepared_rows)}.\n"
                f"Безпечний ліміт на цю партію: {batch_limit}.\n"
                f"Максимальна фактична витрата: ≈{estimated} од. квоти.\n"
                f"Резерв {budget['reserve']} од. не буде використано.\n\n"
                + "\n".join(preview_lines)
                + "\n\nБуде змінено лише назву, опис і теги. "
                "Дата й час публікації, видимість, параметри трансляції та "
                "налаштування розкладу залишаться без змін. Продовжити?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 0

        if not self._prechange_backup_or_warn(
            f"перед пакетом запланованих · {self.current_profile}",
            notify=notify,
        ):
            return 0

        changed_ids: list[str] = []
        errors: list[str] = []
        for row, prepared in prepared_rows:
            video_id = str(row["video_id"])
            try:
                current_title, current_description, current_tags = (
                    self._current_video_metadata(video_id)
                )
                (
                    new_title,
                    prepared_description,
                    chapters,
                    new_tags,
                    check,
                    prep_changes,
                ) = prepared
                final_description = compose_description(
                    prepared_description,
                    chapters,
                )

                history_id = save_metadata_snapshot(
                    self.conn,
                    video_id,
                    current_title,
                    current_description,
                    current_tags,
                    "before_scheduled_package_batch",
                )
                self._quota_update_video_with_client(
                    self.client,
                    video_id,
                    title=new_title,
                    description=final_description,
                    tags=new_tags,
                    respect_reserve=True,
                )
                record_optimization_event(
                    self.conn,
                    history_id=history_id,
                    video_id=video_id,
                    profile=self.current_profile,
                    reason="scheduled_package_batch",
                    changed_fields="назва + опис + теги",
                )
                save_optimization_draft(
                    self.conn,
                    video_id,
                    new_title,
                    prepared_description,
                    chapters,
                    new_tags,
                    "applied",
                    json.loads(row["title_variants_json"] or "[]"),
                )
                changed_ids.append(video_id)
            except Exception as exc:
                errors.append(f"{video_id}: {exc}")
                if quota_exhausted(self.conn):
                    break

        if changed_ids:
            sync_specific_videos(self.client, self.conn, changed_ids)

        log_action(
            self.conn,
            profile=self.current_profile,
            category="заплановані",
            action="Пакет застосовано",
            details=(
                f"оновлено {len(changed_ids)} з {len(prepared_rows)}; "
                f"помилок {len(errors)}; резерв {budget['reserve']}"
            ),
        )
        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_action_log()
        self.update_dashboard()

        if notify:
            message = (
                f"Готово. Оптимізовано запланованих стрімів: {len(changed_ids)}."
            )
            if errors:
                preview = "\n".join(errors[:5])
                message += f"\nПомилок: {len(errors)}.\n\n{preview}"
            QMessageBox.information(self, APP_NAME, message)
        return len(changed_ids)

    def _safe_archive_candidates_for_profile(
        self,
        profile: str,
        limit: int = 20,
    ) -> tuple[list[str], int]:
        rows = self.conn.execute(
            """SELECT v.video_id,v.audit_json,v.views,
                      a.analytics_views,a.impressions,a.ctr_percent
               FROM videos v
               LEFT JOIN video_analytics_cache a
                 ON a.video_id=v.video_id AND a.profile=v.profile
               WHERE v.profile=?
                 AND v.privacy_status='public'
                 AND v.scheduled_publish_at IS NULL""",
            (profile,),
        ).fetchall()

        ctr_values = [
            float(row["ctr_percent"] or 0)
            for row in rows
            if int(row["impressions"] or 0) >= 1000
            and float(row["ctr_percent"] or 0) > 0
        ]
        channel_median_ctr = median(ctr_values) if ctr_values else 0.0

        ranked: list[tuple[int, int, int, int, str]] = []
        for row in rows:
            try:
                issues = list(
                    json.loads(row["audit_json"] or "{}").get("issues", [])
                )
            except Exception:
                issues = []
            if not is_safe_archive_candidate(issues):
                continue
            potential = archive_potential_score(
                lifetime_views=int(row["views"] or 0),
                analytics_views=int(row["analytics_views"] or 0),
                impressions=int(row["impressions"] or 0),
                ctr_percent=float(row["ctr_percent"] or 0),
                median_ctr_percent=channel_median_ctr,
                issues=issues,
            )
            ranked.append((
                potential,
                int(row["impressions"] or 0),
                int(row["analytics_views"] or 0),
                int(row["views"] or 0),
                str(row["video_id"]),
            ))

        ranked.sort(reverse=True)
        candidates = [item[-1] for item in ranked]
        return candidates[:limit], len(candidates)

    def _safe_archive_candidates(
        self,
        limit: int = 20,
    ) -> tuple[list[str], int]:
        return self._safe_archive_candidates_for_profile(
            self.current_profile,
            limit=limit,
        )

    def _run_safe_metadata_autopilot(
        self,
        profile: str,
        client: YouTubeClient,
        *,
        max_items: int = 3,
    ) -> int:
        if archive_priority_enabled(self.conn):
            return 0

        if get_setting(
            self.conn,
            f"safe_metadata_autopilot_{profile}",
            "0",
        ) != "1":
            return 0

        now = datetime.now(timezone.utc)
        interval_minutes = int(
            get_setting(
                self.conn,
                f"safe_autopilot_interval_minutes_{profile}",
                str(DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES),
            )
            or DEFAULT_SAFE_AUTOPILOT_INTERVAL_MINUTES
        )
        daily_limit = int(
            get_setting(
                self.conn,
                f"safe_autopilot_daily_limit_{profile}",
                str(DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT),
            )
            or DEFAULT_SAFE_AUTOPILOT_DAILY_LIMIT
        )

        last_key = f"safe_autopilot_last_run_{profile}"
        last_raw = get_setting(self.conn, last_key, "").strip()
        if not last_raw:
            # Existing enabled installations must not immediately mutate three
            # more videos just because the application was updated/restarted.
            set_setting(self.conn, last_key, now.isoformat())
            log_action(
                self.conn,
                profile=profile,
                category="автопілот",
                action="Захисний інтервал",
                details=(
                    f"ініціалізовано · наступний цикл не раніше ніж через "
                    f"{interval_minutes} хв"
                ),
            )
            return 0

        try:
            last_run = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
        except ValueError:
            last_run = now
            set_setting(self.conn, last_key, now.isoformat())

        elapsed_minutes = (now - last_run).total_seconds() / 60.0
        if elapsed_minutes < interval_minutes:
            return 0

        quota_day = current_quota_day()
        count_key = f"safe_autopilot_count_{profile}_{quota_day}"
        daily_count = int(get_setting(self.conn, count_key, "0") or 0)
        remaining_daily = max(0, daily_limit - daily_count)
        if remaining_daily <= 0:
            return 0

        budget = quota_budget_status(self.conn)
        allowed = min(
            max_items,
            remaining_daily,
            max(0, int(budget["spendable"]) // VIDEO_UPDATE_COST),
        )
        if allowed <= 0 or bool(budget["exhausted"]):
            return 0

        video_ids, _total = self._safe_archive_candidates_for_profile(
            profile,
            limit=allowed,
        )
        if not video_ids:
            set_setting(self.conn, last_key, now.isoformat())
            return 0

        try:
            self._create_automatic_recovery_backup(
                f"перед автопілотом метаданих · {PROFILE_LABELS[profile]}",
                force=True,
                profile=profile,
            )
        except Exception as exc:
            log_action(
                self.conn,
                profile=profile,
                category="автопілот",
                action="Зупинено",
                details=f"не створено резервну копію: {exc}",
            )
            return 0

        # Set the timestamp before remote writes. A restart or an exception
        # therefore cannot immediately trigger another batch.
        set_setting(self.conn, last_key, now.isoformat())

        changed = 0
        for video_id in video_ids:
            try:
                items = client.video_details([video_id])
                record_quota_units(self.conn, 1, purpose="video")
                if not items:
                    continue
                snippet = items[0].get("snippet", {})
                title = str(snippet.get("title") or "")
                description = str(snippet.get("description") or "")
                tags = list(snippet.get("tags") or [])
                fix = safe_description_fix(description, title)
                if safe_description_needs_content_package(fix.after, title):
                    self._store_local_safe_audit(video_id, description, tags)
                    continue
                if not fix.changes or fix.after == description:
                    self._store_local_safe_audit(video_id, description, tags)
                    continue

                history_id = save_metadata_snapshot(
                    self.conn,
                    video_id,
                    title,
                    description,
                    tags,
                    "before_safe_autopilot",
                )
                self._quota_update_video_with_client(
                    client,
                    video_id,
                    description=fix.after,
                    respect_reserve=True,
                    safe_mode=True,
                )
                record_optimization_event(
                    self.conn,
                    history_id=history_id,
                    video_id=video_id,
                    profile=profile,
                    reason="safe_optimization",
                    changed_fields="посилання + хештеги · автопілот",
                )
                self._store_local_safe_audit(video_id, fix.after, tags)
                changed += 1
                daily_count += 1
                set_setting(self.conn, count_key, str(daily_count))
                log_action(
                    self.conn,
                    profile=profile,
                    category="автопілот",
                    action="Безпечні метадані",
                    details=(
                        f"{video_id}: {', '.join(fix.changes)} · "
                        f"сьогодні {daily_count}/{daily_limit}"
                    ),
                )
                if daily_count >= daily_limit:
                    break
            except Exception as exc:
                if _is_quota_exceeded_error(exc):
                    mark_quota_exhausted(self.conn)
                    self.refresh_youtube_quota_label()
                log_action(
                    self.conn,
                    profile=profile,
                    category="автопілот",
                    action="Помилка",
                    details=f"{video_id}: {exc}",
                )
                if quota_exhausted(self.conn):
                    break

        log_action(
            self.conn,
            profile=profile,
            category="автопілот",
            action="Цикл завершено",
            details=(
                f"змінено {changed}; сьогодні {daily_count}/{daily_limit}; "
                f"наступний цикл не раніше ніж через {interval_minutes} хв"
            ),
        )
        return changed

    def _store_local_safe_audit(
        self, video_id: str, description: str, tags: list[str]
    ) -> None:
        row = self.conn.execute(
            "SELECT title,duration FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
        title = str(row["title"] or "") if row else ""
        duration = str(row["duration"] or "") if row else ""
        result = audit(description, tags, title, duration)
        payload = json.dumps(
            {"score": result.score, "issues": list(result.issues)},
            ensure_ascii=False,
        )
        self.conn.execute(
            "UPDATE videos SET audit_json=? WHERE video_id=?",
            (payload, video_id),
        )
        self.conn.commit()

    def apply_next_safe_archive_batch(
        self,
        daily: bool = False,
        *,
        confirm: bool = True,
        notify: bool = True,
    ) -> int:
        budget = quota_budget_status(self.conn)
        if daily and not archive_priority_enabled(self.conn):
            if notify:
                QMessageBox.information(
                    self,
                    "Пріоритет архіву",
                    "Для денного пакета спочатку увімкніть «Пріоритет архіву».",
                )
            return 0

        if daily:
            batch_limit = reserve_safe_daily_batch_capacity(
                int(budget["spendable"]),
                500,
            )
        else:
            batch_limit = reserve_safe_batch_capacity(
                int(budget["spendable"]),
                DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT,
                final_refresh_reads=1,
            )
        if batch_limit <= 0:
            save_campaign_checkpoint(
                self.conn,
                phase="safe",
                target=self.current_profile,
                status="paused_quota",
                note="protected_comment_reserve",
            )
            if notify:
                QMessageBox.information(
                    self,
                    "Резерв квоти",
                    "Безпечний резерв квоти вже досягнуто. "
                    "Архівну партію сьогодні не запускаємо.",
                )
            return 0
        use_prepared = (
            not daily
            and hasattr(self, "optimization_filter")
            and self.optimization_filter.currentData() == "prepared"
        )
        if use_prepared:
            prepared_ids = self._prepared_queue_ids()
            valid_ids = []
            for video_id in prepared_ids:
                row = self.conn.execute(
                    """SELECT v.audit_json,d.status
                       FROM videos v
                       JOIN optimization_drafts d ON d.video_id=v.video_id
                       WHERE v.video_id=? AND v.profile=?
                         AND v.privacy_status='public'
                         AND v.scheduled_publish_at IS NULL""",
                    (video_id, self.current_profile),
                ).fetchone()
                if row is None or str(row["status"] or "") != "ready":
                    continue
                try:
                    issues = json.loads(row["audit_json"] or "{}").get(
                        "issues", []
                    )
                except Exception:
                    issues = []
                if "latin_title_review" in issues:
                    continue
                valid_ids.append(video_id)
            video_ids = valid_ids[:batch_limit]
            total_candidates = len(valid_ids)
        else:
            video_ids, total_candidates = self._safe_archive_candidates(
                limit=batch_limit
            )
        if not video_ids:
            if notify:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "В архіві більше немає відео з безпечними правками.",
                )
            return 0

        refresh_reads = (len(video_ids) + 49) // 50
        metadata_reads = refresh_reads if daily else len(video_ids)
        estimated = (
            len(video_ids) * VIDEO_UPDATE_COST
            + metadata_reads * READ_REQUEST_COST
            + refresh_reads * READ_REQUEST_COST
        )
        dialog_title = (
            "Архів: денний пакет"
            if daily
            else f"Архів: безпечні {DEFAULT_ARCHIVE_SAFE_BATCH_LIMIT}"
        )
        if confirm:
            answer = QMessageBox.question(
                self,
                dialog_title,
                f"Знайдено відео з безпечними правками: {total_candidates}.\n"
                f"Зараз буде оброблено: {len(video_ids)}.\n"
                f"Безпечний ліміт за поточною квотою: {batch_limit}.\n"
                + (
                    "Режим: весь доступний денний бюджет архіву.\n"
                    if daily
                    else ""
                )
                + f"Максимальна фактична витрата: ≈{estimated} од. квоти.\n"
                f"Резерв {budget['reserve']} од. не буде використано.\n\n"
                + (
                    "Використовується підготовлена черга за пріоритетом.\n"
                    if use_prepared
                    else "Черга автоматично відсортована за потенціалом оптимізації.\n"
                )
                + (
                    "Буде застосовано підготовлені опис і теги. "
                    "Назва відео та налаштування публікації не змінюються. "
                    if use_prepared
                    else
                    "Буде змінено лише старі або відсутні посилання "
                    "проєкту й донату та окремий рядок хештегів: "
                    "2 постійні + 1 тематичний. Назва, теги YouTube, "
                    "розділи та решта тексту залишаться без змін. "
                )
                + "Для кожного запису зберігається точка відкату. "
                "Продовжити?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 0
        backup_reason = (
            f"перед денним пакетом архіву · {self.current_profile}"
            if daily
            else f"перед безпечним пакетом архіву · {self.current_profile}"
        )
        if not self._prechange_backup_or_warn(
            backup_reason,
            notify=notify,
        ):
            return 0

        prefetched_metadata: dict[str, dict] = {}
        if daily:
            counted = getattr(
                self.client,
                "video_details_with_request_count",
                None,
            )
            if callable(counted):
                items, requests = counted(video_ids)
                record_quota_units(
                    self.conn,
                    int(requests) * READ_REQUEST_COST,
                purpose="video",
                )
            else:
                items = self.client.video_details(video_ids)
                requests = (len(video_ids) + 49) // 50
                record_quota_units(
                    self.conn,
                    requests * READ_REQUEST_COST,
                purpose="video",
                )
            prefetched_metadata = {
                str(item.get("id") or ""): item
                for item in items
                if item.get("id")
            }
            self.refresh_youtube_quota_label()

        changed_ids: list[str] = []
        skipped_ids: list[str] = []
        error_text = ""
        progress = None
        if daily and notify:
            progress = QProgressDialog(
                "Обробка денного пакета архіву...",
                "Зупинити після поточного відео",
                0,
                len(video_ids),
                self,
            )
            progress.setWindowTitle("Архів: денний пакет")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.show()

        self._set_process(
            dialog_title,
            "підготовка",
            percent=0,
            eta=f"{len(video_ids)} відео · ≈{estimated} од. максимум",
        )
        try:
            for index, video_id in enumerate(video_ids, start=1):
                self._set_process(
                    dialog_title,
                    f"{index}/{len(video_ids)} · {video_id}",
                    percent=round((index - 1) / max(1, len(video_ids)) * 100),
                    eta=f"залишок ≈{len(video_ids) - index + 1} відео",
                )
                if progress is not None:
                    if progress.wasCanceled():
                        error_text = "cancelled"
                        break
                    progress.setLabelText(
                        f"Обробка {index}/{len(video_ids)} · {video_id}"
                    )
                    progress.setValue(index - 1)
                self.statusBar().showMessage(
                    f"Безпечна оптимізація архіву: "
                    f"{index}/{len(video_ids)} · {video_id}"
                )
                QApplication.processEvents()
                try:
                    live_budget = quota_budget_status(self.conn)
                    required_cost = (
                        VIDEO_UPDATE_COST
                        if daily
                        else SAFE_METADATA_ITEM_COST
                    )
                    if int(live_budget["spendable"]) < required_cost:
                        error_text = "reserve_reached"
                        break
                    if daily:
                        item = prefetched_metadata.get(video_id)
                        if item is None:
                            skipped_ids.append(video_id)
                            if progress is not None:
                                progress.setValue(index)
                            continue
                        snippet = item.get("snippet", {})
                        title = snippet.get("title", "")
                        description = snippet.get("description", "")
                        tags = snippet.get("tags", []) or []
                    else:
                        title, description, tags = self._current_video_metadata(
                            video_id
                        )

                    if use_prepared:
                        draft = get_optimization_draft(self.conn, video_id)
                        if draft is None or str(draft["status"] or "") != "ready":
                            skipped_ids.append(video_id)
                            if progress is not None:
                                progress.setValue(index)
                            continue
                        prepared_description = str(
                            draft["description"] or ""
                        ).strip()
                        try:
                            prepared_tags = [
                                str(item).strip()
                                for item in json.loads(
                                    draft["tags_json"] or "[]"
                                )
                                if str(item).strip()
                            ]
                        except Exception:
                            prepared_tags = []
                        check = validate_content_package(
                            title,
                            prepared_description,
                            "",
                            prepared_tags,
                            [],
                        )
                        if check.errors:
                            error_text = (
                                f"{video_id}: "
                                + "; ".join(check.errors)
                            )
                            break
                        same_description = prepared_description == description
                        same_tags = (
                            sorted(item.casefold() for item in prepared_tags)
                            == sorted(str(item).casefold() for item in tags)
                        )
                        if same_description and same_tags:
                            set_optimization_draft_status(
                                self.conn,
                                video_id,
                                "applied",
                            )
                            skipped_ids.append(video_id)
                            if progress is not None:
                                progress.setValue(index)
                            continue
                        history_id = save_metadata_snapshot(
                            self.conn,
                            video_id,
                            title,
                            description,
                            tags,
                            "before_content_package",
                        )
                        self._quota_update_video_with_client(
                            self.client,
                            video_id,
                            description=prepared_description,
                            tags=prepared_tags,
                            safe_mode=True,
                            respect_reserve=True,
                        )
                        record_optimization_event(
                            self.conn,
                            history_id=history_id,
                            video_id=video_id,
                            profile=self.current_profile,
                            reason="content_package",
                            changed_fields="опис + теги · 0-quota prepared",
                        )
                        set_optimization_draft_status(
                            self.conn,
                            video_id,
                            "applied",
                        )
                        self._store_local_safe_audit(
                            video_id,
                            prepared_description,
                            prepared_tags,
                        )
                    else:
                        fix = safe_description_fix(description, title)
                        if not fix.changes or fix.after == description:
                            skipped_ids.append(video_id)
                            if progress is not None:
                                progress.setValue(index)
                            continue

                        history_id = save_metadata_snapshot(
                            self.conn,
                            video_id,
                            title,
                            description,
                            tags,
                            "before_safe_archive_batch",
                        )
                        self._quota_update_video_with_client(
                            self.client,
                            video_id,
                            description=fix.after,
                            safe_mode=True,
                            respect_reserve=True,
                        )
                        record_optimization_event(
                            self.conn,
                            history_id=history_id,
                            video_id=video_id,
                            profile=self.current_profile,
                            reason="safe_archive_batch",
                            changed_fields="посилання + хештеги",
                        )
                        self._store_local_safe_audit(
                            video_id,
                            fix.after,
                            tags,
                        )
                    changed_ids.append(video_id)
                    if progress is not None:
                        progress.setValue(index)
                except Exception as exc:
                    if _is_quota_exceeded_error(exc):
                        mark_quota_exhausted(self.conn)
                        self.refresh_youtube_quota_label()
                        error_text = "quota_exceeded"
                    else:
                        error_text = f"{video_id}: {exc}"
                    break

            if progress is not None:
                progress.close()

            if changed_ids:
                counter_key = (
                    f"archive_campaign_changed_{self.current_profile}_"
                    f"{current_quota_day()}"
                )
                previous = int(
                    get_setting(self.conn, counter_key, "0") or 0
                )
                set_setting(
                    self.conn,
                    counter_key,
                    str(previous + len(changed_ids)),
                )

            refresh_ids = changed_ids + skipped_ids
            if refresh_ids and error_text not in {"quota_exceeded", "cancelled"}:
                sync_specific_videos(self.client, self.conn, refresh_ids)
            self.reload_videos()
            self.reload_optimization_queue()
            self._advance_archive_campaign()

            remaining = max(
                0,
                total_candidates - len(changed_ids) - len(skipped_ids),
            )
            message = (
                f"Готово. Змінено: {len(changed_ids)}. "
                f"Без змін: {len(skipped_ids)}.\n"
                f"Залишилося в черзі безпечних правок: ≈{remaining}."
            )
            if notify:
                if error_text == "cancelled":
                    QMessageBox.information(
                        self,
                        "Денний пакет зупинено",
                        message
                        + "\n\nЗупинено користувачем. Уже змінені відео "
                        "збережено, решта залишилася в черзі.",
                    )
                elif error_text == "quota_exceeded":
                    QMessageBox.warning(
                        self,
                        "Квоту YouTube вичерпано",
                        message
                        + "\n\nДенну квоту YouTube Data API вичерпано. "
                        "Обробку зупинено безпечно. Уже змінені відео "
                        "збережено й повторно в чергу не потраплять. "
                        "Продовжіть після відновлення квоти.",
                    )
                elif error_text:
                    QMessageBox.warning(
                        self,
                        APP_NAME,
                        message + f"\n\nОбробку зупинено через помилку:\n{error_text}",
                    )
                else:
                    self._set_process_idle("Архівний пакет завершено")
                    self._toast("✓ " + message.replace("\n", " · "), 8000)
            return len(changed_ids)
        except Exception as exc:
            if progress is not None:
                progress.close()
            if notify:
                self._error("Помилка пакетної оптимізації архіву", exc)
            else:
                log_action(
                    self.conn,
                    profile=self.current_profile,
                    category="кампанія архіву",
                    action="Автозапуск зупинено",
                    details=str(exc),
                )
            return len(changed_ids)

    def apply_safe_optimization(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if not video_ids:
            QMessageBox.information(
                self, APP_NAME, "Виберіть відео для безпечної оптимізації."
            )
            return
        if len(video_ids) > 20:
            QMessageBox.warning(
                self,
                APP_NAME,
                "За один пакет можна обробити не більше 20 відео.",
            )
            return

        budget = quota_budget_status(self.conn)
        safe_capacity = reserve_safe_batch_capacity(
            int(budget["spendable"]),
            len(video_ids),
            final_refresh_reads=1,
        )
        if safe_capacity < len(video_ids):
            QMessageBox.warning(
                self,
                "Резерв квоти",
                f"Вибрано: {len(video_ids)}. "
                f"Зараз безпечно можна змінити не більше: {safe_capacity}.\n\n"
                "Зменште вибір або продовжіть наступного квотного дня.",
            )
            return

        estimated = (
            len(video_ids) * SAFE_METADATA_ITEM_COST
            + READ_REQUEST_COST
        )
        answer = QMessageBox.question(
            self,
            "Застосувати безпечні правки",
            f"Вибрано відео: {len(video_ids)}.\n"
            f"Максимальна фактична витрата: ≈{estimated} од. квоти.\n"
            f"Резерв квоти не буде використано.\n\n"
            "Буде змінено лише старі/відсутні посилання та окремий рядок "
            "хештегів: 2 постійні + 1 тематичний. "
            "Назва, теги YouTube та решта тексту залишаться без змін. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if len(video_ids) > 1 and not self._prechange_backup_or_warn(
            f"перед безпечною оптимізацією {len(video_ids)} відео · "
            f"{self.current_profile}"
        ):
            return

        changed = 0
        skipped = 0
        changed_ids: list[str] = []
        self._set_process(
            "Безпечна оптимізація",
            "запис у YouTube",
            percent=0,
            eta=f"{len(video_ids)} відео",
        )
        try:
            for index, video_id in enumerate(video_ids, start=1):
                self._set_process(
                    "Безпечна оптимізація",
                    f"{index}/{len(video_ids)} · {video_id}",
                    percent=round((index - 1) / max(1, len(video_ids)) * 100),
                    eta=f"≈{estimated} од. квоти максимум",
                )
                title, description, tags = self._current_video_metadata(video_id)
                fix = safe_description_fix(description, title)
                if safe_description_needs_content_package(fix.after, title):
                    skipped += 1
                    log_action(
                        self.conn,
                        profile=self.current_profile,
                        category="безпечна оптимізація",
                        action="Пропущено",
                        details=(
                            f"{video_id}: після очищення немає достатнього "
                            "змістовного опису; потрібен контент-пакет"
                        ),
                    )
                    continue
                if not fix.changes or fix.after == description:
                    skipped += 1
                    continue
                history_id = save_metadata_snapshot(
                    self.conn,
                    video_id,
                    title,
                    description,
                    tags,
                    "before_safe_optimization",
                )
                self._quota_update_video_with_client(
                    self.client,
                    video_id,
                    description=fix.after,
                    safe_mode=True,
                    respect_reserve=True,
                )
                record_optimization_event(
                    self.conn, history_id=history_id, video_id=video_id,
                    profile=self.current_profile, reason="safe_optimization",
                    changed_fields="посилання + хештеги",
                )
                changed += 1
                changed_ids.append(video_id)

            if changed_ids:
                sync_specific_videos(self.client, self.conn, changed_ids)
            self.reload_videos()
            self.reload_optimization_queue()
            self._set_process_idle("Безпечна оптимізація завершена")
            self._toast(
                f"✓ Безпечна оптимізація: змінено {changed} · "
                f"без змін {skipped}",
                7000,
            )
        except Exception as exc:
            self._error("Помилка безпечної оптимізації", exc)

    def rollback_last_optimized_metadata(self) -> None:
        if quota_exhausted(self.conn):
            QMessageBox.information(
                self,
                "Квоту YouTube вичерпано",
                "Відкат заблоковано до наступного квотного дня.",
            )
            return
        row = self.conn.execute(
            """SELECT video_id,optimized_at
               FROM optimization_events
               WHERE profile=?
               ORDER BY optimized_at DESC,event_id DESC
               LIMIT 1""",
            (self.current_profile,),
        ).fetchone()
        if row is None:
            self._toast("Немає останньої оптимізації для відкату")
            return
        video_id = str(row["video_id"] or "")
        snapshot = latest_metadata_snapshot(self.conn, video_id)
        if snapshot is None:
            self._toast("Для останньої оптимізації немає точки відкату")
            return

        answer = QMessageBox.question(
            self,
            "Відкотити останню зміну",
            f"Відео: {video_id}\n"
            f"Оптимізація: {str(row['optimized_at'] or '')[:19]}\n\n"
            f"Повернути попередні назву, опис і теги? "
            f"Це використає ≈{VIDEO_UPDATE_COST + READ_REQUEST_COST} од. квоти.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        import json
        try:
            current_title, current_description, current_tags = (
                self._current_video_metadata(video_id)
            )
            save_metadata_snapshot(
                self.conn,
                video_id,
                current_title,
                current_description,
                current_tags,
                "before_quick_undo",
            )
            self._set_process(
                f"Відкат · {video_id}",
                "videos.update",
                percent=None,
                eta=f"≈{VIDEO_UPDATE_COST + READ_REQUEST_COST} од. квоти",
            )
            self._quota_update_video(
                video_id,
                title=snapshot["title"],
                description=snapshot["description"],
                tags=json.loads(snapshot["tags_json"] or "[]"),
            )
            sync_specific_videos(self.client, self.conn, [video_id])
            self.reload_videos()
            self.reload_optimization_queue()
            self._set_process_idle("Останню зміну відкотили")
            self._toast("✓ Попередні метадані відновлено")
        except Exception as exc:
            self._error("Помилка швидкого відкату", exc)

    def rollback_selected_metadata(self) -> None:
        if quota_exhausted(self.conn):
            QMessageBox.information(
                self,
                "Квоту YouTube вичерпано",
                "Відкат метаданих через YouTube API заблоковано до "
                "наступного квотного дня.",
            )
            return
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для відкату виберіть рівно одне відео."
            )
            return
        video_id = video_ids[0]
        snapshot = latest_metadata_snapshot(self.conn, video_id)
        if snapshot is None:
            QMessageBox.information(
                self, APP_NAME, "Для цього відео ще немає збереженої версії."
            )
            return

        import json
        answer = QMessageBox.question(
            self,
            "Відкат метаданих",
            f"Повернути метадані зі збереження {snapshot['created_at']}?\n"
            f"Причина збереження: {snapshot['reason']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            current_title, current_description, current_tags = (
                self._current_video_metadata(video_id)
            )
            save_metadata_snapshot(
                self.conn,
                video_id,
                current_title,
                current_description,
                current_tags,
                "before_rollback",
            )
            self._quota_update_video(
                video_id,
                title=snapshot["title"],
                description=snapshot["description"],
                tags=json.loads(snapshot["tags_json"] or "[]"),
            )
            sync_specific_videos(self.client, self.conn, [video_id])
            self.reload_videos()
            self.reload_optimization_queue()
            self.statusBar().showMessage("Метадані відео відновлено")
        except Exception as exc:
            self._error("Помилка відкату метаданих", exc)

    def run_background_maintenance(self) -> None:
        if archive_priority_enabled(self.conn):
            self._run_archive_campaign_autorun()
            self.check_quota_plan_ready()
            return

        changed_total = 0
        summaries: list[str] = []
        for profile in PROFILE_TARGETS:
            if get_setting(
                self.conn,
                f"safe_metadata_autopilot_{profile}",
                "0",
            ) != "1":
                continue
            client = YouTubeClient(profile=profile)
            try:
                client.credentials()
            except Exception:
                continue
            changed = self._run_safe_metadata_autopilot(
                profile,
                client,
                max_items=3,
            )
            if changed:
                changed_total += changed
                summaries.append(
                    f"{PROFILE_LABELS[profile]}: {changed}"
                )

        if changed_total:
            self.reload_videos()
            self.reload_optimization_queue()
            self.reload_action_log()
            self.update_dashboard()
            self.statusBar().showMessage(
                "Автопілот безпечних метаданих: "
                + ", ".join(summaries)
            )
        self.check_quota_plan_ready()

    def background_scan_all_channels(self) -> None:
        if not hasattr(self, "background_box") or not self.background_box.isChecked():
            return
        if getattr(self, "_archive_campaign_autorun_running", False):
            return
        if archive_priority_enabled(self.conn):
            now = datetime.now(timezone.utc)
            raw = get_setting(
                self.conn,
                "archive_priority_comment_scan_last",
                "",
            )
            if raw:
                try:
                    last = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    if (now - last).total_seconds() < 30 * 60:
                        return
                except ValueError:
                    pass
            set_setting(
                self.conn,
                "archive_priority_comment_scan_last",
                now.isoformat(),
            )

        summaries: list[str] = []
        for profile, target_id in PROFILE_TARGETS.items():
            client = YouTubeClient(profile=profile)
            try:
                client.credentials()
            except Exception:
                continue

            default_auto = (
                get_setting(self.conn, "auto_reply_enabled", "0")
                if profile == "main"
                else "0"
            )
            auto_enabled = get_setting(
                self.conn,
                f"auto_reply_enabled_{profile}",
                default_auto,
            ) == "1"
            daily_limit = int(
                get_setting(
                    self.conn,
                    f"auto_reply_daily_limit_{profile}",
                    str(DEFAULT_MAX_AUTO_REPLIES_PER_DAY),
                )
            )
            scan_limit = int(
                get_setting(
                    self.conn,
                    f"auto_reply_scan_limit_{profile}",
                    str(DEFAULT_MAX_AUTO_REPLIES_PER_SCAN),
                )
            )
            age_hours = int(
                get_setting(
                    self.conn,
                    f"auto_reply_max_age_hours_{profile}",
                    str(DEFAULT_AUTO_REPLY_MAX_AGE_HOURS),
                )
            )

            try:
                stats = scan_channel_comments(
                    client,
                    self.conn,
                    target_id,
                    auto_reply=auto_enabled,
                    max_auto_replies=daily_limit,
                    max_auto_replies_per_scan=scan_limit,
                    max_auto_age_hours=age_hours,
                )
                summaries.append(
                    f"{PROFILE_LABELS[profile]}: нових {stats['seen']}, "
                    f"авто {stats['auto_replied']}, API {stats['api_reads']}"
                )
            except Exception:
                summaries.append(f"{PROFILE_LABELS[profile]}: помилка")

        self.reload_comments()
        self.reload_action_log()
        self.update_dashboard()
        if summaries:
            self.statusBar().showMessage(" · ".join(summaries))

    def scan_comment_queue(self, silent: bool = False) -> None:
        if silent and not self.background_box.isChecked():
            return
        profile = self.current_profile
        try:
            stats = scan_channel_comments(
                self.client,
                self.conn,
                PROFILE_TARGETS[profile],
                auto_reply=self.auto_box.isChecked(),
                max_auto_replies=self.daily_limit_spin.value(),
                max_auto_replies_per_scan=self.scan_limit_spin.value(),
                max_auto_age_hours=self.age_limit_spin.value(),
            )
            self.reload_comments()
            self.reload_action_log()
            self.statusBar().showMessage(
                "Нові: {seen} · черга: {queued} · авто: {auto_replied} · "
                "вже відповіли: {already_replied} · перевірка: {skipped_review} · "
                "ліміт: {skipped_limit} · API читань: {api_reads} · "
                "відомих пропущено: {known_skipped} · квота: {quota_blocked}".format(
                    **stats
                )
            )
        except Exception as exc:
            if silent:
                self.statusBar().showMessage("Фонова перевірка коментарів не виконана")
            else:
                self._error("Помилка коментарів", exc)

    def _test_reply_fallback(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=self.age_limit_spin.value()
        )
        rows = self.conn.execute(
            """SELECT c.comment_id,c.author,c.text,c.published_at,
                      v.title AS video_title,c.reply_text
               FROM comments c
               JOIN videos v ON v.video_id=c.video_id
               WHERE v.profile=? AND c.status='new'
               ORDER BY c.published_at DESC
               LIMIT 100""",
            (self.current_profile,),
        ).fetchall()

        candidates = []
        for row in rows:
            raw = str(row["published_at"] or "")
            try:
                published = datetime.fromisoformat(
                    raw.replace("Z", "+00:00")
                )
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if published < cutoff:
                continue
            candidates.append(row)
            if len(candidates) >= 10:
                break

        if not candidates:
            QMessageBox.information(
                self,
                APP_NAME,
                "Немає свіжих коментарів для контрольного ручного тесту.",
            )
            return

        labels = []
        for row in candidates:
            text = " ".join(str(row["text"] or "").split())
            if len(text) > 70:
                text = text[:67] + "..."
            labels.append(
                f"{row['author'] or '—'} · {text}"
            )

        selected, ok = QInputDialog.getItem(
            self,
            "Контрольний тест відповіді",
            "Автоматично безпечного кандидата немає.\n"
            "Виберіть один свіжий коментар для ручного контрольного тесту:",
            labels,
            0,
            False,
        )
        if not ok or not selected:
            return

        index = labels.index(selected)
        row = candidates[index]
        original_text = str(row["text"] or "")
        suggested = str(row["reply_text"] or "").strip()
        if not suggested:
            suggested = "Дякуємо за коментар!"

        reply_text, ok = QInputDialog.getMultiLineText(
            self,
            "Перевірка відповіді",
            "Повний коментар:\n"
            f"{original_text}\n\n"
            "Відповідь нижче можна відредагувати перед відправленням:",
            suggested,
        )
        if not ok:
            return
        reply_text = reply_text.strip()
        if not reply_text:
            QMessageBox.information(
                self,
                APP_NAME,
                "Порожню відповідь не надіслано.",
            )
            return

        budget = quota_budget_status(self.conn)
        if (
            int(budget["spendable"]) < COMMENT_REPLY_COST
            or bool(budget["exhausted"])
        ):
            QMessageBox.information(
                self,
                APP_NAME,
                "Контрольну відповідь не відправлено: досягнуто резерву "
                "або вичерпано квоту.",
            )
            return

        confirm = QMessageBox.question(
            self,
            "Підтвердити контрольну відповідь",
            f"Коментар:\n{original_text}\n\n"
            f"Відповідь:\n{reply_text}\n\n"
            "Надіслати цю одну відповідь у YouTube?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        manual_reply(
            self.client,
            self.conn,
            str(row["comment_id"]),
            reply_text,
        )
        self.reload_comments()
        self.reload_action_log()
        self.update_dashboard()
        QMessageBox.information(
            self,
            APP_NAME,
            "Контрольний тест успішний: надіслано 1 підтверджену відповідь.",
        )

    def test_one_auto_reply(self) -> None:
        answer = QMessageBox.question(
            self,
            "Тест автовідповіді",
            "Програма спочатку спробує взяти один свіжий безпечний "
            "коментар із локальної черги. Якщо такого немає - перевірить "
            "нові коментарі YouTube. Буде надіслано максимум одну відповідь. "
            "Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            queued = reply_one_queued_safe_comment(
                self.client,
                self.conn,
                self.current_profile,
                max_auto_age_hours=self.age_limit_spin.value(),
                max_auto_replies=self.daily_limit_spin.value(),
            )
            if queued["sent"] == 1:
                self.reload_comments()
                self.reload_action_log()
                self.update_dashboard()
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Тест успішний: надіслано 1 безпечну автовідповідь "
                    "із локальної черги.",
                )
                return
            if queued["quota_blocked"] > 0:
                budget = quota_budget_status(self.conn)
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Тестову відповідь не відправлено через обмеження квоти.\n"
                    f"Залишок: ≈{budget['remaining']} од. · "
                    f"резерв: {budget['reserve']} од.\n"
                    f"Скидання: {budget['reset']}.",
                )
                return
            if queued["limit_blocked"] > 0:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Денний ліміт автовідповідей для цього каналу вже досягнуто.",
                )
                return

            stats = scan_channel_comments(
                self.client,
                self.conn,
                PROFILE_TARGETS[self.current_profile],
                auto_reply=True,
                max_auto_replies=self.daily_limit_spin.value(),
                max_auto_replies_per_scan=1,
                max_auto_age_hours=self.age_limit_spin.value(),
            )
            self.reload_comments()
            self.reload_action_log()
            self.update_dashboard()
            if stats["auto_replied"] == 1:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Тест успішний: надіслано 1 безпечну автовідповідь "
                    "на новий коментар.",
                )
            elif stats["quota_blocked"] > 0:
                budget = quota_budget_status(self.conn)
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Тестову відповідь не відправлено через обмеження квоти.\n"
                    f"Залишок: ≈{budget['remaining']} од. · "
                    f"резерв: {budget['reserve']} од.\n"
                    f"Скидання: {budget['reset']}.",
                )
            else:
                self._test_reply_fallback()
        except Exception as exc:
            self._error("Помилка тестової автовідповіді", exc)

    def reload_videos(self) -> None:
        import json

        profile = self.current_profile
        search = (
            self.video_search.text().strip().casefold()
            if hasattr(self, "video_search")
            else ""
        )
        rows = self.conn.execute(
            "SELECT video_id,title,views,audit_json FROM videos "
            "WHERE profile=? ORDER BY published_at DESC LIMIT 1200",
            (profile,),
        ).fetchall()
        if search:
            rows = [
                row for row in rows
                if search in str(row["video_id"] or "").casefold()
                or search in str(row["title"] or "").casefold()
            ]

        self.video_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            audit_data = json.loads(row["audit_json"] or "{}")
            issues = _issue_labels(list(audit_data.get("issues", [])))
            values = [
                row["video_id"],
                row["title"],
                str(row["views"] or 0),
                str(audit_data.get("score", "")),
                issues,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row["video_id"])
                if column == 3:
                    score = int(audit_data.get("score") or 0)
                    item.setForeground(
                        QColor(
                            SUCCESS
                            if score >= 100
                            else WARNING
                            if score >= 70
                            else YOUTUBE_RED
                        )
                    )
                    item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                self.video_table.setItem(index, column, item)
        if hasattr(self, "video_density"):
            self._apply_table_density(self.video_table, self.video_density)
        self._update_video_context_card()
        self.update_dashboard()


    def _run_local_tool(self, label: str, func, on_success) -> None:
        worker = getattr(self, "_local_tool_worker", None)
        if worker is not None and worker.isRunning():
            self._toast("Локальний інструмент уже виконує інше завдання")
            return

        self._last_local_task = (label, func, on_success)
        self._set_process(label, "виконується", percent=None, eta="локально · 0 квоти")
        self.statusBar().showMessage(f"{label}...")

        def resilient_task():
            last_exc = None
            for attempt in range(1, 4):
                try:
                    return func()
                except Exception as exc:
                    last_exc = exc
                    text = str(exc).casefold()
                    transient = any(
                        token in text
                        for token in (
                            "timeout",
                            "timed out",
                            "connection",
                            "tempor",
                            "reset by peer",
                            "503",
                            "502",
                            "429",
                        )
                    )
                    if not transient or attempt >= 3:
                        raise
                    delay = 2 * attempt
                    worker_ref = getattr(self, "_local_tool_worker", None)
                    if worker_ref is not None:
                        worker_ref.progress.emit(
                            f"Спроба {attempt + 1}/3 через {delay} с"
                        )
                    time.sleep(delay)
            if last_exc is not None:
                raise last_exc

        worker = LocalToolWorker(resilient_task, self)
        self._local_tool_worker = worker

        def success(result) -> None:
            try:
                on_success(result)
                self._last_failed_local_task = None
                self._set_process_idle(f"{label} · готово")
                self._toast(f"✓ {label} · готово")
                self.update_task_center()
            except Exception as exc:
                self._set_process(
                    label,
                    "помилка",
                    percent=100,
                    error=True,
                )
                self._error("Помилка локального інструмента", exc)

        def failed(message: str) -> None:
            self._last_failed_local_task = (label, func, on_success)
            self._set_process(label, "помилка", percent=100, error=True)
            self.statusBar().showMessage("Локальний інструмент: помилка")
            log_action(
                self.conn,
                profile=self.current_profile,
                category="локально",
                action="Помилка локального інструмента",
                details=f"{label}: {message[:400]}",
            )
            self.update_task_center()

        def cleanup() -> None:
            self._local_tool_worker = None

        worker.progress.connect(
            lambda message: self._set_process(
                label,
                message,
                percent=None,
                eta="автоматичний retry",
            )
        )
        worker.succeeded.connect(success)
        worker.failed.connect(failed)
        worker.finished.connect(cleanup)
        worker.start()


    def refresh_free_tools_status(self) -> None:
        try:
            probes = probe_free_tools()
            self._free_tools_last_probe = probes
            yt = probes.get("yt_dlp", {})
            tr = probes.get("transcript", {})
            ol = probes.get("ollama", {})
            model = probes.get("ollama_model", {})
            text = (
                "0-quota · yt-dlp: "
                + ("OK" if yt.get("available") else "—")
                + " · transcript: "
                + ("OK" if tr.get("available") else "—")
                + " · Ollama: "
                + ("OK" if ol.get("available") else "—")
                + " · "
                + DEFAULT_OLLAMA_MODEL
                + ": "
                + ("OK" if model.get("available") else "не готова")
            )
            if hasattr(self, "free_tools_status_label"):
                self.free_tools_status_label.setText(text)
            self._set_health_state(
                "ollama",
                bool(ol.get("available") and model.get("available")),
                "Ollama",
            )
            self._set_health_state(
                "transcript",
                bool(tr.get("available")),
                "Transcript",
            )
            self._toast(text, 3500)
            self.update_task_center()
        except Exception as exc:
            self._free_tools_last_probe = {}
            if hasattr(self, "free_tools_status_label"):
                self.free_tools_status_label.setText(f"0-quota: {exc}")
            self._set_health_state("ollama", False, "Ollama")
            self._set_health_state("transcript", False, "Transcript")


    def local_seo_selected(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self,
                APP_NAME,
                "Для локального SEO виберіть рівно одне відео.",
            )
            return
        video_id = video_ids[0]

        def task():
            context = fetch_public_metadata(video_id)
            current_title = str(context.get("title") or "")
            raw_description = str(context.get("description") or "")
            cleaned_description = safe_description_fix(
                raw_description,
                current_title,
            ).after
            needs_transcript = safe_description_needs_content_package(
                cleaned_description,
                current_title,
            )

            trends_path = self.data_dir / "google_trends_latest.json"
            if trends_path.exists():
                try:
                    context["google_trends"] = load_google_trends_summary(
                        trends_path,
                        max_terms=12,
                    )
                except Exception:
                    context["google_trends"] = []
            try:
                transcript_rows = fetch_transcript(video_id)
                transcript = transcript_sample_text(
                    transcript_rows,
                    max_chars=12000,
                    segments=6,
                )
            except Exception:
                transcript_rows = []
                transcript = ""

            if needs_transcript and not transcript.strip():
                raise RuntimeError(
                    "Для цього відео після очищення старого опису немає "
                    "достатнього змістовного тексту, а транскрипт недоступний. "
                    "SEO-пакет не створено, щоб не вигадувати зміст."
                )

            context_for_model = dict(context)
            context_for_model["description"] = cleaned_description
            package = generate_seo_package_local(
                current_title=current_title,
                current_description=cleaned_description,
                current_tags=list(context.get("tags") or []),
                transcript=transcript,
                public_context=context_for_model,
                is_short=int(context.get("duration") or 0) <= 70,
            )
            return {
                "video_id": video_id,
                "context": context,
                "transcript_rows": transcript_rows,
                "package": package,
            }

        self._run_local_tool(
            "Локальна SEO-оптимізація (0 квоти)",
            task,
            self._save_local_seo_result,
        )

    def _save_local_seo_result(self, result: dict) -> None:
        video_id = str(result["video_id"])
        package = dict(result["package"])
        context = dict(result["context"])

        title = str(package.get("title") or "").strip()
        description = str(package.get("description") or "").strip()
        description = sanitize_imported_package_description(
            description,
            title,
        ).after
        description = safe_description_fix(
            description,
            title,
        ).after
        tags = [
            str(item).strip()
            for item in package.get("tags", [])
            if str(item).strip()
        ]
        chapters = str(package.get("chapters") or "").strip()
        if chapters:
            chapters_ok, _ = validate_chapters(chapters)
            if not chapters_ok:
                chapters = ""
        variants = [
            str(item).strip()
            for item in package.get("title_variants", [])
            if str(item).strip()
        ]
        variants = list(dict.fromkeys(variants))
        variants = [item for item in variants if item.casefold() != title.casefold()]
        if len(variants) < 3:
            raise RuntimeError(
                "Локальна модель не створила 3 різні A/B варіанти назви. "
                "Пакет не збережено."
            )
        variants = variants[:3]

        check = validate_content_package(
            title,
            description,
            chapters,
            tags,
            variants,
        )
        if not check.ready:
            raise RuntimeError("\n".join(check.errors))

        before_title = str(context.get("title") or "")
        before_description = str(context.get("description") or "")
        before_tags = list(context.get("tags") or [])
        if not self._preview_deep_content_package(
            video_id=video_id,
            current_title=before_title,
            current_description=before_description,
            current_tags=before_tags,
            new_title=title,
            new_description=compose_description(description, chapters),
            new_tags=tags,
        ):
            self.statusBar().showMessage("Локальну SEO-чернетку скасовано")
            return

        save_optimization_draft(
            self.conn,
            video_id,
            title,
            description,
            chapters,
            tags,
            "ready",
            variants,
        )
        log_action(
            self.conn,
            profile=self.current_profile,
            category="локально",
            action="SEO-чернетка · 0 квоти",
            details=f"{video_id}: {package.get('provider', DEFAULT_OLLAMA_MODEL)}",
        )
        self.reload_optimization_queue()
        self.reload_action_log()
        self._set_process_idle("SEO-пакет готовий до застосування")
        self._toast(
            "✓ SEO-пакет перевірено · статус «Готово до застосування» · "
            "YouTube API: 0",
            7000,
        )
        self._update_optimization_context_card()

    def local_comment_reply_selected(self) -> None:
        row = self.comment_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, APP_NAME, "Виберіть опублікований коментар."
            )
            return
        key_item = self.comment_table.item(row, 0)
        comment_item = self.comment_table.item(row, 3)
        video_item = self.comment_table.item(row, 1)
        comment_id = key_item.data(Qt.ItemDataRole.UserRole)
        comment_text = comment_item.text() if comment_item else ""
        video_title = video_item.text() if video_item else ""
        if not comment_id or not comment_text.strip():
            return

        def task():
            return generate_comment_reply_local(
                comment_text=comment_text,
                video_title=video_title,
            )

        self._run_local_tool(
            "Локальна чернетка відповіді (0 квоти)",
            task,
            lambda text: self._save_local_comment_reply(
                str(comment_id), str(text)
            ),
        )

    def local_comment_reply_batch(self) -> None:
        rows = self.conn.execute(
            """SELECT c.comment_id,c.text,v.title AS video_title
               FROM comments c
               JOIN videos v ON v.video_id=c.video_id
               WHERE v.profile=?
                 AND c.status='new'
                 AND COALESCE(TRIM(c.reply_text),'')=''
               ORDER BY c.published_at DESC
               LIMIT 20""",
            (self.current_profile,),
        ).fetchall()
        items = [
            {
                "comment_id": str(row["comment_id"]),
                "comment_text": str(row["text"] or ""),
                "video_title": str(row["video_title"] or ""),
            }
            for row in rows
            if str(row["text"] or "").strip()
        ]
        if not items:
            QMessageBox.information(
                self,
                APP_NAME,
                "У локальній базі немає нових коментарів без чернетки.",
            )
            return

        def task():
            result = []
            for item in items:
                reply = generate_comment_reply_local(
                    comment_text=item["comment_text"],
                    video_title=item["video_title"],
                )
                result.append(
                    {
                        "comment_id": item["comment_id"],
                        "reply": reply,
                    }
                )
            return result

        self._run_local_tool(
            f"Локальні чернетки для {len(items)} коментарів (0 квоти)",
            task,
            self._save_local_comment_reply_batch,
        )

    def _save_local_comment_reply_batch(self, items: list[dict]) -> None:
        saved = 0
        for item in items:
            comment_id = str(item.get("comment_id") or "")
            reply = str(item.get("reply") or "").strip()
            if not comment_id or not reply:
                continue
            self.conn.execute(
                "UPDATE comments SET reply_text=? WHERE comment_id=? AND status='new'",
                (reply, comment_id),
            )
            saved += 1
        self.conn.commit()
        log_action(
            self.conn,
            profile=self.current_profile,
            category="локально",
            action="Пакет чернеток відповідей · 0 квоти",
            details=f"збережено {saved}; нічого не відправлено в YouTube",
        )
        self.reload_comments()
        self.reload_action_log()
        self.statusBar().showMessage(
            f"Локальні чернетки: {saved} · не опубліковано · 0 квоти"
        )
        QMessageBox.information(
            self,
            APP_NAME,
            f"Створено локальних чернеток: {saved}.\n"
            "У YouTube нічого не відправлено. Квота YouTube API: 0.",
        )

    def _save_local_comment_reply(self, comment_id: str, reply: str) -> None:
        text = (reply or "").strip()
        if not text:
            raise RuntimeError("Локальна модель повернула порожню відповідь.")
        self.conn.execute(
            "UPDATE comments SET reply_text=? WHERE comment_id=?",
            (text, comment_id),
        )
        self.conn.commit()
        log_action(
            self.conn,
            profile=self.current_profile,
            category="локально",
            action="Чернетка відповіді · 0 квоти",
            details=f"{comment_id}: збережено локально, не відправлено",
        )
        self.reload_comments()
        self.reload_action_log()
        self.statusBar().showMessage(
            "Чернетку відповіді збережено · не опубліковано · 0 квоти"
        )

    def import_google_trends_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Імпорт Google Trends CSV",
            "",
            "CSV (*.csv);;Усі файли (*.*)",
        )
        if not path:
            return
        try:
            rows = load_google_trends_csv(path)
            target = self.data_dir / "google_trends_latest.json"
            target.write_text(
                json.dumps(
                    {
                        "source_file": path,
                        "imported_at": datetime.now(timezone.utc).isoformat(),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            columns = list(rows[0].keys()) if rows else []
            QMessageBox.information(
                self,
                APP_NAME,
                f"Google Trends імпортовано локально.\n"
                f"Рядків: {len(rows)}. Полів: {len(columns)}.\n"
                "YouTube API квота: 0.",
            )
            self.statusBar().showMessage("Google Trends CSV імпортовано · 0 квоти")
        except Exception as exc:
            self._error("Помилка імпорту Google Trends", exc)

    def reload_comments(self, _index: int = -1) -> None:
        profile = self.current_profile
        status_filter = (
            self.comment_status_filter.currentData()
            if hasattr(self, "comment_status_filter")
            else ""
        )
        category_filter = (
            self.comment_category_filter.currentData()
            if hasattr(self, "comment_category_filter")
            else ""
        )

        query = """SELECT c.comment_id,c.published_at,c.video_id,v.title AS video_title,
                          c.author,c.text,c.category,c.status,c.reply_text
                   FROM comments c
                   JOIN videos v ON v.video_id=c.video_id
                   WHERE v.profile=?"""
        params: list[str] = [profile]
        if status_filter:
            query += " AND c.status=?"
            params.append(str(status_filter))
        if category_filter:
            query += " AND c.category=?"
            params.append(str(category_filter))
        query += " ORDER BY c.published_at DESC LIMIT 500"

        rows = self.conn.execute(query, tuple(params)).fetchall()
        self.comment_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row["published_at"] or "",
                row["video_title"] or row["video_id"],
                row["author"] or "",
                row["text"],
                COMMENT_CATEGORY_LABELS.get(
                    str(row["category"] or ""),
                    str(row["category"] or ""),
                ),
                COMMENT_STATUS_LABELS.get(
                    str(row["status"] or ""),
                    str(row["status"] or ""),
                ),
                row["reply_text"] or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row["comment_id"])
                    item.setData(Qt.ItemDataRole.UserRole + 1, row["video_id"])
                elif column == 4:
                    category_color = {
                        "thanks": SUCCESS,
                        "links": "#4da3ff",
                        "donate": WARNING,
                        "schedule": "#b78cff",
                        "review": MUTED,
                    }.get(str(row["category"]), MUTED)
                    item.setForeground(QColor(category_color))
                elif column == 5:
                    status_color = {
                        "replied": SUCCESS,
                        "new": YOUTUBE_RED,
                        "ignored": MUTED,
                    }.get(str(row["status"]), MUTED)
                    item.setForeground(QColor(status_color))
                    if str(row["status"]) in {"replied", "new"}:
                        item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                self.comment_table.setItem(index, column, item)

        self.update_dashboard()
        if hasattr(self, "auto_quota_label"):
            safe_used = today_auto_reply_count(self.conn, self.current_profile)
            total_used = today_reply_count(self.conn, self.current_profile)
            daily_limit = (
                self.daily_limit_spin.value()
                if hasattr(self, "daily_limit_spin")
                else DEFAULT_MAX_AUTO_REPLIES_PER_DAY
            )
            self.auto_quota_label.setText(
                f"Автовідповіді: {safe_used}/{daily_limit} "
                f"· надіслано через застосунок сьогодні: {total_used} "
                f"· ≈{total_used * VIDEO_UPDATE_COST} од. квоти"
            )

    def reply_selected(self) -> None:
        row = self.comment_table.currentRow()
        if row < 0:
            return
        key_item = self.comment_table.item(row, 0)
        draft_item = self.comment_table.item(row, 6)
        comment_id = key_item.data(Qt.ItemDataRole.UserRole)
        draft = draft_item.text() if draft_item else ""
        text, ok = QInputDialog.getMultiLineText(
            self, "Відповідь на коментар", "Текст відповіді:", draft
        )
        if not ok or not text.strip():
            return
        try:
            manual_reply(self.client, self.conn, comment_id, text.strip())
            self.reload_comments()
            self.statusBar().showMessage("Відповідь опубліковано")
        except Exception as exc:
            self._error("Помилка відповіді", exc)

    def set_selected_comment_status(self, status: str) -> None:
        row = self.comment_table.currentRow()
        if row < 0:
            return
        key_item = self.comment_table.item(row, 0)
        comment_id = key_item.data(Qt.ItemDataRole.UserRole)
        if not comment_id:
            return
        set_comment_status(self.conn, str(comment_id), status)
        self.reload_comments()
        labels = {
            "ignored": "Коментар позначено як проігнорований",
            "new": "Коментар повернуто в чергу",
        }
        self.statusBar().showMessage(labels.get(status, "Статус оновлено"))

    def save_reply_template(self, category: str, value: str) -> None:
        text = value.strip() or DEFAULT_REPLY_TEMPLATES[category]
        set_setting(
            self.conn,
            f"reply_template_{self.current_profile}_{category}",
            text,
        )
        if category in self.reply_template_edits:
            self.reply_template_edits[category][1].setText(text)
        self.statusBar().showMessage(
            f"Шаблон автовідповіді збережено для {PROFILE_LABELS[self.current_profile]}"
        )

    def save_auto_limits(self, _value: int = 0) -> None:
        profile = self.current_profile
        set_setting(
            self.conn,
            f"auto_reply_daily_limit_{profile}",
            str(self.daily_limit_spin.value()),
        )
        set_setting(
            self.conn,
            f"auto_reply_scan_limit_{profile}",
            str(self.scan_limit_spin.value()),
        )
        set_setting(
            self.conn,
            f"auto_reply_max_age_hours_{profile}",
            str(self.age_limit_spin.value()),
        )
        self.reload_comments()

    def save_quota_reserve(self, _value: int = 0) -> None:
        set_setting(
            self.conn,
            "youtube_quota_reserve_units",
            str(self.quota_reserve_spin.value()),
        )
        self.refresh_youtube_quota_label()
        self.update_task_center()

    def save_vidiq_budget(self, _value: int = 0) -> None:
        limit = int(self.vidiq_monthly_limit_spin.value())
        reserve = min(int(self.vidiq_reserve_spin.value()), limit)
        if reserve != self.vidiq_reserve_spin.value():
            self.vidiq_reserve_spin.blockSignals(True)
            self.vidiq_reserve_spin.setValue(reserve)
            self.vidiq_reserve_spin.blockSignals(False)
        status = set_vidiq_limits(
            self.conn,
            limit=limit,
            reserve=reserve,
        )
        self.vidiq_used_spin.blockSignals(True)
        self.vidiq_used_spin.setMaximum(status.limit)
        self.vidiq_used_spin.setValue(status.used)
        self.vidiq_used_spin.blockSignals(False)
        self.refresh_vidiq_quota_label()
        self.update_task_center()

    def save_vidiq_usage(self, _value: int = 0) -> None:
        status = set_vidiq_manual_usage(
            self.conn,
            int(self.vidiq_used_spin.value()),
        )
        self.vidiq_used_spin.blockSignals(True)
        self.vidiq_used_spin.setValue(status.used)
        self.vidiq_used_spin.blockSignals(False)
        self.refresh_vidiq_quota_label()
        self.update_task_center()

    def save_auto_setting(self, _state: int) -> None:
        set_setting(
            self.conn,
            f"auto_reply_enabled_{self.current_profile}",
            "1" if self.auto_box.isChecked() else "0",
        )
        if self.current_profile == "main":
            set_setting(
                self.conn,
                "auto_reply_enabled",
                "1" if self.auto_box.isChecked() else "0",
            )

    def _refresh_archive_priority_controls(self) -> None:
        if not hasattr(self, "safe_autopilot_box"):
            return
        active = archive_priority_enabled(self.conn)
        self.safe_autopilot_box.setEnabled(not active)
        if hasattr(self, "autopilot_interval_spin"):
            self.autopilot_interval_spin.setEnabled(not active)
        if hasattr(self, "autopilot_daily_spin"):
            self.autopilot_daily_spin.setEnabled(not active)
        if hasattr(self, "daily_archive_btn"):
            self.daily_archive_btn.setEnabled(active)
        if active:
            self.safe_autopilot_box.blockSignals(True)
            self.safe_autopilot_box.setChecked(False)
            self.safe_autopilot_box.blockSignals(False)

    def save_archive_priority_setting(self, _state: int) -> None:
        enabled = self.archive_priority_box.isChecked()
        set_archive_priority_mode(
            self.conn,
            enabled,
            tuple(PROFILE_TARGETS.keys()),
        )
        if enabled:
            set_setting(self.conn, "archive_campaign_autorun", "1")
        self._refresh_archive_priority_controls()

        if not enabled:
            restored = (
                get_setting(
                    self.conn,
                    f"safe_metadata_autopilot_{self.current_profile}",
                    "0",
                )
                == "1"
            )
            self.safe_autopilot_box.blockSignals(True)
            self.safe_autopilot_box.setChecked(restored)
            self.safe_autopilot_box.blockSignals(False)

        log_action(
            self.conn,
            profile=self.current_profile,
            category="квота",
            action="Пріоритет архіву",
            details=(
                "увімкнено - автопілот метаданих призупинено"
                if enabled
                else "вимкнено - попередній стан автопілота відновлено"
            ),
        )
        self.reload_action_log()
        self.update_task_center()
        self.statusBar().showMessage(
            "Пріоритет архіву увімкнено"
            if enabled
            else "Пріоритет архіву вимкнено"
        )

    def save_safe_autopilot_setting(self, _state: int) -> None:
        if archive_priority_enabled(self.conn):
            self._refresh_archive_priority_controls()
            return
        enabled = self.safe_autopilot_box.isChecked()
        set_setting(
            self.conn,
            f"safe_metadata_autopilot_{self.current_profile}",
            "1" if enabled else "0",
        )
        if enabled:
            set_setting(
                self.conn,
                f"safe_autopilot_last_run_{self.current_profile}",
                datetime.now(timezone.utc).isoformat(),
            )
        log_action(
            self.conn,
            profile=self.current_profile,
            category="автопілот",
            action="Налаштування",
            details="увімкнено" if enabled else "вимкнено",
        )
        self.reload_action_log()

    def save_safe_autopilot_limits(self, _value: int = 0) -> None:
        set_setting(
            self.conn,
            f"safe_autopilot_interval_minutes_{self.current_profile}",
            str(self.autopilot_interval_spin.value()),
        )
        set_setting(
            self.conn,
            f"safe_autopilot_daily_limit_{self.current_profile}",
            str(self.autopilot_daily_spin.value()),
        )
        log_action(
            self.conn,
            profile=self.current_profile,
            category="автопілот",
            action="Ліміти",
            details=(
                f"інтервал {self.autopilot_interval_spin.value()} хв; "
                f"денний ліміт {self.autopilot_daily_spin.value()} відео"
            ),
        )
        self.reload_action_log()

    def save_background_setting(self, _state: int) -> None:
        set_setting(
            self.conn,
            "background_scan_enabled",
            "1" if self.background_box.isChecked() else "0",
        )

    def check_for_updates_silent(self) -> None:
        try:
            info = check_for_update()
        except Exception:
            return
        if info is not None:
            self._offer_update(info)

    def check_for_updates_manual(self) -> None:
        self.statusBar().showMessage("Перевіряю оновлення...")
        QApplication.processEvents()
        try:
            info = check_for_update()
        except Exception as exc:
            self._error("Помилка перевірки оновлень", exc)
            return
        if info is None:
            self.statusBar().showMessage("Встановлено актуальну версію")
            QMessageBox.information(
                self,
                APP_NAME,
                f"Встановлено актуальну версію {__version__}.",
            )
            return
        self._offer_update(info)

    def _offer_update(self, info: UpdateInfo) -> None:
        answer = QMessageBox.question(
            self,
            "Доступне оновлення",
            f"Доступна версія {info.version}.\n"
            f"Встановлена версія {__version__}.\n\n"
            "Завантажити й установити оновлення зараз?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage(
            f"Завантажую RG YouTube Control {info.version}..."
        )
        QApplication.processEvents()
        try:
            installer = download_update(info)
        except Exception as exc:
            self._error("Помилка завантаження оновлення", exc)
            return

        self.statusBar().showMessage("Запускаю встановлення оновлення...")
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(installer)))
        if not opened:
            QMessageBox.warning(
                self,
                APP_NAME,
                f"Не вдалося запустити інсталятор автоматично.\n"
                f"Файл збережено тут:\n{installer}",
            )
            return
        QTimer.singleShot(800, QApplication.quit)

    def _error(self, title: str, exc: Exception) -> None:
        try:
            log_action(
                self.conn,
                profile=getattr(self, "current_profile", None),
                category="помилка",
                action=title,
                details=str(exc),
            )
            self.reload_action_log()
        except Exception:
            pass
        QMessageBox.critical(self, title, str(exc))
        self.statusBar().showMessage(str(exc))