"""Media discovery and settings. No GUI dependency; safe to test independently."""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

VIDEO_EXTS = frozenset({
    '.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.wmv', '.mpeg',
    '.mpg', '.ts', '.m2ts', '.mts', '.flv', '.vob', '.3gp', '.mp3',
    '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma', '.opus',
})
IMAGE_EXTS = frozenset({
    '.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.tif', '.tiff',
})
SPEED_PRESETS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS
SKIP_DIRS = frozenset({'$recycle.bin', 'system volume information', '.git', '__pycache__'})


@dataclass(frozen=True)
class MediaItem:
    path: str
    name: str
    kind: str
    size: int

    @property
    def folder(self) -> str:
        return str(Path(self.path).parent)


def display_media_name(name: str) -> str:
    """Human-readable filename without a recognized media extension."""
    base, ext = os.path.splitext(name)
    return base if base and ext.casefold() in MEDIA_EXTS else name

def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(path))))


def scan_media(roots: Iterable[str], stop: Callable[[], bool] | None = None,
               progress: Callable[[int], None] | None = None) -> list[MediaItem]:
    """Iterative walk without following folder symlinks/junctions."""
    found: list[MediaItem] = []
    seen_dirs: set[str] = set()
    seen_files: set[str] = set()
    stack = [str(x) for x in roots if x]
    while stack:
        if stop and stop():
            break
        folder = stack.pop()
        canonical = normalize_path(folder)
        if canonical in seen_dirs:
            continue
        seen_dirs.add(canonical)
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if stop and stop():
                        return found
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.casefold() not in SKIP_DIRS:
                                stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        suffix = os.path.splitext(entry.name)[1].casefold()
                        if suffix not in MEDIA_EXTS:
                            continue
                        file_key = normalize_path(entry.path)
                        if file_key in seen_files:
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        seen_files.add(file_key)
                        found.append(MediaItem(
                            entry.path, entry.name,
                            'photo' if suffix in IMAGE_EXTS else 'video',
                            stat.st_size,
                        ))
                        if progress and len(found) % 500 == 0:
                            progress(len(found))
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError):
            continue
    found.sort(key=lambda x: (x.name.casefold(), x.path.casefold()))
    return found


def filter_media(items: Iterable[MediaItem], query: str, kind: str = 'all',
                 favorites: set[str] | None = None, favorites_only: bool = False) -> list[MediaItem]:
    words = query.casefold().split()
    favorites = favorites or set()
    matches = (
        item for item in items
        if (kind == 'all' or item.kind == kind)
        and (not favorites_only or normalize_path(item.path) in favorites)
        and all(w in item.name.casefold() for w in words)
    )
    return sorted(matches, key=lambda item: (
        normalize_path(item.path) not in favorites,
        item.name.casefold(), item.path.casefold(),
    ))


def should_stop_current_on_selection(current: MediaItem | None, selected: MediaItem | None,
                                     enabled: bool) -> bool:
    """Stop playing live video/audio on deliberate selection of a different file."""
    return bool(enabled and current is not None and selected is not None
                and current.kind == 'video' and current.path != selected.path)


def settings_path() -> Path:
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_CONFIG_HOME')
    if not base:
        base = str(Path.home() / '.config')
    return Path(base) / 'RGMediaDeck' / 'settings.json'


def normalize_playback_rate(value) -> float:
    """Snap legacy or malformed user settings to a safe, supported preset."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 1.0
    return min(SPEED_PRESETS, key=lambda speed: abs(speed - value))


def load_settings(path: Path | None = None) -> dict:
    p = path or settings_path()
    defaults = {'roots': [], 'favorites': [], 'volume': 80, 'muted': False, 'playback_rate': 1.0, 'auto_crop': True}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return defaults
        roots = data.get('roots', [])
        favs = data.get('favorites', [])
        if not isinstance(roots, list) or not isinstance(favs, list):
            return defaults
        volume = data.get('volume', 80)
        if not isinstance(volume, (int, float)):
            volume = 80
        return {
            'roots': [x for x in roots if isinstance(x, str)],
            'favorites': [x for x in favs if isinstance(x, str)],
            'volume': max(0, min(100, int(volume))),
            'muted': data.get('muted', False) is True,
            'playback_rate': normalize_playback_rate(data.get('playback_rate', 1.0)),
            'auto_crop': data.get('auto_crop', True) is not False,
        }
    except (ValueError, OSError, UnicodeError):
        return defaults


def save_settings(data: dict, path: Path | None = None) -> None:
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='settings_', suffix='.tmp', dir=p.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
