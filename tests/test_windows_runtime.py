from __future__ import annotations

import subprocess

import pytest

from rg_youtube_control import windows_runtime


class _Completed:
    returncode = 0
    stdout = "7.5.2\n"
    stderr = ""


def test_find_powershell_prefers_pwsh(monkeypatch):
    def fake_which(name):
        return "C:/Program Files/PowerShell/7/pwsh.exe" if name == "pwsh.exe" else None

    monkeypatch.setattr(windows_runtime.shutil, "which", fake_which)

    assert windows_runtime.find_powershell().lower().endswith("pwsh.exe")


def test_run_powershell_is_noninteractive_and_captures_output(monkeypatch):
    monkeypatch.setattr(
        windows_runtime,
        "find_powershell",
        lambda: "C:/Program Files/PowerShell/7/pwsh.exe",
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = windows_runtime.run_powershell("Write-Output ok")

    assert "-NoProfile" in captured["command"]
    assert "-NonInteractive" in captured["command"]
    assert "-ExecutionPolicy" in captured["command"]
    assert result.stdout == "7.5.2"


def test_run_powershell_raises_clean_error(monkeypatch):
    monkeypatch.setattr(windows_runtime, "find_powershell", lambda: "powershell.exe")

    class Failed:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Failed())

    with pytest.raises(RuntimeError, match="boom"):
        windows_runtime.run_powershell("throw 'boom'")


def test_status_without_powershell(monkeypatch):
    def unavailable():
        raise windows_runtime.PowerShellUnavailable("missing")

    monkeypatch.setattr(windows_runtime, "find_powershell", unavailable)
    status = windows_runtime.powershell_status()

    assert status["available"] is False
    assert status["error"] == "missing"
