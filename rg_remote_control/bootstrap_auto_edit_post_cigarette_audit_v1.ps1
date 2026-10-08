$ErrorActionPreference='Stop'
$commit='08db3d9c9c2fae23653e270c62ab8f24d69e52f7'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_locate_886_fast.py'
$task=Join-Path $env:TEMP 'rg_task_locate_886_fast.json'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'locate_auto_edit_886_artifacts_v2'){throw '886 artifact locator action missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}

$json=@{
  target='alexpc'
  contour='auto_edit'
  action='locate_auto_edit_886_artifacts_v2'
  args=@{}
} | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($task,$json,(New-Object System.Text.UTF8Encoding($false)))

Write-Host '886 ARTIFACT LOCATOR DIRECT CONTROL: PASS'
Write-Host '=== 886 ARTIFACT LOCATOR DIRECT RESULT ==='
& $runtime -u -X utf8 $tmp $task
if($LASTEXITCODE -ne 0){throw "Direct locator failed with exit code $LASTEXITCODE"}
