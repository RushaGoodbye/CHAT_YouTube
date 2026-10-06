param(
    [string]$NasRoot = "\\AlexLosServer\docker"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$base = "https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/main/rg_remote_control/nas"
$files = @(
    "RG_NAS_COMMAND_BUS.sh",
    "RG_NAS_SCHEDULER_TICK.sh",
    "RG_TELEGRAM_CONTROL_AGENT.sh",
    "RG_TELEGRAM_CONTROL_APP_INSTALL.sh"
)

if (-not (Test-Path $NasRoot)) {
    throw "NAS path unavailable: $NasRoot"
}

$state = Join-Path $NasRoot "RG_NAS_STATE"
$telegram = Join-Path $NasRoot "RG_TELEGRAM"
$requestDir = Join-Path $telegram "control-requests"
New-Item -ItemType Directory -Force $state, $requestDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path $state "rgtc_stage1_bootstrap_$stamp"
New-Item -ItemType Directory -Force $backupDir | Out-Null

$tmpRoot = Join-Path $env:TEMP "rgtc_stage1_$stamp"
New-Item -ItemType Directory -Force $tmpRoot | Out-Null

try {
    foreach ($name in $files) {
        $src = "$base/$name"
        $tmp = Join-Path $tmpRoot $name
        Invoke-WebRequest -UseBasicParsing -Uri $src -OutFile $tmp

        if (-not (Test-Path $tmp) -or (Get-Item $tmp).Length -lt 100) {
            throw "Downloaded file is invalid: $name"
        }

        $target = Join-Path $NasRoot $name
        if (Test-Path $target) {
            Copy-Item $target (Join-Path $backupDir $name) -Force
        }

        $new = "$target.new"
        Copy-Item $tmp $new -Force
        Move-Item $new $target -Force
        Write-Host "SYNCED $name"
    }

    Remove-Item (Join-Path $state "rg_telegram_control_app_status") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $state "rg_telegram_control_app_error_at") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $state "rg_telegram_control_app_last_error") -Force -ErrorAction SilentlyContinue

    $requestId = "rgtc-stage1-bootstrap-$stamp"
    $request = [ordered]@{
        id = $requestId
        action = "control-app-install"
        args = @{}
        issuedAt = (Get-Date).ToUniversalTime().ToString("o")
        note = "RG Telegram Control Stage 1 bootstrap from AlexPC"
    }

    $requestPath = Join-Path $requestDir "$requestId.json"
    $requestJson = $request | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText(
        $requestPath,
        $requestJson + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host "REQUESTED control-app-install"

    $deadline = (Get-Date).AddMinutes(7)
    $statusFile = Join-Path $state "rg_telegram_control_app_status"
    $portFile = Join-Path $state "rg_telegram_control_app_port"

    do {
        Start-Sleep -Seconds 5

        $status = ""
        if (Test-Path $statusFile) {
            $status = (Get-Content $statusFile -Raw -ErrorAction SilentlyContinue).Trim()
        }

        $port = ""
        if (Test-Path $portFile) {
            $port = (Get-Content $portFile -Raw -ErrorAction SilentlyContinue).Trim()
        }

        $healthOk = $false
        if ($port -match '^\d+$') {
            try {
                $health = Invoke-RestMethod -Uri ("http://AlexLosServer:{0}/healthz" -f $port) -TimeoutSec 3
                $healthOk = [bool]$health.ok
            } catch {}
        }

        if ($status -eq "OK" -and $healthOk) {
            Write-Host "RG_TELEGRAM_CONTROL_STAGE1_OK"
            Write-Host ("port={0}" -f $port)
            Write-Host "healthz=OK"
            exit 0
        }

        if ($status -eq "ERROR") {
            $lastError = Get-Content (Join-Path $state "rg_telegram_control_app_last_error") -Raw -ErrorAction SilentlyContinue
            $installLog = Get-Content (Join-Path $state "rg-telegram-control-install.log") -Tail 80 -ErrorAction SilentlyContinue
            if ($lastError) { Write-Host ("INSTALL_ERROR: " + $lastError.Trim()) }
            if ($installLog) { $installLog | ForEach-Object { Write-Host $_ } }
            throw "RG Telegram Control installer reported ERROR"
        }
    } while ((Get-Date) -lt $deadline)

    throw "Stage 1 did not reach healthz=OK before bootstrap timeout"
}
finally {
    Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
}
