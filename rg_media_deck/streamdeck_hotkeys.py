"""Configurable Windows global function-key shortcuts for Stream Deck Hotkey actions.

Works while OBS owns keyboard focus. No server, token, external plugin or OS
keyboard hook: user32 RegisterHotKey + Qt native event dispatch. F1-F12 with at
least two modifiers; conflicts are reported, never silently overwrite an
existing mapping or steal an occupied Windows/OBS shortcut.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 1, 2, 4, 8
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
BASE_ID = 0x6A30

ACTIONS = {
    "play_pause": "Play / Pause",
    "stop": "Стоп",
    "mute": "Звук",
    "play_selected": "Показати вибране",
    "next_media": "Наступний файл",
    "collection_1": "Добірка 1",
    "collection_2": "Добірка 2",
}
DEFAULT_BINDINGS = {
    "play_pause": "Ctrl+Alt+Shift+F6",
    "stop": "Ctrl+Alt+Shift+F7",
    "mute": "Ctrl+Alt+Shift+F8",
    "play_selected": "Ctrl+Alt+Shift+F9",
    "next_media": "Ctrl+Alt+Shift+F10",
    "collection_1": "Ctrl+Alt+Shift+F11",
    "collection_2": "Ctrl+Alt+Shift+F12",
}
MODIFIERS = {"ctrl": ("Ctrl", MOD_CONTROL), "alt": ("Alt", MOD_ALT),
             "shift": ("Shift", MOD_SHIFT), "win": ("Win", MOD_WIN)}
_PATTERN = re.compile(r"F(?:[1-9]|1[0-2])$", flags=re.I)


def parse_hotkey(value: str) -> tuple[str, int, int]:
    """Canonical chord and Win32 registration mask/vk. Fail closed."""
    if not isinstance(value, str):
        raise ValueError("Клавіша має бути текстом")
    segments = [part.strip() for part in value.split("+")]
    if len(segments) < 3 or not _PATTERN.fullmatch(segments[-1]):
        raise ValueError("Формат: Ctrl+Alt+Shift+F6 (F1–F12)")
    seen = set()
    mods = 0
    for segment in segments[:-1]:
        key = segment.casefold()
        if key not in MODIFIERS or key in seen:
            raise ValueError("Неприпустимі або повторні модифікатори")
        seen.add(key)
        mods |= MODIFIERS[key][1]
    if len(seen) < 2:
        raise ValueError("Для ефіру потрібно щонайменше два модифікатори")
    # Avoid Win+... combinations which may be owned by Windows.
    if "win" in seen:
        raise ValueError("Клавіша Win зарезервована системою")
    ordered = [MODIFIERS[key][0] for key in ("ctrl", "alt", "shift") if key in seen]
    key = segments[-1].upper()
    return "+".join([*ordered, key]), mods | MOD_NOREPEAT, 0x6F + int(key[1:])


def validated_bindings(settings) -> dict[str, str]:
    output = DEFAULT_BINDINGS.copy()
    if not isinstance(settings, dict):
        return output
    for action, raw in settings.items():
        if action not in ACTIONS:
            continue
        try:
            canonical, _, _ = parse_hotkey(raw)
        except ValueError:
            continue
        output[action] = canonical
    # Drop collisions deterministically instead of losing an arbitrary action.
    used = set()
    for action in list(ACTIONS):
        combo = output.get(action)
        if combo in used:
            output.pop(action, None)
        elif combo:
            used.add(combo)
    return output


def hotkey_guide(bindings: dict[str, str] | None = None) -> str:
    pairs = bindings if bindings is not None else DEFAULT_BINDINGS
    return "\n".join(f"{pairs.get(action, 'Не призначено')}: {label}"
                     for action, label in ACTIONS.items())


class GlobalMediaHotkeys(QAbstractNativeEventFilter):
    def __init__(self, callback, bindings=None):
        super().__init__()
        self.callback = callback
        self.bindings = validated_bindings(bindings)
        self.registered: dict[int, str] = {}
        self.errors: list[str] = []

    def configure(self, bindings) -> None:
        self.close()
        self.bindings = validated_bindings(bindings)
        self.register()

    def register(self) -> None:
        self.close()
        self.errors = []
        if os.name != "nt":
            self.errors.append("Глобальні клавіші доступні лише у Windows")
            return
        user32 = ctypes.windll.user32
        for offset, action in enumerate(ACTIONS):
            shortcut = self.bindings.get(action)
            if not shortcut:
                continue
            try:
                _, modifiers, vk = parse_hotkey(shortcut)
            except ValueError as exc:
                self.errors.append(f"{action}: {exc}")
                continue
            key_id = BASE_ID + offset
            if user32.RegisterHotKey(None, key_id, modifiers, vk):
                self.registered[key_id] = action
            else:
                self.errors.append(
                    f"{ACTIONS[action]} ({shortcut}): зайнято Windows або OBS")

    def nativeEventFilter(self, event_type, message):
        if os.name != "nt" or str(event_type) not in (
                "windows_generic_MSG", "windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (ValueError, TypeError):
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) in self.registered:
            self.callback(self.registered[int(msg.wParam)])
            return True, 0
        return False, 0

    def close(self):
        if os.name == "nt":
            for key_id in self.registered:
                ctypes.windll.user32.UnregisterHotKey(None, key_id)
        self.registered.clear()
