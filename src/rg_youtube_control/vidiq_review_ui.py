"""vidIQ-only batch review: readable per-video editorial workflow, never publishes."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QPlainTextEdit,
    QRadioButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .vidiq_review import (
    load_inbox, set_editorial_reviewed, set_review_decision, reopen_for_review,
)

STAGE_LABELS = {
    "AWAITING_VIDIQ": "Очікує vidIQ",
    "VIDIQ_SUGGESTED": "На перевірці",
    "CONTENT_REVIEWED": "Затверджено",
    "APPLIED": "Застосовано",
    "REJECTED": "Відхилено всі",
    "SKIPPED": "Пропущено",
}


def best_suggestion(video: dict) -> dict:
    """Highest vidIQ score is informational; never an editorial approval."""
    return max(video["title_suggestions"], key=lambda v: v["vidiq_score"])


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
            raise ValueError("vidIQ inbox belongs to a different YouTube channel")
        self._loading = False

        self.setWindowTitle("vidIQ · пакетна перевірка · без публікації")
        self.resize(1400, 880)
        self.setMinimumSize(1140, 700)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        heading = QLabel(
            "SEO створює лише vidIQ. Оцінка vidIQ НЕ підтверджує факти. "
            "Рішення зберігаються локально, на YouTube нічого не публікується."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.summary = QLabel()
        layout.addWidget(self.summary)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.addWidget(QLabel("Відео · одне відео в рядку"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Відео", "Статус", "SRT"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 54)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        left_layout.addWidget(self.table)
        self.splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        self.counter = QLabel()
        right_layout.addWidget(self.counter)
        self.original = QLabel()
        self.original.setWordWrap(True)
        right_layout.addWidget(self.original)
        self.score_label = QLabel(
            "Рекомендація vidIQ позначена окремо. Оберіть ОДИН заголовок для затвердження."
        )
        self.score_label.setWordWrap(True)
        right_layout.addWidget(self.score_label)

        self.options_area = QScrollArea()
        self.options_area.setWidgetResizable(True)
        self.options_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        options_host = QWidget()
        option_layout = QVBoxLayout(options_host)
        option_layout.setContentsMargins(2, 4, 2, 4)
        option_layout.setSpacing(6)
        self.option_buttons = QButtonGroup(self)
        self.option_buttons.setExclusive(True)
        self.option_radios: list[QRadioButton] = []
        self.option_labels: list[QLabel] = []
        self.option_score_labels: list[QLabel] = []
        self.option_cards: list[QFrame] = []
        for i in range(3):
            card = QFrame()
            card.setObjectName("vidiqOptionCard")
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(9, 7, 9, 7)
            card_layout.setSpacing(4)
            top = QHBoxLayout()
            radio = QRadioButton(f"Варіант {i + 1}")
            top.addWidget(radio)
            score = QLabel()
            score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            top.addWidget(score, 1)
            card_layout.addLayout(top)
            full_title = QLabel()
            full_title.setWordWrap(True)
            full_title.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            full_title.setMinimumHeight(36)
            card_layout.addWidget(full_title)
            option_layout.addWidget(card)
            self.option_buttons.addButton(radio, i)
            self.option_radios.append(radio)
            self.option_labels.append(full_title)
            self.option_score_labels.append(score)
            self.option_cards.append(card)
            radio.toggled.connect(self._update_buttons)
        option_layout.addStretch()
        self.options_area.setWidget(options_host)
        self.options_area.setMinimumHeight(185)
        self.options_area.setMaximumHeight(295)
        right_layout.addWidget(self.options_area, 2)

        right_layout.addWidget(QLabel("Редакторські зауваження"))
        self.remarks_text = QPlainTextEdit()
        self.remarks_text.setReadOnly(True)
        self.remarks_text.setMaximumHeight(100)
        right_layout.addWidget(self.remarks_text)

        srt_controls = QHBoxLayout()
        self.srt_toggle = QCheckBox("Показати повний SRT")
        self.srt_toggle.setChecked(False)
        srt_controls.addWidget(self.srt_toggle)
        self.srt_search = QLineEdit()
        self.srt_search.setPlaceholderText("Пошук у SRT")
        self.srt_search.setClearButtonEnabled(True)
        srt_controls.addWidget(self.srt_search, 1)
        self.srt_find_next = QPushButton("Знайти далі")
        srt_controls.addWidget(self.srt_find_next)
        right_layout.addLayout(srt_controls)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setVisible(False)
        self.preview.setPlaceholderText("SRT відсутній")
        right_layout.addWidget(self.preview, 3)
        self.confirm = QCheckBox(
            "Я перевірив(ла) вибраний заголовок за повним відео/SRT"
        )
        right_layout.addWidget(self.confirm)
        right_layout.addStretch(1)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setSizes([590, 790])

        navigation = QHBoxLayout()
        self.previous_btn = QPushButton("Попереднє")
        self.next_btn = QPushButton("Наступне")
        self.skip_btn = QPushButton("Пропустити")
        self.reject_btn = QPushButton("Відхилити всі 3")
        self.reopen_btn = QPushButton("Повернути на перевірку")
        self.review_btn = QPushButton("Затвердити вибраний варіант")
        for b in (
            self.previous_btn, self.next_btn, self.skip_btn, self.reject_btn,
            self.reopen_btn, self.review_btn
        ):
            navigation.addWidget(b)
        layout.addLayout(navigation)

        actions = QHBoxLayout()
        self.copy_btn = QPushButton("Копіювати заголовок")
        self.open_video_btn = QPushButton("Відкрити відео")
        self.open_vidiq = QPushButton("Відкрити vidIQ")
        self.open_studio = QPushButton("YouTube Studio + vidIQ")
        close_btn = QPushButton("Закрити")
        for b in (self.copy_btn, self.open_video_btn, self.open_vidiq,
                  self.open_studio, close_btn):
            actions.addWidget(b)
        layout.addLayout(actions)

        self.table.itemSelectionChanged.connect(self._changed)
        self.confirm.toggled.connect(self._update_buttons)
        self.previous_btn.clicked.connect(lambda: self._navigate(-1))
        self.next_btn.clicked.connect(lambda: self._navigate(+1))
        self.skip_btn.clicked.connect(self._skip)
        self.reject_btn.clicked.connect(self._reject)
        self.reopen_btn.clicked.connect(self._reopen)
        self.review_btn.clicked.connect(self._review)
        self.copy_btn.clicked.connect(self._copy)
        self.open_video_btn.clicked.connect(self._video)
        self.open_vidiq.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://app.vidiq.com/"))
        )
        self.open_studio.clicked.connect(self._studio)
        close_btn.clicked.connect(self.accept)
        self.srt_toggle.toggled.connect(self._toggle_srt)
        self.srt_search.returnPressed.connect(self._find_next)
        self.srt_find_next.clicked.connect(self._find_next)
        self._populate()

    @staticmethod
    def _read_remarks(path: Path | None) -> dict[str, dict]:
        if not path or not Path(path).is_file():
            return {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            return {
                x["video_id"]: x for x in raw.get("items", [])
                if isinstance(x, dict) and isinstance(x.get("video_id"), str)
            }
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _videos(self) -> list[dict]:
        return self.data["videos"]

    def _selected_video(self) -> dict | None:
        index = self.table.currentRow()
        videos = self._videos()
        return videos[index] if 0 <= index < len(videos) else None

    def _populate(self, selected_id: str = "") -> None:
        self.data = load_inbox(self.inbox_path)
        videos = self._videos()
        prior = max(self.table.currentRow(), 0)
        self.table.blockSignals(True)
        self.table.setRowCount(len(videos))
        for i, video in enumerate(videos):
            vid = video["video_id"]
            title = self.original_titles.get(vid, "Назву не знайдено")
            values = [
                title, STAGE_LABELS.get(video["stage"], "Очікує vidIQ"),
                "Є" if (self.transcript_dir / (vid + ".srt")).is_file() else "Немає",
            ]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(("Video ID: " + vid + "\n" + value) if j == 0 else value)
                if j == 0:
                    item.setData(Qt.ItemDataRole.UserRole, vid)
                self.table.setItem(i, j, item)
        self.table.blockSignals(False)
        if videos:
            target = next((i for i, video in enumerate(videos)
                           if video["video_id"] == selected_id),
                          min(prior, len(videos) - 1))
            self.table.selectRow(target)
        else:
            self._render_detail()
        counts = {
            state: sum(video["stage"] == state for video in videos)
            for state in STAGE_LABELS
        }
        reviewed = counts["CONTENT_REVIEWED"] + counts["APPLIED"]
        left = counts["VIDIQ_SUGGESTED"] + counts["AWAITING_VIDIQ"]
        self.summary.setText(
            f"Перевірено: {reviewed}/{len(videos)}  ·  "
            f"Залишилося: {left}  ·  "
            f"Пропущено: {counts['SKIPPED']}  ·  "
            f"Відхилено: {counts['REJECTED']}  ·  "
            f"Застосовано: {counts['APPLIED']}"
        )
        self._changed()

    def _changed(self) -> None:
        self.confirm.setChecked(False)
        self.option_buttons.setExclusive(False)
        for radio in self.option_radios:
            radio.blockSignals(True)
            radio.setChecked(False)
            radio.blockSignals(False)
        self.option_buttons.setExclusive(True)
        self._render_detail()

    def _render_detail(self) -> None:
        video = self._selected_video()
        if not video:
            self.counter.setText("Немає вибраного відео")
            self.original.clear()
            self.preview.clear()
            self.remarks_text.clear()
            for card in self.option_cards:
                card.hide()
            self._update_buttons()
            return
        vid = video["video_id"]
        index = self.table.currentRow()
        self.counter.setText(
            f"Відео {index + 1} з {len(self._videos())}  ·  {vid}  ·  "
            + STAGE_LABELS.get(video["stage"], "Очікує vidIQ")
        )
        self.original.setText(
            "Оригінальна назва: " +
            self.original_titles.get(vid, "Не знайдена у локальній базі")
        )
        top_option = best_suggestion(video)
        selected = video.get("selected_title")
        for i, card in enumerate(self.option_cards):
            if i >= len(video["title_suggestions"]):
                card.hide()
                continue
            option = video["title_suggestions"][i]
            card.show()
            is_top = option is top_option
            is_selected = option["title"] == selected
            self.option_labels[i].setText(option["title"])
            self.option_score_labels[i].setText(
                f"vidIQ: {option['vidiq_score']}/100"
                + (" · Найвища оцінка" if is_top else "")
                + (" · Затверджено" if is_selected and video["stage"] == "CONTENT_REVIEWED" else "")
            )
            radio = self.option_radios[i]
            radio.setEnabled(video["stage"] not in ("REJECTED", "SKIPPED", "APPLIED"))
            radio.blockSignals(True)
            radio.setChecked(is_selected)
            radio.blockSignals(False)
            card.setStyleSheet(
                "QFrame#vidiqOptionCard {"
                + ("border: 2px solid #2376ac;" if is_selected else
                   "border: 1px solid #666;" if is_top else
                   "border: 1px solid #404040;")
                + "border-radius: 5px; }"
            )
        note = self.remarks.get(vid)
        if note:
            self.remarks_text.setPlainText(
                "Тема: " + str(note.get("srt_topic") or "") + "\n"
                + "Увага: " + str(note.get("caution") or "") + "\n"
                + "Ризик: " + str(note.get("risk") or "не визначено")
            )
        else:
            self.remarks_text.setPlainText(
                "Зауважень немає. Звірте твердження з повним відео."
            )
        path = self.transcript_dir / (vid + ".srt")
        if path.is_file():
            try:
                self.preview.setPlainText(
                    path.read_text(encoding="utf-8-sig", errors="replace")
                )
            except OSError as exc:
                self.preview.setPlainText(str(exc))
        else:
            self.preview.setPlainText("SRT відсутній. Перегляньте оригінальне відео.")
        self._toggle_srt(self.srt_toggle.isChecked())
        self._update_buttons()

    def _chosen_title(self) -> str:
        video = self._selected_video()
        if not video:
            return ""
        i = self.option_buttons.checkedId()
        choices = video["title_suggestions"]
        return choices[i]["title"] if 0 <= i < len(choices) else ""

    def _update_buttons(self) -> None:
        video = self._selected_video()
        index = self.table.currentRow()
        exists = bool(video)
        stage = video.get("stage") if video else ""
        choice = bool(self._chosen_title())
        self.previous_btn.setEnabled(exists and index > 0)
        self.next_btn.setEnabled(exists and index < len(self._videos()) - 1)
        self.skip_btn.setEnabled(exists and stage == "VIDIQ_SUGGESTED")
        self.reject_btn.setEnabled(exists and stage == "VIDIQ_SUGGESTED")
        self.reopen_btn.setEnabled(exists and stage in ("REJECTED", "SKIPPED"))
        self.review_btn.setEnabled(
            exists and stage in ("VIDIQ_SUGGESTED", "CONTENT_REVIEWED")
            and choice and self.confirm.isChecked()
        )
        self.copy_btn.setEnabled(choice)
        self.open_video_btn.setEnabled(exists)
        self.open_studio.setEnabled(exists)
        if video:
            top = best_suggestion(video)
            chosen = self._chosen_title()
            for i, card in enumerate(self.option_cards):
                if i >= len(video["title_suggestions"]):
                    continue
                option = video["title_suggestions"][i]
                is_approved = (
                    stage == "CONTENT_REVIEWED"
                    and option["title"] == video.get("selected_title")
                )
                is_current = bool(chosen and option["title"] == chosen)
                is_recommended = option is top
                if is_approved:
                    stroke = "2px solid #188755"
                elif is_current:
                    stroke = "2px solid #0894f9"
                elif is_recommended:
                    stroke = "1px solid #e9a814"
                else:
                    stroke = "1px solid #505050"
                card.setStyleSheet(
                    "QFrame#vidiqOptionCard { border: " + stroke
                    + "; border-radius: 5px; }"
                )
                self.option_score_labels[i].setText(
                    f"vidIQ: {option['vidiq_score']}/100"
                    + (" · Найвища оцінка" if is_recommended else "")
                    + (" · ЗАТВЕРДЖЕНО" if is_approved else
                       " · ВИБРАНО" if is_current else "")
                )

    def _navigate(self, offset: int) -> None:
        next_index = self.table.currentRow() + offset
        if 0 <= next_index < len(self._videos()):
            self.table.selectRow(next_index)

    def _skip(self) -> None:
        video = self._selected_video()
        if video and video["stage"] == "VIDIQ_SUGGESTED":
            set_review_decision(self.inbox_path, video["video_id"], decision="SKIPPED")
            self._populate(video["video_id"])
            self._navigate(1)

    def _reject(self) -> None:
        video = self._selected_video()
        if not video or video["stage"] != "VIDIQ_SUGGESTED":
            return
        decision = QMessageBox.question(
            self, "Відхилити всі пропозиції vidIQ",
            "Усі три заголовки будуть відхилені для цього відео.\n"
            "Зміни на YouTube НЕ вносяться. Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return
        set_review_decision(
            self.inbox_path, video["video_id"], decision="REJECTED",
            reason=str(self.remarks.get(video["video_id"], {}).get("caution") or
                       "Жоден із варіантів не підходить"),
        )
        self._populate(video["video_id"])
        self._navigate(1)

    def _reopen(self) -> None:
        video = self._selected_video()
        if video and video["stage"] in ("REJECTED", "SKIPPED"):
            reopen_for_review(self.inbox_path, video["video_id"])
            self._populate(video["video_id"])

    def _copy(self) -> None:
        title = self._chosen_title()
        if title:
            QApplication.clipboard().setText(title)

    def _video(self) -> None:
        video = self._selected_video()
        if video:
            QDesktopServices.openUrl(
                QUrl("https://www.youtube.com/watch?v=" + video["video_id"])
            )

    def _studio(self) -> None:
        video = self._selected_video()
        if video:
            QDesktopServices.openUrl(
                QUrl("https://studio.youtube.com/video/" + video["video_id"] + "/edit")
            )

    def _toggle_srt(self, expanded: bool) -> None:
        self.preview.setVisible(expanded)
        self.srt_search.setEnabled(expanded)
        self.srt_find_next.setEnabled(expanded)

    def _find_next(self) -> None:
        word = self.srt_search.text().strip()
        if not word:
            return
        self.srt_toggle.setChecked(True)
        if not self.preview.find(word):
            self.preview.moveCursor(QTextCursor.MoveOperation.Start)
            self.preview.find(word)

    def _review(self) -> None:
        video = self._selected_video()
        title = self._chosen_title()
        if not video or not title or not self.confirm.isChecked():
            return
        answer = QMessageBox.question(
            self, "Підтвердити заголовок vidIQ",
            "Ви особисто звірили вибраний заголовок з повним відео або SRT?\n\n"
            + title + "\n\nПублікації на YouTube не буде.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        set_editorial_reviewed(
            self.inbox_path, video["video_id"],
            confirmed_content=True, selected_title=title
        )
        self.confirm.setChecked(False)
        self._populate(video["video_id"])
        self._navigate(1)
