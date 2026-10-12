"""On-screen, opt-in diagnostics for USB mini-keyboard shortcuts.

Reports which global shortcuts were accepted by Windows and which WM_HOTKEY
events actually arrived. Only active while this dialog is open; never logs
passwords, general keystrokes or other applications' keyboard activity.
"""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from streamdeck_hotkeys import ACTIONS, BROADCAST_BINDINGS, parse_hotkey


class MiniKeyboardDiagnostics(QDialog):
    def __init__(self, hotkeys, parent=None):
        super().__init__(parent)
        self.hotkeys = hotkeys
        self.setWindowTitle("RG Media Deck — Перевірка mini keyboard")
        self.resize(630, 510)
        lay = QVBoxLayout(self)
        info = QLabel(
            "Натискай кнопки на mini keyboard. Тут відображаються отримані "
            "Windows-сигнали без запуску або зупинки відео.\n"
            "Якщо біля клавіші «НЕ ЗАРЕЄСТРОВАНО», вона зайнята іншою "
            "програмою або налаштована інакше.\n"
            "Після перевірки натисни «Закрити» — керування відновиться.")
        info.setWordWrap(True)
        lay.addWidget(info)
        lines = []
        for action, chord in BROADCAST_BINDINGS.items():
            # Start+pause physically occupies ONE Windows registration.
            reg = ("start" if action == "pause"
                   and hotkeys.bindings.get("start") == chord else action)
            chosen = hotkeys.bindings.get(action)
            registered = (reg in hotkeys.registered_chords and
                          hotkeys.registered_chords[reg] == chord)
            state = "ЗАРЕЄСТРОВАНО" if registered else "НЕ ЗАРЕЄСТРОВАНО"
            lines.append(f"{ACTIONS[action]}: {chord} — {state}"
                         + (f" (активна: {chosen})" if chord != chosen else ""))
        self.registrations = QLabel("\n".join(lines))
        self.registrations.setWordWrap(True)
        lay.addWidget(self.registrations)
        self.received = QLabel("Останній сигнал: очікування на mini keyboard...")
        self.received.setStyleSheet("font-weight: bold; color: #58caff;")
        lay.addWidget(self.received)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("Натисни F17, F9, +/- ...")
        lay.addWidget(self.history, 1)
        if hotkeys.errors:
            self.history.appendPlainText("Конфлікти Windows:\n" + "\n".join(hotkeys.errors))
        close = QPushButton("Закрити перевірку")
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        hotkeys.diagnostic_callback = self.record_hotkey

    def record_hotkey(self, action: str):
        now = datetime.now().strftime("%H:%M:%S")
        message = f"{now} — {ACTIONS.get(action, action)} — Windows WM_HOTKEY ✓"
        self.received.setText("Останній сигнал: " + message)
        self.history.appendPlainText(message)

    def keyPressEvent(self, event):
        # Optional local fallback when the hotkey could not be registered:
        # only display the exact supported keys, not a generic keylogger.
        mapping = {
            Qt.Key.Key_F17: "F17", Qt.Key.Key_F9: "F9",
            Qt.Key.Key_Plus: "+", Qt.Key.Key_Equal: "=",
            Qt.Key.Key_Minus: "-",
        }
        key_name = mapping.get(Qt.Key(event.key()))
        if key_name:
            mods = []
            for flag, text in [
                (Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                (Qt.KeyboardModifier.AltModifier, "Alt"),
                (Qt.KeyboardModifier.ShiftModifier, "Shift"),
            ]:
                if event.modifiers() & flag:
                    mods.append(text)
            message = f"{datetime.now():%H:%M:%S} — Qt сигнал: " + "+".join([*mods, key_name])
            self.history.appendPlainText(message)
            self.received.setText("Останній сигнал: " + message)
        super().keyPressEvent(event)

    def done(self, result: int):
        if self.hotkeys.diagnostic_callback == self.record_hotkey:
            self.hotkeys.diagnostic_callback = None
        super().done(result)
