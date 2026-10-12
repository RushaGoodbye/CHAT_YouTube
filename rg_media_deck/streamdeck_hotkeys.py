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
    "start": "Старт / продовжити",
    "pause": "Пауза",
    "speed_up": "Швидкість +",
    "speed_down": "Швидкість −",
    "volume_down": "Звук тихіше",
    "volume_up": "Звук гучніше",
    "mute": "Вимкнути / увімкнути звук",
    "play_pause": "Play / Pause (разом)",
    "stop": "Стоп",
    "play_selected": "Показати вибране",
    "next_media": "Наступний файл",
    "collection_1": "Добірка 1",
    "collection_2": "Добірка 2",
}
DEFAULT_BINDINGS = {
    "start": "Ctrl+Alt+F1",
    "pause": "Ctrl+Alt+F2",
    "speed_up": "Ctrl+Alt+F3",
    "speed_down": "Ctrl+Alt+F4",
    "volume_down": "Ctrl+Alt+F5",
    "volume_up": "Ctrl+Alt+F6",
    "mute": "Ctrl+Alt+Shift+F8",
    "play_pause": "Ctrl+Alt+Shift+F6",
    "stop": "Ctrl+Alt+Shift+F7",
    "play_selected": "Ctrl+Alt+Shift+F9",
    "next_media": "Ctrl+Alt+Shift+F10",
    "collection_1": "Ctrl+Alt+Shift+F11",
    "collection_2": "Ctrl+Alt+Shift+F12",
}
MODIFIERS = {"ctrl": ("Ctrl", MOD_CONTROL), "alt": ("Alt", MOD_ALT),
             "shift": ("Shift", MOD_SHIFT), "win": ("Win", MOD_WIN)}
_PATTERN = re.compile(r"(?:F(?:[1-9]|1[0-2])|[A-Z]|[0-9])$", flags=re.I)


def parse_hotkey(value: str) -> tuple[str, int, int]:
    """Canonical chord, Win32 modifier bits and virtual key for Windows.

    Two modifiers minimum, no OS Win chords, no bare keys or media keys;
    safely supports F1..F12 plus Latin A..Z and digits 0..9.
    """
    if not isinstance(value, str):
        raise ValueError("Комбінація має бути текстом")
    segments = [part.strip() for part in value.split("+")]
    if len(segments) < 3 or not _PATTERN.fullmatch(segments[-1]):
        raise ValueError("Приклад: Ctrl+Alt+F1 або Ctrl+Shift+P")
    seen = set()
    mods = 0
    for segment in segments[:-1]:
        key = segment.casefold()
        if key not in MODIFIERS or key in seen:
            raise ValueError("Неприпустимі або повторні модифікатори")
        seen.add(key)
        mods |= MODIFIERS[key][1]
    if len(seen) < 2:
        raise ValueError("Потрібно щонайменше два модифікатори")
    if "win" in seen:
        raise ValueError("Клавіша Win зарезервована Windows")
    ordered = [MODIFIERS[key][0] for key in ("ctrl", "alt", "shift") if key in seen]
    key = segments[-1].upper()
    vk = 0x6F + int(key[1:]) if key.startswith("F") and len(key)>1 else ord(key)
    return "+".join([*ordered, key]), mods | MOD_NOREPEAT, vk


def validated_bindings(settings) -> dict[str, str]:
    """Keep legacy user overrides before applying any new default shortcuts.

    Priority is explicit user assignment > defaults. On collisions, the less
    important default is disabled rather than silently overriding older keys.
    Empty string explicitly disables an action across relaunches.
    """
    values = DEFAULT_BINDINGS.copy()
    explicitly_set = set()
    if isinstance(settings, dict):
        for action, raw in settings.items():
            if action not in ACTIONS:
                continue
            if raw == "":
                values.pop(action, None)
                explicitly_set.add(action)
                continue
            try:
                canonical, _, _ = parse_hotkey(raw)
            except ValueError:
                continue
            explicitly_set.add(action)
            values[action] = canonical
    priority = ([name for name in ACTIONS if name in explicitly_set]
                + [name for name in ACTIONS if name not in explicitly_set])
    used, output = set(), {}
    for action in priority:
        combo = values.get(action)
        if combo and combo not in used:
            output[action] = combo
            used.add(combo)
    return output


def check_bindings(bindings: dict[str, str]) -> dict[str, str]:
    """Validate the complete editor form before saving; reject all duplicates."""
    if not isinstance(bindings, dict):
        raise ValueError("Некоректний список призначень")
    result = {}
    for action in ACTIONS:
        raw = bindings.get(action, "")
        if not raw:
            continue
        canonical, _, _ = parse_hotkey(raw)
        if canonical in result.values():
            conflict = next(name for name, value in result.items() if value == canonical)
            raise ValueError(f"{ACTIONS[action]}: комбінацію {canonical} уже призначено для {ACTIONS[conflict]}")
        result[action] = canonical
    return result


def hotkey_guide(bindings: dict[str, str] | None = None) -> str:
    pairs = bindings if bindings is not None else DEFAULT_BINDINGS
    return "\n".join(f"{pairs.get(action, 'Вимкнено')}: {label}"
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
