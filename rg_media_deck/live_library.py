"""Recursive Windows folder watcher and incremental updates; never reads video bytes.

Uses watchdog's native Windows ReadDirectoryChangesW (not frequent full scans).
Directories trigger a background rescan; ordinary file updates update the index.
"""
from __future__ import annotations
import os
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from PySide6.QtCore import QObject, Signal

from library import MediaItem, MEDIA_EXTS, IMAGE_EXTS, normalize_path


def changed_files(items: list[MediaItem], paths: set[str], roots: list[str]) -> list[MediaItem]:
    """Stat only named changed files and leave all other entries untouched."""
    catalog = {normalize_path(x.path): x for x in items}
    allowed = [normalize_path(p) for p in roots]

    def belongs(path: str) -> bool:
        for root in allowed:
            try:
                if os.path.commonpath((path, root)) == root:
                    return True
            except ValueError:
                continue
        return False

    for path in paths:
        key = normalize_path(path)
        if not belongs(key):
            continue
        if Path(path).suffix.casefold() not in MEDIA_EXTS:
            continue
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                catalog.pop(key, None)
                continue
            size = os.stat(path).st_size
            catalog[key] = MediaItem(path, os.path.basename(path),
                                     "photo" if Path(path).suffix.casefold() in IMAGE_EXTS else "video",
                                     size)
        except (PermissionError, OSError):
            # Keep last-known record until next event or rescan.
            continue
    return sorted(catalog.values(), key=lambda x: (x.name.casefold(), x.path.casefold()))


class _ChangeBridge(QObject):
    changed = Signal(str, bool)


class _Handler(FileSystemEventHandler):
    def __init__(self, bridge: _ChangeBridge):
        super().__init__()
        self.bridge = bridge

    def on_any_event(self, event):
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return
        self.bridge.changed.emit(event.src_path, bool(event.is_directory))
        new_path = getattr(event, "dest_path", None)
        if new_path:
            self.bridge.changed.emit(new_path, bool(event.is_directory))


class RecursiveMediaWatcher:
    def __init__(self):
        self.bridge = _ChangeBridge()
        self.observer = None

    def start(self, roots: list[str]) -> list[str]:
        self.stop()
        observer = Observer(timeout=1)
        errors = []
        added = 0
        handler = _Handler(self.bridge)
        for folder in roots:
            if not os.path.isdir(folder):
                errors.append(f"Папку не знайдено: {folder}")
                continue
            try:
                observer.schedule(handler, folder, recursive=True)
                added += 1
            except (PermissionError, OSError) as exc:
                errors.append(str(exc))
        if added:
            observer.daemon = True
            observer.start()
            self.observer = observer
        return errors

    def stop(self):
        observer = self.observer
        self.observer = None
        if observer:
            observer.stop()
            observer.join(timeout=2)
