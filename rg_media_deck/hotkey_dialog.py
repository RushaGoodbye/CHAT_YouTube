"""Compact keyboard shortcut editor for RG Media Deck and Elgato Stream Deck.

Press a key combination instead of typing it. Each action may be assigned
a chord or disabled. A duplicate or unsupported Windows shortcut is rejected
before the settings file is modified.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFormLayout,
    QKeySequenceEdit, QPushButton, QScrollArea, QWidget, QMessageBox,
)

from streamdeck_hotkeys import ACTIONS, DEFAULT_BINDINGS, check_bindings


class HotkeyEditor(QDialog):
    def __init__(self, bindings: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("RG Media Deck — Гарячі клавіші")
        self.setMinimumSize(535, 640)
        self._original = dict(bindings)
        self.bindings: dict[str, str] | None = None
        layout = QVBoxLayout(self)
        header = QLabel(
            "Натисніть потрібну комбінацію в полі. "
            "Клавіші працюють також у Stream Deck, коли OBS активний.\n"
            "F17 працює і для Старту, і для Паузи як одна клавіша Play/Pause. "
            "F9 також можна без модифікаторів. Підтримуються +/= і - з Shift, "
            "функціональні F1–F24 та інші клавіші з модифікаторами.")
        header.setWordWrap(True)
        layout.addWidget(header)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)
        self.fields = {}
        for action, label in ACTIONS.items():
            row = QHBoxLayout()
            editor = QKeySequenceEdit()
            editor.setMaximumSequenceLength(1)
            editor.setKeySequence(QKeySequence(bindings.get(action, "")))
            editor.setMinimumWidth(190)
            editor.setToolTip(f"{label}: клацніть та натисніть нову комбінацію")
            self.fields[action] = editor
            clear_btn = QPushButton("✕")
            clear_btn.setFixedWidth(32)
            clear_btn.setToolTip("Вимкнути цю гарячу клавішу")
            clear_btn.clicked.connect(lambda checked=False, item=editor:
                                      item.setKeySequence(QKeySequence()))
            row.addWidget(editor, 1)
            row.addWidget(clear_btn)
            form.addRow(label, row)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        reset = QPushButton("Клавіші як на фото")
        reset.setToolTip("F17 = старт/пауза; F9 = звук; швидкість і гучність +/-")
        reset.clicked.connect(self._reset_defaults)
        footer.addWidget(reset)
        footer.addStretch()
        cancel = QPushButton("Скасувати")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Зберегти")
        save.setDefault(True)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        layout.addLayout(footer)

    def _reset_defaults(self):
        for action, editor in self.fields.items():
            editor.setKeySequence(QKeySequence(DEFAULT_BINDINGS.get(action, "")))

    def _save(self):
        values = {}
        for action, editor in self.fields.items():
            value = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            values[action] = value
        try:
            self.bindings = check_bindings(values)
        except ValueError as exc:
            QMessageBox.warning(self, "Конфлікт гарячих клавіш", str(exc))
            return
        self.accept()
