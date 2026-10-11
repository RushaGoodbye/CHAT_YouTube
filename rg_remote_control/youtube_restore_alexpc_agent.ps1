# Repair only RG AlexPC Agent and duplicate GitHub Runner logon entry.
# Does not touch the YouTube desktop app, its data or NAS.
$ErrorActionPreference="Stop"
$old='C:\Users\fauto\CHAT_YouTube-main'
$python='C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\pythonw.exe'
$pythonCli='C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\python.exe'
$agent='C:\RG_AGENT\alexpc_agent.py'
$keepTaskName='RG_GITHUB_RUNNER_KEEPALIVE'
$agentTaskName='RG AlexPC Agent'
if(Test-Path -LiteralPath $old){throw 'Obsolete source folder is still present; do not alter task configuration'}
foreach($p in @($python,$pythonCli,$agent)){
  if(-not (Test-Path -LiteralPath $p -PathType Leaf)){throw "Missing independent agent prerequisite: $p"}
}
$agentTask=Get-ScheduledTask -TaskName $agentTaskName -ErrorAction Stop
$keepTask=Get-ScheduledTask -TaskName $keepTaskName -ErrorAction Stop
if([string]$keepTask.State -eq 'Disabled'){throw 'GitHub Runner keepalive scheduled task is disabled'}
$expectedKeep='C:\RG_GITHUB_RUNNER\runner_keepalive.ps1'
if(-not (Test-Path -LiteralPath $expectedKeep -PathType Leaf)){throw 'GitHub Runner keepalive script is missing'}
$actionJoined=(@($keepTask.Actions | ForEach-Object {([string]$_.Execute)+' '+([string]$_.Arguments)})) -join ' '
if($actionJoined -notlike "*$expectedKeep*"){throw 'Keepalive scheduled action differs from expected path'}
# Syntax-check original agent without executing it or installing packages.
$syntaxOut=& $pythonCli -B -c 'import ast,sys,pathlib;ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8-sig"));print("AST_PASS")' $agent 2>&1
if($LASTEXITCODE -ne 0 -or ($syntaxOut -join ' ') -notmatch 'AST_PASS'){throw "Independent agent syntax error: $syntaxOut"}
$runKey='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
$runValue=(Get-ItemProperty -Path $runKey -Name $keepTaskName -ErrorAction SilentlyContinue).$keepTaskName
if($null -ne $runValue -and ([string]$runValue -notlike "*$expectedKeep*")){throw 'Unknown registry command. Keepalive entry will not be changed'}
$root=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\agent-autostart-backup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -Path $root -ItemType Directory -Force | Out-Null
Export-ScheduledTask -TaskName $agentTaskName | Out-File (Join-Path $root 'RG-AlexPC-Agent.xml') -Encoding utf8
Export-ScheduledTask -TaskName $keepTaskName | Out-File (Join-Path $root 'Runner-Keepalive.xml') -Encoding utf8
@{name=$keepTaskName;value=[string]$runValue} | ConvertTo-Json | Set-Content (Join-Path $root 'keepalive-registry-before.json') -Encoding utf8
$oldAction=(@($agentTask.Actions | ForEach-Object {([string]$_.Execute)+' '+([string]$_.Arguments)})) -join ' '
if($oldAction -notlike '*C:\RG_AGENT\alexpc_agent.py*'){throw "Unexpected AlexPC Agent task target, aborting: $oldAction"}
$newAction=New-ScheduledTaskAction -Execute $python -Argument '"C:\RG_AGENT\alexpc_agent.py"' -WorkingDirectory 'C:\RG_AGENT'
Set-ScheduledTask -TaskName $agentTaskName -Action $newAction -ErrorAction Stop | Out-Null
Enable-ScheduledTask -TaskName $agentTaskName -ErrorAction Stop | Out-Null
Start-ScheduledTask -TaskName $agentTaskName -ErrorAction Stop
Start-Sleep -Seconds 4
$agentTaskAfter=Get-ScheduledTask -TaskName $agentTaskName -ErrorAction Stop
$agentInfo=Get-ScheduledTaskInfo -TaskName $agentTaskName -ErrorAction SilentlyContinue
$active=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {[string]$_.CommandLine -match 'C:\\RG_AGENT\\alexpc_agent\.py'} | ForEach-Object { [pscustomobject]@{pid=$_.ProcessId;name=$_.Name} })
$agentOK=($active.Count -gt 0)
# Remove duplicate logon trigger only once the scheduled keepalive path is verified.
$removedDuplicate=$false
if($null -ne $runValue){
  Remove-ItemProperty -Path $runKey -Name $keepTaskName -ErrorAction Stop
  $removedDuplicate=$true
}
$stillRegistry=(Get-ItemProperty -Path $runKey -Name $keepTaskName -ErrorAction SilentlyContinue).$keepTaskName
[pscustomobject]@{
  schema='RG_YOUTUBE_AGENT_REPAIR_V1'
  at=(Get-Date).ToUniversalTime().ToString('o')
  backup=$root
  source_folder_missing=(-not (Test-Path -LiteralPath $old))
  python=$python
  agent_task_enabled=([string]$agentTaskAfter.State -ne 'Disabled')
  agent_process_active=$agentOK
  agent_processes=$active
  agent_task_last_result=if($agentInfo){$agentInfo.LastTaskResult}else{$null}
  keepalive_scheduled_task_unchanged=$true
  keepalive_registry_duplicate_removed=$removedDuplicate
  keepalive_registry_now_absent=($null -eq $stillRegistry)
  youtube_app_untouched=$true
}|ConvertTo-Json -Depth 8 -Compress
if(-not $agentOK){throw "Agent task updated, but agent process was not confirmed. Read output and backup at $root"}
