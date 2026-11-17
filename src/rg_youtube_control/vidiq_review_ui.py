"""vidIQ title review window. No SEO generation and no YouTube write operations."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from .vidiq_review import load_inbox, set_editorial_reviewed


class VidIQReviewDialog(QDialog):
    def __init__(self, inbox_path: Path, transcript_dir: Path, *,
                 channel_id: str, parent=None):
        super().__init__(parent)
        self.inbox_path = Path(inbox_path)
        self.transcript_dir = Path(transcript_dir)
        self.channel_id = channel_id
        self.data = load_inbox(self.inbox_path)
        if self.data["channel_id"] != channel_id:
            raise ValueError("vidIQ inbox does not belong to selected channel")

        self.setWindowTitle("vidIQ · пакетні пропозиції · без публікації")
        self.resize(1160, 720)
        layout = QVBoxLayout(self)
        heading = QLabel(
            "Дані створені vidIQ. Підтвердження фактів — вручну за SRT. "
            "Програма не змінює заголовки, описи чи теги YouTube."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.summary = QLabel()
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Відео ID", "vidIQ: назва", "Оцінка vidIQ", "Етап", "SRT"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 135)
        self.table.setColumnWidth(1, 570)
        self.table.setColumnWidth(2, 105)
        self.table.setColumnWidth(3, 160)
        self.table.setColumnWidth(4, 70)
        layout.addWidget(self.table, 3)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "Виберіть пропозицію vidIQ, щоб побачити текст SRT. "
            "Наявність SRT не означає перевірку фактів."
        )
        self.preview.setMaximumHeight(160)
        layout.addWidget(self.preview, 1)
        self.confirm = QCheckBox(
            "Я особисто перевірив(ла) запропонований заголовок за повним відео/SRT"
        )
        layout.addWidget(self.confirm)

        controls = QHBoxLayout()
        self.copy_btn = QPushButton("Копіювати назву vidIQ")
        self.open_vidiq = QPushButton("Відкрити vidIQ")
        self.open_studio = QPushButton("Опис і теги · YouTube Studio + vidIQ")
        self.review_btn = QPushButton("Позначити як перевірене")
        close = QPushButton("Закрити")
        for button in (self.copy_btn, self.open_vidiq, self.open_studio,
                       self.review_btn, close):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.table.itemSelectionChanged.connect(self._changed)
        self.confirm.toggled.connect(self._changed)
        self.copy_btn.clicked.connect(self._copy)
        self.open_vidiq.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://app.vidiq.com/"))
        )
        self.open_studio.clicked.connect(self._studio)
        self.review_btn.clicked.connect(self._review)
        close.clicked.connect(self.accept)
        self._populate()

    def _populate(self, selected_video_id: str = ""):
        self.data = load_inbox(self.inbox_path)
        self.table.setRowCount(0)
        for video in self.data["videos"]:
            vid = video["video_id"]
            transcript = self.transcript_dir / (vid + ".srt")
            for option in video["title_suggestions"]:
                row = self.table.rowCount()
                self.table.insertRow(row)
                values = [
                    vid, option["title"], str(option["vidiq_score"]),
                    {
                        "VIDIQ_SUGGESTED": "На затвердженні",
                        "CONTENT_REVIEWED": "Контент перевірено",
                        "APPLIED": "Застосовано",
                    }.get(video["stage"], "Очікує vidIQ"),
                    "Є" if transcript.is_file() else "Немає",
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, vid)
                    self.table.setItem(row, col, item)
                if vid == selected_video_id:
                    self.table.selectRow(row)
        reviewed = sum(v["stage"] == "CONTENT_REVIEWED"
                       for v in self.data["videos"])
        self.summary.setText(
            f"Відео: {len(self.data['videos'])} · "
            f"Перевірено вручну: {reviewed} · "
            "Опис і теги: через інструменти vidIQ у YouTube Studio"
        )
        self._changed()

    def _selection(self):
        row = self.table.currentRow()
        if row < 0:
            return "", ""
        vid = self.table.item(row, 0)
        title = self.table.item(row, 1)
        return (vid.text() if vid else "", title.text() if title else "")

    def _changed(self):
        vid, title = self._selection()
        self.copy_btn.setEnabled(bool(title))
        self.open_studio.setEnabled(bool(vid))
        video = next((v for v in self.data["videos"]
                      if v["video_id"] == vid), None)
        can_review = bool(video and video["stage"] == "VIDIQ_SUGGESTED"
                          and self.confirm.isChecked())
        self.review_btn.setEnabled(can_review)
        if not vid:
            self.preview.clear()
            return
        path = self.transcript_dir / (vid + ".srt")
        if not path.is_file():
            self.preview.setPlainText(
                "SRT відсутній. Перевірте повний ролик перед підтвердженням.\n"
                "https://www.youtube.com/watch?v=" + vid
            )
            return
        try:
            excerpt = path.read_text(
                encoding="utf-8-sig", errors="replace"
            )[:7000]
        except OSError as exc:
            excerpt = str(exc)
        self.preview.setPlainText(
            "Джерело SRT: " + str(path) + "\n"
            + "Перегляд перших 7000 символів, НЕ повна редакторська перевірка.\n\n"
            + excerpt
        )

    def _copy(self):
        _, title = self._selection()
        if title:
            QApplication.clipboard().setText(title)

    def _studio(self):
        vid, _ = self._selection()
        if vid:
            QDesktopServices.openUrl(
                QUrl("https://studio.youtube.com/video/" + vid + "/edit")
            )

    def _review(self):
        vid, _ = self._selection()
        if not vid or not self.confirm.isChecked():
            return
        answer = QMessageBox.question(
            self, "Ручне підтвердження",
            "Ви перевірили всі запропоновані твердження за оригінальним відео? "
            "Це позначить перевірку, але НЕ опублікує SEO.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        set_editorial_reviewed(self.inbox_path, vid, confirmed_content=True)
        self.confirm.setChecked(False)
        self._populate(vid)
