$ErrorActionPreference='Stop'
$python='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script=Join-Path $env:TEMP 'RG_886_5_CIGARETTE_LOCAL_XML_REPAIR_V1.py'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/7f179068007ad4910319641c6654dc408ca23af0/rg_remote_control/repair_auto_edit_886_5_local_cigarette_v1.py'
if(!(Test-Path -LiteralPath $python)){throw "Installed Auto Edit Python is missing: $python"}
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
if(!(Test-Path -LiteralPath $script)){throw '886_5 repair script download failed'}
& $python -m py_compile $script
if($LASTEXITCODE -ne 0){throw '886_5 repair code syntax check failed - no files modified'}
Write-Host '=== RG AUTO EDIT 886_5 LOCALIZED BLUR REPAIR V1 ==='
Write-Host 'Uses existing detections; no stream rescan, no dialogue recompute.'
Write-Host 'Staging, strict QA, original XML/audio protection and backup are mandatory.'
& $python -u -X utf8 $script
if($LASTEXITCODE -ne 0){throw '886_5 repair stopped safely; see the STOPPED block above. Do not retry blindly.'}
