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


def test_stale_pages_manifest_does_not_hide_newer_github_release(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_YOUTUBE_UPDATES_PATH", str(tmp_path))
    checked = []

    def request(url):
        checked.append(url)
        if url == updater.PAGES_MANIFEST_URL:
            return {
                "version": "0.1.0",
                "installer_name": "old.exe",
                "installer_url": "https://example.com/old.exe",
            }
        if url == updater.LATEST_MANIFEST_URL:
            return {
                "version": "9.9.9",
                "installer_name": "new.exe",
                "installer_url": "https://example.com/new.exe",
            }
        raise AssertionError(f"Unexpected update endpoint: {url}")

    monkeypatch.setattr(updater, "_request_json", request)
    info = updater.check_for_update()

    assert info is not None
    assert info.version == "9.9.9"
    assert checked == [updater.PAGES_MANIFEST_URL, updater.LATEST_MANIFEST_URL]


def test_stale_manifests_fall_back_to_release_api(tmp_path, monkeypatch):
    monkeypatch.setenv("RG_YOUTUBE_UPDATES_PATH", str(tmp_path))
    checked = []

    def request(url):
        checked.append(url)
        if url in {updater.PAGES_MANIFEST_URL, updater.LATEST_MANIFEST_URL}:
            return {
                "version": "0.1.0",
                "installer_name": "old.exe",
                "installer_url": "https://example.com/old.exe",
            }
        if url == updater.LATEST_RELEASE_URL:
            return {
                "tag_name": "v9.9.9",
                "assets": [{
                    "name": "RG_YouTube_Control_Setup_9.9.9.exe",
                    "browser_download_url": "https://example.com/new.exe",
                }],
            }
        raise AssertionError(f"Unexpected update endpoint: {url}")

    monkeypatch.setattr(updater, "_request_json", request)
    info = updater.check_for_update()

    assert info is not None
    assert info.version == "9.9.9"
    assert checked == [
        updater.PAGES_MANIFEST_URL,
        updater.LATEST_MANIFEST_URL,
        updater.LATEST_RELEASE_URL,
    ]
