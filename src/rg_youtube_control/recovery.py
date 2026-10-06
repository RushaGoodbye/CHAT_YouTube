from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .config import APP_NAME, DEFAULT_NAS_UPDATES_PATH

REPO = "RushaGoodbye/CHAT_YouTube"
USER_AGENT = "RG-YouTube-Control-Recovery"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as response, path.open("wb") as fh:
        shutil.copyfileobj(response, fh, length=1024 * 1024)


def _installer_name(version: str) -> str:
    return f"RG_YouTube_Control_Setup_{version}.exe"


def _installer_url(version: str) -> str:
    name = _installer_name(version)
    return f"https://github.com/{REPO}/releases/download/v{version}/{name}"


def _backup_database(conn: sqlite3.Connection, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(target)
    try:
        conn.backup(destination)
    finally:
        destination.close()


def create_recovery_backup(
    *,
    conn: sqlite3.Connection,
    data_dir: Path,
    backup_root: Path,
    version: str,
    include_installer: bool = True,
    label: str = "RG_YOUTUBE_CONTROL",
) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_label = "".join(
        ch if ch.isalnum() or ch in {"_", "-"} else "_"
        for ch in str(label or "RG_YOUTUBE_CONTROL")
    )
    folder = backup_root / f"{safe_label}_{version}_{stamp}"
    folder.mkdir(parents=True, exist_ok=False)

    database_copy = folder / "rg_youtube_control.db"
    _backup_database(conn, database_copy)

    copied_files: list[str] = [database_copy.name]
    for source in data_dir.iterdir() if data_dir.exists() else []:
        if source.name in {
            "rg_youtube_control.db",
            "rg_youtube_control.db-wal",
            "rg_youtube_control.db-shm",
            "updates",
        }:
            continue
        destination = folder / "app_data" / source.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            continue
        copied_files.append(str(destination.relative_to(folder)))

    installer_name = _installer_name(version)
    installer_target = folder / installer_name
    installer_saved = False
    installer_error = ""
    if include_installer:
        cached = data_dir / "updates" / installer_name
        nas_installer = Path(DEFAULT_NAS_UPDATES_PATH) / installer_name
        try:
            if cached.is_file():
                shutil.copy2(cached, installer_target)
            elif nas_installer.is_file():
                shutil.copy2(nas_installer, installer_target)
            else:
                _download(_installer_url(version), installer_target)
            installer_saved = installer_target.is_file()
            if installer_saved:
                copied_files.append(installer_name)
                (folder / f"{installer_name}.sha256").write_text(
                    f"{_sha256(installer_target)}  {installer_name}\n",
                    encoding="utf-8",
                )
                copied_files.append(f"{installer_name}.sha256")
        except Exception as exc:
            installer_error = str(exc)
            installer_target.unlink(missing_ok=True)
    else:
        installer_error = "installer intentionally omitted from automatic backup"

    manifest = {
        "format": 1,
        "app": APP_NAME,
        "version": version,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": "rg_youtube_control.db",
        "installer_saved": installer_saved,
        "installer_error": installer_error,
        "youtube_tokens_saved": False,
        "note": (
            "YouTube authorization tokens are intentionally not backed up. "
            "After a clean Windows installation, reconnect both YouTube channels once."
        ),
        "files": copied_files,
    }
    (folder / "recovery_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    install_step = (
        "1. Встановіть інсталятор із цієї папки.\n"
        if installer_saved
        else "1. Встановіть RG YouTube Control звичайним інсталятором.\n"
    )
    guide = (
        "RG YouTube Control - відновлення після перевстановлення Windows\n\n"
        + install_step
        + "2. Запустіть програму один раз і закрийте її.\n"
        "3. У Налаштуваннях виберіть «Відновити робочу версію» та вкажіть recovery.zip.\n"
        "4. Перезапустіть програму.\n"
        "5. Один раз перепідключіть обидва YouTube-канали.\n\n"
        "База, налаштування, історія оптимізацій та службові дані відновлюються з копії.\n"
    )
    (folder / "ВІДНОВЛЕННЯ.txt").write_text(guide, encoding="utf-8")

    archive = folder / "recovery.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path == archive or not path.is_file():
                continue
            zf.write(path, path.relative_to(folder))

    return archive


def read_recovery_manifest(archive: Path) -> dict:
    with zipfile.ZipFile(archive, "r") as zf:
        with zf.open("recovery_manifest.json") as fh:
            return json.load(fh)


def restore_recovery_backup(*, data_dir: Path, archive: Path) -> dict:
    manifest = read_recovery_manifest(archive)
    if manifest.get("app") != APP_NAME:
        raise RuntimeError("Це не резервна копія RG YouTube Control.")

    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rg_youtube_restore_") as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(tmp_dir)

        db_source = tmp_dir / "rg_youtube_control.db"
        if not db_source.is_file():
            raise RuntimeError("У резервній копії немає бази даних.")

        for suffix in ("", "-wal", "-shm"):
            (data_dir / f"rg_youtube_control.db{suffix}").unlink(missing_ok=True)
        shutil.copy2(db_source, data_dir / "rg_youtube_control.db")

        app_data = tmp_dir / "app_data"
        if app_data.is_dir():
            for source in app_data.iterdir():
                destination = data_dir / source.name
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, destination)


    return manifest


def prune_recovery_backups(
    backup_root: Path,
    *,
    keep: int = 14,
    prefix: str = "RG_YOUTUBE_CONTROL_AUTO_",
) -> int:
    if keep < 1 or not backup_root.exists():
        return 0
    folders = [
        path
        for path in backup_root.iterdir()
        if path.is_dir() and path.name.startswith(prefix)
    ]
    folders.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    removed = 0
    for old in folders[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed += 1
    return removed
