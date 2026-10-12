"""One-event-per-physical-press gate for the F17 programmable mini keyboard.

Both WM_HOTKEY and GetAsyncKeyState can deliver the SAME press; route it once.
Also handle macro keyboards which send a very short key pulse or when Windows
rejects RegisterHotKey(F17). Never inspect any other keyboard key.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class F17PressGate:
    down: bool = False
    last_activated_ms: int = -1_000_000
    debounce_ms: int = 135

    def observe(self, *, down: bool, pressed_since_poll: bool, now_ms: int) -> bool:
        """Return True once per rising edge or very short pulse."""
        if not down:
            self.down = False
        if not down and not pressed_since_poll:
            return False
        if down and self.down:
            return False
        if now_ms - self.last_activated_ms < self.debounce_ms:
            if down:
                self.down = True
            return False
        self.down = bool(down)
        self.last_activated_ms = now_ms
        return True

    def native_hotkey(self, now_ms: int) -> bool:
        if now_ms - self.last_activated_ms < self.debounce_ms:
            return False
        self.down = True
        self.last_activated_ms = now_ms
        return True
