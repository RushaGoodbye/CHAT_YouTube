import hashlib
import json
from pathlib import Path

from rg_youtube_control import updater


def test_nas_manifest_is_primary_update_source(tmp_path, monkeypatch):
    installer = tmp_path / "RG_YouTube_Control_Setup_9.9.9.exe"
    installer.write_bytes(b"nas-installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    checksum = tmp_path / (installer.name + ".sha256")
    checksum.write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    (tmp_path / "latest.json").write_text(
        json.dumps(
            {
                "version": "9.9.9",
                "installer_name": installer.name,
                "checksum_name": checksum.name,
                "notes": "NAS update test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RG_YOUTUBE_UPDATES_PATH", str(tmp_path))

    info = updater.check_for_update()

    assert info is not None
    assert info.version == "9.9.9"
    assert Path(info.installer_url) == installer
    assert Path(info.checksum_url) == checksum


def test_download_update_copies_from_nas_and_verifies_checksum(tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir()
    local = tmp_path / "local"
    local.mkdir()

    installer = nas / "RG_YouTube_Control_Setup_9.9.9.exe"
    installer.write_bytes(b"verified-nas-installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    checksum = nas / (installer.name + ".sha256")
    checksum.write_text(f"{digest}  {installer.name}\n", encoding="ascii")

    monkeypatch.setenv("LOCALAPPDATA", str(local))

    info = updater.UpdateInfo(
        version="9.9.9",
        installer_url=str(installer),
        installer_name=installer.name,
        checksum_url=str(checksum),
        notes="NAS",
    )
    downloaded = updater.download_update(info)

    assert downloaded.is_file()
    assert downloaded.read_bytes() == installer.read_bytes()
