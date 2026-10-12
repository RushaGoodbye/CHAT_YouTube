param(
    [string]$InstallDir = "",
    [switch]$NonInteractive,
    [int]$WaitPid = 0
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Root "RG_Media_Deck"
if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\RG Media Deck"
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$ProgramDir = Split-Path -Parent $InstallDir
$Backup = Join-Path $ProgramDir ("RG Media Deck.backup." + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$Pending = Join-Path $ProgramDir ("RG Media Deck.pending." + (Get-Date -Format 'yyyyMMdd_HHmmss'))
$CurrentExe = Join-Path $InstallDir 'RG_Media_Deck.exe'
$SourceExe = Join-Path $Source 'RG_Media_Deck.exe'
$Promoted = $false
$BackedUp = $false
$LogDir = Join-Path $env:LOCALAPPDATA 'RGMediaDeck\updates'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir 'last_zip_update.txt'

function Fail([string]$Message) {
    Write-Host "RG UPDATE ERROR: $Message" -ForegroundColor Red
    Set-Content -LiteralPath $LogFile -Value ("FAILED: " + $Message) -Encoding UTF8
    if (-not $NonInteractive) { Read-Host "Enter, щоб закрити" | Out-Null }
    exit 1
}
try {
    if (-not (Test-Path -LiteralPath $SourceExe -PathType Leaf)) {
        Fail "В архіві немає RG_Media_Deck\RG_Media_Deck.exe"
    }
    if (-not (Test-Path -LiteralPath $CurrentExe -PathType Leaf)) {
        Fail "Встановлений RG Media Deck не знайдено: $InstallDir"
    }
    if ($WaitPid -gt 0) {
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            if (-not (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 500
        }
    }
    $active = @(Get-Process -Name RG_Media_Deck -ErrorAction SilentlyContinue)
    if ($active.Count -gt 0) {
        Fail "Спочатку закрийте RG Media Deck, потім повторіть оновлення"
    }
    if (Test-Path -LiteralPath $Pending) { Fail "Тимчасова папка вже існує" }
    # Stage a complete new app in the same volume to allow atomic rename.
    New-Item -ItemType Directory -Path $Pending | Out-Null
    Copy-Item -Path (Join-Path $Source '*') -Destination $Pending -Recurse -Force
    foreach ($item in (Get-ChildItem -LiteralPath $InstallDir -File -Filter 'unins*')) {
        Copy-Item -LiteralPath $item.FullName -Destination $Pending -Force
    }
    $NewExe = Join-Path $Pending 'RG_Media_Deck.exe'
    if (-not (Test-Path -LiteralPath $NewExe)) { Fail "Файли не скопійовано" }
    Write-Host "Перевірка нового EXE перед зміною робочої програми..." -ForegroundColor Cyan
    $check = Start-Process -FilePath $NewExe -ArgumentList '--selftest' -Wait -PassThru
    if ($check.ExitCode -ne 0) {
        Fail ("Тест нової версії не пройдено: " + $check.ExitCode)
    }
    Move-Item -LiteralPath $InstallDir -Destination $Backup
    $BackedUp = $true
    Move-Item -LiteralPath $Pending -Destination $InstallDir
    $Promoted = $true
    $check = Start-Process -FilePath $CurrentExe -ArgumentList '--selftest' -Wait -PassThru
    if ($check.ExitCode -ne 0) {
        throw "Нова версія не пройшла тест після оновлення"
    }
    $msg = "PASS: ZIP-оновлення встановлено, попередню версію збережено: $Backup"
    Write-Host $msg -ForegroundColor Green
    Set-Content -LiteralPath $LogFile -Value $msg -Encoding UTF8
    # Keep only the latest fallback copy; never touch media or settings folders.
    Get-ChildItem -LiteralPath $ProgramDir -Directory -Filter 'RG Media Deck.backup.*' |
       Sort-Object -Property LastWriteTime -Descending |
       Select-Object -Skip 1 |
       Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $CurrentExe
    exit 0
}
catch {
    $message = $_.Exception.Message
    if ($BackedUp) {
        try {
            if ($Promoted -and (Test-Path -LiteralPath $InstallDir)) {
                Remove-Item -LiteralPath $InstallDir -Recurse -Force
            }
            Move-Item -LiteralPath $Backup -Destination $InstallDir
            $message += ' — попередню версію відновлено'
        } catch {
            $message += ' — УВАГА: відновіть із папки ' + $Backup
        }
    }
    Fail $message
}
finally {
    if (Test-Path -LiteralPath $Pending) {
        Remove-Item -LiteralPath $Pending -Recurse -Force -ErrorAction SilentlyContinue
    }
}
