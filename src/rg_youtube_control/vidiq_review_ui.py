"""Batch vidIQ review: one video per row, three alternatives, no publishing."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QPlainTextEdit, QRadioButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QSplitter,
)

from .vidiq_review import load_inbox, set_editorial_reviewed


STAGE_LABELS = {
    "AWAITING_VIDIQ": "Очікує vidIQ",
    "VIDIQ_SUGGESTED": "На перевірці",
    "CONTENT_REVIEWED": "Затверджено",
    "APPLIED": "Застосовано",
}


def best_suggestion(video: dict) -> dict:
    """Score order is informational only. No automatic approval."""
    return max(video["title_suggestions"], key=lambda x: x["vidiq_score"])


class VidIQReviewDialog(QDialog):
    def __init__(self, inbox_path: Path, transcript_dir: Path, *,
                 channel_id: str, parent=None,
                 original_titles: dict[str, str] | None = None,
                 remarks_path: Path | None = None):
        super().__init__(parent)
        self.inbox_path = Path(inbox_path)
        self.transcript_dir = Path(transcript_dir)
        self.channel_id = channel_id
        self.original_titles = dict(original_titles or {})
        self.remarks = self._read_remarks(remarks_path)
        self.data = load_inbox(self.inbox_path)
        if self.data["channel_id"] != channel_id:
            raise ValueError("vidIQ inbox does not belong to selected channel")

        self.setWindowTitle("vidIQ · 10 відео · пакетна перевірка · без публікації")
        self.resize(1250, 800)
        layout = QVBoxLayout(self)
        heading = QLabel(
            "Пропозиції створені виключно vidIQ. "
            "Оцінка vidIQ не є перевіркою фактів. "
            "Затвердження не публікує SEO на YouTube."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.summary = QLabel()
        layout.addWidget(self.summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.addWidget(QLabel("Відео · один рядок на ролик"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Відео ID", "Оригінальна назва", "Етап", "SRT"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for index, width in enumerate((120, 330, 140, 52)):
            self.table.setColumnWidth(index, width)
        list_layout.addWidget(self.table)
        splitter.addWidget(list_panel)

        detail_panel = QWidget()
        detail = QVBoxLayout(detail_panel)
        self.counter = QLabel()
        detail.addWidget(self.counter)
        self.original = QLabel()
        self.original.setWordWrap(True)
        detail.addWidget(self.original)
        detail.addWidget(QLabel("Три варіанти vidIQ · найвища оцінка позначена, але НЕ затверджена"))
        self.option_buttons = QButtonGroup(self)
        self.option_buttons.setExclusive(True)
        self.option_radios: list[QRadioButton] = []
        for index in range(3):
            radio = QRadioButton()
            radio.setWordWrap(False) if hasattr(radio, "setWordWrap") else None
            radio.setToolTip("Поставте позначку, якщо обрали цей варіант після перевірки")
            self.option_buttons.addButton(radio, index)
            self.option_radios.append(radio)
            detail.addWidget(radio)
            radio.toggled.connect(self._update_buttons)

        detail.addWidget(QLabel("Редакторські зауваження"))
        self.remarks_text = QPlainTextEdit()
        self.remarks_text.setReadOnly(True)
        self.remarks_text.setMaximumHeight(95)
        detail.addWidget(self.remarks_text)
        detail.addWidget(QLabel("Повний SRT · джерело для ручної перевірки"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        detail.addWidget(self.preview, 1)
        self.confirm = QCheckBox(
            "Я перевірив(ла) вибраний заголовок vidIQ за повним відео/SRT"
        )
        detail.addWidget(self.confirm)
        self.confirm.toggled.connect(self._update_buttons)
        splitter.addWidget(detail_panel)
        splitter.setSizes([490, 720])

        nav = QHBoxLayout()
        self.previous_btn = QPushButton("Попереднє")
        self.next_btn = QPushButton("Наступне")
        self.skip_btn = QPushButton("Пропустити")
        self.review_btn = QPushButton("Затвердити вибраний варіант")
        nav.addWidget(self.previous_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.skip_btn)
        nav.addWidget(self.review_btn)
        layout.addLayout(nav)

        actions = QHBoxLayout()
        self.copy_btn = QPushButton("Копіювати вибраний заголовок")
        self.open_video_btn = QPushButton("Відкрити відео")
        self.open_vidiq = QPushButton("Відкрити vidIQ")
        self.open_studio = QPushButton("Опис і теги · YouTube Studio + vidIQ")
        close = QPushButton("Закрити")
        for widget in (
            self.copy_btn, self.open_video_btn, self.open_vidiq,
            self.open_studio, close
        ):
            actions.addWidget(widget)
        layout.addLayout(actions)

        self.table.itemSelectionChanged.connect(self._changed)
        self.previous_btn.clicked.connect(lambda: self._navigate(-1))
        self.next_btn.clicked.connect(lambda: self._navigate(+1))
        self.skip_btn.clicked.connect(self._skip)
        self.review_btn.clicked.connect(self._review)
        self.copy_btn.clicked.connect(self._copy)
        self.open_video_btn.clicked.connect(self._video)
        self.open_vidiq.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://app.vidiq.com/"))
        )
        self.open_studio.clicked.connect(self._studio)
        close.clicked.connect(self.accept)
        self._populate()

    @staticmethod
    def _read_remarks(path: Path | None) -> dict[str, dict]:
        if path is None or not Path(path).is_file():
            return {}
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            return {
                r["video_id"]: r for r in payload.get("items", [])
                if isinstance(r, dict) and isinstance(r.get("video_id"), str)
            }
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _videos(self) -> list[dict]:
        return self.data["videos"]

    def _selected_video(self) -> dict | None:
        row = self.table.currentRow()
        videos = self._videos()
        return videos[row] if 0 <= row < len(videos) else None

    def _populate(self, selected_video_id: str = ""):
        self.data = load_inbox(self.inbox_path)
        videos = self._videos()
        old_index = self.table.currentRow()
        self.table.blockSignals(True)
        self.table.setRowCount(len(videos))
        for index, video in enumerate(videos):
            vid = video["video_id"]
            original_title = self.original_titles.get(vid, "Назву не завантажено")
            items = [
                vid, original_title, STAGE_LABELS.get(video["stage"], "Очікує vidIQ"),
                "Є" if (self.transcript_dir / (vid + ".srt")).is_file() else "Немає",
            ]
            for col, value in enumerate(items):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, col, item)
        self.table.blockSignals(False)
        if videos:
            target_index = next((
                i for i, v in enumerate(videos)
                if v["video_id"] == selected_video_id
            ), min(max(old_index, 0), len(videos)-1))
            self.table.selectRow(target_index)
        counts = {stage: sum(v["stage"] == stage for v in videos)
                  for stage in STAGE_LABELS}
        self.summary.setText(
            f"Відео: {len(videos)} · "
            f"Очікує vidIQ: {counts['AWAITING_VIDIQ']} · "
            f"На перевірці: {counts['VIDIQ_SUGGESTED']} · "
            f"Затверджено: {counts['CONTENT_REVIEWED']} · "
            f"Застосовано: {counts['APPLIED']}"
        )
        self._changed()

    def _changed(self):
        self.confirm.setChecked(False)
        for button in self.option_radios:
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
        self._render_detail()

    def _render_detail(self):
        video = self._selected_video()
        if video is None:
            self.counter.setText("Відео не вибране")
            self.original.setText("")
            self.remarks_text.clear()
            self.preview.clear()
            for radio in self.option_radios:
                radio.hide()
            self._update_buttons()
            return

        index = self.table.currentRow()
        vid = video["video_id"]
        self.counter.setText(
            f"Відео {index+1} з {len(self._videos())} · "
            f"{vid} · {STAGE_LABELS.get(video['stage'], 'Очікує vidIQ')}"
        )
        self.original.setText(
            "Оригінальна назва: " +
            self.original_titles.get(vid, "Не знайдена у локальній базі")
        )
        best = best_suggestion(video)
        for i, radio in enumerate(self.option_radios):
            if i >= len(video["title_suggestions"]):
                radio.hide()
                continue
            radio.show()
            option = video["title_suggestions"][i]
            recommended = option is best
            radio.setText(
                f"{i+1}. {option['title']}  ·  vidIQ {option['vidiq_score']}/100"
                + ("  ★ Найвища оцінка" if recommended else "")
            )
            radio.setStyleSheet(
                "font-weight: 700;" if recommended else "font-weight: 400;"
            )
            radio.setToolTip(option["title"])
            if option["title"] == video.get("selected_title"):
                radio.blockSignals(True)
                radio.setChecked(True)
                radio.blockSignals(False)

        note = self.remarks.get(vid)
        if note:
            self.remarks_text.setPlainText(
                "Тема: " + str(note.get("srt_topic") or "") + "\n"
                "Увага: " + str(note.get("caution") or "") + "\n"
                "Ризик: " + str(note.get("risk") or "не визначено")
            )
        else:
            self.remarks_text.setPlainText(
                "Редакторських зауважень ще немає. "
                "Перевірте твердження у повному SRT та самому відео."
            )
        path = self.transcript_dir / (vid + ".srt")
        if path.is_file():
            try:
                full_srt = path.read_text(encoding="utf-8-sig", errors="replace")
                self.preview.setPlainText(full_srt)
            except OSError as exc:
                self.preview.setPlainText(str(exc))
        else:
            self.preview.setPlainText("SRT немає. Перевірте оригінальне відео.")
        self._update_buttons()

    def _chosen_title(self) -> str:
        video = self._selected_video()
        if not video:
            return ""
        index = self.option_buttons.checkedId()
        variants = video["title_suggestions"]
        return variants[index]["title"] if 0 <= index < len(variants) else ""

    def _update_buttons(self):
        video = self._selected_video()
        valid = video is not None
        index = self.table.currentRow()
        self.previous_btn.setEnabled(valid and index > 0)
        self.next_btn.setEnabled(valid and index < len(self._videos())-1)
        self.skip_btn.setEnabled(valid and index < len(self._videos())-1)
        self.open_video_btn.setEnabled(valid)
        self.open_studio.setEnabled(valid)
        self.copy_btn.setEnabled(bool(self._chosen_title()))
        self.review_btn.setEnabled(
            valid and video["stage"] in ("VIDIQ_SUGGESTED", "CONTENT_REVIEWED")
            and self.confirm.isChecked() and bool(self._chosen_title())
        )

    def _navigate(self, change: int):
        index = self.table.currentRow()
        target = index + change
        if 0 <= target < len(self._videos()):
            self.table.selectRow(target)

    def _skip(self):
        # Skipping only changes navigation, not the saved editorial stage.
        self._navigate(1)

    def _copy(self):
        title = self._chosen_title()
        if title:
            QApplication.clipboard().setText(title)

    def _video(self):
        video = self._selected_video()
        if video:
            QDesktopServices.openUrl(
                QUrl("https://www.youtube.com/watch?v=" + video["video_id"])
            )

    def _studio(self):
        video = self._selected_video()
        if video:
            QDesktopServices.openUrl(
                QUrl("https://studio.youtube.com/video/" + video["video_id"] + "/edit")
            )

    def _review(self):
        video = self._selected_video()
        title = self._chosen_title()
        if video is None or not title or not self.confirm.isChecked():
            return
        answer = QMessageBox.question(
            self, "Підтвердження одного варіанта vidIQ",
            "Ви особисто звірили вибраний заголовок з повним відео або SRT?\n\n"
            + title + "\n\n"
            "Підтвердження НЕ публікує заголовок на YouTube.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        vid = video["video_id"]
        set_editorial_reviewed(
            self.inbox_path, vid,
            confirmed_content=True, selected_title=title
        )
        self.confirm.setChecked(False)
        self._populate(vid)
        if self.table.currentRow() < len(self._videos()) - 1:
            self._navigate(1)
