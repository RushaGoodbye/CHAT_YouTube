"""Validate and stage downloaded ZIP updates before replacing the running EXE.

ZIP never directly writes to the installed app folder. An external PowerShell
helper checks two launches and moves directories atomically after the old
program exits. No install wizard and no registry modifications.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import updater

MAX_ENTRIES = 12000
MAX_UNCOMPRESSED = 3 * 1024 * 1024 * 1024
SCRIPT = "Apply_RG_Media_Deck_Update.ps1"
LAUNCHER = "ОНОВИТИ_RG_Media_Deck.cmd"
PROGRAM_EXE = "RG_Media_Deck/RG_Media_Deck.exe"
MANIFEST = "version.txt"


def validate_members(entries: list[zipfile.ZipInfo]) -> int:
    if not entries or len(entries) > MAX_ENTRIES:
        raise ValueError("Неправильний список файлів у ZIP")
    total = 0
    names = set()
    for info in entries:
        name = info.filename
        if "\\" in name or ":" in name or name.startswith("/"):
            raise ValueError("Недопустимий шлях у ZIP")
        path = PurePosixPath(name)
        if not name or any(part in ("", ".", "..") for part in path.parts):
            raise ValueError("ZIP містить небезпечний шлях")
        if path.parts[0] != "RG_Media_Deck" and name not in (
                SCRIPT, LAUNCHER, MANIFEST):
            raise ValueError("ZIP містить сторонні файли")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("ZIP містить символічні посилання")
        if name in names:
            raise ValueError("Повторений шлях у ZIP")
        names.add(name)
        total += info.file_size
        if total > MAX_UNCOMPRESSED:
            raise ValueError("ZIP перевищує дозволений розмір")
    if not {SCRIPT, LAUNCHER, PROGRAM_EXE, MANIFEST}.issubset(names):
        raise ValueError("Немає файлів RG Media Deck або програми оновлення")
    return total


def verify_zip(archive: Path, sha256: str, expected_version: str) -> bool:
    archive = Path(archive)
    updater.version_tuple(expected_version)
    if not archive.is_file() or not updater.verify_checksum(archive, sha256):
        raise ValueError("SHA256 ZIP не збігається")
    if not zipfile.is_zipfile(archive):
        raise ValueError("Файл не є ZIP")
    with zipfile.ZipFile(archive) as doc:
        validate_members(doc.infolist())
        if doc.read(MANIFEST).decode("utf-8-sig").strip() != expected_version:
            raise ValueError("Неправильна версія оновлення")
        if doc.testzip() is not None:
            raise ValueError("Архів ZIP пошкоджений")
    return True


def stage_zip(archive: Path, sha256: str, version: str) -> Path:
    verify_zip(archive, sha256, version)
    directory = Path(tempfile.mkdtemp(prefix=f"rg_zip_{version}_",
                                       dir=updater.update_folder()))
    try:
        with zipfile.ZipFile(archive) as doc:
            for info in doc.infolist():
                # Members have already been validated. Never use extractall()
                # on an untrusted archive or follow a filesystem symlink.
                destination = directory.joinpath(*PurePosixPath(info.filename).parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with doc.open(info, "r") as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
        if not (directory / PROGRAM_EXE).is_file():
            raise ValueError("Немає EXE для оновлення")
        return directory
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def prepare_zip_command(archive: Path, sha256: str, version: str) -> list[str]:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("ZIP-оновлення застосовується лише у Windows-збірці")
    archive = Path(archive).resolve()
    if archive.parent != updater.update_folder().resolve():
        raise ValueError("ZIP має бути завантажено через RG Media Deck")
    directory = stage_zip(archive, sha256, version)
    script = directory / SCRIPT
    return [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-InstallDir", str(Path(sys.executable).resolve().parent),
        "-NonInteractive", "-WaitPid", str(os.getpid()),
    ]
