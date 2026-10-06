from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import DEFAULT_NAS_UPDATES_PATH

REPO = "RushaGoodbye/CHAT_YouTube"
LATEST_MANIFEST_URL = f"https://github.com/{REPO}/releases/latest/download/latest.json"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = "RG-YouTube-Control-Updater"

@dataclass(frozen=True)
class UpdateInfo:
    version: str
    installer_url: str
    installer_name: str
    checksum_url: str | None
    notes: str

def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    result: list[int] = []
    for part in cleaned.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        result.append(int(digits or 0))
    return tuple(result)

def _request_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

def _from_manifest(data: dict) -> UpdateInfo | None:
    remote = str(data.get("version") or "").lstrip("vV")
    if not remote or _version_tuple(remote) <= _version_tuple(__version__):
        return None

    installer_name = str(data.get("installer_name") or "").strip()
    installer_url = str(data.get("installer_url") or "").strip()
    checksum_url = str(data.get("checksum_url") or "").strip() or None
    if not installer_name or not installer_url:
        raise RuntimeError("У маніфесті оновлення немає інсталятора Windows.")

    return UpdateInfo(
        version=remote,
        installer_url=installer_url,
        installer_name=installer_name,
        checksum_url=checksum_url,
        notes=str(data.get("notes") or ""),
    )


def _nas_update_root() -> Path:
    override = os.getenv("RG_YOUTUBE_UPDATES_PATH", "").strip()
    return Path(override or DEFAULT_NAS_UPDATES_PATH)


def _from_nas_manifest(path: Path) -> UpdateInfo | None:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    remote = str(data.get("version") or "").lstrip("vV")
    if not remote or _version_tuple(remote) <= _version_tuple(__version__):
        return None

    installer_name = str(data.get("installer_name") or "").strip()
    if not installer_name:
        raise RuntimeError("У NAS-маніфесті немає installer_name.")

    installer = path.parent / installer_name
    if not installer.is_file():
        raise RuntimeError(f"На NAS немає інсталятора: {installer}")

    checksum_name = str(data.get("checksum_name") or "").strip()
    checksum = path.parent / (
        checksum_name or f"{installer_name}.sha256"
    )

    return UpdateInfo(
        version=remote,
        installer_url=str(installer),
        installer_name=installer_name,
        checksum_url=str(checksum) if checksum.is_file() else None,
        notes=str(data.get("notes") or "Оновлення з NAS"),
    )


def check_for_update() -> UpdateInfo | None:
    nas_manifest = _nas_update_root() / "latest.json"
    try:
        if nas_manifest.is_file():
            info = _from_nas_manifest(nas_manifest)
            if info is not None:
                return info
    except Exception:
        # NAS is primary, but update checks must stay usable if the share is
        # temporarily unavailable. GitHub is only an emergency fallback.
        pass

    try:
        manifest = _request_json(LATEST_MANIFEST_URL)
        return _from_manifest(manifest)
    except Exception:
        pass

    data = _request_json(LATEST_RELEASE_URL)
    remote = str(data.get("tag_name") or "").lstrip("vV")
    if not remote or _version_tuple(remote) <= _version_tuple(__version__):
        return None

    installer = None
    checksum = None
    for asset in data.get("assets", []):
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.lower().startswith("rg_youtube_control_setup_") and name.lower().endswith(".exe"):
            installer = (name, url)
        elif name.lower().endswith(".sha256"):
            checksum = url

    if not installer:
        raise RuntimeError("У релізі немає інсталятора Windows.")

    return UpdateInfo(
        version=remote,
        installer_url=installer[1],
        installer_name=installer[0],
        checksum_url=checksum,
        notes=str(data.get("body") or ""),
    )

def _download(url: str, path: Path) -> None:
    source = Path(str(url))
    if source.is_file():
        shutil.copy2(source, path)
        return

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as response, path.open("wb") as fh:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def prune_cached_updates(root: Path | None = None, keep: int = 3) -> list[str]:
    if root is None:
        base = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir()))
        root = base / "RGYouTubeControl" / "updates"
    if not root.exists():
        return []

    pattern = re.compile(
        r"^RG_YouTube_Control_Setup_(\d+(?:\.\d+)+)\.exe(?:\.sha256)?$",
        re.IGNORECASE,
    )
    versions: dict[str, list[Path]] = {}
    for path in root.iterdir():
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        versions.setdefault(match.group(1), []).append(path)

    keep_versions = {
        version
        for version in sorted(
            versions,
            key=_version_tuple,
            reverse=True,
        )[: max(1, int(keep))]
    }
    removed: list[str] = []
    for version, paths in versions.items():
        if version in keep_versions:
            continue
        for path in paths:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:
                continue
    return removed


def download_update(info: UpdateInfo) -> Path:
    base = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir()))
    root = base / "RGYouTubeControl" / "updates"
    root.mkdir(parents=True, exist_ok=True)
    installer = root / info.installer_name
    _download(info.installer_url, installer)

    if info.checksum_url:
        checksum_path = root / f"{info.installer_name}.sha256"
        _download(info.checksum_url, checksum_path)
        expected = checksum_path.read_text(encoding="utf-8").strip().split()[0].lower()
        actual = _sha256(installer).lower()
        if expected != actual:
            installer.unlink(missing_ok=True)
            raise RuntimeError("SHA-256 оновлення не збігається. Встановлення скасовано.")

    prune_cached_updates(root, keep=3)
    return installer