"""Installer-based updates for RG Media Deck, with release-scoped SHA256 checks."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from library import settings_path

REPO = 'RushaGoodbye/CHAT_YouTube'
RELEASES_API = f'https://api.github.com/repos/{REPO}/releases?per_page=50'
TAG_PATTERN = re.compile(r'^rg-media-deck-v(\d+\.\d+\.\d+)$')
VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+$')
SHA_PATTERN = re.compile(r'^[a-fA-F0-9]{64}$')
INSTALLER_NAME = 'RG_Media_Deck_Setup.exe'
CHECKSUM_NAME = INSTALLER_NAME + '.sha256'
MAX_INSTALLER_BYTES = 600 * 1024 * 1024
AGENT = 'RG-Media-Deck-Updater/0.1.6'


def version_tuple(version: str) -> tuple[int, int, int]:
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise ValueError('Некоректний формат версії')
    return tuple(map(int, version.split('.')))


def trusted_download_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'github.com'
            and not parsed.username and not parsed.password and parsed.port in (None, 443)
            and not parsed.fragment and
            parsed.path.startswith(f'/{REPO}/releases/download/'))


def _request(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={
        'User-Agent': AGENT, 'Accept': 'application/vnd.github+json'})
    return urllib.request.urlopen(req, timeout=timeout)


def _asset_urls(release: dict) -> dict:
    urls = {}
    for item in release.get('assets', []):
        if not isinstance(item, dict):
            continue
        name, url = item.get('name'), item.get('browser_download_url')
        if name in (INSTALLER_NAME, CHECKSUM_NAME) and trusted_download_url(url):
            if name in urls:
                return {}
            urls[name] = url
    return urls


def select_release(releases, current_version: str) -> dict | None:
    current = version_tuple(current_version)
    if not isinstance(releases, list):
        raise ValueError('Некоректна відповідь GitHub')
    candidates = []
    for entry in releases:
        if not isinstance(entry, dict) or entry.get('draft'):
            continue
        match = TAG_PATTERN.fullmatch(str(entry.get('tag_name', '')))
        if not match:
            continue
        version = match.group(1)
        if version_tuple(version) <= current:
            continue
        urls = _asset_urls(entry)
        if set(urls) == {INSTALLER_NAME, CHECKSUM_NAME}:
            candidates.append((version_tuple(version), {
                'version': version,
                'installer_url': urls[INSTALLER_NAME],
                'sha_url': urls[CHECKSUM_NAME],
                'notes': str(entry.get('body') or '')[:700],
            }))
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def fetch_latest(current_version: str) -> dict | None:
    with _request(RELEASES_API) as response:
        return select_release(json.loads(response.read(1_000_000).decode('utf-8')), current_version)


def _validate_final_url(response) -> None:
    parsed = urlsplit(response.geturl())
    host = parsed.hostname or ''
    trusted = (host == 'github.com' or host == 'release-assets.githubusercontent.com'
               or host.endswith('.githubusercontent.com'))
    if parsed.scheme != 'https' or not trusted:
        raise ValueError('Недовірений сервер завантаження')


def fetch_checksum(url: str) -> str:
    if not trusted_download_url(url):
        raise ValueError('Недовірене джерело SHA256')
    with _request(url) as response:
        _validate_final_url(response)
        line = response.read(300).decode('ascii').strip()
    checksum = line.split()[0] if line else ''
    if not SHA_PATTERN.fullmatch(checksum):
        raise ValueError('Некоректна контрольна сума SHA256')
    return checksum.lower()


def update_folder() -> Path:
    folder = settings_path().parent / 'updates'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def verify_checksum(path: Path, expected: str) -> bool:
    if not SHA_PATTERN.fullmatch(expected):
        return False
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest().lower() == expected.lower()


def download_update(release: dict, progress=None, cancelled=None) -> tuple[Path, str]:
    version_tuple(release['version'])
    url = release['installer_url']
    if not trusted_download_url(url):
        raise ValueError('Недовірене посилання на інсталятор')
    expected = fetch_checksum(release['sha_url'])
    folder = update_folder()
    staged = folder / f'RG_Media_Deck_Setup_{release["version"]}.exe'
    partial = folder / f'RG_Media_Deck_Setup_{release["version"]}.part'
    digest = hashlib.sha256()
    size = 0
    try:
        with _request(url, timeout=90) as response:
            _validate_final_url(response)
            expected_size = int(response.headers.get('Content-Length') or 0)
            if expected_size > MAX_INSTALLER_BYTES:
                raise ValueError('Інсталятор перевищує максимальний розмір')
            with partial.open('wb') as handle:
                while True:
                    if cancelled is not None and cancelled():
                        raise InterruptedError('Завантаження скасовано')
                    block = response.read(262144)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_INSTALLER_BYTES:
                        raise ValueError('Інсталятор перевищує максимальний розмір')
                    handle.write(block)
                    digest.update(block)
                    if progress is not None and expected_size:
                        progress(min(100, int(size * 100 / expected_size)))
        if size < 1024 or digest.hexdigest().lower() != expected:
            raise ValueError('Пошкоджене завантаження: SHA256 не збігається')
        with partial.open('rb') as handle:
            signature = handle.read(2)
        if signature != b'MZ':
            raise ValueError('Файл не є Windows EXE')
        os.replace(partial, staged)
        return staged, expected
    finally:
        partial.unlink(missing_ok=True)


def prepare_installer(staged: Path, expected: str, version: str) -> list[str]:
    """Return an Inno Setup invocation; caller must exit application after launch."""
    version_tuple(version)
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Оновлення доступні у встановленій Windows-версії')
    staged = Path(staged).resolve()
    if staged.parent != update_folder().resolve() or not staged.is_file():
        raise ValueError('Невірний файл оновлення')
    if not verify_checksum(staged, expected):
        raise ValueError('Контрольна сума SHA256 не збігається')
    with staged.open('rb') as handle:
        signature = handle.read(2)
    if signature != b'MZ':
        raise ValueError('Некоректний інсталятор')
    return [str(staged), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS']
