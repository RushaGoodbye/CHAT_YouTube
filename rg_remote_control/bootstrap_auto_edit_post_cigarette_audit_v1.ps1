$ErrorActionPreference='Stop'
$commit='9419be26368701f16fda4e9856120d91a775a04a'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_reconcile_886_direct.py'
$task=Join-Path $env:TEMP 'rg_task_reconcile_886_direct.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'reconcile_auto_edit_post_cigarette_v1'){throw 'Reconcile action missing'}
if($src -notmatch 'RG_CIGARETTE_VALIDATOR_HOTFIX_V1'){throw 'Cigarette validator hotfix missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='reconcile_auto_edit_post_cigarette_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host '886 RECONCILE DIRECT CONTROL: PASS'
Write-Host '=== 886 RECONCILE DIRECT RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Direct reconcile failed with exit code $LASTEXITCODE"}
