"""Configurable Windows global function-key shortcuts for Stream Deck Hotkey actions.

Works while OBS owns keyboard focus. No server, token, external plugin or OS
keyboard hook: user32 RegisterHotKey + Qt native event dispatch. F9/F17
may be bare; Ctrl/Alt/Shift with OEM +/- keyboard keys supported.
"""
from __future__ import annotations

import ctypes
import os
import re
import time
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer
from f17_press import F17PressGate

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
    "frame_back": "Кадр назад",
    "frame_forward": "Кадр вперед",
    "play_pause": "Play / Pause (разом)",
    "stop": "Стоп",
    "play_selected": "Показати вибране",
    "next_media": "Наступний файл",
    "collection_1": "Добірка 1",
    "collection_2": "Добірка 2",
}
# Preset approved for live Stream Deck workflow.
# F17 is intentionally used for BOTH start/pause; it is registered ONCE
# and toggles the existing player. All other duplicate chords are rejected.
BROADCAST_BINDINGS = {
    "start": "F17",
    "pause": "F17",
    "speed_up": "Ctrl+Alt+Shift+=",
    "speed_down": "Ctrl+Alt+Shift+-",
    "volume_down": "Alt+Shift+-",
    "volume_up": "Alt+Shift+=",
    "mute": "F9",
}
DEFAULT_BINDINGS = {
    **BROADCAST_BINDINGS,
    "frame_back": "Alt+Shift+PgDown",
    "frame_forward": "Alt+Shift+PgUp",
    "play_pause": "Ctrl+Alt+Shift+F6",
    "stop": "Ctrl+Alt+Shift+F7",
    "play_selected": "Ctrl+Alt+Shift+F9",
    "next_media": "Ctrl+Alt+Shift+F10",
    "collection_1": "Ctrl+Alt+Shift+F11",
    "collection_2": "Ctrl+Alt+Shift+F12",
}
LEGACY_BINDINGS = {
    "start": "Ctrl+Alt+F1",
    "pause": "Ctrl+Alt+F2",
    "speed_up": "Ctrl+Alt+F3",
    "speed_down": "Ctrl+Alt+F4",
    "volume_down": "Ctrl+Alt+F5",
    "volume_up": "Ctrl+Alt+F6",
    "mute": "Ctrl+Alt+Shift+F8",
}
MODIFIERS = {"ctrl": ("Ctrl", MOD_CONTROL), "alt": ("Alt", MOD_ALT),
             "shift": ("Shift", MOD_SHIFT), "win": ("Win", MOD_WIN)}
_FUNCTION_KEY = re.compile(r"F([1-9]|1[0-9]|2[0-4])$", re.I)
_LETTER_DIGIT = re.compile(r"[A-Z0-9]$", re.I)
_SHARED_PAIR = frozenset(("start", "pause"))
_PUNCT_VK = {"=": 0xBB, "+": 0xBB, "-": 0xBD}
# Windows VK_NEXT / VK_PRIOR; Qt QKeySequenceEdit displays PgDown/PgUp.
_PAGE_KEYS = {"PGDOWN": ("PgDown", 0x22),
              "PAGEDOWN": ("PgDown", 0x22),
              "PGUP": ("PgUp", 0x21),
              "PAGEUP": ("PgUp", 0x21)}


def parse_hotkey(value: str) -> tuple[str, int, int]:
    """Windows physical virtual-key chords, including F17 and OEM +/- keys.

    Ctrl+Alt+Shift+= resolves to VK_OEM_PLUS (the =/+ keyboard key).
    Bare keys are limited to F9 and F13..F24 to avoid stealing everyday
    keyboard controls. A chord using the Windows key is never allowed.
    """
    if not isinstance(value, str):
        raise ValueError("Комбінація має бути текстом")
    raw = value.strip()
    if not raw:
        raise ValueError("Не вибрано клавішу")
    segments = [chunk.strip() for chunk in raw.split("+")]
    # Qt may display a shifted plus key with a trailing literal '+'.
    if segments[-1] == "" and len(segments) > 1:
        segments = segments[:-2] + ["+"]
    key = segments[-1].upper()
    match = _FUNCTION_KEY.fullmatch(key)
    if match:
        number = int(match.group(1))
        vk = 0x6F + number
        if len(segments) == 1 and number != 9 and number < 13:
            raise ValueError("Без модифікаторів дозволено F9 та F13–F24")
    elif key in _PAGE_KEYS:
        key, vk = _PAGE_KEYS[key]
    elif key in _PUNCT_VK:
        vk = _PUNCT_VK[key]
        if key == "+":
            key = "="  # canonical =/+ physical key
    elif _LETTER_DIGIT.fullmatch(key):
        vk = ord(key)
    else:
        raise ValueError("Доступні F1–F24, A–Z, 0–9, =, -, PgUp та PgDown")
    mods = 0
    used = set()
    for raw_modifier in segments[:-1]:
        token = raw_modifier.casefold()
        if token not in MODIFIERS or token in used:
            raise ValueError("Неприпустимі або повторні модифікатори")
        used.add(token)
        mods |= MODIFIERS[token][1]
    if "win" in used:
        raise ValueError("Комбінації з Win недоступні")
    if not used and (key not in ("F9",) and
                     not (_FUNCTION_KEY.fullmatch(key) and int(key[1:]) >= 13)):
        raise ValueError("Для цієї клавіші потрібні модифікатори")
    if used and len(used) < 2:
        raise ValueError("Потрібно Ctrl+Alt, Ctrl+Shift або Alt+Shift")
    if key in ("=", "-") and "shift" not in used:
        raise ValueError("Для = та - використайте Shift з іншим модифікатором")
    ordered = [MODIFIERS[k][0] for k in ("ctrl", "alt", "shift") if k in used]
    return "+".join((*ordered, key)), mods | MOD_NOREPEAT, vk


def is_shared_toggle(action_a: str, action_b: str) -> bool:
    return frozenset((action_a, action_b)) == _SHARED_PAIR


def normalized_duplicates(bindings: dict[str, str]) -> dict[str, str]:
    """Return a single action per chord for OS hotkey registration.

    The start+pause pair becomes a play/pause toggle without registering an
    impossible second Windows hotkey. All other duplicates are an error.
    """
    result = {}
    prior = {}
    for action in ACTIONS:
        chord = bindings.get(action)
        if not chord:
            continue
        if chord in prior:
            existing = prior[chord]
            if is_shared_toggle(existing, action):
                result[existing] = "play_pause"
                continue
            raise ValueError(
                f"{ACTIONS[action]}: {chord} вже використовується для {ACTIONS[existing]}")
        prior[chord] = action
        result[action] = action
    return result


def check_bindings(bindings: dict[str, str]) -> dict[str, str]:
    if not isinstance(bindings, dict):
        raise ValueError("Некоректний список призначень")
    result = {}
    for action in ACTIONS:
        raw = bindings.get(action, "")
        if raw:
            canonical, _, _ = parse_hotkey(raw)
            result[action] = canonical
    normalized_duplicates(result)
    return result


def validated_bindings(settings) -> dict[str, str]:
    """Keep user changes and disabled bindings; allow only start+pause F17."""
    values = DEFAULT_BINDINGS.copy()
    priority = []
    if isinstance(settings, dict):
        for action, raw in settings.items():
            if action not in ACTIONS:
                continue
            priority.append(action)
            if raw == "":
                values.pop(action, None)
                continue
            try:
                values[action] = parse_hotkey(raw)[0]
            except ValueError:
                continue
    order = list(dict.fromkeys(priority + list(ACTIONS)))
    result = {}
    for action in order:
        value = values.get(action)
        if not value:
            continue
        conflicts = [old for old, chord in result.items() if chord == value]
        if conflicts and not all(is_shared_toggle(old, action) for old in conflicts):
            continue
        result[action] = value
    return result


def hotkey_guide(bindings: dict[str, str] | None = None) -> str:
    pairs = bindings if bindings is not None else DEFAULT_BINDINGS
    return "\n".join(f"{pairs.get(action, 'Вимкнено')}: {label}"
                     for action, label in ACTIONS.items())


class GlobalMediaHotkeys(QAbstractNativeEventFilter):
    def __init__(self, callback, bindings=None):
        super().__init__()
        self.callback = callback
        self.diagnostic_callback = None
        self.received_hotkeys = 0
        self.registered_chords: dict[str, str] = {}
        self._f17_gate = F17PressGate()
        self._f17_timer = QTimer()
        self._f17_timer.setInterval(12)
        self._f17_timer.timeout.connect(self._poll_f17)
        self._f17_route: str | None = None
        self._frame_timer = QTimer()
        self._frame_timer.setInterval(12)
        self._frame_timer.timeout.connect(self._poll_frame_keys)
        self._frame_routes: dict[int, str] = {}
        self._frame_gates: dict[int, F17PressGate] = {}
        self.f17_poll_count = 0
        self.bindings = validated_bindings(bindings)
        self.registered: dict[int, str] = {}
        self.errors: list[str] = []

    def configure(self, bindings) -> None:
        self.close()
        self.bindings = validated_bindings(bindings)
        self.register()

    def register(self) -> None:
        self.close()
        self.registered_chords = {}
        self.errors = []
        if os.name != "nt":
            self.errors.append("Глобальні клавіші доступні лише у Windows")
            return
        user32 = ctypes.windll.user32
        resolved = normalized_duplicates(self.bindings)
        self._f17_gate = F17PressGate()
        self._f17_route = next(
            (resolved[action] for action in ACTIONS
             if self.bindings.get(action) == "F17" and action in resolved), None)
        if self._f17_route:
            self._f17_timer.start()
        self._frame_routes = {}
        self._frame_gates = {}
        for vk, chord in ((0x81, "F18"), (0x82, "F19")):
            for action in ACTIONS:
                if self.bindings.get(action) == chord and action in resolved:
                    self._frame_routes[vk] = resolved[action]
                    self._frame_gates[vk] = F17PressGate(debounce_ms=75)
                    break
        if self._frame_routes:
            self._frame_timer.start()
        for offset, action in enumerate(ACTIONS):
            shortcut = self.bindings.get(action)
            if not shortcut or action not in resolved:
                continue
            if action == "pause" and self.bindings.get("start") == shortcut:
                continue
            try:
                _, modifiers, vk = parse_hotkey(shortcut)
            except ValueError as exc:
                self.errors.append(f"{action}: {exc}")
                continue
            key_id = BASE_ID + offset
            if user32.RegisterHotKey(None, key_id, modifiers, vk):
                self.registered[key_id] = resolved[action]
                self.registered_chords[action] = shortcut
            else:
                self.errors.append(
                    f"{ACTIONS[action]} ({shortcut}): зайнято Windows або OBS")

    def _deliver_hotkey(self, action: str):
        self.received_hotkeys += 1
        if self.diagnostic_callback is not None:
            self.diagnostic_callback(action)
        else:
            self.callback(action)

    def _poll_f17(self):
        """Read ONLY VK_F17 (0x80), even when OBS has keyboard focus.

        Some HID macro keyboards emit F17 pulses too short for a global
        registered hotkey. This fallback does not suppress the Windows key,
        nor log or inspect any other keyboard input.
        """
        if os.name != "nt" or not self._f17_route:
            return
        try:
            state = ctypes.windll.user32.GetAsyncKeyState(0x80)
        except (AttributeError, OSError):
            self._f17_timer.stop()
            self.errors.append("F17: Windows GetAsyncKeyState недоступний")
            return
        self.f17_poll_count += 1
        now_ms = int(time.monotonic() * 1000)
        if self._f17_gate.observe(down=bool(state & 0x8000),
                                  pressed_since_poll=bool(state & 0x0001),
                                  now_ms=now_ms):
            self._deliver_hotkey(self._f17_route)

    def _poll_frame_keys(self):
        """Read only configured F18/F19 to support short USB macro key pulses."""
        if os.name != "nt" or not self._frame_routes:
            return
        now = int(time.monotonic() * 1000)
        for vk, action in self._frame_routes.items():
            try:
                state = ctypes.windll.user32.GetAsyncKeyState(vk)
            except (AttributeError, OSError):
                self._frame_timer.stop()
                self.errors.append("F18/F19: GetAsyncKeyState недоступний")
                return
            gate = self._frame_gates[vk]
            if gate.observe(down=bool(state & 0x8000),
                            pressed_since_poll=bool(state & 0x0001),
                            now_ms=now):
                self._deliver_hotkey(action)

    @staticmethod
    def _native_type(event_type) -> str:
        """PySide6 delivers a QByteArray; str(QByteArray) may contain b'...'."""
        try:
            return bytes(event_type).decode("ascii", errors="ignore")
        except (TypeError, ValueError, AttributeError):
            return str(event_type).removeprefix("b'").removesuffix("'")

    def nativeEventFilter(self, event_type, message):
        if os.name != "nt" or self._native_type(event_type) not in (
                "windows_generic_MSG", "windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (ValueError, TypeError, OSError):
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) in self.registered:
            action = self.registered[int(msg.wParam)]
            if action == self._f17_route and self._f17_route:
                if self._f17_gate.native_hotkey(int(time.monotonic() * 1000)):
                    self._deliver_hotkey(action)
            elif action in self._frame_routes.values():
                vk = next((key for key, route in self._frame_routes.items()
                           if route == action), None)
                gate = self._frame_gates.get(vk)
                if gate and gate.native_hotkey(int(time.monotonic() * 1000)):
                    self._deliver_hotkey(action)
            else:
                self._deliver_hotkey(action)
            return True, 0
        return False, 0

    def close(self):
        self._f17_timer.stop()
        self._frame_timer.stop()
        self._frame_routes.clear()
        self._frame_gates.clear()
        self._f17_route = None
        if os.name == "nt":
            for key_id in self.registered:
                ctypes.windll.user32.UnregisterHotKey(None, key_id)
        self.registered.clear()
