"""Conservative dynamic picture-in-picture crop control for long live videos.

One sample every few seconds after startup, not every decoded frame. The
viewer/OBS rectangle remains fixed; only a normalized source crop changes.
Manual crops are intentionally controlled by the caller and never overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from video_fit import Crop, stable_crop


@dataclass(slots=True)
class DynamicCropState:
    sample_period_frames: int = 150
    crop: Crop | None = None
    frame_count: int = 0
    samples: list[Crop | None] = field(default_factory=list)
    _initial_frames: tuple[int, ...] = (6, 14, 23, 35, 48, 64)

    def reset(self) -> None:
        self.crop = None
        self.frame_count = 0
        self.samples.clear()

    def next_frame(self) -> bool:
        """Called for each decoded frame; True only when detection is due."""
        self.frame_count += 1
        return (self.frame_count in self._initial_frames or
                self.frame_count >= self.sample_period_frames and
                self.frame_count % self.sample_period_frames == 0)

    def observe(self, candidate: Crop | None) -> bool:
        """Return True only if the displayed crop changes.

        Three consecutive matching samples confirm a new crop. Three
        consecutive None samples restore the full source frame. A single
        anomalous scene never changes live output.
        """
        self.samples.append(candidate)
        self.samples = self.samples[-3:]
        if len(self.samples) < 3:
            return False
        if all(value is None for value in self.samples):
            if self.crop is not None:
                self.crop = None
                return True
            return False
        result = stable_crop(self.samples)
        if result is None:
            return False
        if self.crop is None or any(
            abs(getattr(self.crop, attr) - getattr(result, attr)) > 0.018
            for attr in ("left", "top", "right", "bottom")
        ):
            self.crop = result
            return True
        return False


@dataclass(slots=True)
class PlaybackHealth:
    """Pure monotonic-time stall detector, no forced on-air restarts."""
    timeout_ms: int = 16000
    started_ms: int | None = None
    last_progress_ms: int | None = None
    last_position_ms: int = 0
    warned: bool = False

    def reset(self, now_ms: int, position_ms: int = 0) -> None:
        self.started_ms = now_ms
        self.last_progress_ms = now_ms
        self.last_position_ms = max(0, position_ms)
        self.warned = False

    def progress(self, now_ms: int, position_ms: int) -> None:
        if self.started_ms is None:
            self.reset(now_ms, position_ms)
            return
        if position_ms >= self.last_position_ms + 100:
            self.last_position_ms = position_ms
            self.last_progress_ms = now_ms
            self.warned = False
        elif position_ms < self.last_position_ms - 300:
            # Seeked backwards, so restart the stall window.
            self.reset(now_ms, position_ms)

    def stalled(self, now_ms: int, *, playing: bool,
                buffering: bool = False, photo: bool = False) -> bool:
        if not playing or photo or self.started_ms is None or buffering:
            return False
        if self.warned:
            return False
        if now_ms - (self.last_progress_ms or self.started_ms) >= self.timeout_ms:
            self.warned = True
            return True
        return False
