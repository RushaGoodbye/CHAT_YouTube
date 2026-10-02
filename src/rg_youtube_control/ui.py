from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from statistics import median
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
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
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .config import (
    APP_NAME,
    DEFAULT_AUTO_REPLY_MAX_AGE_HOURS,
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
    get_optimization_draft,
    get_setting,
    latest_metadata_snapshot,
    save_metadata_snapshot,
    save_optimization_draft,
    set_comment_status,
    set_optimization_draft_status,
    set_setting,
    upsert_video_analytics,
)
from .metadata_audit import audit, normalize_links
from .package_bridge import bridge_health, fetch_package, upload_transcript
from .optimization import (
    archive_potential_score,
    compose_description,
    extract_chapters_from_description,
    has_safe_link_issue,
    priority_label,
    safe_description_fix,
    validate_chapters,
    validate_content_package,
)
from .service import (
    manual_reply,
    scan_comments,
    sync_specific_videos,
    sync_videos,
    today_auto_reply_count,
    today_reply_count,
    today_quota_units,
    record_quota_units,
    quota_exhausted,
    mark_quota_exhausted,
    YOUTUBE_DAILY_QUOTA_DEFAULT,
    VIDEO_UPDATE_COST,
)
from .youtube_api import YouTubeClient
from .style import APP_STYLESHEET, MUTED, SUCCESS, WARNING, YOUTUBE_RED
from .updater import UpdateInfo, check_for_update, download_update

def _is_quota_exceeded_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return "quotaexceeded" in text or "quota exceeded" in text


ISSUE_LABELS = {
    "old_links": "старі посилання",
    "missing_project_link": "немає посилання проєкту",
    "missing_donate_link": "немає посилання на донат",
    "thin_description": "закороткий опис",
    "no_chapters": "немає розділів",
    "too_many_hashtags": "забагато хештегів",
    "no_tags": "немає тегів",
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
}

def _issue_labels(issues: list[str]) -> str:
    return ", ".join(ISSUE_LABELS.get(item, item) for item in issues)


def _standard_hyphen(text: str) -> str:
    return str(text or "").replace("—", "-").replace("–", "-")


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

        if scheduled_publish_at:
            scheduled_note = QLabel(
                f"Запланований стрім · {scheduled_publish_at}\n"
                "Назву, опис і теги можна оптимізувати заздалегідь. "
                "Дата, час публікації та видимість не змінюються."
            )
            scheduled_note.setWordWrap(True)
            layout.addWidget(scheduled_note)

        if not (chapters or "").strip():
            description, detected_chapters = extract_chapters_from_description(
                description
            )
            if detected_chapters:
                chapters = detected_chapters

        form = QFormLayout()
        self.title_edit = QLineEdit(_standard_hyphen(title))
        self.description_edit = QPlainTextEdit(_standard_hyphen(description))
        self.chapters_edit = QPlainTextEdit(_standard_hyphen(chapters))
        self.chapters_edit.setPlaceholderText(
            "00:00 Вступ\n05:20 Наступний блок\n12:40 Фінальна частина"
        )
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
        form.addRow("Розділи:", self.chapters_edit)
        form.addRow("Теги:", self.tags_edit)
        form.addRow("A/B варіанти назви:", self.title_variants_edit)
        form.addRow("Статус:", self.status_combo)
        layout.addLayout(form)

        checks = QHBoxLayout()
        validate_btn = QPushButton("Перевірити розділи")
        validate_btn.clicked.connect(self.validate_chapters_now)
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
            _standard_hyphen(self.description_edit.toPlainText().strip()),
            _standard_hyphen(self.chapters_edit.toPlainText().strip()),
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
        self._build_videos_tab()
        self._build_optimization_tab()
        self._build_comments_tab()
        self._build_analytics_tab()
        self._build_settings_tab()

        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.background_scan_all_channels)
        self.scan_timer.start(DEFAULT_SCAN_MINUTES * 60 * 1000)

        self.statusBar().showMessage("СИСТЕМА ГОТОВА")
        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()
        self.update_dashboard()
        self._refresh_channel_header()
        QTimer.singleShot(3000, self.check_for_updates_silent)

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
        title = QLabel("YouTube Control")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Відео · оптимізація · коментарі")
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
        sync_btn.setProperty("role", "primary")
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
        self.update_dashboard()
        self._refresh_channel_header()
        self.statusBar().showMessage(
            f"Активний канал: {PROFILE_LABELS[self.current_profile]}"
        )

    def _build_videos_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        connect_btn = QPushButton("Підключити YouTube")
        connect_btn.clicked.connect(self.connect_youtube)
        sync_btn = QPushButton("Синхронізувати відео")
        sync_btn.clicked.connect(self.sync_video_list)
        sync_both_btn = QPushButton("Синхронізувати обидва канали")
        sync_both_btn.clicked.connect(self.sync_both_channels)
        edit_btn = QPushButton("Редагувати вибране")
        edit_btn.clicked.connect(self.edit_selected_video)
        controls.addWidget(connect_btn)
        controls.addWidget(sync_btn)
        controls.addWidget(sync_both_btn)
        controls.addWidget(edit_btn)
        controls.addStretch()

        self.video_table = QTableWidget(0, 5)
        self.video_table.setHorizontalHeaderLabels(
            ["Відео", "Назва", "Перегляди", "Аудит", "Проблеми"]
        )
        self.video_table.horizontalHeader().setStretchLastSection(True)
        self._configure_table(self.video_table)
        layout.addLayout(controls)
        layout.addWidget(self.video_table)
        self.tabs.addTab(page, "Відео")

    def _build_optimization_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        sync_row = QHBoxLayout()
        safe_row = QHBoxLayout()
        content_row = QHBoxLayout()

        sync_all_btn = QPushButton("Синхронізувати весь архів")
        sync_all_btn.clicked.connect(self.sync_full_archive)
        refresh_btn = QPushButton("Оновити чергу")
        refresh_btn.clicked.connect(self.reload_optimization_queue)
        potential_btn = QPushButton("Оновити ТОП потенціал")
        potential_btn.clicked.connect(self.refresh_archive_potential)
        preview_btn = QPushButton("Попередній перегляд безпечних правок")
        preview_btn.clicked.connect(self.preview_safe_optimization)
        apply_btn = QPushButton("Застосувати безпечні")
        apply_btn.clicked.connect(self.apply_safe_optimization)
        next_safe_btn = QPushButton("Архів: безпечні 50")
        next_safe_btn.clicked.connect(self.apply_next_safe_archive_batch)
        package_btn = QPushButton("Пакет контенту")
        package_btn.clicked.connect(self.edit_content_package)
        transcript_btn = QPushButton("Транскрипт → NAS")
        transcript_btn.clicked.connect(self.export_selected_transcript_to_nas)
        batch_transcript_btn = QPushButton("Транскрипти запланованих → NAS")
        batch_transcript_btn.clicked.connect(
            self.export_scheduled_transcripts_to_nas
        )
        nas_test_btn = QPushButton("Перевірити сховища")
        nas_test_btn.clicked.connect(self.test_nas_transcript_path)
        import_btn = QPushButton("Імпорт пакета")
        import_btn.clicked.connect(self.import_selected_package_from_nas)
        apply_package_btn = QPushButton("Застосувати пакет")
        apply_package_btn.setProperty("role", "primary")
        apply_package_btn.clicked.connect(self.apply_content_package)
        rollback_btn = QPushButton("Відкотити останнє")
        rollback_btn.clicked.connect(self.rollback_selected_metadata)

        self.optimization_filter = QComboBox()
        self.optimization_filter.addItem("Усі відео", "all")
        self.optimization_filter.addItem("Лише заплановані", "scheduled")
        self.optimization_filter.addItem("Архів", "archive")
        self.optimization_filter.addItem(
            "Архів: ТОП потенціал",
            "archive_top",
        )
        self.optimization_filter.currentIndexChanged.connect(
            self.reload_optimization_queue
        )
        fetch_scheduled_btn = QPushButton("Отримати пакети запланованих")
        fetch_scheduled_btn.clicked.connect(
            self.fetch_scheduled_packages
        )
        audit_scheduled_btn = QPushButton("Перевірити заплановані")
        audit_scheduled_btn.clicked.connect(
            self.audit_scheduled_packages
        )
        apply_scheduled_btn = QPushButton("Застосувати готові заплановані")
        apply_scheduled_btn.clicked.connect(
            self.apply_ready_scheduled_packages
        )

        sync_row.addWidget(sync_all_btn)
        sync_row.addWidget(refresh_btn)
        sync_row.addWidget(potential_btn)
        sync_row.addSpacing(12)
        sync_row.addWidget(QLabel("Фільтр:"))
        sync_row.addWidget(self.optimization_filter)
        sync_row.addWidget(fetch_scheduled_btn)
        sync_row.addWidget(audit_scheduled_btn)
        sync_row.addWidget(apply_scheduled_btn)
        sync_row.addStretch()

        safe_row.addWidget(QLabel("Безпечні правки:"))
        safe_row.addWidget(preview_btn)
        safe_row.addWidget(apply_btn)
        safe_row.addWidget(next_safe_btn)
        safe_row.addStretch()

        content_row.addWidget(QLabel("Контент:"))
        content_row.addWidget(package_btn)
        content_row.addWidget(transcript_btn)
        content_row.addWidget(batch_transcript_btn)
        content_row.addWidget(nas_test_btn)
        content_row.addWidget(import_btn)
        content_row.addWidget(apply_package_btn)
        content_row.addWidget(rollback_btn)
        content_row.addStretch()

        self.optimization_table = QTableWidget(0, 10)
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
                "Проблеми",
            ]
        )
        self.optimization_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.optimization_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.optimization_table.horizontalHeader().setStretchLastSection(True)
        self._configure_table(self.optimization_table)
        self.optimization_table.doubleClicked.connect(
            lambda _index: self.edit_content_package()
        )

        layout.addLayout(sync_row)
        layout.addLayout(safe_row)
        layout.addLayout(content_row)
        layout.addWidget(self.optimization_table)
        self.tabs.addTab(page, "Оптимізація")

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
            "vidIQ та його AI Credits для цієї вкладки не використовуються."
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
                    "почне формувати щоденні Reach-звіти. Історичні "
                    "дані приблизно за 30 днів з’являться не одразу, зазвичай протягом "
                    "кількох годин або до доби.",
                )
            else:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "CTR / покази вже підключені для цього каналу. "
                    f"Job ID: {job.get('id', '—')}",
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
                "LIVE_REDIRECT": "Live Redirect",
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
                        f"Доступний період Reach: {min(reach_dates)} — {max(reach_dates)}"
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
                    "• Reach-завдання активне, але звіти ще не готові. "
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
                    f"+{subs} subs{reach_text}"
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

        self.daily_limit_spin = QSpinBox()
        self.daily_limit_spin.setRange(1, 100)
        self.daily_limit_spin.setValue(
            int(
                get_setting(
                    self.conn,
                    "auto_reply_daily_limit",
                    str(DEFAULT_MAX_AUTO_REPLIES_PER_DAY),
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
                    "auto_reply_scan_limit",
                    str(DEFAULT_MAX_AUTO_REPLIES_PER_SCAN),
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
                    "auto_reply_max_age_hours",
                    str(DEFAULT_AUTO_REPLY_MAX_AGE_HOURS),
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
                    f"reply_template_{category}",
                    DEFAULT_REPLY_TEMPLATES[category],
                )
            )
            edit.setPlaceholderText(label)
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

        oauth_btn = QPushButton("Вибрати OAuth client JSON")
        oauth_btn.clicked.connect(self.choose_oauth_file)

        self.youtube_quota_label = QLabel()
        self.refresh_youtube_quota_label()
        self.version_label = QLabel(f"Версія: {__version__}")
        update_btn = QPushButton("Перевірити оновлення")
        update_btn.clicked.connect(self.check_for_updates_manual)

        layout.addWidget(self.profile_combo)
        layout.addWidget(self.channel_label)
        layout.addWidget(self.background_box)
        layout.addWidget(self.auto_box)
        layout.addWidget(QLabel("Денний ліміт автовідповідей"))
        layout.addWidget(self.daily_limit_spin)
        layout.addWidget(QLabel("Ліміт автовідповідей за одне сканування"))
        layout.addWidget(self.scan_limit_spin)
        layout.addWidget(QLabel("Автовідповідь лише на коментарі не старші за"))
        layout.addWidget(self.age_limit_spin)
        for label, edit in self.reply_template_edits.values():
            layout.addWidget(QLabel(label))
            layout.addWidget(edit)
        layout.addWidget(QLabel("NAS · транскрипти"))
        layout.addWidget(self.nas_transcripts_edit)
        layout.addWidget(QLabel("NAS · пакети оптимізації"))
        layout.addWidget(self.nas_packages_edit)
        layout.addWidget(oauth_btn)
        layout.addWidget(QLabel("YouTube API · квота"))
        layout.addWidget(self.youtube_quota_label)
        layout.addWidget(self.version_label)
        layout.addWidget(update_btn)
        layout.addStretch()
        self.tabs.addTab(page, "Налаштування")

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
        used = today_quota_units(self.conn)
        exhausted = quota_exhausted(self.conn)
        state = "ВИЧЕРПАНО" if exhausted else "доступна"
        self.youtube_quota_label.setText(
            f"Враховано застосунком: ≈{used}/{YOUTUBE_DAILY_QUOTA_DEFAULT} units · {state}"
        )

    def _quota_update_video(self, video_id: str, **kwargs) -> None:
        if quota_exhausted(self.conn):
            raise RuntimeError(
                "Денну квоту YouTube Data API вже вичерпано. "
                "Продовжіть після її відновлення."
            )
        try:
            self.client.update_video(video_id, **kwargs)
        except Exception as exc:
            if _is_quota_exceeded_error(exc):
                mark_quota_exhausted(self.conn)
                self.refresh_youtube_quota_label()
            raise
        record_quota_units(self.conn, VIDEO_UPDATE_COST)
        self.refresh_youtube_quota_label()

    def switch_profile(self, _index: int) -> None:
        profile = self.profile_combo.currentData()
        if not profile:
            return
        self._activate_profile(str(profile))

    def choose_oauth_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "OAuth client JSON", str(Path.home()), "JSON (*.json)"
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

    def sync_video_list(self) -> None:
        try:
            rows = sync_videos(self.client, self.conn, limit=50)
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            self.statusBar().showMessage(f"Відео синхронізовано: {len(rows)}")
        except Exception as exc:
            self._error("Помилка синхронізації", exc)

    def sync_both_channels(self) -> None:
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
        message = "Синхронізовано:\n" + ("\n".join(results) or "—")
        if errors:
            message += "\n\nНе виконано:\n" + "\n".join(errors)
        QMessageBox.information(self, APP_NAME, message)

    def edit_selected_video(self) -> None:
        row = self.video_table.currentRow()
        if row < 0:
            return
        video_id = self.video_table.item(row, 0).text()
        try:
            item = self.client.video_details([video_id])[0]
            snippet = item.get("snippet", {})
            dialog = MetadataDialog(
                snippet.get("title", ""),
                snippet.get("description", ""),
                snippet.get("tags", []),
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
                snippet.get("title", ""),
                snippet.get("description", ""),
                snippet.get("tags", []) or [],
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
            self.statusBar().showMessage("Синхронізую весь архів...")
            QApplication.processEvents()
            rows = sync_videos(self.client, self.conn, limit=1000)
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            stored = self.conn.execute(
                "SELECT COUNT(*) AS n FROM videos WHERE profile=?",
                (self.current_profile,),
            ).fetchone()["n"]
            self.statusBar().showMessage(
                f"Архів синхронізовано: {len(rows)} унікальних відео · "
                f"у базі профілю: {stored}"
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

    def reload_optimization_queue(self) -> None:
        if not hasattr(self, "optimization_table"):
            return
        import json

        profile = self.current_profile
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

        rows = self.conn.execute(
            f"""SELECT v.video_id,v.title,v.published_at,v.scheduled_publish_at,
                       v.privacy_status,v.views,v.audit_json,
                       d.status AS draft_status,
                       a.analytics_views,a.impressions,a.ctr_percent,
                       a.avd_seconds,a.subs_gained,
                       a.updated_at AS analytics_updated_at
                FROM videos v
                LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
                LEFT JOIN video_analytics_cache a
                  ON a.video_id=v.video_id AND a.profile=v.profile
                WHERE v.profile=?{extra_where}""",
            (profile,),
        ).fetchall()

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
            if queue_filter == "archive_top":
                priority_value = archive_potential_score(
                    lifetime_views=int(row["views"] or 0),
                    analytics_views=int(row["analytics_views"] or 0),
                    impressions=int(row["impressions"] or 0),
                    ctr_percent=float(row["ctr_percent"] or 0),
                    median_ctr_percent=float(channel_median_ctr),
                    issues=issues,
                )
                priority_text = f"ПОТЕНЦІАЛ {priority_value}"
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

        if queue_filter == "archive_top":
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
                _issue_labels(issues),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setData(Qt.ItemDataRole.UserRole, row["video_id"])
                if column == 0:
                    if priority_text == "ЗАПЛАНОВАНО":
                        item.setForeground(QColor(YOUTUBE_RED))
                        item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                    elif priority_text.startswith("ПОТЕНЦІАЛ "):
                        potential = int(priority_text.rsplit(" ", 1)[-1])
                        item.setForeground(
                            QColor(
                                YOUTUBE_RED
                                if potential >= 80
                                else WARNING
                                if potential >= 55
                                else SUCCESS
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
                    item.setForeground(
                        QColor(
                            SUCCESS
                            if draft_status == "ЗАСТОСОВАНО"
                            else WARNING
                            if draft_status == "ЧЕРНЕТКА"
                            else YOUTUBE_RED
                        )
                    )
                    item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                self.optimization_table.setItem(index, column, item)
        self.update_dashboard()

    def _current_video_metadata(self, video_id: str) -> tuple[str, str, list[str]]:
        item = self.client.video_details([video_id])[0]
        snippet = item.get("snippet", {})
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

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Попередній перегляд · {title}")
            dialog.resize(1050, 720)
            layout = QVBoxLayout(dialog)
            changes = ", ".join(fix.changes) if fix.changes else "змін немає"
            layout.addWidget(QLabel(f"Безпечні зміни: {changes}"))

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

        track, srt = self.client.download_best_caption_srt(video_id)
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
            f"Оцінка квоти Captions API: до ≈{estimated} units.\n\n"
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
            "Операція читання caption-track витрачає квоту API. Продовжити?",
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
        requested_status = str(payload.get("status") or "ready")
        if requested_status not in {"draft", "ready"}:
            requested_status = "ready"
        status = (
            "draft"
            if check.errors and requested_status == "ready"
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
        return status, check.errors, check.warnings

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

    def apply_content_package(self) -> None:
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
            final_description = compose_description(
                draft["description"],
                draft["chapters"],
            )
            current_title, current_description, current_tags = (
                self._current_video_metadata(video_id)
            )
            new_tags = json.loads(draft["tags_json"] or "[]")
            new_title = draft["new_title"]

            answer = QMessageBox.question(
                self,
                "Застосувати пакет оптимізації",
                f"Відео: {video_id}\n\n"
                f"Назва:\n{current_title}\n→\n{new_title}\n\n"
                f"Опис: {len(current_description)} → "
                f"{len(final_description)} символів\n"
                f"Теги: {len(current_tags)} → {len(new_tags)}\n\n"
                "Усі поля буде надіслано одним videos.update "
                "(≈50 quota units). Продовжити?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

            save_metadata_snapshot(
                self.conn,
                video_id,
                current_title,
                current_description,
                current_tags,
                "before_content_package",
            )
            self._quota_update_video(
                video_id,
                title=new_title,
                description=final_description,
                tags=new_tags,
            )
            set_optimization_draft_status(self.conn, video_id, "applied")
            sync_specific_videos(self.client, self.conn, [video_id])
            self.reload_videos()
            self.reload_optimization_queue()
            QMessageBox.information(
                self,
                APP_NAME,
                "Пакет застосовано. Перед зміною збережено точку відкату.",
            )
        except Exception as exc:
            self._error("Помилка застосування пакета", exc)

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

            description = str(row["description"] or "")
            chapters = str(row["chapters"] or "")
            tags = json.loads(row["tags_json"] or "[]")
            title_variants = json.loads(
                row["title_variants_json"] or "[]"
            )

            clean_description, detected_chapters = (
                extract_chapters_from_description(description)
            )
            if detected_chapters:
                description = clean_description
                if not chapters.strip():
                    chapters = detected_chapters
                if status == "applied":
                    status = "ready"
                    applied -= 1
                    ready += 1
                save_optimization_draft(
                    self.conn,
                    video_id,
                    str(row["new_title"] or ""),
                    description,
                    chapters,
                    tags,
                    status,
                    title_variants,
                )
                chapters_fixed += 1

            check = validate_content_package(
                str(row["new_title"] or ""),
                description,
                chapters,
                tags,
                title_variants,
            )
            errors_total += len(check.errors)
            warnings_total += len(check.warnings)
            if check.errors or check.warnings:
                summary = []
                if check.errors:
                    summary.append(f"помилок {len(check.errors)}")
                if check.warnings:
                    summary.append(f"рекомендацій {len(check.warnings)}")
                details.append(
                    f"{scheduled_at} · {video_id}: " + ", ".join(summary)
                )

        self.reload_optimization_queue()

        lines = [
            f"Запланованих стрімів: {len(rows)}",
            f"Застосовано: {applied}",
            f"Готово до застосування: {ready}",
            f"Чернеток: {draft}",
            f"Без пакета: {missing}",
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

    def apply_ready_scheduled_packages(self) -> None:
        rows = self.conn.execute(
            """SELECT v.video_id,v.scheduled_publish_at,
                      d.new_title,d.description,d.chapters,d.tags_json
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
            QMessageBox.information(
                self,
                APP_NAME,
                "Немає запланованих стрімів із пакетом «Готово до застосування».",
            )
            return

        estimated = len(rows) * 50
        answer = QMessageBox.question(
            self,
            "Оптимізація запланованих стрімів",
            f"Готових пакетів: {len(rows)}.\n"
            f"Максимальна витрата videos.update: ≈{estimated} units.\n\n"
            "Буде змінено лише назву, опис і теги. "
            "Дата й час публікації, видимість і налаштування розкладу "
            "залишаться без змін. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        import json

        changed_ids: list[str] = []
        errors: list[str] = []
        for row in rows:
            video_id = str(row["video_id"])
            try:
                current_title, current_description, current_tags = (
                    self._current_video_metadata(video_id)
                )
                final_description = compose_description(
                    row["description"] or "",
                    row["chapters"] or "",
                )
                new_tags = json.loads(row["tags_json"] or "[]")
                new_title = str(row["new_title"] or "").strip()
                if not new_title:
                    raise RuntimeError("Назва не може бути порожньою.")

                save_metadata_snapshot(
                    self.conn,
                    video_id,
                    current_title,
                    current_description,
                    current_tags,
                    "before_scheduled_package_batch",
                )
                self._quota_update_video(
                    video_id,
                    title=new_title,
                    description=final_description,
                    tags=new_tags,
                )
                set_optimization_draft_status(self.conn, video_id, "applied")
                changed_ids.append(video_id)
            except Exception as exc:
                errors.append(f"{video_id}: {exc}")

        if changed_ids:
            sync_specific_videos(self.client, self.conn, changed_ids)
        self.reload_videos()
        self.reload_optimization_queue()

        message = (
            f"Готово. Оптимізовано запланованих стрімів: {len(changed_ids)}."
        )
        if errors:
            preview = "\n".join(errors[:5])
            message += f"\nПомилок: {len(errors)}.\n\n{preview}"
        QMessageBox.information(self, APP_NAME, message)

    def _safe_archive_candidates(
        self,
        limit: int = 20,
    ) -> tuple[list[str], int]:
        rows = self.conn.execute(
            """
            SELECT video_id,audit_json,views,published_at
            FROM videos
            WHERE profile=?
              AND privacy_status='public'
              AND scheduled_publish_at IS NULL
            ORDER BY views DESC, published_at DESC, video_id
            """,
            (self.current_profile,),
        ).fetchall()

        candidates: list[str] = []
        for row in rows:
            try:
                issues = json.loads(row["audit_json"] or "{}").get("issues", [])
            except Exception:
                issues = []
            if has_safe_link_issue(issues):
                candidates.append(row["video_id"])

        return candidates[:limit], len(candidates)

    def _store_local_safe_audit(
        self, video_id: str, description: str, tags: list[str]
    ) -> None:
        result = audit(description, tags)
        payload = json.dumps(
            {"score": result.score, "issues": list(result.issues)},
            ensure_ascii=False,
        )
        self.conn.execute(
            "UPDATE videos SET audit_json=? WHERE video_id=?",
            (payload, video_id),
        )
        self.conn.commit()

    def apply_next_safe_archive_batch(self) -> None:
        batch_limit = 50
        video_ids, total_candidates = self._safe_archive_candidates(
            limit=batch_limit
        )
        if not video_ids:
            QMessageBox.information(
                self,
                APP_NAME,
                "В архіві більше немає відео з безпечними правками.",
            )
            return

        estimated = len(video_ids) * 50
        answer = QMessageBox.question(
            self,
            "Архів: безпечні 50",
            f"Знайдено відео з безпечними правками: {total_candidates}.\n"
            f"Зараз буде оброблено: {len(video_ids)}.\n"
            f"Максимальна витрата videos.update: ≈{estimated} units.\n\n"
            "Черга йде від відео з найбільшою кількістю переглядів.\n"
            "Буде змінено лише старі або відсутні посилання "
            "проєкту й донату та окремий рядок хештегів: "
            "2 постійні + до 3 тематичних. "
            "Назви, теги YouTube, розділи та решта тексту залишаться "
            "без змін. Для кожного запису зберігається точка відкату. "
            "Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        changed_ids: list[str] = []
        skipped_ids: list[str] = []
        error_text = ""
        try:
            for index, video_id in enumerate(video_ids, start=1):
                self.statusBar().showMessage(
                    f"Безпечна оптимізація архіву: "
                    f"{index}/{len(video_ids)} · {video_id}"
                )
                QApplication.processEvents()
                try:
                    title, description, tags = self._current_video_metadata(video_id)
                    fix = safe_description_fix(description, title)
                    if not fix.changes or fix.after == description:
                        skipped_ids.append(video_id)
                        continue

                    save_metadata_snapshot(
                        self.conn,
                        video_id,
                        title,
                        description,
                        tags,
                        "before_safe_archive_batch",
                    )
                    self._quota_update_video(video_id, description=fix.after)
                    self._store_local_safe_audit(video_id, fix.after, tags)
                    changed_ids.append(video_id)
                except Exception as exc:
                    if _is_quota_exceeded_error(exc):
                        mark_quota_exhausted(self.conn)
                        self.refresh_youtube_quota_label()
                        error_text = "quota_exceeded"
                    else:
                        error_text = f"{video_id}: {exc}"
                    break

            refresh_ids = changed_ids + skipped_ids
            if refresh_ids and error_text != "quota_exceeded":
                sync_specific_videos(self.client, self.conn, refresh_ids)
            self.reload_videos()
            self.reload_optimization_queue()

            remaining = max(
                0,
                total_candidates - len(changed_ids) - len(skipped_ids),
            )
            message = (
                f"Готово. Змінено: {len(changed_ids)}. "
                f"Без змін: {len(skipped_ids)}.\n"
                f"Залишилося в черзі безпечних правок: ≈{remaining}."
            )
            if error_text == "quota_exceeded":
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
                QMessageBox.information(self, APP_NAME, message)
        except Exception as exc:
            self._error("Помилка пакетної оптимізації архіву", exc)

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

        estimated = len(video_ids) * 50
        answer = QMessageBox.question(
            self,
            "Застосувати безпечні правки",
            f"Вибрано відео: {len(video_ids)}.\n"
            f"Максимальна витрата на videos.update: ≈{estimated} units.\n\n"
            "Буде змінено лише старі/відсутні посилання та окремий рядок "
            "хештегів: 2 постійні + до 3 тематичних. "
            "Назва, теги YouTube та решта тексту залишаться без змін. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        changed = 0
        skipped = 0
        changed_ids: list[str] = []
        try:
            for video_id in video_ids:
                title, description, tags = self._current_video_metadata(video_id)
                fix = safe_description_fix(description, title)
                if not fix.changes or fix.after == description:
                    skipped += 1
                    continue
                save_metadata_snapshot(
                    self.conn,
                    video_id,
                    title,
                    description,
                    tags,
                    "before_safe_optimization",
                )
                self._quota_update_video(video_id, description=fix.after)
                changed += 1
                changed_ids.append(video_id)

            if changed_ids:
                sync_specific_videos(self.client, self.conn, changed_ids)
            self.reload_videos()
            self.reload_optimization_queue()
            QMessageBox.information(
                self,
                APP_NAME,
                f"Готово. Змінено: {changed}. Без змін: {skipped}.",
            )
        except Exception as exc:
            self._error("Помилка безпечної оптимізації", exc)

    def rollback_selected_metadata(self) -> None:
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

    def background_scan_all_channels(self) -> None:
        if not hasattr(self, "background_box") or not self.background_box.isChecked():
            return

        summaries: list[str] = []
        for profile, target_id in PROFILE_TARGETS.items():
            client = YouTubeClient(profile=profile)
            try:
                client.credentials()
            except Exception:
                continue

            video_ids = [
                row["video_id"]
                for row in self.conn.execute(
                    "SELECT video_id FROM videos "
                    "WHERE profile=? AND privacy_status='public' "
                    "ORDER BY published_at DESC LIMIT 20",
                    (profile,),
                ).fetchall()
            ]
            if not video_ids:
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

            try:
                stats = scan_comments(
                    client,
                    self.conn,
                    video_ids,
                    auto_reply=auto_enabled,
                    max_auto_replies=self.daily_limit_spin.value(),
                    max_auto_replies_per_scan=self.scan_limit_spin.value(),
                    max_auto_age_hours=self.age_limit_spin.value(),
                )
                summaries.append(
                    f"{PROFILE_LABELS[profile]}: {stats['seen']} ком."
                )
            except Exception as exc:
                summaries.append(f"{PROFILE_LABELS[profile]}: помилка")

        self.reload_comments()
        self.update_dashboard()
        if summaries:
            self.statusBar().showMessage(" · ".join(summaries))

    def scan_comment_queue(self, silent: bool = False) -> None:
        if silent and not self.background_box.isChecked():
            return
        profile = self.current_profile
        video_ids = [
            row["video_id"]
            for row in self.conn.execute(
                "SELECT video_id FROM videos "
                "WHERE profile=? AND privacy_status='public' "
                "ORDER BY published_at DESC LIMIT 20",
                (profile,),
            ).fetchall()
        ]
        if not video_ids:
            if not silent:
                QMessageBox.information(self, APP_NAME, "Спочатку синхронізуйте відео.")
            return
        try:
            stats = scan_comments(
                self.client,
                self.conn,
                video_ids,
                auto_reply=self.auto_box.isChecked(),
                max_auto_replies=self.daily_limit_spin.value(),
                max_auto_replies_per_scan=self.scan_limit_spin.value(),
                max_auto_age_hours=self.age_limit_spin.value(),
            )
            self.reload_comments()
            self.statusBar().showMessage(
                "Коментарі: {seen}, черга: {queued}, автовідповіді: {auto_replied}, "
                "пропущено без коментарів: {skipped_disabled}".format(**stats)
            )
        except Exception as exc:
            if silent:
                self.statusBar().showMessage(f"Фонова перевірка: {exc}")
            else:
                self._error("Помилка коментарів", exc)

    def test_one_auto_reply(self) -> None:
        answer = QMessageBox.question(
            self,
            "Тест автовідповіді",
            "Програма надішле рівно одну безпечну автовідповідь "
            "на свіжий коментар. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        profile = self.current_profile
        video_ids = [
            row["video_id"]
            for row in self.conn.execute(
                "SELECT video_id FROM videos "
                "WHERE profile=? AND privacy_status='public' "
                "ORDER BY published_at DESC LIMIT 20",
                (profile,),
            ).fetchall()
        ]
        if not video_ids:
            QMessageBox.information(self, APP_NAME, "Спочатку синхронізуйте відео.")
            return

        try:
            stats = scan_comments(
                self.client,
                self.conn,
                video_ids,
                auto_reply=True,
                max_auto_replies=self.daily_limit_spin.value(),
                max_auto_replies_per_scan=1,
                max_auto_age_hours=self.age_limit_spin.value(),
            )
            self.reload_comments()
            if stats["auto_replied"] == 1:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Тест успішний: надіслано 1 безпечну автовідповідь.",
                )
            else:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Відповідного свіжого безпечного коментаря для тесту не знайдено.",
                )
        except Exception as exc:
            self._error("Помилка тестової автовідповіді", exc)

    def reload_videos(self) -> None:
        import json

        profile = self.current_profile
        rows = self.conn.execute(
            "SELECT video_id,title,views,audit_json FROM videos "
            "WHERE profile=? ORDER BY published_at DESC LIMIT 200",
            (profile,),
        ).fetchall()
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
                if column == 3:
                    score = int(audit_data.get("score") or 0)
                    item.setForeground(
                        QColor(SUCCESS if score >= 100 else WARNING if score >= 70 else YOUTUBE_RED)
                    )
                    item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                self.video_table.setItem(index, column, item)
        self.update_dashboard()

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
            safe_used = today_auto_reply_count(self.conn)
            total_used = today_reply_count(self.conn)
            daily_limit = (
                self.daily_limit_spin.value()
                if hasattr(self, "daily_limit_spin")
                else DEFAULT_MAX_AUTO_REPLIES_PER_DAY
            )
            self.auto_quota_label.setText(
                f"Автовідповіді: {safe_used}/{daily_limit} "
                f"· надіслано через застосунок сьогодні: {total_used} "
                f"· ≈{total_used * 50} units"
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
        set_setting(self.conn, f"reply_template_{category}", text)
        if category in self.reply_template_edits:
            self.reply_template_edits[category][1].setText(text)
        self.statusBar().showMessage("Шаблон автовідповіді збережено")

    def save_auto_limits(self, _value: int = 0) -> None:
        set_setting(
            self.conn,
            "auto_reply_daily_limit",
            str(self.daily_limit_spin.value()),
        )
        set_setting(
            self.conn,
            "auto_reply_scan_limit",
            str(self.scan_limit_spin.value()),
        )
        set_setting(
            self.conn,
            "auto_reply_max_age_hours",
            str(self.age_limit_spin.value()),
        )
        self.reload_comments()

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
        QMessageBox.critical(self, title, str(exc))
        self.statusBar().showMessage(str(exc))