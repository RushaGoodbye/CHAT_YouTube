from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _pairs(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and value:
            result[key] = value
    return result


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
    allowed_commands: frozenset[str]
    ssh_aliases: dict[str, str]
    ssh_user: str
    ssh_key: Path
    ssh_known_hosts: Path
    max_read_bytes: int
    max_write_bytes: int

    @classmethod
    def from_env(cls) -> "Settings":
        roots = {
            alias: Path(path).expanduser().resolve()
            for alias, path in _pairs(
                os.getenv(
                    "RG_REMOTE_ROOTS",
                    "/data/youtube=/mnt/youtube;/data/auto_edit=/mnt/auto_edit",
                )
            ).items()
        }
        aliases = _pairs(os.getenv("RG_REMOTE_SSH_ALIASES", "alexpc=alexpc:22"))
        return cls(
            host=os.getenv("RG_REMOTE_HOST", "0.0.0.0"),
            port=int(os.getenv("RG_REMOTE_PORT", "8765")),
            roots=roots,
            allowed_commands=_csv(
                os.getenv(
                    "RG_REMOTE_ALLOWED_COMMANDS",
                    "python,python3,git,ls,cat,find,grep,du,df",
                )
            ),
            ssh_aliases=aliases,
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
