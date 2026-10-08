$ErrorActionPreference='Stop'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script=Join-Path $env:TEMP 'RG_AUTO_EDIT_RETRY_886_5_DIRECT_V5.py'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/c70df1084e78d806a489f00c2f7f9ab1faa89693/rg_remote_control/auto_edit_retry_8865_direct_v5.py'
if(!(Test-Path -LiteralPath $runtime)){throw "RG Auto Edit runtime not found: $runtime"}
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
if(!(Test-Path -LiteralPath $script)){throw 'Retry V5 script download failed'}
& $runtime -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Retry V5 Python compile failed'}
Write-Host '=== RETRY 886_5 DIRECT V5 CONTROL ==='
Write-Host 'Stale NAS preparation request: validate and quarantine, never delete.'
Write-Host 'Protected dialogues 1-4 and fail-closed blur remain mandatory.'
& $runtime -u -X utf8 $script
if($LASTEXITCODE -ne 0){throw 'Retry V5 stopped or QA not PASS; inspect the output block above.'}
