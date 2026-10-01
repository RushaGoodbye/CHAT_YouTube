from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
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
    PROFILE_LABELS,
    PROFILE_TARGETS,
    app_data_dir,
    normalize_nas_unc_path,
)
from .db import (
    connect,
    get_optimization_draft,
    get_setting,
    latest_metadata_snapshot,
    save_metadata_snapshot,
    save_optimization_draft,
    set_comment_status,
    set_optimization_draft_status,
    set_setting,
)
from .metadata_audit import normalize_links
from .optimization import (
    compose_description,
    has_safe_link_issue,
    priority_label,
    safe_description_fix,
    validate_chapters,
)
from .service import (
    manual_reply,
    scan_comments,
    sync_specific_videos,
    sync_videos,
    today_auto_reply_count,
    today_reply_count,
)
from .youtube_api import YouTubeClient
from .style import APP_STYLESHEET, MUTED, SUCCESS, WARNING, YOUTUBE_RED
from .updater import UpdateInfo, check_for_update, download_update

class MetadataDialog(QDialog):
    def __init__(self, title: str, description: str, tags: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Метаданные видео")
        self.resize(780, 620)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit(title)
        self.description_edit = QPlainTextEdit(description)
        self.tags_edit = QPlainTextEdit(", ".join(tags))
        form.addRow("Название:", self.title_edit)
        form.addRow("Описание:", self.description_edit)
        form.addRow("Теги:", self.tags_edit)
        layout.addLayout(form)

        normalize_btn = QPushButton("Заменить старые ссылки")
        normalize_btn.clicked.connect(self.normalize_description_links)
        layout.addWidget(normalize_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
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
            self.title_edit.text().strip(),
            self.description_edit.toPlainText().strip(),
            tags,
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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Пакет оптимизации контента")
        self.resize(980, 760)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.title_edit = QLineEdit(title)
        self.description_edit = QPlainTextEdit(description)
        self.chapters_edit = QPlainTextEdit(chapters)
        self.chapters_edit.setPlaceholderText(
            "00:00 Вступ\n05:20 Наступний блок\n12:40 Фінальна частина"
        )
        self.tags_edit = QPlainTextEdit(", ".join(tags))
        self.title_variants_edit = QPlainTextEdit(
            "\n".join(title_variants or [])
        )
        self.title_variants_edit.setPlaceholderText(
            "Вариант A — сильный конфликт / цитата\n"
            "Вариант B — конфликт + контекст\n"
            "Вариант C — сильный хук | ЧАТ РУЛЕТКА"
        )
        self.status_combo = QComboBox()
        self.status_combo.addItem("Черновик", "draft")
        self.status_combo.addItem("Готово к применению", "ready")
        idx = self.status_combo.findData(status)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)

        form.addRow("Новое название:", self.title_edit)
        form.addRow("Полное описание:", self.description_edit)
        form.addRow("Главы:", self.chapters_edit)
        form.addRow("Теги:", self.tags_edit)
        form.addRow("A/B варианты названия:", self.title_variants_edit)
        form.addRow("Статус:", self.status_combo)
        layout.addLayout(form)

        validate_btn = QPushButton("Проверить главы")
        validate_btn.clicked.connect(self.validate_chapters_now)
        layout.addWidget(validate_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate_chapters_now(self) -> None:
        ok, message = validate_chapters(self.chapters_edit.toPlainText())
        if ok:
            QMessageBox.information(self, APP_NAME, "Главы корректны.")
        else:
            QMessageBox.warning(self, APP_NAME, message)

    def _accept_checked(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, "Название не может быть пустым.")
            return
        ok, message = validate_chapters(self.chapters_edit.toPlainText())
        if not ok:
            QMessageBox.warning(self, APP_NAME, message)
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
            self.title_edit.text().strip(),
            self.description_edit.toPlainText().strip(),
            self.chapters_edit.toPlainText().strip(),
            tags,
            str(self.status_combo.currentData()),
            title_variants,
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

        self.statusBar().showMessage("SYSTEM READY")
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
        subtitle = QLabel("Видео · оптимизация · комментарии")
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

        sync_btn = QPushButton("Синхронизировать")
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

        self.metric_videos = MetricCard("Видео в базе")
        self.metric_scheduled = MetricCard("Запланировано")
        self.metric_attention = MetricCard("Требует внимания")
        self.metric_comments = MetricCard("Комментарии в очереди")

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
            self.header_channel_state.setText("○ не подключён")
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
        self.metric_scheduled.set_value(str(scheduled), "будущие публикации")
        self.metric_attention.set_value(str(attention), "Audit < 100")
        self.metric_comments.set_value(str(queued), "новые / не обработаны")

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
                else "YouTube: не подключен"
            )

        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()
        self.update_dashboard()
        self._refresh_channel_header()
        self.statusBar().showMessage(
            f"Активный канал: {PROFILE_LABELS[self.current_profile]}"
        )

    def _build_videos_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        connect_btn = QPushButton("Подключить YouTube")
        connect_btn.clicked.connect(self.connect_youtube)
        sync_btn = QPushButton("Синхронизировать видео")
        sync_btn.clicked.connect(self.sync_video_list)
        sync_both_btn = QPushButton("Синхронизировать оба канала")
        sync_both_btn.clicked.connect(self.sync_both_channels)
        edit_btn = QPushButton("Редактировать выбранное")
        edit_btn.clicked.connect(self.edit_selected_video)
        controls.addWidget(connect_btn)
        controls.addWidget(sync_btn)
        controls.addWidget(sync_both_btn)
        controls.addWidget(edit_btn)
        controls.addStretch()

        self.video_table = QTableWidget(0, 5)
        self.video_table.setHorizontalHeaderLabels(
            ["Видео", "Название", "Просмотры", "Audit", "Проблемы"]
        )
        self.video_table.horizontalHeader().setStretchLastSection(True)
        self._configure_table(self.video_table)
        layout.addLayout(controls)
        layout.addWidget(self.video_table)
        self.tabs.addTab(page, "Видео")

    def _build_optimization_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        sync_all_btn = QPushButton("Синхронизировать весь архив")
        sync_all_btn.clicked.connect(self.sync_full_archive)
        refresh_btn = QPushButton("Обновить очередь")
        refresh_btn.clicked.connect(self.reload_optimization_queue)
        preview_btn = QPushButton("Предпросмотр безопасных правок")
        preview_btn.clicked.connect(self.preview_safe_optimization)
        apply_btn = QPushButton("Применить безопасные")
        apply_btn.clicked.connect(self.apply_safe_optimization)
        next_safe_btn = QPushButton("Архив: следующие 20")
        next_safe_btn.clicked.connect(self.apply_next_safe_archive_batch)
        package_btn = QPushButton("Пакет контента")
        package_btn.clicked.connect(self.edit_content_package)
        transcript_btn = QPushButton("Транскрипт → NAS")
        transcript_btn.clicked.connect(self.export_selected_transcript_to_nas)
        batch_transcript_btn = QPushButton("Транскрипты запланированных → NAS")
        batch_transcript_btn.clicked.connect(
            self.export_scheduled_transcripts_to_nas
        )
        nas_test_btn = QPushButton("Проверить NAS")
        nas_test_btn.clicked.connect(self.test_nas_transcript_path)
        import_btn = QPushButton("Импорт пакета NAS")
        import_btn.clicked.connect(self.import_selected_package_from_nas)
        apply_package_btn = QPushButton("Применить пакет")
        apply_package_btn.setProperty("role", "primary")
        apply_package_btn.clicked.connect(self.apply_content_package)
        rollback_btn = QPushButton("Откатить последнее")
        rollback_btn.clicked.connect(self.rollback_selected_metadata)

        controls.addWidget(sync_all_btn)
        controls.addWidget(refresh_btn)
        controls.addWidget(preview_btn)
        controls.addWidget(apply_btn)
        controls.addWidget(next_safe_btn)
        controls.addWidget(package_btn)
        controls.addWidget(transcript_btn)
        controls.addWidget(batch_transcript_btn)
        controls.addWidget(nas_test_btn)
        controls.addWidget(import_btn)
        controls.addWidget(apply_package_btn)
        controls.addWidget(rollback_btn)
        controls.addStretch()

        self.optimization_table = QTableWidget(0, 10)
        self.optimization_table.setHorizontalHeaderLabels(
            [
                "Приоритет",
                "Публикация",
                "Статус",
                "Видео",
                "Название",
                "Просмотры",
                "Audit",
                "Транскрипт",
                "Пакет",
                "Проблемы",
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

        layout.addLayout(controls)
        layout.addWidget(self.optimization_table)
        self.tabs.addTab(page, "Оптимизация")

    def _build_comments_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        scan_btn = QPushButton("Проверить комментарии")
        scan_btn.clicked.connect(lambda: self.scan_comment_queue(silent=False))
        test_auto_btn = QPushButton("Тест: 1 автоответ")
        test_auto_btn.clicked.connect(self.test_one_auto_reply)
        reply_btn = QPushButton("Ответить на выбранный")
        reply_btn.clicked.connect(self.reply_selected)
        ignore_btn = QPushButton("Игнорировать")
        ignore_btn.clicked.connect(lambda: self.set_selected_comment_status("ignored"))
        queue_btn = QPushButton("Вернуть в очередь")
        queue_btn.clicked.connect(lambda: self.set_selected_comment_status("new"))

        self.comment_status_filter = QComboBox()
        self.comment_status_filter.addItem("Все статусы", "")
        self.comment_status_filter.addItem("Новые", "new")
        self.comment_status_filter.addItem("Отвеченные", "replied")
        self.comment_status_filter.addItem("Игнорированные", "ignored")
        self.comment_status_filter.currentIndexChanged.connect(self.reload_comments)

        self.comment_category_filter = QComboBox()
        self.comment_category_filter.addItem("Все категории", "")
        self.comment_category_filter.addItem("На проверке", "review")
        self.comment_category_filter.addItem("Благодарности", "thanks")
        self.comment_category_filter.addItem("Ссылки", "links")
        self.comment_category_filter.addItem("Донаты", "donate")
        self.comment_category_filter.addItem("Расписание", "schedule")
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
            ["Дата", "Видео", "Автор", "Комментарий", "Категория", "Статус", "Черновик"]
        )
        self.comment_table.horizontalHeader().setStretchLastSection(True)
        self._configure_table(self.comment_table)
        layout.addLayout(controls)
        layout.addWidget(self.comment_table)
        self.tabs.addTab(page, "Комментарии")

    def _build_analytics_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        self.analytics_period_combo = QComboBox()
        self.analytics_period_combo.addItem("28 дней", 28)
        self.analytics_period_combo.addItem("90 дней", 90)
        self.analytics_period_combo.addItem("180 дней", 180)
        self.analytics_period_combo.setCurrentIndex(1)

        refresh_btn = QPushButton("Обновить аналитику")
        refresh_btn.setProperty("role", "primary")
        refresh_btn.clicked.connect(self.load_channel_analytics)

        reauth_btn = QPushButton("Переподключить YouTube")
        reauth_btn.clicked.connect(self.connect_youtube)

        reach_btn = QPushButton("Включить CTR / показы")
        reach_btn.clicked.connect(self.setup_reach_reporting)

        controls.addWidget(QLabel("Период:"))
        controls.addWidget(self.analytics_period_combo)
        controls.addWidget(refresh_btn)
        controls.addWidget(reach_btn)
        controls.addWidget(reauth_btn)
        controls.addStretch()

        hint = QLabel(
            "Данные берутся напрямую из YouTube Analytics API. "
            "vidIQ и его AI Credits для этой вкладки не используются."
        )
        hint.setWordWrap(True)

        self.analytics_text = QPlainTextEdit()
        self.analytics_text.setReadOnly(True)
        self.analytics_text.setPlaceholderText(
            "Нажмите «Обновить аналитику». "
            "После установки версии с аналитикой потребуется один раз "
            "переподключить каждый YouTube-канал, чтобы разрешить чтение Analytics."
        )

        layout.addLayout(controls)
        layout.addWidget(hint)
        layout.addWidget(self.analytics_text, 1)
        self.tabs.addTab(page, "Аналитика")

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
                    "Задание CTR / показов создано. YouTube Reporting API "
                    "начнёт формировать ежедневные Reach-отчёты. Исторические "
                    "данные примерно за 30 дней появятся не сразу, обычно в "
                    "течение нескольких часов или до суток.",
                )
            else:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "CTR / показы уже подключены для этого канала. "
                    f"Job ID: {job.get('id', '—')}",
                )
        except Exception as exc:
            message = str(exc)
            if "accessNotConfigured" in message or "SERVICE_DISABLED" in message:
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    "YouTube Reporting API пока не включён в Google Cloud. "
                    "Включите его для проекта RG YouTube Control и повторите.",
                )
                return
            self._error("Ошибка подключения CTR / показов", exc)

    def load_channel_analytics(self) -> None:
        days = int(self.analytics_period_combo.currentData() or 90)
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=max(days - 1, 0))
        start_s = start.isoformat()
        end_s = end.isoformat()

        try:
            self.statusBar().showMessage("Загрузка YouTube Analytics…")
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
                max_results=25,
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
                "ANNOTATION": "Аннотации / карточки",
                "END_SCREEN": "Конечные заставки",
                "EXT_URL": "Внешние сайты / Google",
                "HASHTAGS": "Хештеги",
                "LIVE_REDIRECT": "Live Redirect",
                "NO_LINK_EMBEDDED": "Встроенные плееры",
                "NO_LINK_OTHER": "Прямые / неизвестные",
                "NOTIFICATION": "Уведомления",
                "PLAYLIST": "Плейлисты",
                "RELATED_VIDEO": "Рекомендованные видео",
                "SHORTS": "Лента Shorts",
                "SOUND_PAGE": "Страницы звука",
                "SUBSCRIBER": "Главная / подписки",
                "YT_CHANNEL": "Страницы каналов",
                "YT_OTHER_PAGE": "Другие страницы YouTube",
                "YT_SEARCH": "Поиск YouTube",
                "VIDEO_REMIXES": "Ремиксы",
            }

            lines: list[str] = []
            lines.append(
                f"{PROFILE_LABELS[self.current_profile]} · "
                f"{start_s} — {end_s} · {days} дней"
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
                    f"Просмотры: {views:,} · Вовлечённые просмотры: {engaged:,} · "
                    f"Часы просмотра: {minutes / 60:,.1f} · "
                    f"Подписчики: +{subs:,}"
                )
                lines.append("")

            lines.append("ИСТОЧНИКИ ТРАФИКА")
            traffic_rows = self._analytics_result_rows(traffic)
            traffic_total = sum(float(r[1] or 0) for r in traffic_rows) or 1.0
            for row in traffic_rows[:15]:
                source = traffic_names.get(str(row[0]), str(row[0]))
                views = float(row[1] or 0)
                pct = views / traffic_total * 100
                hours = float(row[2] or 0) / 60
                lines.append(
                    f"• {source}: {int(views):,} просмотров "
                    f"({pct:.1f}%), {hours:,.1f} ч"
                )
            lines.append("")

            lines.append("ПОИСКОВЫЕ ЗАПРОСЫ YOUTUBE")
            search_rows = self._analytics_result_rows(search)
            if not search_rows:
                lines.append("• Нет данных за выбранный период")
            else:
                for row in search_rows:
                    term = str(row[0] or "—")
                    views = int(row[1] or 0)
                    hours = float(row[2] or 0) / 60
                    lines.append(f"• {term}: {views:,} просмотров, {hours:,.1f} ч")
            lines.append("")

            lines.append("ГЕОГРАФИЯ")
            for row in self._analytics_result_rows(geography)[:15]:
                country = str(row[0] or "—")
                views = int(row[1] or 0)
                hours = float(row[2] or 0) / 60
                lines.append(f"• {country}: {views:,} просмотров, {hours:,.1f} ч")
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

            title_by_id = {
                row["video_id"]: row["title"]
                for row in self.conn.execute(
                    "SELECT video_id,title FROM videos WHERE profile=?",
                    (self.current_profile,),
                ).fetchall()
            }

            lines.append("ПОКАЗЫ И CTR")
            if reach_by_video:
                if reach_dates:
                    lines.append(
                        f"Доступный период Reach: {min(reach_dates)} — {max(reach_dates)}"
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
                        f"  {impressions:,} показов · CTR {ctr:.2f}%"
                    )
            elif reach_job is None and not reach_error:
                lines.append(
                    "• CTR/показы ещё не подключены. "
                    "Нажмите «Включить CTR / показы»."
                )
            elif reach_job is not None:
                lines.append(
                    "• Reach-задание активно, но отчёты ещё не готовы. "
                    "YouTube формирует их отдельно."
                )
            elif reach_error:
                if "accessNotConfigured" in reach_error:
                    lines.append(
                        "• YouTube Reporting API не включён в Google Cloud."
                    )
                else:
                    lines.append("• CTR/показы временно недоступны.")
            lines.append("")

            lines.append("ТОП ВИДЕО")
            for row in self._analytics_result_rows(top_videos):
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
                    reach_text = f" · {impressions:,} показов · CTR {ctr:.2f}%"
                lines.append(
                    f"• {title}\n"
                    f"  {views:,} views · {engaged:,} engaged · "
                    f"{hours:,.1f} ч · AVD {avd // 60}:{avd % 60:02d} · "
                    f"+{subs} subs{reach_text}"
                )

            self.analytics_text.setPlainText("\n".join(lines))
            self.statusBar().showMessage("YouTube Analytics обновлена")
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
                    "Для YouTube Analytics нужна новая авторизация. "
                    "Нажмите «Переподключить YouTube» на этой вкладке и "
                    "разрешите доступ, затем повторите загрузку.",
                )
                return
            self._error("Ошибка YouTube Analytics", exc)

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
            self.channel_label = QLabel("YouTube: не подключен")

        self.background_box = QCheckBox(
            f"Фоновая проверка комментариев каждые {DEFAULT_SCAN_MINUTES} минут"
        )
        self.background_box.setChecked(
            get_setting(self.conn, "background_scan_enabled", "1") == "1"
        )
        self.background_box.stateChanged.connect(self.save_background_setting)

        self.auto_box = QCheckBox(
            "Автоответы только на безопасные служебные комментарии"
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
            "thanks": "Ответ на благодарность",
            "links": "Ответ со ссылками",
            "donate": "Ответ про донат",
            "schedule": "Ответ про расписание",
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

        oauth_btn = QPushButton("Выбрать OAuth client JSON")
        oauth_btn.clicked.connect(self.choose_oauth_file)

        self.version_label = QLabel(f"Версия: {__version__}")
        update_btn = QPushButton("Проверить обновления")
        update_btn.clicked.connect(self.check_for_updates_manual)

        layout.addWidget(self.profile_combo)
        layout.addWidget(self.channel_label)
        layout.addWidget(self.background_box)
        layout.addWidget(self.auto_box)
        layout.addWidget(QLabel("Дневной лимит автоответов"))
        layout.addWidget(self.daily_limit_spin)
        layout.addWidget(QLabel("Лимит автоответов за один скан"))
        layout.addWidget(self.scan_limit_spin)
        layout.addWidget(QLabel("Автоответ только на комментарии не старше"))
        layout.addWidget(self.age_limit_spin)
        for label, edit in self.reply_template_edits.values():
            layout.addWidget(QLabel(label))
            layout.addWidget(edit)
        layout.addWidget(QLabel("NAS · транскрипты"))
        layout.addWidget(self.nas_transcripts_edit)
        layout.addWidget(QLabel("NAS · пакеты оптимизации"))
        layout.addWidget(self.nas_packages_edit)
        layout.addWidget(oauth_btn)
        layout.addWidget(self.version_label)
        layout.addWidget(update_btn)
        layout.addStretch()
        self.tabs.addTab(page, "Настройки")

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
            self.statusBar().showMessage("OAuth JSON выбран")

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
                    "Авторизован другой канал. Выберите нужный канал YouTube "
                    f"для профиля {PROFILE_LABELS[self.current_profile]}.",
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
            self.statusBar().showMessage("YouTube подключен")
        except Exception as exc:
            self._error("Ошибка авторизации", exc)

    def sync_video_list(self) -> None:
        try:
            rows = sync_videos(self.client, self.conn, limit=50)
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            self.statusBar().showMessage(f"Видео синхронизированы: {len(rows)}")
        except Exception as exc:
            self._error("Ошибка синхронизации", exc)

    def sync_both_channels(self) -> None:
        answer = QMessageBox.question(
            self,
            "Синхронизация двух каналов",
            "Синхронизировать архивы РАША ГУДБАЙ и РАША ГУДБАЙ LIVE? "
            "Это только чтение метаданных.",
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
                errors.append(f"{PROFILE_LABELS[profile]}: не подключён")
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
        message = "Синхронизировано:\n" + ("\n".join(results) or "—")
        if errors:
            message += "\n\nНе выполнено:\n" + "\n".join(errors)
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
                QMessageBox.warning(self, APP_NAME, "Название не может быть пустым.")
                return
            save_metadata_snapshot(
                self.conn,
                video_id,
                snippet.get("title", ""),
                snippet.get("description", ""),
                snippet.get("tags", []) or [],
                "before_manual_edit",
            )
            self.client.update_video(
                video_id, title=title, description=description, tags=tags
            )
            self.sync_video_list()
            self.statusBar().showMessage("Метаданные видео обновлены")
        except Exception as exc:
            self._error("Ошибка обновления видео", exc)

    def sync_full_archive(self) -> None:
        answer = QMessageBox.question(
            self,
            "Полная синхронизация архива",
            "Синхронизировать весь архив канала? Это только чтение метаданных "
            "и не изменит видео.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.statusBar().showMessage("Синхронизирую весь архив...")
            QApplication.processEvents()
            rows = sync_videos(self.client, self.conn, limit=1000)
            self.reload_videos()
            self.reload_optimization_queue()
            self.update_dashboard()
            self.statusBar().showMessage(
                f"Архив синхронизирован: {len(rows)} видео"
            )
        except Exception as exc:
            self._error("Ошибка полной синхронизации", exc)

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
        rows = self.conn.execute(
            """SELECT v.video_id,v.title,v.published_at,v.scheduled_publish_at,
                      v.privacy_status,v.views,v.audit_json,
                      d.status AS draft_status
               FROM videos v
               LEFT JOIN optimization_drafts d ON d.video_id=v.video_id
               WHERE v.profile=?""",
            (profile,),
        ).fetchall()

        prepared = []
        for row in rows:
            audit_data = json.loads(row["audit_json"] or "{}")
            score = int(audit_data.get("score") or 0)
            issues = list(audit_data.get("issues", []))
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
                "draft": "ЧЕРНОВИК",
                "ready": "ГОТОВО",
                "applied": "ПРИМЕНЕНО",
            }.get(row["draft_status"] or "", "")
            values = [
                priority_text,
                publish_text,
                row["privacy_status"] or "",
                row["video_id"],
                row["title"],
                str(row["views"] or 0),
                str(score),
                transcript_status,
                draft_status,
                ", ".join(issues),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setData(Qt.ItemDataRole.UserRole, row["video_id"])
                if column == 0:
                    if priority_text == "ЗАПЛАНОВАНО":
                        item.setForeground(QColor(YOUTUBE_RED))
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
                    item.setForeground(
                        QColor(
                            SUCCESS
                            if draft_status == "ПРИМЕНЕНО"
                            else WARNING
                            if draft_status == "ЧЕРНОВИК"
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
                self, APP_NAME, "Выберите одно видео в очереди оптимизации."
            )
            return
        video_id = video_ids[0]
        try:
            title, description, _tags = self._current_video_metadata(video_id)
            fix = safe_description_fix(description)

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Предпросмотр · {title}")
            dialog.resize(1050, 720)
            layout = QVBoxLayout(dialog)
            changes = ", ".join(fix.changes) if fix.changes else "изменений нет"
            layout.addWidget(QLabel(f"Безопасные изменения: {changes}"))

            columns = QHBoxLayout()
            before = QPlainTextEdit(fix.before)
            before.setReadOnly(True)
            after = QPlainTextEdit(fix.after)
            after.setReadOnly(True)
            left = QVBoxLayout()
            left.addWidget(QLabel("ДО"))
            left.addWidget(before)
            right = QVBoxLayout()
            right.addWidget(QLabel("ПОСЛЕ"))
            right.addWidget(after)
            columns.addLayout(left)
            columns.addLayout(right)
            layout.addLayout(columns)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject)
            buttons.accepted.connect(dialog.accept)
            buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
                dialog.accept
            )
            layout.addWidget(buttons)
            dialog.exec()
        except Exception as exc:
            self._error("Ошибка предпросмотра", exc)

    def test_nas_transcript_path(self) -> None:
        target_dir = self._nas_path(
            "nas_transcripts_path",
            DEFAULT_NAS_TRANSCRIPTS_PATH,
        )
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
                raise RuntimeError("Контрольное чтение не совпало с записью.")
            probe.unlink(missing_ok=True)
            QMessageBox.information(
                self,
                APP_NAME,
                f"NAS доступен на запись и чтение:\n{target_dir}",
            )
            self.statusBar().showMessage("NAS: запись и чтение OK")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка доступа к NAS",
                f"Путь:\n{target_dir}\n\n{exc}",
            )
            self.statusBar().showMessage("NAS: ошибка записи/чтения")

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

        if srt_path.exists() and srt_path.stat().st_size > 0:
            return srt_path, False

        track, srt = self.client.download_best_caption_srt(video_id)
        snippet = track.get("snippet", {})
        srt_path.write_text(srt, encoding="utf-8")

        row = self.conn.execute(
            "SELECT title FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
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
                "На активном канале нет запланированных видео.",
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

        if not pending:
            QMessageBox.information(
                self,
                APP_NAME,
                f"Все {len(rows)} запланированных транскриптов уже есть на NAS.",
            )
            self.reload_optimization_queue()
            return

        if len(pending) > 20:
            QMessageBox.warning(
                self,
                APP_NAME,
                "За один пакет можно получить не более 20 транскриптов.",
            )
            return

        estimated = len(pending) * 250
        answer = QMessageBox.question(
            self,
            "Транскрипты запланированных видео",
            f"Найдено запланированных: {len(rows)}.\n"
            f"Уже на NAS: {already}.\n"
            f"Нужно получить: {len(pending)}.\n"
            f"Оценка квоты Captions API: до ≈{estimated} units.\n\n"
            "Получить транскрипты сейчас?",
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
                f"Транскрипты: {index}/{len(pending)} · {video_id}"
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
            f"Готово. Сохранено новых транскриптов: {saved}.\n"
            f"Уже существовало: {skipped}."
        )
        if errors:
            preview = "\n".join(errors[:8])
            message += f"\n\nНе удалось получить: {len(errors)}\n{preview}"
            if len(errors) > 8:
                message += "\n…"
        if report_write_error:
            message += (
                "\n\nОтчёт на NAS записать не удалось:\n"
                + report_write_error
            )
        else:
            message += f"\n\nДиагностический отчёт:\n{report_path}"
        QMessageBox.information(self, APP_NAME, message)
        self.statusBar().showMessage("Пакет транскриптов обработан")

    def export_selected_transcript_to_nas(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для транскрипта выберите ровно одно видео."
            )
            return

        video_id = video_ids[0]
        answer = QMessageBox.question(
            self,
            "Получить транскрипт",
            "Будет использован официальный YouTube Captions API. "
            "Операция чтения caption-track расходует квоту API. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            srt_path, downloaded = self._export_transcript_video_to_nas(video_id)
            action = "сохранён" if downloaded else "уже был на NAS"
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
            self._error("Ошибка получения транскрипта", exc)

    def import_selected_package_from_nas(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для импорта выберите ровно одно видео."
            )
            return

        video_id = video_ids[0]
        try:
            package_dir = self._nas_path(
                "nas_packages_path",
                DEFAULT_NAS_PACKAGES_PATH,
            )
            package_path = package_dir / f"{video_id}.json"
            if not package_path.exists():
                QMessageBox.information(
                    self,
                    APP_NAME,
                    f"Пакет пока не найден:\n{package_path}",
                )
                return

            payload = json.loads(package_path.read_text(encoding="utf-8"))
            package_video_id = str(payload.get("video_id") or video_id)
            if package_video_id != video_id:
                raise RuntimeError(
                    "video_id в пакете не совпадает с выбранным видео."
                )

            title = str(
                payload.get("new_title")
                or payload.get("title")
                or ""
            ).strip()
            description = str(payload.get("description") or "").strip()
            chapters = str(payload.get("chapters") or "").strip()
            tags_value = payload.get("tags") or []
            title_variants_value = payload.get("title_variants") or []
            if isinstance(title_variants_value, str):
                title_variants = [
                    item.strip()
                    for item in title_variants_value.splitlines()
                    if item.strip()
                ][:3]
            else:
                title_variants = [
                    str(item).strip()
                    for item in title_variants_value
                    if str(item).strip()
                ][:3]
            if isinstance(tags_value, str):
                tags = [
                    item.strip()
                    for item in tags_value.replace("\n", ",").split(",")
                    if item.strip()
                ]
            else:
                tags = [str(item).strip() for item in tags_value if str(item).strip()]

            if not title:
                raise RuntimeError("В пакете отсутствует название.")
            ok, message = validate_chapters(chapters)
            if not ok:
                raise RuntimeError(message)

            status = str(payload.get("status") or "ready")
            if status not in {"draft", "ready"}:
                status = "ready"

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
            self.reload_optimization_queue()
            QMessageBox.information(
                self,
                APP_NAME,
                f"Пакет импортирован: {package_path.name}",
            )
        except Exception as exc:
            self._error("Ошибка импорта пакета", exc)

    def edit_content_package(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для пакета контента выберите ровно одно видео."
            )
            return

        video_id = video_ids[0]
        try:
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
            self.statusBar().showMessage("Пакет оптимизации сохранён")
        except Exception as exc:
            self._error("Ошибка пакета оптимизации", exc)

    def apply_content_package(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для применения выберите ровно одно видео."
            )
            return

        video_id = video_ids[0]
        draft = get_optimization_draft(self.conn, video_id)
        if draft is None:
            QMessageBox.information(
                self, APP_NAME, "Для этого видео ещё нет пакета оптимизации."
            )
            return
        if draft["status"] != "ready":
            QMessageBox.warning(
                self,
                APP_NAME,
                "Пакет должен иметь статус «Готово к применению».",
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
                "Применить пакет оптимизации",
                f"Видео: {video_id}\n\n"
                f"Название:\n{current_title}\n→\n{new_title}\n\n"
                f"Описание: {len(current_description)} → "
                f"{len(final_description)} символов\n"
                f"Теги: {len(current_tags)} → {len(new_tags)}\n\n"
                "Все поля будут отправлены одним videos.update "
                "(≈50 quota units). Продолжить?",
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
            self.client.update_video(
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
                "Пакет применён. Перед изменением сохранена точка отката.",
            )
        except Exception as exc:
            self._error("Ошибка применения пакета", exc)

    def _safe_archive_candidates(
        self,
        limit: int = 20,
    ) -> tuple[list[str], int]:
        rows = self.conn.execute(
            """
            SELECT video_id,audit_json
            FROM videos
            WHERE profile=?
              AND privacy_status='public'
              AND scheduled_publish_at IS NULL
            ORDER BY published_at DESC, video_id
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

    def apply_next_safe_archive_batch(self) -> None:
        video_ids, total_candidates = self._safe_archive_candidates(limit=20)
        if not video_ids:
            QMessageBox.information(
                self,
                APP_NAME,
                "В архиве больше нет видео с безопасными правками ссылок.",
            )
            return

        estimated = len(video_ids) * 50
        answer = QMessageBox.question(
            self,
            "Архив: следующие 20",
            f"Найдено видео с безопасными правками: {total_candidates}.\n"
            f"Сейчас будет обработано: {len(video_ids)}.\n"
            f"Максимальный расход videos.update: ≈{estimated} units.\n\n"
            "Будут изменены только старые или отсутствующие ссылки "
            "проекта и доната. Названия, теги, главы и остальной текст "
            "останутся без изменений. Для каждой записи сохраняется "
            "точка отката. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        changed_ids: list[str] = []
        skipped_ids: list[str] = []
        error_text = ""
        try:
            for video_id in video_ids:
                try:
                    title, description, tags = self._current_video_metadata(video_id)
                    fix = safe_description_fix(description)
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
                    self.client.update_video(video_id, description=fix.after)
                    changed_ids.append(video_id)
                except Exception as exc:
                    error_text = f"{video_id}: {exc}"
                    break

            refresh_ids = changed_ids + skipped_ids
            if refresh_ids:
                sync_specific_videos(self.client, self.conn, refresh_ids)
            self.reload_videos()
            self.reload_optimization_queue()

            remaining = max(
                0,
                total_candidates - len(changed_ids) - len(skipped_ids),
            )
            message = (
                f"Готово. Изменено: {len(changed_ids)}. "
                f"Без изменений: {len(skipped_ids)}.\n"
                f"Осталось в очереди безопасных правок: ≈{remaining}."
            )
            if error_text:
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    message + f"\n\nОбработка остановлена на ошибке:\n{error_text}",
                )
            else:
                QMessageBox.information(self, APP_NAME, message)
        except Exception as exc:
            self._error("Ошибка пакетной оптимизации архива", exc)

    def apply_safe_optimization(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if not video_ids:
            QMessageBox.information(
                self, APP_NAME, "Выберите видео для безопасной оптимизации."
            )
            return
        if len(video_ids) > 20:
            QMessageBox.warning(
                self,
                APP_NAME,
                "За один пакет можно обработать не более 20 видео.",
            )
            return

        estimated = len(video_ids) * 50
        answer = QMessageBox.question(
            self,
            "Применить безопасные правки",
            f"Выбрано видео: {len(video_ids)}.\n"
            f"Максимальный расход на videos.update: ≈{estimated} units.\n\n"
            "Будут изменены только старые/отсутствующие ссылки в описании. "
            "Название, теги и остальной текст останутся без изменений. Продолжить?",
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
                fix = safe_description_fix(description)
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
                self.client.update_video(video_id, description=fix.after)
                changed += 1
                changed_ids.append(video_id)

            if changed_ids:
                sync_specific_videos(self.client, self.conn, changed_ids)
            self.reload_videos()
            self.reload_optimization_queue()
            QMessageBox.information(
                self,
                APP_NAME,
                f"Готово. Изменено: {changed}. Без изменений: {skipped}.",
            )
        except Exception as exc:
            self._error("Ошибка безопасной оптимизации", exc)

    def rollback_selected_metadata(self) -> None:
        video_ids = self._selected_optimization_video_ids()
        if len(video_ids) != 1:
            QMessageBox.information(
                self, APP_NAME, "Для отката выберите ровно одно видео."
            )
            return
        video_id = video_ids[0]
        snapshot = latest_metadata_snapshot(self.conn, video_id)
        if snapshot is None:
            QMessageBox.information(
                self, APP_NAME, "Для этого видео ещё нет сохранённой версии."
            )
            return

        import json
        answer = QMessageBox.question(
            self,
            "Откат метаданных",
            f"Вернуть метаданные из сохранения {snapshot['created_at']}?\n"
            f"Причина сохранения: {snapshot['reason']}",
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
            self.client.update_video(
                video_id,
                title=snapshot["title"],
                description=snapshot["description"],
                tags=json.loads(snapshot["tags_json"] or "[]"),
            )
            sync_specific_videos(self.client, self.conn, [video_id])
            self.reload_videos()
            self.reload_optimization_queue()
            self.statusBar().showMessage("Метаданные видео восстановлены")
        except Exception as exc:
            self._error("Ошибка отката метаданных", exc)

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
                    f"{PROFILE_LABELS[profile]}: {stats['seen']} комм."
                )
            except Exception as exc:
                summaries.append(f"{PROFILE_LABELS[profile]}: ошибка")

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
                QMessageBox.information(self, APP_NAME, "Сначала синхронизируйте видео.")
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
                "Комментарии: {seen}, очередь: {queued}, автоответы: {auto_replied}, "
                "пропущено без комментариев: {skipped_disabled}".format(**stats)
            )
        except Exception as exc:
            if silent:
                self.statusBar().showMessage(f"Фоновая проверка: {exc}")
            else:
                self._error("Ошибка комментариев", exc)

    def test_one_auto_reply(self) -> None:
        answer = QMessageBox.question(
            self,
            "Тест автоответа",
            "Программа отправит ровно один безопасный автоответ "
            "на свежий комментарий. Продолжить?",
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
            QMessageBox.information(self, APP_NAME, "Сначала синхронизируйте видео.")
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
                    "Тест успешен: отправлен 1 безопасный автоответ.",
                )
            else:
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "Подходящего свежего безопасного комментария для теста не найдено.",
                )
        except Exception as exc:
            self._error("Ошибка тестового автоответа", exc)

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
            issues = ", ".join(audit_data.get("issues", []))
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
                row["category"],
                row["status"],
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
                    }.get(str(value), MUTED)
                    item.setForeground(QColor(category_color))
                elif column == 5:
                    status_color = {
                        "replied": SUCCESS,
                        "new": YOUTUBE_RED,
                        "ignored": MUTED,
                    }.get(str(value), MUTED)
                    item.setForeground(QColor(status_color))
                    if str(value) in {"replied", "new"}:
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
                f"Автоответы: {safe_used}/{daily_limit} "
                f"· отправлено через приложение сегодня: {total_used} "
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
            self, "Ответ на комментарий", "Текст ответа:", draft
        )
        if not ok or not text.strip():
            return
        try:
            manual_reply(self.client, self.conn, comment_id, text.strip())
            self.reload_comments()
            self.statusBar().showMessage("Ответ опубликован")
        except Exception as exc:
            self._error("Ошибка ответа", exc)

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
            "ignored": "Комментарий помечен как игнорируемый",
            "new": "Комментарий возвращён в очередь",
        }
        self.statusBar().showMessage(labels.get(status, "Статус обновлён"))

    def save_reply_template(self, category: str, value: str) -> None:
        text = value.strip() or DEFAULT_REPLY_TEMPLATES[category]
        set_setting(self.conn, f"reply_template_{category}", text)
        if category in self.reply_template_edits:
            self.reply_template_edits[category][1].setText(text)
        self.statusBar().showMessage("Шаблон автоответа сохранён")

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
        self.statusBar().showMessage("Проверяю обновления...")
        QApplication.processEvents()
        try:
            info = check_for_update()
        except Exception as exc:
            self._error("Ошибка проверки обновлений", exc)
            return
        if info is None:
            self.statusBar().showMessage("Установлена актуальная версия")
            QMessageBox.information(
                self,
                APP_NAME,
                f"Установлена актуальная версия {__version__}.",
            )
            return
        self._offer_update(info)

    def _offer_update(self, info: UpdateInfo) -> None:
        answer = QMessageBox.question(
            self,
            "Доступно обновление",
            f"Доступна версия {info.version}.\n"
            f"Установлена версия {__version__}.\n\n"
            "Скачать и установить обновление сейчас?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage(
            f"Скачиваю RG YouTube Control {info.version}..."
        )
        QApplication.processEvents()
        try:
            installer = download_update(info)
        except Exception as exc:
            self._error("Ошибка загрузки обновления", exc)
            return

        self.statusBar().showMessage("Запускаю установку обновления...")
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(installer)))
        if not opened:
            QMessageBox.warning(
                self,
                APP_NAME,
                f"Не удалось запустить установщик автоматически.\n"
                f"Файл сохранён здесь:\n{installer}",
            )
            return
        QTimer.singleShot(800, QApplication.quit)

    def _error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
        self.statusBar().showMessage(str(exc))