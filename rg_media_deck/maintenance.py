"""Local diagnostics and bounded cache maintenance for RG Media Deck.

No background uploads or reading source media. User explicitly chooses whether
to create diagnostics. Cache only removes files within private thumbnail folder.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from library import settings_path
from settings_safety import backup_dir, recover_settings_from_backup


def clean_thumbnail_cache(folder: Path, max_bytes: int = 512 * 1024 * 1024,
                          max_files: int = 10000) -> tuple[int, int]:
    folder = Path(folder)
    if max_bytes <= 0 or max_files <= 0:
        raise ValueError("Cache limits must be positive")
    if not folder.is_dir():
        return 0, 0
    entries = []
    for path in folder.iterdir():
        if path.suffix.lower() != '.png' or path.is_symlink() or not path.is_file():
            continue
        try:
            stat = path.stat()
            entries.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    entries.sort(reverse=True)  # newest files first
    retained, size = 0, 0
    removed, freed = 0, 0
    for _, count, path in entries:
        if retained < max_files and size + count <= max_bytes:
            retained += 1
            size += count
        else:
            try:
                path.unlink()
                removed += 1
                freed += count
            except OSError:
                pass
    return removed, freed


def write_diagnostics(folder: Path | None = None, *, version: str = 'unknown',
                      file_count: int = 0) -> Path:
    root = Path(folder) if folder else settings_path().parent
    root.mkdir(parents=True, exist_ok=True)
    output = root / f'RG_Media_Deck_Diagnostics_{datetime.now():%Y%m%d_%H%M%S}.zip'
    summary = {
        'version': version,
        'utc_time': datetime.now(timezone.utc).isoformat(),
        'file_count': max(0, file_count),
        'settings_file_present': (root / 'settings.json').is_file(),
        'settings_backup_count': len(list(backup_dir(root / 'settings.json').glob('settings_*.json'))),
        'thumbnail_cache_files': sum(
            1 for p in (root / 'thumbnails').glob('*.png')) if (root / 'thumbnails').is_dir() else 0,
    }
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('system_summary.json', json.dumps(summary, ensure_ascii=False, indent=2))
        log = root / 'app.log'
        if log.is_file():
            # Logs may contain original file paths; bundle stays local until
            # user explicitly decides to share it.
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size - 100_000))
                archive.writestr('app.log', stream.read())
    return output


def restore_latest_backup(settings: Path | None = None) -> bool:
    settings = Path(settings) if settings else settings_path()
    found = recover_settings_from_backup(settings)
    if found is None:
        return False
    from library import save_settings
    # Creates current safety copy using normal atomic save.
    save_settings(found, settings)
    return True
