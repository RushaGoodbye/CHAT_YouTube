"""Verified previous-installer preservation + supervised Windows update rollback.

Before updating, download the currently installed release from GitHub and
SHA256-verify it. An external PowerShell helper (outside Program Files) waits
for RG Media Deck to exit, installs the new version, checks its --selftest and
automatically restores the previous verified installer if health fails.
No overwrite/rollback occurs during an active stream.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import updater
from library import settings_path

WATCHDOG_SCRIPT = r'''
param(
 [Parameter(Mandatory=$true)][string]$NewInstaller,
 [Parameter(Mandatory=$true)][string]$NewSha,
 [Parameter(Mandatory=$true)][string]$OldInstaller,
 [Parameter(Mandatory=$true)][string]$OldSha,
 [Parameter(Mandatory=$true)][string]$ApplicationExe,
 [Parameter(Mandatory=$true)][string]$Snapshot,
 [Parameter(Mandatory=$true)][int]$OldPid,
 [Parameter(Mandatory=$true)][string]$ResultFile
)
$ErrorActionPreference = 'Stop'
function Verified([string]$file, [string]$sha) {
 return ((Test-Path -LiteralPath $file -PathType Leaf) -and
         ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -eq $sha.ToLowerInvariant()))
}
function LogResult([string]$message) {
 Set-Content -LiteralPath $ResultFile -Value $message -Encoding UTF8
}
function Install([string]$file) {
 $arguments = @('/SILENT','/SUPPRESSMSGBOXES','/NORESTART','/CLOSEAPPLICATIONS','/NOAUTOSTART')
 $proc = Start-Process -FilePath $file -ArgumentList $arguments -Wait -PassThru
 return $proc.ExitCode
}
try {
  # Never patch a running player: wait for old process to fully exit.
  for ($i = 0; $i -lt 120; $i++) {
    if (-not (Get-Process -Id $OldPid -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
  }
  if (Get-Process -Id $OldPid -ErrorAction SilentlyContinue) {
    LogResult 'SKIPPED: old app still running; no installer executed'
    exit 2
  }
  if (-not (Verified $NewInstaller $NewSha) -or -not (Verified $OldInstaller $OldSha)) {
    LogResult 'BLOCKED: installer SHA256 mismatch; unchanged version'
    exit 3
  }
  $status = Install $NewInstaller
  $healthy = $false
  if ($status -eq 0 -and (Test-Path -LiteralPath $ApplicationExe -PathType Leaf)) {
    try {
      $check = Start-Process -FilePath $ApplicationExe -ArgumentList '--selftest' -Wait -PassThru
      $healthy = ($check.ExitCode -eq 0)
    } catch {
      $healthy = $false
    }
  }
  if ($healthy) {
    LogResult 'PASS: new version installed; EXE selftest successful'
    Start-Process -FilePath $ApplicationExe
    exit 0
  }
  if (-not (Verified $OldInstaller $OldSha)) {
    LogResult 'FAILED: new version unhealthy; previous installer corrupted; restore blocked'
    exit 4
  }
  $rollbackResult = Install $OldInstaller
  if ($rollbackResult -ne 0) {
    LogResult "FAILED: rollback installer returned $rollbackResult"
    exit 5
  }
  if (Test-Path -LiteralPath $Snapshot -PathType Leaf) {
    Copy-Item -LiteralPath $Snapshot -Destination (Join-Path (Split-Path -Parent $Snapshot) '..\..\settings.json') -Force
  }
  LogResult 'ROLLBACK: previous verified installer restored after failed new-version selftest'
  if (Test-Path -LiteralPath $ApplicationExe -PathType Leaf) {
    Start-Process -FilePath $ApplicationExe
  }
  exit 10
} catch {
  LogResult ('FAILED: ' + $_.Exception.Message)
  exit 99
}
'''


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def storage() -> Path:
    dest = settings_path().parent / "updates" / "rollback"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def previous_release(version: str) -> dict:
    updater.version_tuple(version)
    with updater._request(f'https://api.github.com/repos/{updater.REPO}/releases/tags/rg-media-deck-v{version}') as response:
        release = json.loads(response.read(2_000_000).decode("utf-8"))
    if release.get("tag_name") != f"rg-media-deck-v{version}":
        raise ValueError("Неправильна версія резервного релізу")
    links = updater._asset_urls(release)
    if set(links) != {updater.INSTALLER_NAME, updater.CHECKSUM_NAME}:
        raise ValueError("Немає перевіреного попереднього інсталятора")
    return {"version": version, "installer_url": links[updater.INSTALLER_NAME],
            "sha_url": links[updater.CHECKSUM_NAME]}


def stage_verified_previous(current_version: str, progress=None, cancelled=None) -> tuple[Path, str]:
    """Fail closed if the previous version cannot be preserved."""
    release = previous_release(current_version)
    expected = updater.fetch_checksum(release["sha_url"])
    dest = storage() / f"RG_Media_Deck_Previous_{current_version}.exe"
    if dest.is_file() and updater.verify_checksum(dest, expected):
        save_rollback_manifest(current_version, dest, expected)
        return dest, expected
    if cancelled is not None and cancelled():
        raise InterruptedError("Скасовано")
    downloaded, digest = updater.download_update(release, progress, cancelled)
    if digest != expected or not updater.verify_checksum(downloaded, expected):
        raise ValueError("SHA256 попередньої версії не підтверджено")
    shutil.copy2(downloaded, dest)
    if not updater.verify_checksum(dest, expected):
        dest.unlink(missing_ok=True)
        raise ValueError("SHA256 резервного інсталятора не збігається")
    save_rollback_manifest(current_version, dest, expected)
    return dest, expected


def save_rollback_manifest(version: str, path: Path, sha: str) -> None:
    updater.version_tuple(version)
    # Only persist a verified installer in our private rollback directory.
    if Path(path).resolve().parent != storage().resolve() or not updater.verify_checksum(path, sha):
        raise ValueError("Невірний інсталятор відкату")
    body = {"version": version, "file": Path(path).name, "sha256": sha.lower()}
    temporary = storage() / "rollback_manifest.tmp"
    temporary.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, storage() / "rollback_manifest.json")


def verified_saved_rollback() -> tuple[str, Path, str] | None:
    try:
        info = json.loads((storage() / "rollback_manifest.json").read_text(encoding="utf-8"))
        version = info["version"]
        updater.version_tuple(version)
        expected_file = f"RG_Media_Deck_Previous_{version}.exe"
        if info.get("file") != expected_file:
            return None
        path = storage() / expected_file
        sha = info["sha256"]
        if not updater.verify_checksum(path, sha):
            return None
        return version, path, sha
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prepare_supervised_update(new_installer: Path, new_sha: str, new_version: str,
                              old_installer: Path, old_sha: str, old_version: str,
                              application_exe: Path | None = None) -> list[str]:
    """Create a supervised updater script and settings snapshot on local disk."""
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise RuntimeError("Інсталятор оновлення доступний тільки у Windows EXE")
    updater.version_tuple(new_version)
    updater.version_tuple(old_version)
    if updater.version_tuple(new_version) <= updater.version_tuple(old_version):
        raise ValueError("Оновлення має бути новішим")
    # Pin current release to its signed source and verify BOTH installers.
    new_installer = Path(new_installer).resolve()
    old_installer = Path(old_installer).resolve()
    if new_installer.parent != updater.update_folder().resolve():
        raise ValueError("Неочікувана папка нового інсталятора")
    if old_installer.parent != storage().resolve():
        raise ValueError("Неочікувана папка попередньої версії")
    if not updater.verify_checksum(new_installer, new_sha) or not updater.verify_checksum(old_installer, old_sha):
        raise ValueError("Пошкоджений інсталятор. Оновлення скасовано.")
    root = storage()
    snapshot = root / f"settings_before_{new_version}.json"
    current_settings = settings_path()
    if current_settings.exists():
        shutil.copy2(current_settings, snapshot)
    else:
        snapshot.write_text("{}", encoding="utf-8")
    result_file = root / "update_status.txt"
    script = root / "run_supervised_update.ps1"
    script.write_text(WATCHDOG_SCRIPT, encoding="utf-8")
    exe = Path(application_exe or sys.executable).resolve()
    # No shell interpolation: subprocess passes each path as its own argument.
    return [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-NewInstaller", str(new_installer), "-NewSha", new_sha,
        "-OldInstaller", str(old_installer), "-OldSha", old_sha,
        "-ApplicationExe", str(exe), "-Snapshot", str(snapshot),
        "-OldPid", str(os.getpid()), "-ResultFile", str(result_file),
    ]


def rollback_status() -> str:
    path = storage() / "update_status.txt"
    try:
        return path.read_text(encoding="utf-8-sig")[:500]
    except OSError:
        return "Оновлення ще не запускалося"
