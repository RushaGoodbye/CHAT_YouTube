$ErrorActionPreference='Stop'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script=Join-Path $env:TEMP 'RG_886_CHECKPOINT_ROOT_CAUSE_V1.py'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/e59707a92f597e7daebd7f50e4284780fd0b10f7/rg_remote_control/inspect_auto_edit_886_checkpoints_v1.py'
if(!(Test-Path -LiteralPath $runtime)){throw "RG Auto Edit runtime missing: $runtime"}
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
if(!(Test-Path -LiteralPath $script)){throw 'Diagnostic script unavailable'}
& $runtime -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Checkpoint diagnostic compile failed'}
Write-Host '=== RG 886 READ-ONLY CHECKPOINT AUDIT ==='
& $runtime -u -X utf8 $script
if($LASTEXITCODE -ne 0){throw "886 checkpoint audit failed with exit code $LASTEXITCODE"}
