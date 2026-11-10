"""Opt-in SEO v2 preview tab. No YouTube API calls or background processing.

Only explicit clicks launch local LM Studio analysis. Runs in a QThread so
long SRT processing does not freeze the existing application.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QPlainTextEdit, QVBoxLayout, QWidget,
)

from .config import app_data_dir
from .seo_v2_cli import _local_chat, _save_json
from .seo_v3_pipeline import generate_claim_first_seo as generate_universal_seo


class _SEOv2Worker(QObject):
    line = Signal(str)
    completed = Signal()

    def __init__(self, files: list[Path], destination: Path) -> None:
        super().__init__()
        self.files = files
        self.destination = destination

    @Slot()
    def run(self) -> None:
        summary: list[dict] = []
        for source in self.files:
            output = self.destination / (source.stem + ".seo_v2_review.json")
            try:
                content = source.read_text(encoding="utf-8-sig")
                result = generate_universal_seo(
                    content, _local_chat, independent_review=_local_chat,
                )
                _save_json(output, result)
                row = {
                    "file": source.name,
                    "status": result["status"],
                    "quotes": len(result["evidence"]["accepted"]),
                    "output": str(output),
                    "publication_allowed": False,
                }
                draft = result.get("draft") or {}
                self.line.emit(
                    "\n".join([
                        "=== " + source.name + " | Claim-first v3 ===",
                        "ОСНОВНА НАЗВА: " + str(draft.get("title") or "—"),
                        "A/B: " + " | ".join(str(item) for item in
                                              draft.get("title_variants") or []),
                        "ОПИС: " + str(draft.get("description") or "—"),
                        "ТЕГИ: " + ", ".join(str(item) for item in
                                             draft.get("tags") or []),
                        "СТАТУС: " + str(result.get("status") or "REVIEW_REQUIRED"),
                        "ТИПІЗОВАНІ ЦИТАТИ: " + str(len((result.get("claims") or {}).get("claims") or [])),
                        "ПОМИЛКИ ТВЕРДЖЕНЬ: " + json.dumps(result.get("modality_issues") or [], ensure_ascii=False),
                        "ПЕРЕВІРКА ДЖЕРЕЛ: " + ", ".join(
                            str(item) for item in
                            (result.get("gate") or {}).get("issues") or []
                        ),
                        "ПІДОЗРІЛІ ІМЕНА: " + ", ".join(
                            str(item) for item in
                            (result.get("gate") or {}).get("unverified_names") or []
                        ),
                        "ЗАУВАЖЕННЯ РЕДАКТОРА: " + "\\n".join(
                            str(item.get("field") or "reviewer")
                            + ": " + str(item.get("reason") or "")
                            for item in (
                                (result.get("independent_review") or {})
                                .get("issues") or []
                            )
                            if isinstance(item, dict)
                        ),
                        "ВИПРАВЛЕНІ ПОЛЯ: " + (
                            ", ".join(result.get("semantic_repaired_fields") or [])
                            or "немає"
                        ),
                        "ПРИЧИНИ ВІДМОВИ ВИПРАВЛЕНЬ: " + json.dumps(
                            result.get("semantic_repair_diagnostics") or {},
                            ensure_ascii=False,
                        ),
                    ])
                )
            except Exception as exc:
                # Keep the entire batch alive if a model request fails
                # unexpectedly; show the exception TYPE only, not SRT text.
                row = {
                    "file": source.name,
                    "status": "ERROR_NEEDS_REVIEW",
                    "error": type(exc).__name__,
                    "publication_allowed": False,
                }
            summary.append(row)
            self.line.emit(json.dumps(row, ensure_ascii=False))
        try:
            _save_json(self.destination / "_summary.json", {
                "schema": "RG_SEO_V2_GUI_BATCH",
                "results": summary,
                "publication_allowed": False,
            })
        except OSError as exc:
            self.line.emit("Не вдалося зберегти підсумок: " + type(exc).__name__)
        self.completed.emit()


class SEOv2PreviewTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files: list[Path] = []
        self._thread: QThread | None = None
        self._worker: _SEOv2Worker | None = None
        layout = QVBoxLayout(self)
        title = QLabel("Універсальний SEO v3 · перевірка тверджень")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "Виберіть SRT або папку SRT. Обробка працює лише після натискання "
            "«Створити». Жодні дані YouTube не змінюються."
        ))
        actions = QHBoxLayout()
        choose_file = QPushButton("Вибрати SRT")
        choose_dir = QPushButton("Вибрати папку SRT")
        self._start = QPushButton("Створити SEO-чернетки")
        self._start.setEnabled(False)
        actions.addWidget(choose_file)
        actions.addWidget(choose_dir)
        actions.addWidget(self._start)
        layout.addLayout(actions)
        self._selection = QLabel("Файли не вибрані")
        layout.addWidget(self._selection)
        layout.addWidget(QLabel(
            "Для папки обробляються перші 10 SRT за назвою. "
            "Результати: окремі JSON-файли в папці даних програми."
        ))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log)
        choose_file.clicked.connect(self._choose_file)
        choose_dir.clicked.connect(self._choose_folder)
        self._start.clicked.connect(self._launch)
        self._choose_file_button = choose_file
        self._choose_dir_button = choose_dir

    def _choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Виберіть субтитри", "", "SubRip subtitles (*.srt)"
        )
        if filename:
            self._set_files([Path(filename)])

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Виберіть папку SRT")
        if folder:
            files = sorted(
                [p for p in Path(folder).iterdir()
                 if p.is_file() and p.suffix.casefold() == ".srt"],
                key=lambda item: item.name.casefold(),
            )[:10]
            self._set_files(files)

    def _set_files(self, files: list[Path]) -> None:
        self._files = files
        self._selection.setText(
            f"Вибрано SRT: {len(files)}" if files else "У папці немає SRT"
        )
        self._start.setEnabled(bool(files) and self._thread is None)

    def _launch(self) -> None:
        if not self._files or self._thread is not None:
            return
        output = app_data_dir() / "seo_v2_previews"
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError:
            QMessageBox.warning(self, "SEO v2", "Неможливо створити папку звітів")
            return
        self._log.clear()
        self._log.appendPlainText("Початок локальної обробки. Публікацію вимкнено.")
        self._start.setEnabled(False)
        self._choose_file_button.setEnabled(False)
        self._choose_dir_button.setEnabled(False)
        thread = QThread(self)
        worker = _SEOv2Worker(list(self._files), output)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.line.connect(self._log.appendPlainText)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(self._finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot()
    def _finished(self) -> None:
        self._thread = None
        self._worker = None
        self._start.setEnabled(bool(self._files))
        self._choose_file_button.setEnabled(True)
        self._choose_dir_button.setEnabled(True)
        self._log.appendPlainText("Завершено. Чернетки не опубліковано.")


def install_seo_v2_preview(window: QWidget) -> None:
    """Non-invasive extra tab; legacy SEO and its production code stay intact."""
    window.tabs.addTab(SEOv2PreviewTab(window), "SEO v2")
