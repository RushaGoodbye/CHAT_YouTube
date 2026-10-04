from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(raw: str) -> frozenset[str]:
    return frozenset(
        item.strip().casefold()
        for item in (raw or "").split(",")
        if item.strip()
    )


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    roots: dict[str, Path]
    ssh_aliases: dict[str, str]
    ssh_windows_aliases: frozenset[str]
    ssh_user: str
    ssh_key: Path
    ssh_known_hosts: Path
    max_read_bytes: int
    max_write_bytes: int

    @classmethod
    def from_env(cls) -> "Settings":
        roots = {
            "youtube": Path(
                os.getenv("RG_REMOTE_YOUTUBE_ROOT", "/contours/youtube")
            ).resolve(),
            "telegram": Path(
                os.getenv("RG_REMOTE_TELEGRAM_ROOT", "/contours/telegram")
            ).resolve(),
            "auto_edit": Path(
                os.getenv("RG_REMOTE_AUTO_EDIT_ROOT", "/contours/auto_edit")
            ).resolve(),
        }
        return cls(
            host=os.getenv("RG_REMOTE_HOST", "0.0.0.0"),
            port=int(os.getenv("RG_REMOTE_PORT", "8765")),
            roots=roots,
            ssh_aliases={"alexpc": os.getenv("RG_REMOTE_ALEXPC", "alexpc:22")},
            ssh_windows_aliases=_csv(
                os.getenv("RG_REMOTE_SSH_WINDOWS_ALIASES", "alexpc")
            ),
            ssh_user=os.getenv("RG_REMOTE_SSH_USER", "rgremote"),
            ssh_key=Path(
                os.getenv("RG_REMOTE_SSH_KEY", "/run/secrets/alexpc_ssh_key")
            ),
            ssh_known_hosts=Path(
                os.getenv(
                    "RG_REMOTE_SSH_KNOWN_HOSTS",
                    "/run/secrets/known_hosts",
                )
            ),
            max_read_bytes=int(
                os.getenv("RG_REMOTE_MAX_READ_BYTES", str(1024 * 1024))
            ),
            max_write_bytes=int(
                os.getenv("RG_REMOTE_MAX_WRITE_BYTES", str(1024 * 1024))
            ),
        )


settings = Settings.from_env()
