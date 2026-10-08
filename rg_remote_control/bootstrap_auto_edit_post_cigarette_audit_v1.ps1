$ErrorActionPreference='Stop'
$commit='dc4297b1752c7ff4498379b64efba51980414258'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_launcher_reexec_inspect.py'
$task=Join-Path $env:TEMP 'rg_task_launcher_reexec_inspect.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'inspect_auto_edit_launcher_reexec_v1'){throw 'Launcher re-exec inspection action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='inspect_auto_edit_launcher_reexec_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'LAUNCHER REEXEC INSPECT CONTROL: PASS'
Write-Host '=== LAUNCHER REEXEC INSPECT RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Launcher inspection failed with exit code $LASTEXITCODE"}
