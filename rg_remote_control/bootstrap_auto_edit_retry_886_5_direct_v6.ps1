$ErrorActionPreference='Stop'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script=Join-Path $env:TEMP 'RG_AUTO_EDIT_RETRY_886_5_DIRECT_V6.py'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/905f0478aa6bc668723a616f0e54f4691eb0c232/rg_remote_control/auto_edit_retry_8865_direct_v6.py'
if(!(Test-Path -LiteralPath $runtime)){throw "RG Auto Edit runtime not found: $runtime"}
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
if(!(Test-Path -LiteralPath $script)){throw 'Retry V6 script download failed'}
& $runtime -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Retry V6 Python compile failed'}
Write-Host '=== RETRY 886_5 DIRECT V6 CONTROL ==='
Write-Host 'Discover XML checkpoints in both App and App\886.'
Write-Host 'Never recalculate 886_1-4; backup and verify before retry.'
& $runtime -u -X utf8 $script
if($LASTEXITCODE -ne 0){throw 'Retry V6 stopped safely or QA not PASS; inspect the preceding result.'}
