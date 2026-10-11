"""Fail-safe resource admission control and broadcast health counters.

No media transcoding and no changes to OBS. Limit concurrent decoding by
disabling silent pre-roll when CPU, physical RAM or process RSS is high.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None


@dataclass
class ResourceSnapshot:
    cpu: float = 0.0
    physical_ram: float = 0.0
    process_bytes: int = 0
    at: float = 0.0


def permit_preload(snapshot: ResourceSnapshot, *,
                   cpu_limit: float = 85.0,
                   ram_limit: float = 88.0,
                   rss_limit: int = 1600 * 1024 * 1024) -> bool:
    return (snapshot.cpu < cpu_limit and snapshot.physical_ram < ram_limit
            and snapshot.process_bytes < rss_limit)


@dataclass
class BroadcastGuard:
    snapshot: ResourceSnapshot = field(default_factory=ResourceSnapshot)
    switch_count: int = 0
    decoder_errors: int = 0
    preload_skipped: int = 0
    stalled_count: int = 0
    peak_rss: int = 0
    max_cpu: float = 0
    _last_sample: float = 0

    def sample(self, now: float | None = None) -> ResourceSnapshot:
        now = time.monotonic() if now is None else now
        if now - self._last_sample < 3 and self._last_sample:
            return self.snapshot
        self._last_sample = now
        if psutil is not None:
            try:
                proc = psutil.Process()
                snapshot = ResourceSnapshot(
                    cpu=psutil.cpu_percent(interval=None),
                    physical_ram=psutil.virtual_memory().percent,
                    process_bytes=proc.memory_info().rss, at=now)
                self.snapshot = snapshot
                self.peak_rss = max(self.peak_rss, snapshot.process_bytes)
                self.max_cpu = max(self.max_cpu, snapshot.cpu)
            except (OSError, RuntimeError, AttributeError):
                pass
        return self.snapshot

    def can_preload(self, now: float | None = None) -> bool:
        ok = permit_preload(self.sample(now))
        if not ok:
            self.preload_skipped += 1
        return ok

    def summary(self, state: str, name: str = "") -> dict:
        return {
            "state": state,
            "file_name": os.path.basename(name)[:180],
            "switch_count": self.switch_count,
            "decoder_errors": self.decoder_errors,
            "preload_skipped": self.preload_skipped,
            "stalled_count": self.stalled_count,
            "peak_memory_mb": round(self.peak_rss / 1048576, 1),
            "cpu_peak_percent": round(self.max_cpu, 1),
            "current_cpu_percent": self.snapshot.cpu,
            "physical_ram_percent": self.snapshot.physical_ram,
        }

    def write_state(self, folder: Path, state: str, name: str = "") -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "streamdeck_state.json"
        partial = folder / "streamdeck_state.tmp"
        partial.write_text(json.dumps(self.summary(state, name), ensure_ascii=False),
                           encoding="utf-8")
        os.replace(partial, path)
        return path
