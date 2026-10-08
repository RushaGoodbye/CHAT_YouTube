$ErrorActionPreference='Stop'
$commit='2834dc6e59bdb0ccce9d6135c2eb2569242d2c44'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_single_studio_v1.py'
$task=Join-Path $env:TEMP 'rg_task_single_studio_v1.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'harden_auto_edit_single_studio_v1'){throw 'Single Studio action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='harden_auto_edit_single_studio_v1'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host 'SINGLE STUDIO V1 CONTROL: PASS'
Write-Host '=== SINGLE STUDIO V1 RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Single Studio hardening failed with exit code $LASTEXITCODE"}
