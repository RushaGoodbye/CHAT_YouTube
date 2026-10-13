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

Write-Host '=== PYINSTALLER START (max 12 minutes) ==='
$py = (py -3.12 -c 'import sys; print(sys.executable)').Trim()
if (!(Test-Path $py)) { throw 'Python 3.12 executable not found' }
$buildLog = Join-Path $PSScriptRoot 'pyinstaller.stdout.log'
$buildErr = Join-Path $PSScriptRoot 'pyinstaller.stderr.log'
$buildArgs = '-m PyInstaller --noconfirm --clean --windowed --onedir --name RG_Media_Deck --add-data "assets;assets" --collect-all PySide6.QtMultimedia --collect-all PySide6.QtMultimediaWidgets app.py'
$build = Start-Process -FilePath $py -ArgumentList $buildArgs -PassThru -RedirectStandardOutput $buildLog -RedirectStandardError $buildErr
try {
    if (!$build.WaitForExit(720000)) {
        & taskkill.exe /PID $build.Id /T /F | Out-Host
        Get-Content $buildLog -Tail 50 -ErrorAction SilentlyContinue | Out-Host
        Get-Content $buildErr -Tail 80 -ErrorAction SilentlyContinue | Out-Host
        throw 'PyInstaller TIMEOUT: 12 minutes'
    }
    $build.Refresh()
    Get-Content $buildLog -Tail 30 -ErrorAction SilentlyContinue | Out-Host
    Get-Content $buildErr -Tail 40 -ErrorAction SilentlyContinue | Out-Host
    if ($build.ExitCode -ne 0) { throw "PyInstaller failed: $($build.ExitCode)" }
} finally {
    if (!$build.HasExited) { Stop-Process -Id $build.Id -Force -ErrorAction SilentlyContinue }
}
Write-Host '=== PYINSTALLER PASS ==='
$exe = Join-Path $PSScriptRoot 'dist\RG_Media_Deck\RG_Media_Deck.exe'
if (!(Test-Path $exe)) { throw 'Missing Windows EXE' }

Write-Host '=== FROZEN EXE SELFTEST (120-second hard timeout) ==='
$check = Start-Process -FilePath $exe -ArgumentList '--selftest' -PassThru
try {
    $finished = $check.WaitForExit(120000)
    if (!$finished) {
        & taskkill.exe /PID $check.Id /T /F | Out-Host
        throw 'Frozen EXE selftest TIMEOUT after 120 seconds'
    }
    $check.Refresh()
    if ($check.ExitCode -ne 0) { throw "Frozen EXE selftest failed: $($check.ExitCode)" }
    Write-Host '=== FROZEN EXE SELFTEST PASS ==='
} finally {
    if (!$check.HasExited) { Stop-Process -Id $check.Id -Force -ErrorAction SilentlyContinue }
}

$iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (!(Test-Path $iscc)) { throw 'Inno Setup 6 required: https://jrsoftware.org/isdl.php' }
Write-Host '=== INNO SETUP START ==='
& $iscc 'installer\RG_Media_Deck.iss'
Assert-ExitCode 'Inno Setup'
$installer = Join-Path $PSScriptRoot 'dist_installer\RG_Media_Deck_Setup.exe'
if (!(Test-Path $installer)) { throw 'Windows installer missing' }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
"$hash  RG_Media_Deck_Setup.exe" | Set-Content -Encoding Ascii "$installer.sha256"
Write-Host "Ready: $installer"
Write-Host "SHA256: $hash"
