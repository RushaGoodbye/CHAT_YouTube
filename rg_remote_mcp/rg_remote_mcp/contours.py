from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class Contour:
    name: str
    root: Path
    allowed_commands: frozenset[str]


def _cmds(env_name: str, fallback: str) -> frozenset[str]:
    import os
    return frozenset(
        item.strip().casefold()
        for item in os.getenv(env_name, fallback).split(",")
        if item.strip()
    )


CONTOURS = {
    "youtube": Contour(
        "youtube",
        settings.roots["youtube"],
        _cmds(
            "RG_REMOTE_YOUTUBE_COMMANDS",
            "python,python3,powershell,git,ls,cat,find,grep,du,df",
        ),
    ),
    "telegram": Contour(
        "telegram",
        settings.roots["telegram"],
        _cmds(
            "RG_REMOTE_TELEGRAM_COMMANDS",
            "python,python3,powershell,git,docker,docker-compose,ls,cat,find,grep,du,df",
        ),
    ),
    "auto_edit": Contour(
        "auto_edit",
        settings.roots["auto_edit"],
        _cmds(
            "RG_REMOTE_AUTO_EDIT_COMMANDS",
            "python,python3,powershell,git,docker,docker-compose,ls,cat,find,grep,du,df",
        ),
    ),
}


def get_contour(name: str) -> Contour:
    key = str(name or "").strip().casefold()
    contour = CONTOURS.get(key)
    if contour is None:
        raise ValueError(f"Unknown contour: {name}")
    return contour
