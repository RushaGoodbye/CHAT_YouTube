from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
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
    PROFILE_LABELS,
    PROFILE_TARGETS,
    app_data_dir,
)
from .db import (
    connect,
    get_setting,
    latest_metadata_snapshot,
    save_metadata_snapshot,
    set_comment_status,
    set_setting,
)
from .metadata_audit import normalize_links
from .optimization import priority_label, safe_description_fix
from .service import (
    manual_reply,
    scan_comments,
    sync_videos,
    today_auto_reply_count,
    today_reply_count,
)
from .youtube_api import YouTubeClient
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

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.data_dir = app_data_dir()
        self.conn = connect(self.data_dir / "rg_youtube_control.db")
        self.current_profile = get_setting(self.conn, "current_profile", "main")
        self.client = YouTubeClient(profile=self.current_profile)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_videos_tab()
        self._build_optimization_tab()
        self._build_comments_tab()
        self._build_settings_tab()

        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(lambda: self.scan_comment_queue(silent=True))
        self.scan_timer.start(DEFAULT_SCAN_MINUTES * 60 * 1000)

        self.statusBar().showMessage("SYSTEM READY")
        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()
        QTimer.singleShot(3000, self.check_for_updates_silent)

    def _build_videos_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        connect_btn = QPushButton("Подключить YouTube")
        connect_btn.clicked.connect(self.connect_youtube)
        sync_btn = QPushButton("Синхронизировать видео")
        sync_btn.clicked.connect(self.sync_video_list)
        edit_btn = QPushButton("Редактировать выбранное")
        edit_btn.clicked.connect(self.edit_selected_video)
        controls.addWidget(connect_btn)
        controls.addWidget(sync_btn)
        controls.addWidget(edit_btn)
        controls.addStretch()

        self.video_table = QTableWidget(0, 5)
        self.video_table.setHorizontalHeaderLabels(
            ["Видео", "Название", "Просмотры", "Audit", "Проблемы"]
        )
        self.video_table.horizontalHeader().setStretchLastSection(True)
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
        apply_btn = QPushButton("Применить к выбранным")
        apply_btn.clicked.connect(self.apply_safe_optimization)
        rollback_btn = QPushButton("Откатить последнее")
        rollback_btn.clicked.connect(self.rollback_selected_metadata)

        controls.addWidget(sync_all_btn)
        controls.addWidget(refresh_btn)
        controls.addWidget(preview_btn)
        controls.addWidget(apply_btn)
        controls.addWidget(rollback_btn)
        controls.addStretch()

        self.optimization_table = QTableWidget(0, 8)
        self.optimization_table.setHorizontalHeaderLabels(
            [
                "Приоритет",
                "Публикация",
                "Статус",
                "Видео",
                "Название",
                "Просмотры",
                "Audit",
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
        self.optimization_table.doubleClicked.connect(
            lambda _index: self.preview_safe_optimization()
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
        layout.addLayout(controls)
        layout.addWidget(self.comment_table)
        self.tabs.addTab(page, "Комментарии")

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
        self.auto_box.setChecked(
            get_setting(self.conn, "auto_reply_enabled", "0") == "1"
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
        layout.addWidget(oauth_btn)
        layout.addWidget(self.version_label)
        layout.addWidget(update_btn)
        layout.addStretch()
        self.tabs.addTab(page, "Настройки")

    def switch_profile(self, _index: int) -> None:
        profile = self.profile_combo.currentData()
        if not profile:
            return
        self.current_profile = str(profile)
        set_setting(self.conn, "current_profile", self.current_profile)
        self.client = YouTubeClient(profile=self.current_profile)
        title = get_setting(
            self.conn, f"channel_title_{self.current_profile}", ""
        )
        channel_id = get_setting(
            self.conn, f"channel_id_{self.current_profile}", ""
        )
        if title and channel_id:
            self.channel_label.setText(f"YouTube: {title} · {channel_id}")
        else:
            self.channel_label.setText("YouTube: не подключен")
        self.reload_videos()
        self.reload_optimization_queue()
        self.reload_comments()

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
            self.statusBar().showMessage("YouTube подключен")
        except Exception as exc:
            self._error("Ошибка авторизации", exc)

    def sync_video_list(self) -> None:
        try:
            rows = sync_videos(self.client, self.conn, limit=50)
            self.reload_videos()
            self.reload_optimization_queue()
            self.statusBar().showMessage(f"Видео синхронизированы: {len(rows)}")
        except Exception as exc:
            self._error("Ошибка синхронизации", exc)

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

        target_id = PROFILE_TARGETS[self.current_profile]
        rows = self.conn.execute(
            """SELECT video_id,title,published_at,scheduled_publish_at,
                      privacy_status,views,audit_json
               FROM videos
               WHERE channel_id=?""",
            (target_id,),
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
            values = [
                priority_text,
                publish_text,
                row["privacy_status"] or "",
                row["video_id"],
                row["title"],
                str(row["views"] or 0),
                str(score),
                ", ".join(issues),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setData(Qt.ItemDataRole.UserRole, row["video_id"])
                self.optimization_table.setItem(index, column, item)

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

            if changed:
                sync_videos(self.client, self.conn, limit=1000)
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
            sync_videos(self.client, self.conn, limit=1000)
            self.reload_videos()
            self.reload_optimization_queue()
            self.statusBar().showMessage("Метаданные видео восстановлены")
        except Exception as exc:
            self._error("Ошибка отката метаданных", exc)

    def scan_comment_queue(self, silent: bool = False) -> None:
        if silent and not self.background_box.isChecked():
            return
        target_id = PROFILE_TARGETS[self.current_profile]
        video_ids = [
            row["video_id"]
            for row in self.conn.execute(
                "SELECT video_id FROM videos "
                "WHERE channel_id=? AND privacy_status='public' "
                "ORDER BY published_at DESC LIMIT 20",
                (target_id,),
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

        target_id = PROFILE_TARGETS[self.current_profile]
        video_ids = [
            row["video_id"]
            for row in self.conn.execute(
                "SELECT video_id FROM videos "
                "WHERE channel_id=? AND privacy_status='public' "
                "ORDER BY published_at DESC LIMIT 20",
                (target_id,),
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

        target_id = PROFILE_TARGETS[self.current_profile]
        rows = self.conn.execute(
            "SELECT video_id,title,views,audit_json FROM videos "
            "WHERE channel_id=? ORDER BY published_at DESC LIMIT 200",
            (target_id,),
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
                self.video_table.setItem(index, column, QTableWidgetItem(value))

    def reload_comments(self, _index: int = -1) -> None:
        target_id = PROFILE_TARGETS[self.current_profile]
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
                   WHERE v.channel_id=?"""
        params: list[str] = [target_id]
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
                self.comment_table.setItem(index, column, item)

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