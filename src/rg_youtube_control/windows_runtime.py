from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PowerShellResult:
    executable: str
    returncode: int
    stdout: str
    stderr: str


class PowerShellUnavailable(RuntimeError):
    pass


def find_powershell() -> str:
    """Return the best available PowerShell executable.

    PowerShell 7 is preferred. Windows PowerShell 5.1 is the fallback.
    Nothing is installed or downloaded here: RG YouTube Control uses the
    Windows runtime already present on the machine.
    """
    for candidate in ("pwsh.exe", "powershell.exe", "pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise PowerShellUnavailable(
        "PowerShell не знайдено. Встановіть PowerShell 7 або увімкніть Windows PowerShell."
    )


def _hidden_process_options() -> dict:
    """subprocess options which prevent a console window on Windows."""
    options: dict = {}
    if os.name != "nt":
        return options

    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if creationflags:
        options["creationflags"] = creationflags

    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_cls is not None and startf_use_showwindow:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= startf_use_showwindow
        startupinfo.wShowWindow = sw_hide
        options["startupinfo"] = startupinfo
    return options


def run_powershell(
    script: str,
    *,
    timeout: float = 120.0,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> PowerShellResult:
    """Run a PowerShell command invisibly and capture all output.

    This is the only supported PowerShell entry point for the desktop app.
    UI code should never open a terminal window or ask the user to paste
    PowerShell commands for routine application work.
    """
    executable = find_powershell()
    command = [
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "$ProgressPreference='SilentlyContinue'; " + str(script),
    ]

    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_hidden_process_options(),
    )
    result = PowerShellResult(
        executable=executable,
        returncode=int(completed.returncode),
        stdout=(completed.stdout or "").strip(),
        stderr=(completed.stderr or "").strip(),
    )
    if check and result.returncode != 0:
        detail = result.stderr or result.stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"Службова команда Windows завершилась помилкою: {detail}")
    return result


def run_powershell_file(
    path: str | Path,
    args: Iterable[str] = (),
    *,
    timeout: float = 300.0,
    cwd: str | Path | None = None,
    check: bool = True,
) -> PowerShellResult:
    """Run a local .ps1 file through the hidden PowerShell runtime."""
    script_path = Path(path)
    if not script_path.is_file():
        raise FileNotFoundError(script_path)

    def quote(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    arg_text = " ".join(quote(str(item)) for item in args)
    command = f"& {quote(str(script_path))}"
    if arg_text:
        command += " " + arg_text
    return run_powershell(
        command,
        timeout=timeout,
        cwd=cwd or script_path.parent,
        check=check,
    )


def powershell_status() -> dict[str, str | bool]:
    """Small diagnostics payload safe to show in the app."""
    try:
        executable = find_powershell()
    except PowerShellUnavailable as exc:
        return {"available": False, "executable": "", "version": "", "error": str(exc)}

    try:
        result = run_powershell(
            "$PSVersionTable.PSVersion.ToString()",
            timeout=10,
            check=True,
        )
        return {
            "available": True,
            "executable": executable,
            "version": result.stdout.strip(),
            "error": "",
        }
    except Exception as exc:
        return {
            "available": True,
            "executable": executable,
            "version": "",
            "error": str(exc),
        }
