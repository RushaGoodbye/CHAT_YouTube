from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import Settings
from .contours import get_contour


def resolve_contour_path(
    settings: Settings,
    contour_name: str,
    relative: str = "",
) -> Path:
    contour = get_contour(contour_name)
    base = contour.root.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("Path escapes the selected contour") from exc
    return candidate


def list_dir(
    settings: Settings,
    contour_name: str,
    relative: str = "",
) -> list[dict]:
    path = resolve_contour_path(settings, contour_name, relative)
    if not path.is_dir():
        raise ValueError(f"Not a directory: {relative or '.'}")
    out = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
        stat = item.stat()
        out.append({
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
            "size": stat.st_size if item.is_file() else None,
            "mtime_ns": stat.st_mtime_ns,
        })
    return out


def read_text(
    settings: Settings,
    contour_name: str,
    relative: str,
) -> str:
    path = resolve_contour_path(settings, contour_name, relative)
    if not path.is_file():
        raise ValueError(f"Not a file: {relative}")
    size = path.stat().st_size
    if size > settings.max_read_bytes:
        raise ValueError(f"File is {size} bytes; limit is {settings.max_read_bytes}")
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(
    settings: Settings,
    contour_name: str,
    relative: str,
    content: str,
    create_parents: bool = True,
) -> dict:
    raw = content.encode("utf-8")
    if len(raw) > settings.max_write_bytes:
        raise ValueError(
            f"Payload is {len(raw)} bytes; limit is {settings.max_write_bytes}"
        )
    path = resolve_contour_path(settings, contour_name, relative)
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".rgremote.tmp")
    temp.write_bytes(raw)
    os.replace(temp, path)
    return {"path": str(path), "bytes": len(raw), "contour": contour_name}


def make_dir(settings: Settings, contour_name: str, relative: str) -> str:
    path = resolve_contour_path(settings, contour_name, relative)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def copy_path(
    settings: Settings,
    contour_name: str,
    source: str,
    destination: str,
) -> str:
    src = resolve_contour_path(settings, contour_name, source)
    dst = resolve_contour_path(settings, contour_name, destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            raise ValueError("Destination already exists")
        shutil.copytree(src, dst)
    elif src.is_file():
        shutil.copy2(src, dst)
    else:
        raise ValueError("Source does not exist")
    return str(dst)
