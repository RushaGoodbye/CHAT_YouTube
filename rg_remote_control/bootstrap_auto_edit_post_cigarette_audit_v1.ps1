$ErrorActionPreference='Stop'
$commit='ed38af6375ce56e356bf76dfaed042970f369a43'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_telemetry_runtime_proof_v1.py'
$task=Join-Path $env:TEMP 'rg_task_telemetry_runtime_proof_v1.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'apply_auto_edit_telemetry_runtime_proof_v1'){throw 'Telemetry runtime proof action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='apply_auto_edit_telemetry_runtime_proof_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'TELEMETRY RUNTIME PROOF CONTROL: PASS'
Write-Host '=== TELEMETRY RUNTIME PROOF RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Telemetry runtime proof installation failed with exit code $LASTEXITCODE"}
