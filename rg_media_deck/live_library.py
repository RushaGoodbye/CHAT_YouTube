"""Windows native event watcher and conservative file identity matching.

Same-volume renames preserve metadata by explicit moved events or stable
(st_dev, st_ino) identity. Never guess cross-volume moves from filenames.
Missing/offline roots are kept in the library without unlinking metadata.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from PySide6.QtCore import QObject, Signal

from library import MediaItem, MEDIA_EXTS, IMAGE_EXTS, normalize_path


def unavailable_roots(roots: list[str]) -> list[str]:
    return [root for root in roots if not os.path.isdir(root)]


def keep_offline_entries(scanned: list[MediaItem], previous: list[MediaItem],
                         roots: list[str]) -> list[MediaItem]:
    offline = [normalize_path(root) for root in unavailable_roots(roots)]
    if not offline:
        return scanned
    catalog = {normalize_path(item.path): item for item in scanned}
    for item in previous:
        name = normalize_path(item.path)
        for root in offline:
            try:
                if os.path.commonpath((name, root)) == root:
                    catalog.setdefault(name, item)
            except ValueError:
                continue
    return sorted(catalog.values(), key=lambda x: (x.name.casefold(), x.path.casefold()))


def changed_files(items: list[MediaItem], paths: set[str], roots: list[str]) -> list[MediaItem]:
    """Stat only named files; never remove a record while its disk is offline."""
    catalog = {normalize_path(x.path): x for x in items}
    allowed = [normalize_path(p) for p in roots if os.path.isdir(p)]
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
        if not belongs(key) or Path(path).suffix.casefold() not in MEDIA_EXTS:
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
            continue
    return sorted(catalog.values(), key=lambda x: (x.name.casefold(), x.path.casefold()))


def relocated_path(old_file: str, old_dir: str, new_dir: str) -> str | None:
    """Map all media paths for a moved directory without changing files."""
    try:
        relative = os.path.relpath(old_file, old_dir)
    except ValueError:
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    return os.path.normpath(os.path.join(new_dir, relative))


class FileIdentityIndex:
    """Low-cost (volume, file-id) lookup for moves captured as create+delete."""
    def __init__(self):
        self.by_id: dict[tuple[int, int], str] = {}

    @staticmethod
    def identity(path: str) -> tuple[int, int] | None:
        try:
            stat = os.stat(path)
        except (OSError, ValueError):
            return None
        if not os.path.isfile(path) or stat.st_ino == 0:
            return None
        return (stat.st_dev, stat.st_ino)

    def seed(self, items: list[MediaItem]) -> None:
        self.by_id.clear()
        for item in items:
            key = self.identity(item.path)
            if key is not None:
                self.by_id[key] = item.path

    def match_new_file(self, path: str) -> str | None:
        key = self.identity(path)
        old = self.by_id.get(key) if key is not None else None
        if old and normalize_path(old) != normalize_path(path) and not os.path.exists(old):
            self.by_id[key] = path
            return old
        return None

    def update_moved(self, src: str, dst: str):
        key = self.identity(dst)
        if key is not None:
            self.by_id[key] = dst


class _ChangeBridge(QObject):
    changed = Signal(str, bool)
    moved = Signal(str, str, bool)


class _Handler(FileSystemEventHandler):
    def __init__(self, bridge: _ChangeBridge):
        super().__init__()
        self.bridge = bridge

    def on_any_event(self, event):
        if event.event_type in ("opened", "closed", "closed_no_write", "moved"):
            return
        self.bridge.changed.emit(event.src_path, bool(event.is_directory))

    def on_moved(self, event):
        self.bridge.moved.emit(event.src_path, event.dest_path,
                               bool(event.is_directory))


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
                errors.append(f"Немає доступу до папки (метадані збережені): {folder}")
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
