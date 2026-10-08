$ErrorActionPreference='Stop'
$commit='53a3da25b02dc28e59f1db7c7b983cd4add88cc9'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_telemetry_restart_verify.py'
$task=Join-Path $env:TEMP 'rg_task_telemetry_restart_verify.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'restart_and_verify_auto_edit_telemetry_v1'){throw 'Telemetry restart verification action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='restart_and_verify_auto_edit_telemetry_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'TELEMETRY RESTART VERIFY CONTROL: PASS'
Write-Host '=== TELEMETRY RESTART VERIFY RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Telemetry restart verification failed with exit code $LASTEXITCODE"}
