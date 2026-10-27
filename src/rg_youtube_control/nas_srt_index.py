"""Non-blocking NAS SRT directory index for the optimization table.

Never run a network filesystem listing or per-file stat in the Qt GUI thread.
The scan reads directory entry names only and does not alter any files.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def scan_nas_srt_ids(folder: Path) -> set[str] | None:
    """Return exact YouTube IDs in a NAS folder, or None when unavailable.

    A failed network lookup must not be interpreted as 'no transcripts'.
    """
    video_ids: set[str] = set()
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                name = entry.name
                if not name.lower().endswith(".srt"):
                    continue
                video_id = name[:-4]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    video_ids.add(video_id)
    except OSError:
        return None
    return video_ids
