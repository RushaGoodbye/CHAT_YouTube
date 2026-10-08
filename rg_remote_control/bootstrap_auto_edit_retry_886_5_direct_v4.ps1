$ErrorActionPreference = 'Stop'
$runtime = 'F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script = Join-Path $env:TEMP 'RG_AUTO_EDIT_RETRY_886_5_DIRECT_V4.py'
$url = 'https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/cce5c898db3f7bc5225c1de16dc574e639185674/rg_remote_control/auto_edit_retry_8865_direct_v4.py'

if (!(Test-Path -LiteralPath $runtime)) { throw "RG Auto Edit runtime not found: $runtime" }
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
if (!(Test-Path -LiteralPath $script)) { throw "Retry script download failed" }
& $runtime -m py_compile $script
if ($LASTEXITCODE -ne 0) { throw "Retry V4 Python syntax check failed" }
Write-Host '=== RETRY 886_5 DIRECT V4 CONTROL ==='
Write-Host 'NAS agent not required; fail-closed and checkpoints remain enforced.'
& $runtime -u -X utf8 $script
if ($LASTEXITCODE -ne 0) { throw "Retry V4 did not pass. See the STOPPED SAFELY / FINAL RESULT block above." }
