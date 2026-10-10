# RG Telegram: isolated self-hosted Windows runner installer (one-time setup).
# Does not modify C:\RG_GITHUB_RUNNER or NAS. Registration token stays local.
# Run from elevated Windows PowerShell. Never paste the token into ChatGPT.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repoUrl = 'https://github.com/RushaGoodbye/rasha-goodbye-news-bot'
$dest = 'C:\RG_TELEGRAM_RUNNER'
$name = 'ALEXPC-TELEGRAM'
$labels = 'rg-telegram'
$admin = [Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Run Windows PowerShell as Administrator (the runner service needs this).'
}
if (Test-Path (Join-Path $dest '.runner')) {
  throw "Runner is already registered at $dest. Refusing to overwrite an existing installation."
}
if (Test-Path (Join-Path $dest 'config.cmd')) {
  throw "Partial runner install exists at $dest. Inspect it before retrying; no automatic deletion."
}
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }
Write-Host 'Downloading the latest official GitHub Actions Runner for Windows x64...'
$headers = @{ 'User-Agent' = 'RG-Telegram-Runner-Setup'; 'Accept' = 'application/vnd.github+json' }
$release = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/runner/releases/latest' -Headers $headers -TimeoutSec 40
$asset = @($release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-[0-9.]+\.zip$' }) | Select-Object -First 1
if (-not $asset) { throw 'Official Windows x64 runner archive not present in latest GitHub release.' }
$expected = $null
if ([string]$asset.digest -match '^sha256:([a-fA-F0-9]{64})$') {
  $expected = $Matches[1].ToUpperInvariant()
} else {
  $match = [regex]::Match([string]$release.body, 'actions-runner-win-x64-[0-9.]+\.zip[^\r\n]*?([a-fA-F0-9]{64})', 'IgnoreCase')
  if ($match.Success) { $expected = $match.Groups[1].Value.ToUpperInvariant() }
}
if (-not $expected) { throw 'Cannot find the official SHA-256 for the selected runner release. Refusing unverified installation.' }
$archive = Join-Path $env:TEMP ([string]$asset.name)
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive -UseBasicParsing -TimeoutSec 300
$actual = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToUpperInvariant()
if ($actual -ne $expected) { throw "Runner archive checksum does not match official GitHub SHA-256. Installation aborted." }
Write-Host ('Verified runner: ' + $asset.name)
Expand-Archive -Path $archive -DestinationPath $dest -Force
Remove-Item -LiteralPath $archive -Force
if (-not (Test-Path (Join-Path $dest 'config.cmd'))) { throw 'Runner config.cmd missing after extraction.' }

Write-Host ''
Write-Host 'Open your private repository:'
Write-Host "$repoUrl/settings/actions/runners/new"
Write-Host 'Select Windows / x64. Copy ONLY the one-time registration token from the Configure command.'
Write-Host 'Do not paste the token into ChatGPT or GitHub Issues.'
$secret = Read-Host 'Enter registration token (input hidden)' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
  $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  if ([string]::IsNullOrWhiteSpace($token)) { throw 'Empty registration token.' }
  Push-Location $dest
  try {
    & .\config.cmd --unattended --url $repoUrl --token $token --name $name --labels $labels --work '_work' --runasservice
    if ($LASTEXITCODE -ne 0) { throw "Runner registration exited with code $LASTEXITCODE." }
  } finally { Pop-Location }
} finally {
  $token = $null
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if (-not (Test-Path (Join-Path $dest '.runner'))) { throw 'Runner registration did not create .runner. Inspect local runner logs.' }
Write-Host ''
Write-Host 'RG_TELEGRAM_RUNNER_REGISTERED: YES'
Write-Host ('Private repository: ' + $repoUrl)
Write-Host ('Runner name: ' + $name + ' | label: ' + $labels)
Write-Host 'Verify in GitHub > Settings > Actions > Runners: status should be Idle or Active.'
Write-Host 'Existing C:\RG_GITHUB_RUNNER was not changed.'
