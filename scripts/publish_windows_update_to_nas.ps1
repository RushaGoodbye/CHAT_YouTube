param(
    [string]$NasRoot = "\\AlexLosServer\RG_AUTO_EDIT\YOUTUBE_CONTROL\UPDATES"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$line = Select-String -Path "pyproject.toml" -Pattern '^version = "([^"]+)"'
if (-not $line) { throw "Version not found in pyproject.toml" }
$version = $line.Matches[0].Groups[1].Value

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

$env:PYTHONPATH = "src"
python -m pytest -q tests

Remove-Item -Recurse -Force "dist\RG YouTube Control" -ErrorAction SilentlyContinue
pyinstaller --noconfirm --clean --windowed --onedir --name "RG YouTube Control" --paths src run_app.py

$inno = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $inno)) {
    throw "Inno Setup 6 not found: $inno"
}

New-Item -ItemType Directory -Force installer | Out-Null
& $inno "/DMyAppVersion=$version" "packaging\installer.iss"

$installer = Get-ChildItem "installer\RG_YouTube_Control_Setup_$version.exe" | Select-Object -First 1
if (-not $installer) { throw "Installer was not built" }

New-Item -ItemType Directory -Force $NasRoot | Out-Null

$hash = (Get-FileHash $installer.FullName -Algorithm SHA256).Hash.ToLower()
$checksumName = "$($installer.Name).sha256"
$checksumPath = Join-Path $NasRoot $checksumName
$targetInstaller = Join-Path $NasRoot $installer.Name

Copy-Item $installer.FullName $targetInstaller -Force
"$hash  $($installer.Name)" | Set-Content -Encoding ascii $checksumPath

$manifest = [ordered]@{
    version = $version
    installer_name = $installer.Name
    checksum_name = $checksumName
    notes = "NAS update $version"
    published_at = (Get-Date).ToUniversalTime().ToString("o")
}
$manifest | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $NasRoot "latest.json")

Write-Host "NAS UPDATE READY: $version"
Write-Host $targetInstaller
