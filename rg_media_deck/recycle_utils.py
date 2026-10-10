"""Safe Windows Recycle Bin path handling for media files.

Send2Trash uses the Windows shell and may reject mixed separator paths when its
internal long-path prefix is added. Normalize before handing paths to the shell.
Never fall back to permanent deletion.
"""
from __future__ import annotations

import ntpath
import os


def normalize_recycle_path(path: str | os.PathLike[str]) -> str:
    """Return a fully qualified Windows path with consistent backslashes.

    Preserve Unicode, spaces, non-Latin folder names and UNC shares. Reject
    relative paths, device paths and roots. Never use this to rename a file.
    """
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ValueError("Неприпустимий шлях до файлу.")

    normalized = ntpath.normpath(raw)
    if normalized.startswith("\\\\.\\"):
        raise ValueError("Шлях пристрою не підтримується для видалення.")

    # The recycle-shell API expects a conventional DOS/UNC path. Windows
    # extended-length prefixes are an implementation detail of Send2Trash.
    if normalized.startswith("\\\\?\\UNC\\"):
        normalized = "\\\\" + normalized[8:]
    elif normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    normalized = ntpath.normpath(normalized)

    drive, remainder = ntpath.splitdrive(normalized)
    if not ntpath.isabs(normalized) or not drive or not remainder or remainder == "\\":
        raise ValueError("Потрібен абсолютний шлях до конкретного файлу.")
    if len(drive) == 2 and drive[1] == ":" and not remainder.startswith("\\"):
        raise ValueError("Відносний шлях диска не підтримується.")
    return normalized
