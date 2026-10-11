"""Daily, bounded backups of RG Media Deck settings. Never copies media files."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path


def backup_dir(settings: Path) -> Path:
    return settings.parent / "settings_backups"


def backup_settings_once_daily(settings: Path, day: date | None = None,
                               keep: int = 7) -> Path:
    """Keep the current valid settings as the day's snapshot.

    This is run only after an atomic successful primary write. Settings saves
    on volume-slider changes do NOT copy again if today's backup exists.
    """
    settings = Path(settings)
    day = day or date.today()
    folder = backup_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"settings_{day.isoformat()}.json"
    if not target.exists():
        fd, temp = tempfile.mkstemp(prefix="settings_", suffix=".tmp", dir=folder)
        os.close(fd)
        try:
            shutil.copyfile(settings, temp)
            with open(temp, encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError("Invalid settings data")
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    old = sorted(folder.glob("settings_????-??-??.json"))
    for obsolete in old[:-max(1, keep)]:
        obsolete.unlink(missing_ok=True)
    return target


def recover_settings_from_backup(settings: Path) -> dict | None:
    """Read most recent valid snapshot after primary JSON is corrupt/missing."""
    folder = backup_dir(Path(settings))
    for candidate in sorted(folder.glob("settings_????-??-??.json"), reverse=True):
        try:
            with candidate.open(encoding="utf-8") as file:
                data = json.load(file)
            if (isinstance(data, dict) and
                    isinstance(data.get("roots", []), list) and
                    isinstance(data.get("favorites", []), list)):
                return data
        except (OSError, ValueError, UnicodeError):
            continue
    return None
