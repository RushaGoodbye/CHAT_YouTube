from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config import (
    APP_NAME,
    DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
    DEFAULT_SCAN_MINUTES,
    PROFILE_LABELS,
    PROFILE_TARGETS,
    app_data_dir,
)
from .db import connect, get_setting, set_setting
from .metadata_audit import normalize_links
from .service import manual_reply, scan_comments, sync_videos
from .youtube_api import YouTubeClient

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
        self._build_comments_tab()
        self._build_settings_tab()

        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(lambda: self.scan_comment_queue(silent=True))
        self.scan_timer.start(DEFAULT_SCAN_MINUTES * 60 * 1000)

        self.statusBar().showMessage("SYSTEM READY")
        self.reload_videos()
        self.reload_comments()

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

    def _build_comments_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()

        scan_btn = QPushButton("Проверить комментарии")
        scan_btn.clicked.connect(lambda: self.scan_comment_queue(silent=False))
        reply_btn = QPushButton("Ответить на выбранный")
        reply_btn.clicked.connect(self.reply_selected)
        controls.addWidget(scan_btn)
        controls.addWidget(reply_btn)
        controls.addStretch()

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

        oauth_btn = QPushButton("Выбрать OAuth client JSON")
        oauth_btn.clicked.connect(self.choose_oauth_file)
        layout.addWidget(self.profile_combo)
        layout.addWidget(self.channel_label)
        layout.addWidget(self.background_box)
        layout.addWidget(self.auto_box)
        layout.addWidget(oauth_btn)
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
            self.client.update_video(
                video_id, title=title, description=description, tags=tags
            )
            self.sync_video_list()
            self.statusBar().showMessage("Метаданные видео обновлены")
        except Exception as exc:
            self._error("Ошибка обновления видео", exc)

    def scan_comment_queue(self, silent: bool = False) -> None:
        if silent and not self.background_box.isChecked():
            return
        target_id = PROFILE_TARGETS[self.current_profile]
        video_ids = [
            row["video_id"]
            for row in self.conn.execute(
                "SELECT video_id FROM videos WHERE channel_id=? "
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
                max_auto_replies=DEFAULT_MAX_AUTO_REPLIES_PER_DAY,
            )
            self.reload_comments()
            self.statusBar().showMessage(
                "Комментарии: {seen}, очередь: {queued}, автоответы: {auto_replied}".format(
                    **stats
                )
            )
        except Exception as exc:
            if silent:
                self.statusBar().showMessage(f"Фоновая проверка: {exc}")
            else:
                self._error("Ошибка комментариев", exc)

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

    def reload_comments(self) -> None:
        target_id = PROFILE_TARGETS[self.current_profile]
        rows = self.conn.execute(
            """SELECT c.comment_id,c.published_at,c.video_id,c.author,c.text,
                      c.category,c.status,c.reply_text
               FROM comments c
               JOIN videos v ON v.video_id=c.video_id
               WHERE v.channel_id=?
               ORDER BY c.published_at DESC LIMIT 500""",
            (target_id,),
        ).fetchall()
        self.comment_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row["published_at"] or "",
                row["video_id"],
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
                self.comment_table.setItem(index, column, item)

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

    def _error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))
        self.statusBar().showMessage(str(exc))