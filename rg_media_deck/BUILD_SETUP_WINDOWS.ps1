$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Assert-ExitCode([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed: exit code $LASTEXITCODE" }
}

py -3.12 -m pip install -r requirements.txt pyinstaller==6.16.0
Assert-ExitCode 'Dependency installation'

py -3.12 -m unittest discover -s tests -v
Assert-ExitCode 'Unit tests'

py -3.12 build_icon.py
Assert-ExitCode 'Generate application icons'
if (!(Test-Path 'assets/RG_Media_Deck.ico')) { throw 'Generated icon missing' }

py -3.12 -m PyInstaller --noconfirm --clean --windowed --onedir --name RG_Media_Deck --add-data 'assets;assets' --collect-all PySide6.QtMultimedia --collect-all PySide6.QtMultimediaWidgets app.py
Assert-ExitCode 'PyInstaller'
$exe = Join-Path $PSScriptRoot 'dist\RG_Media_Deck\RG_Media_Deck.exe'
if (!(Test-Path $exe)) { throw 'Missing Windows EXE' }

$check = Start-Process -FilePath $exe -ArgumentList '--selftest' -Wait -PassThru -NoNewWindow
if ($check.ExitCode -ne 0) { throw "Frozen EXE selftest failed: $($check.ExitCode)" }

$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (!(Test-Path $iscc)) { throw 'Inno Setup 6 required: https://jrsoftware.org/isdl.php' }
& $iscc 'installer\RG_Media_Deck.iss'
Assert-ExitCode 'Inno Setup'
$installer = Join-Path $PSScriptRoot 'dist_installer\RG_Media_Deck_Setup.exe'
if (!(Test-Path $installer)) { throw 'Windows installer missing' }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
"$hash  RG_Media_Deck_Setup.exe" | Set-Content -Encoding Ascii "$installer.sha256"
Write-Host "Ready: $installer"
Write-Host "SHA256: $hash"
