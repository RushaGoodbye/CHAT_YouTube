$ErrorActionPreference='Stop'
$commit='54695fe5239e2d4aba1a695ede50c1ce5a5729f3'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_telemetry_v1.py'
$task=Join-Path $env:TEMP 'rg_task_telemetry_v1.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'apply_auto_edit_telemetry_v1'){throw 'Telemetry action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='apply_auto_edit_telemetry_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'TELEMETRY V1 DIRECT CONTROL: PASS'
Write-Host '=== TELEMETRY V1 DIRECT RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Telemetry hotfix failed with exit code $LASTEXITCODE"}
