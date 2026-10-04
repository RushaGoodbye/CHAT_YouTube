from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import asyncssh

from .config import Settings
from .execops import _validate_argv


def _target(settings: Settings, alias: str) -> tuple[str, int]:
    raw = settings.ssh_aliases.get(alias)
    if not raw:
        raise ValueError(f"Unknown SSH alias: {alias}")
    if ":" in raw:
        host, port = raw.rsplit(":", 1)
        return host.strip(), int(port)
    return raw.strip(), 22


async def run_ssh(
    settings: Settings,
    alias: str,
    argv: list[str],
    *,
    timeout_seconds: int = 180,
) -> dict:
    argv = _validate_argv(settings, argv)
    host, port = _target(settings, alias)
    if not settings.ssh_key.is_file():
        raise RuntimeError("SSH private key is not mounted")
    if not settings.ssh_known_hosts.is_file():
        raise RuntimeError("known_hosts is not mounted")

    command = (\n        subprocess.list2cmdline(argv)\n        if alias.casefold() in settings.ssh_windows_aliases\n        else shlex.join(argv)\n    )
    async with asyncssh.connect(
        host,
        port=port,
        username=settings.ssh_user,
        client_keys=[str(settings.ssh_key)],
        known_hosts=str(settings.ssh_known_hosts),
    ) as conn:
        result = await conn.run(
            command,
            check=False,
            timeout=max(1, min(int(timeout_seconds), 900)),
        )
    return {
        "host_alias": alias,
        "exit_code": int(result.exit_status),
        "stdout": str(result.stdout)[-200000:],
        "stderr": str(result.stderr)[-200000:],
    }
