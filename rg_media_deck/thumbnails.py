"""On-demand, disk-cached thumbnails. Never touches live player/audio.

Runs thumbnail decoding in a QThread only after the user hovers a media row.
Video frames use the bundled ffmpeg executable in a silent, timeout-limited
subprocess; photo thumbnails use Qt's image reader without loading full photos.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QSize
from PySide6.QtGui import QImageReader

from library import settings_path

THUMB_SIZE = QSize(260, 180)


def thumbnail_path(source: str) -> Path:
    stat = os.stat(source)
    signature = "\0".join((os.path.normcase(os.path.normpath(os.path.abspath(source))),
                              str(stat.st_size), str(stat.st_mtime_ns)))
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return settings_path().parent / "thumbnails" / (digest + ".png")


def make_thumbnail(source: str, kind: str, *, ffmpeg: str | None = None) -> Path | None:
    """Return cached PNG or None; fails closed on missing/corrupt input."""
    try:
        source = os.path.normpath(source)
        dest = thumbnail_path(source)
        if dest.is_file() and 0 < dest.stat().st_size < 2_000_000:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".partial.png")
        try:
            if kind == "photo":
                reader = QImageReader(source)
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    size.scale(THUMB_SIZE, 1)  # Keep aspect ratio
                    reader.setScaledSize(size)
                image = reader.read()
                if image.isNull() or not image.save(str(tmp), "PNG"):
                    return None
            else:
                if not ffmpeg:
                    try:
                        import imageio_ffmpeg
                        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
                    except (ImportError, RuntimeError, OSError):
                        return None
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                       "-ss", "00:00:00.5", "-i", source, "-frames:v", "1",
                       "-vf", "scale=260:180:force_original_aspect_ratio=decrease",
                       "-an", "-y", str(tmp)]
                outcome = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, timeout=8,
                                         creationflags=flags, check=False)
                if outcome.returncode != 0 or not tmp.is_file():
                    return None
            if tmp.stat().st_size > 2_000_000 or tmp.stat().st_size < 10:
                return None
            os.replace(tmp, dest)
            return dest
        finally:
            if tmp.exists():
                tmp.unlink()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


class ThumbnailThread(QThread):
    ready = Signal(str, str)

    def __init__(self, source: str, kind: str, parent=None):
        super().__init__(parent)
        self.source = source
        self.kind = kind

    def run(self):
        result = make_thumbnail(self.source, self.kind)
        self.ready.emit(self.source, str(result) if result else "")
