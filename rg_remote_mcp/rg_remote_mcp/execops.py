from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings
from .contours import get_contour
from .fsops import resolve_contour_path


def _validate_argv(contour_name: str, argv: list[str]) -> list[str]:
    if not argv:
        raise ValueError("argv must not be empty")
    contour = get_contour(contour_name)
    command = Path(str(argv[0])).name.casefold()
    if command not in contour.allowed_commands:
        raise ValueError(
            f"Command is not allow-listed in contour {contour_name}: {command}"
        )
    return [str(item) for item in argv]


async def run_local(
    settings: Settings,
    contour_name: str,
    argv: list[str],
    *,
    cwd_relative: str = "",
    timeout_seconds: int = 120,
) -> dict:
    argv = _validate_argv(contour_name, argv)
    cwd = str(resolve_contour_path(settings, contour_name, cwd_relative))
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
        "contour": contour_name,
        "exit_code": int(proc.returncode or 0),
        "stdout": stdout.decode("utf-8", errors="replace")[-200000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-200000:],
    }
