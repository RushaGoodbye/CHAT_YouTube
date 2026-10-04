from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings
from .fsops import resolve_path


def _validate_argv(settings: Settings, argv: list[str]) -> list[str]:
    if not argv:
        raise ValueError("argv must not be empty")
    command = Path(str(argv[0])).name.casefold()
    if command not in settings.allowed_commands:
        raise ValueError(f"Command is not allow-listed: {command}")
    return [str(item) for item in argv]


async def run_local(
    settings: Settings,
    argv: list[str],
    *,
    cwd_root: str | None = None,
    cwd_relative: str = "",
    timeout_seconds: int = 120,
) -> dict:
    argv = _validate_argv(settings, argv)
    cwd = None
    if cwd_root:
        cwd = str(resolve_path(settings, cwd_root, cwd_relative))
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=max(1, min(int(timeout_seconds), 900)),
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError("Command timed out")
    return {
        "exit_code": int(proc.returncode or 0),
        "stdout": stdout.decode("utf-8", errors="replace")[-200000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-200000:],
    }
