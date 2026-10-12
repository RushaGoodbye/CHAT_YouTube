"""Low-overhead diagnosis of actual Qt GUI thread freezes.

The GUI sends a heartbeat every second. A daemon worker (never touching Qt
widgets) records Python thread stacks if the heartbeat stops for 9+ seconds.
Stores no recording, frame or audio data. This is for identifying hard freezes
that ordinary playback stall detectors cannot diagnose.
"""
from __future__ import annotations

import faulthandler
import threading
import time
from pathlib import Path


class UIHangWatch:
    def __init__(self, log_folder: Path, timeout_seconds: float = 9.0):
        self.log_file = Path(log_folder) / "ui_freeze_trace.log"
        self.timeout_seconds = max(5.0, float(timeout_seconds))
        self._alive = threading.Event()
        self._stopping = threading.Event()
        self._last_seen = time.monotonic()
        self._reported = False
        self._thread = threading.Thread(
            target=self._monitor, name="RGMediaUIHangWatch", daemon=True)
        self._thread.start()

    def tick(self) -> None:
        self._last_seen = time.monotonic()
        self._reported = False

    def stop(self) -> None:
        self._stopping.set()

    def _monitor(self):
        while not self._stopping.wait(2.0):
            delay = time.monotonic() - self._last_seen
            if delay < self.timeout_seconds or self._reported:
                continue
            self._reported = True
            try:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                if self.log_file.is_file() and self.log_file.stat().st_size > 2_000_000:
                    self.log_file.unlink()
                with self.log_file.open("a", encoding="utf-8") as logfile:
                    logfile.write(
                        f"\nRG_MEDIA_DECK_GUI_STALL {time.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"ui_heartbeat_delay={delay:.1f}s\n")
                    logfile.flush()
                    faulthandler.dump_traceback(file=logfile, all_threads=True)
            except (OSError, RuntimeError):
                pass
