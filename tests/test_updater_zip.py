import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from rg_youtube_control import updater


def _make_update_zip(path: Path, *, version: str = "9.9.9", payload: bytes = b"installer") -> Path:
    installer_name = f"RG_YouTube_Control_Setup_{version}.exe"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "version": version,
        "installer_name": installer_name,
        "notes": "ZIP update test",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("latest.json", json.dumps(manifest))
        zf.writestr(installer_name, payload)
        zf.writestr(
            installer_name + ".sha256",
            f"{digest}  {installer_name}\n",
        )
    return path


def test_prepare_update_from_zip_validates_and_stages(tmp_path, monkeypatch):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    archive = _make_update_zip(tmp_path / "update.zip")

    info, installer = updater.prepare_update_from_zip(archive)

    assert info.version == "9.9.9"
    assert installer.is_file()
    assert installer.read_bytes() == b"installer"
    assert Path(info.checksum_url).is_file()


def test_prepare_update_from_zip_rejects_bad_checksum(tmp_path, monkeypatch):
    local = tmp_path / "local"
    local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    archive = tmp_path / "bad.zip"
    installer_name = "RG_YouTube_Control_Setup_9.9.9.exe"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "latest.json",
            json.dumps({"version": "9.9.9", "installer_name": installer_name}),
        )
        zf.writestr(installer_name, b"bad")
        zf.writestr(installer_name + ".sha256", "0" * 64)

    with pytest.raises(RuntimeError, match="SHA-256"):
        updater.prepare_update_from_zip(archive)
