"""Windows global hotkeys for Elgato Stream Deck's built-in Hotkey action.

Commands are keyboard shortcuts, no Stream Deck plugin/credentials required.
Use Ctrl+Alt+Shift+F6..F10 in Stream Deck. All OS hooks are unregistered at exit.
Only the running RG Media Deck process handles registered shortcuts.
"""
from __future__ import annotations

import os
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
BASE_ID = 0x6A30
HOTKEYS = {
    0: ("play_pause", "Play / Pause", 0x75),    # F6
    1: ("stop", "Стоп", 0x76),                 # F7
    2: ("mute", "Звук", 0x77),                 # F8
    3: ("play_selected", "Показати обране", 0x78), # F9
    4: ("next_media", "Наступний файл", 0x79), # F10
}
COMBINATION = "Ctrl+Alt+Shift+"


def hotkey_guide() -> str:
    return "\n".join(f"{COMBINATION}F{6 + i}: {value[1]}"
                     for i, value in HOTKEYS.items())


class GlobalMediaHotkeys(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = []
        self.errors = []

    def register(self) -> None:
        if os.name != "nt":
            self.errors.append("Глобальні клавіші доступні лише у Windows")
            return
        user32 = ctypes.windll.user32
        for offset, (action, label, vk) in HOTKEYS.items():
            key_id = BASE_ID + offset
            if user32.RegisterHotKey(
                    None, key_id, MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, vk):
                self.registered.append(key_id)
            else:
                self.errors.append(f"{label}: комбінація зайнята іншою програмою")

    def nativeEventFilter(self, event_type, message):
        if os.name != "nt":
            return False, 0
        if str(event_type) not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (ValueError, TypeError):
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) in self.registered:
            self.callback(HOTKEYS[int(msg.wParam) - BASE_ID][0])
            return True, 0
        return False, 0

    def close(self):
        if os.name == "nt":
            for key_id in self.registered:
                ctypes.windll.user32.UnregisterHotKey(None, key_id)
        self.registered.clear()
