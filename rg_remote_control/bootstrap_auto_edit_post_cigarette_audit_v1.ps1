$ErrorActionPreference='Stop'
$commit='aa5cf9f2038493f45f16eeb6638cafc0c6fe3261'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_single_logical_studio_v2.py'
$task=Join-Path $env:TEMP 'rg_task_single_logical_studio_v2.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'verify_auto_edit_single_logical_studio_v2'){throw 'Logical Studio verification action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='verify_auto_edit_single_logical_studio_v2'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'SINGLE LOGICAL STUDIO V2 CONTROL: PASS'
Write-Host '=== SINGLE LOGICAL STUDIO V2 RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Logical Studio verification failed with exit code $LASTEXITCODE"}
