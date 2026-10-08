$ErrorActionPreference='Stop'
$commit='e0890457d7516b361848c119f8e995e80d75444c'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_live_cig_diag_v1.py'
$task=Join-Path $env:TEMP 'rg_task_live_cig_diag_v1.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'inspect_auto_edit_live_cigarette_failure_v1'){throw 'Live cigarette diagnosis action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='inspect_auto_edit_live_cigarette_failure_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'LIVE CIGARETTE DIAG CONTROL: PASS'
Write-Host '=== LIVE CIGARETTE DIAG RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Live cigarette diagnosis failed with exit code $LASTEXITCODE"}
