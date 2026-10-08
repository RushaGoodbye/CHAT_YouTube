$ErrorActionPreference='Stop'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script=Join-Path $env:TEMP 'RG_AUTO_EDIT_886_5_DELIVERY_QA_V1.py'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/8f76c864dfa89b153e1eb27b569f085d7e33d1a9/rg_remote_control/finalize_auto_edit_886_5_delivery_v1.py'
if(!(Test-Path -LiteralPath $runtime)){throw "RG Auto Edit runtime missing: $runtime"}
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
if(!(Test-Path -LiteralPath $script)){throw 'Delivery QA download failed'}
& $runtime -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Delivery QA syntax validation failed; no changes made'}
Write-Host '=== RG 886_5 SAFE DELIVERY + QA ==='
Write-Host 'Only corrected RG_EDITED_886_5.xml is eligible for delivery.'
Write-Host 'Other dialogues untouched; missing stream work is not marked complete.'
& $runtime -u -X utf8 $script
if($LASTEXITCODE -ne 0){throw '886_5 delivery QA blocked. See STOPPED result above.'}
