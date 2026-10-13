"""Make full-fidelity Windows ZIP patch; include hidden files and Qt plugins.

PowerShell Compress-Archive silently omits some hidden files. zipfile packs
EVERY regular file, including PyInstaller's _internal resources. The update
contains no installer and never contains the user's library or settings.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path


def build(root: Path | None = None, version: str = '0.5.0') -> Path:
    root = Path(root) if root else Path(__file__).resolve().parent
    app_dir = root / 'dist' / 'RG_Media_Deck'
    if not (app_dir / 'RG_Media_Deck.exe').is_file():
        raise FileNotFoundError("Frozen EXE missing")
    scripts = root / 'zip_update'
    installer = scripts / 'Apply_RG_Media_Deck_Update.ps1'
    launchers = list(scripts.glob('*.cmd'))
    if not installer.is_file() or len(launchers) != 1:
        raise FileNotFoundError("Updater script and one CMD launcher required")
    target = root / 'dist_release'
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / 'RG_Media_Deck_Update.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as output:
        for path in sorted(app_dir.rglob('*')):
            if path.is_symlink():
                raise ValueError(f"Symlink forbidden in patch: {path}")
            if path.is_file():
                output.write(path, path.relative_to(root / 'dist').as_posix())
        # Windows PowerShell 5 reads UTF-8 WITHOUT BOM as legacy ANSI, which
        # corrupts Cyrillic strings and breaks script parsing after extraction.
        output.writestr('Apply_RG_Media_Deck_Update.ps1',
                        bytes((0xEF, 0xBB, 0xBF)) + installer.read_bytes())
        output.write(launchers[0], launchers[0].name)
        output.writestr('version.txt', version)
    with zipfile.ZipFile(zip_path) as written:
        entries = set(written.namelist())
        mandatory = ('RG_Media_Deck/RG_Media_Deck.exe',
                     'RG_Media_Deck/_internal/assets/RG_Media_Deck.ico',
                     'Apply_RG_Media_Deck_Update.ps1',
                     launchers[0].name, 'version.txt')
        if not all(name in entries for name in mandatory):
            raise ValueError("ZIP missing critical PyInstaller runtime files")
    print(f"RG_ZIP_BUILD_PASS {zip_path} {zip_path.stat().st_size}")
    return zip_path


if __name__ == '__main__':
    build()
