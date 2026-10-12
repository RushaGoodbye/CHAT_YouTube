"""Frame-wise seek target planner for Qt Multimedia QMediaPlayer.

Qt QMediaPlayer does not expose stepForward()/stepBackward(); the best safe
operation is to pause and seek to neighboring decoded QVideoFrame timestamps.
Use actual presented PTS where available; otherwise use video-track FPS, then
recent decoded frame durations, finally a conservative 25fps approximation.

Avoid spawning FFmpeg during a live broadcast and do not alter source files.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median
from math import isfinite


@dataclass
class FrameSeekPlanner:
    timestamps_ms: deque[int] = field(default_factory=lambda: deque(maxlen=300))
    frame_durations_ms: deque[float] = field(default_factory=lambda: deque(maxlen=30))
    cursor_ms: int | None = None
    cursor_exact_ms: float | None = None
    fps: float = 0.0
    fallback_ms: float = 40.0

    def reset(self):
        self.timestamps_ms.clear()
        self.frame_durations_ms.clear()
        self.cursor_ms = None
        self.cursor_exact_ms = None
        self.fps = 0.0

    def set_fps(self, value):
        try:
            rate = float(value)
        except (ValueError, TypeError, OverflowError):
            return
        if isfinite(rate) and 1 <= rate <= 240:
            self.fps = rate

    def observe(self, start_us: int, end_us: int):
        """Receive video sink presentation timestamps (microseconds)."""
        if start_us is None or start_us < 0:
            return
        ms = int(round(start_us / 1000))
        if not self.timestamps_ms or self.timestamps_ms[-1] != ms:
            if self.timestamps_ms:
                delta = ms - self.timestamps_ms[-1]
                if 4 <= delta <= 125:
                    self.frame_durations_ms.append(float(delta))
            self.timestamps_ms.append(ms)
        if end_us is not None and end_us > start_us:
            width = (end_us-start_us) / 1000
            if 4 <= width <= 125:
                self.frame_durations_ms.append(float(width))

    @property
    def frame_ms(self) -> float:
        if self.fps:
            return 1000 / self.fps
        if self.frame_durations_ms:
            return median(self.frame_durations_ms)
        return self.fallback_ms

    @property
    def precise(self) -> bool:
        return bool(self.fps or self.frame_durations_ms)

    def step(self, direction: int, current_ms: int, duration_ms: int) -> int:
        """Return new millisecond seek target; repeated presses always advance.

        Caller must pause playback before setPosition; QMediaPlayer only
        seeks at millisecond precision, so compressed/VFR video may map
        nearby targets to the same decoded image.
        """
        if direction not in (-1, 1):
            raise ValueError("Frame step direction must be -1 or +1")
        duration_ms = max(0, int(duration_ms))
        pos = self.cursor_ms if self.cursor_ms is not None else max(0, int(current_ms))
        exact = (self.cursor_exact_ms if self.cursor_exact_ms is not None
                 else float(pos))
        step_ms = max(1.0, self.frame_ms)
        available = sorted(set(t for t in self.timestamps_ms
                               if 0 <= t <= duration_ms))
        # Align an off-frame Qt position to a nearby observed start PTS.
        if available and self.cursor_ms is None:
            nearest = min(available, key=lambda t: abs(t-pos))
            if abs(nearest-pos) <= step_ms * 0.48:
                pos = nearest
                exact = float(nearest)
        # Prefer actual frame boundaries only if adjacent, never jump
        # multiple seconds because decoded samples are sparse.
        if direction > 0:
            candidates = [t for t in available
                          if pos < t <= pos + step_ms * 1.55]
            if candidates:
                target = min(candidates)
                exact = float(target)
            else:
                exact += step_ms
                target = round(exact)
            if target <= pos:
                target = pos + 1
                exact = float(target)
        else:
            candidates = [t for t in available
                          if pos - step_ms * 1.55 <= t < pos]
            if candidates:
                target = max(candidates)
                exact = float(target)
            else:
                exact -= step_ms
                target = round(exact)
            if target >= pos:
                target = pos - 1
                exact = float(target)
        self.cursor_ms = max(0, min(duration_ms, int(target)))
        self.cursor_exact_ms = max(0.0, min(float(duration_ms), exact))
        return self.cursor_ms

    def sync_external_seek(self):
        """Clear cursor after mouse/keyboard timeline seek or new media."""
        self.cursor_ms = None
        self.cursor_exact_ms = None
