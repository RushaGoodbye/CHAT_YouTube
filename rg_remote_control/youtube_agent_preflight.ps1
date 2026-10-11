$ErrorActionPreference='Stop'
$old='C:\Users\fauto\CHAT_YouTube-main'
$agent='C:\RG_AGENT\alexpc_agent.py'
$pyCandidates=@(
'C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\pythonw.exe',
'C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\python.exe',
'C:\Program Files\Python312\pythonw.exe',
'C:\Program Files\Python312\python.exe')
$py=@($pyCandidates | ForEach-Object { [pscustomobject]@{path=$_;exists=(Test-Path -LiteralPath $_ -PathType Leaf)} })
$task=Get-ScheduledTask -TaskName 'RG AlexPC Agent' -ErrorAction SilentlyContinue
$keepTask=Get-ScheduledTask -TaskName 'RG_GITHUB_RUNNER_KEEPALIVE' -ErrorAction SilentlyContinue
$runKey='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
$runValue=(Get-ItemProperty -Path $runKey -Name 'RG_GITHUB_RUNNER_KEEPALIVE' -ErrorAction SilentlyContinue).RG_GITHUB_RUNNER_KEEPALIVE
$taskArgs=if($task){@($task.Actions | ForEach-Object { [string]$_.Execute+' '+[string]$_.Arguments })}else{@()}
$keepArgs=if($keepTask){@($keepTask.Actions | ForEach-Object { [string]$_.Execute+' '+[string]$_.Arguments })}else{@()}
$running=@(Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match '^(pythonw?|powershell|pwsh)\.exe$' -and
  $_.CommandLine -match '(alexpc_agent\.py|youtube_nas_agent\.py|runner_keepalive\.ps1)'
} | ForEach-Object { [pscustomobject]@{pid=$_.ProcessId;name=$_.Name;agent=if($_.CommandLine -match 'alexpc_agent\.py'){'alexpc'}elseif($_.CommandLine -match 'youtube_nas_agent\.py'){'youtube_nas'}else{'runner_keepalive'} } })
$agentLength=if(Test-Path -LiteralPath $agent){(Get-Item -LiteralPath $agent).Length}else{0}
$keepScript='C:\RG_GITHUB_RUNNER\runner_keepalive.ps1'
$keepInfo=if(Test-Path -LiteralPath $keepScript){[pscustomobject]@{exists=$true;bytes=(Get-Item -LiteralPath $keepScript).Length}}else{[pscustomobject]@{exists=$false;bytes=0}}
[pscustomobject]@{
schema='RG_AGENT_PREFLIGHT_V1'
source_exists=(Test-Path -LiteralPath $old)
alexpc_agent_exists=(Test-Path -LiteralPath $agent -PathType Leaf)
alexpc_agent_bytes=$agentLength
python_candidates=$py
agent_task_exists=($null -ne $task)
agent_task_state=if($task){[string]$task.State}else{''}
agent_task_actions=$taskArgs
runner_keepalive_task_exists=($null -ne $keepTask)
runner_keepalive_task_state=if($keepTask){[string]$keepTask.State}else{''}
runner_keepalive_task_actions=$keepArgs
runner_keepalive_registry_exists=($null -ne $runValue)
runner_keepalive_registry_command=[string]$runValue
runner_keepalive_script=$keepInfo
running=$running
}|ConvertTo-Json -Depth 7 -Compress
