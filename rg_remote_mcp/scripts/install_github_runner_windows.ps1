param(
    [Parameter(Mandatory=$true)][string]$RepoUrl,
    [Parameter(Mandatory=$true)][string]$RegistrationToken,
    [string]$RunnerName = "AlexPC-RG",
    [string]$InstallDir = "C:\RG_GITHUB_RUNNER"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Set-Location $InstallDir

$release = Invoke-RestMethod "https://api.github.com/repos/actions/runner/releases/latest"
$asset = $release.assets |
    Where-Object { $_.name -match "^actions-runner-win-x64-.*\.zip$" } |
    Select-Object -First 1
if (-not $asset) { throw "Windows x64 runner asset not found" }

$zip = Join-Path $InstallDir $asset.name
Invoke-WebRequest $asset.browser_download_url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $InstallDir -Force

& .\config.cmd --unattended `
    --url $RepoUrl `
    --token $RegistrationToken `
    --name $RunnerName `
    --labels "rg,alexpc,windows" `
    --work "_work"

& .\svc install
& .\svc start
Write-Host "GITHUB_RUNNER_READY"
