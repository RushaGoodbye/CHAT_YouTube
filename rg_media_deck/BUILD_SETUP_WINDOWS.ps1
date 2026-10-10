$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3.12 -m pip install -r requirements.txt pyinstaller==6.16.0
py -3.12 -m unittest discover -s tests -v
py -3.12 -m PyInstaller --noconfirm --clean --windowed --onedir --name RG_Media_Deck --collect-all PySide6.QtMultimedia --collect-all PySide6.QtMultimediaWidgets app.py
$iscc=Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (!(Test-Path $iscc)) { throw 'Inno Setup 6 required: https://jrsoftware.org/isdl.php' }
& $iscc installer\RG_Media_Deck.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Write-Host 'Ready: dist_installer\RG_Media_Deck_Setup.exe'
