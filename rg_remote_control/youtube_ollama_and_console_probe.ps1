# Read-only investigation of missing Ollama llama-server binary and periodic console flashes.
$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$ollama=(Get-Command ollama.exe -ErrorAction SilentlyContinue)
$files=@()
foreach($dir in @($root,(Join-Path $root 'lib'),(Join-Path $root 'lib\ollama'),(Join-Path $root 'build\lib\ollama'),(Join-Path $root 'dist\windows-amd64\lib\ollama'))){
 if(Test-Path -LiteralPath $dir){
  $entries=@(Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue | Select-Object -First 45 | ForEach-Object {[pscustomobject]@{name=$_.Name;bytes=$_.Length;modified=$_.LastWriteTime.ToString('o')}})
  $files += [pscustomobject]@{folder=$dir;exists=$true;items=$entries}
 } else {$files += [pscustomobject]@{folder=$dir;exists=$false;items=@()}}
}
$serverCandidates=@()
foreach($base in @($root,(Join-Path $env:LOCALAPPDATA 'Programs'),(Join-Path $env:PROGRAMFILES 'Ollama'))){
 if(Test-Path -LiteralPath $base){
  $serverCandidates+=@(Get-ChildItem -Path $base -Filter 'llama-server.exe' -File -Recurse -ErrorAction SilentlyContinue |
    Select-Object -First 8 -ExpandProperty FullName)
 }
}
$keep='C:\RG_GITHUB_RUNNER\runner_keepalive.ps1'
$keepLines=@()
if(Test-Path -LiteralPath $keep){
 $num=0
 foreach($line in @(Get-Content -LiteralPath $keep -ErrorAction Stop)){
  $num++
  if($line -match '(?i)Start-Process|powershell|cmd\.exe|run\.cmd|start\.cmd|&\s*\$|WindowStyle|NoNewWindow|CREATE_NO_WINDOW|schtasks'){
   $keepLines += [pscustomobject]@{line=$num;text=($line.Trim()).Substring(0,[Math]::Min(200,$line.Trim().Length))}
  }
 }
}
$task=Get-ScheduledTask -TaskName 'RG_GITHUB_RUNNER_KEEPALIVE' -ErrorAction SilentlyContinue
$taskInfo=Get-ScheduledTaskInfo -TaskName 'RG_GITHUB_RUNNER_KEEPALIVE' -ErrorAction SilentlyContinue
$triggerSummary=@()
if($task){
 foreach($trigger in $task.Triggers){$triggerSummary += [pscustomobject]@{kind=$trigger.CimClass.CimClassName;enabled=$trigger.Enabled;repetition=if($trigger.Repetition){[string]$trigger.Repetition.Interval}else{''}}}
}
[pscustomobject]@{
 schema='RG_OLLAMA_AND_CONSOLE_READONLY_V1'
 date=(Get-Date).ToUniversalTime().ToString('o')
 ollama_command=if($ollama){[string]$ollama.Source}else{''}
 ollama_expected_install=$root
 install_folders=$files
 discovered_server_binaries=@($serverCandidates | Select-Object -Unique)
 ollama_processes=@(Get-Process -Name 'ollama*' -ErrorAction SilentlyContinue | Select-Object -First 10 -Property Id,ProcessName,Path)
 keepalive_script_exists=(Test-Path -LiteralPath $keep)
 keepalive_script_launch_lines=$keepLines
 keepalive_triggers=$triggerSummary
 keepalive_last_run=if($taskInfo){[string]$taskInfo.LastRunTime}else{''}
 keepalive_last_result=if($taskInfo){$taskInfo.LastTaskResult}else{$null}
}|ConvertTo-Json -Depth 9 -Compress
