# Non-admin recovery: user Startup shortcut for independent AlexPC agent.
# Preserve the disabled legacy scheduled task. Remove only duplicate HKCU Runner logon.
$ErrorActionPreference='Stop'
$obsolete='C:\Users\fauto\CHAT_YouTube-main'
$agent='C:\RG_AGENT\alexpc_agent.py'
$python='C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\pythonw.exe'
$pythonCli='C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\python.exe'
$keepName='RG_GITHUB_RUNNER_KEEPALIVE'
$keepPath='C:\RG_GITHUB_RUNNER\runner_keepalive.ps1'
$oldTask=Get-ScheduledTask -TaskName 'RG AlexPC Agent' -ErrorAction Stop
if([string]$oldTask.State -ne 'Disabled'){throw 'Existing agent scheduled task is enabled; do not create a duplicate'}
if(Test-Path -LiteralPath $obsolete){throw 'Old 0.5.2 folder unexpectedly exists'}
foreach($path in @($agent,$python,$pythonCli,$keepPath)){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required prerequisite missing: $path"}
}
$runnerTask=Get-ScheduledTask -TaskName $keepName -ErrorAction Stop
if([string]$runnerTask.State -eq 'Disabled'){throw 'Runner keepalive scheduled task is disabled'}
$runnerCommand=(@($runnerTask.Actions|ForEach-Object {([string]$_.Execute)+' '+([string]$_.Arguments)})) -join ' '
if($runnerCommand -notlike "*$keepPath*"){throw 'Runner keepalive task does not match known script'}
$oldPref=$ErrorActionPreference
$ErrorActionPreference='Continue'
$compile=& $pythonCli -B -m py_compile $agent 2>&1
$exit=$LASTEXITCODE
$ErrorActionPreference=$oldPref
if($exit -ne 0){throw "Agent Python syntax check failed: $($compile|Out-String)"}
$root=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\user-agent-startup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -Path $root -ItemType Directory -Force | Out-Null
$startup=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
New-Item -Path $startup -ItemType Directory -Force | Out-Null
$linkPath=Join-Path $startup 'RG AlexPC Agent.lnk'
$ws=New-Object -ComObject WScript.Shell
if(Test-Path -LiteralPath $linkPath){Copy-Item -LiteralPath $linkPath -Destination (Join-Path $root 'RG AlexPC Agent.previous.lnk') -Force}
$lnk=$ws.CreateShortcut($linkPath)
$lnk.TargetPath=$python
$lnk.Arguments='"C:\RG_AGENT\alexpc_agent.py"'
$lnk.WorkingDirectory='C:\RG_AGENT'
$lnk.Description='RG AlexPC Agent - independent user logon start'
$lnk.Save()
$verify=$ws.CreateShortcut($linkPath)
if(-not ([string]$verify.TargetPath).Equals($python,[StringComparison]::OrdinalIgnoreCase)){throw "Agent Startup shortcut verification failed"}
$key='HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
$oldValue=(Get-ItemProperty -Path $key -Name $keepName -ErrorAction SilentlyContinue).$keepName
@{name=$keepName;command=[string]$oldValue} | ConvertTo-Json | Set-Content -Path (Join-Path $root 'runner-logon-before.json') -Encoding utf8
if($null -ne $oldValue){
 if([string]$oldValue -notlike "*$keepPath*"){throw 'Unexpected Runner registry value, do not change'}
 Remove-ItemProperty -Path $key -Name $keepName -ErrorAction Stop
}
$registryAfter=(Get-ItemProperty -Path $key -Name $keepName -ErrorAction SilentlyContinue).$keepName
$launched=$false
$launchError=''
try{
 $p=Start-Process -FilePath 'explorer.exe' -ArgumentList ('"'+$linkPath+'"') -PassThru -ErrorAction Stop
 $launched=$true
}catch{$launchError=$_.Exception.Message}
[pscustomobject]@{
 schema='RG_YOUTUBE_USER_AGENT_RECOVERY_V1'
 backup=$root
 old_source_absent=$true
 independent_python=$python
 startup_shortcut=$linkPath
 startup_shortcut_verified=$true
 old_agent_scheduled_task_left_disabled=$true
 launch_via_explorer_requested=$launched
 launch_error=$launchError
 runner_keepalive_scheduled_task_preserved=$true
 duplicate_runner_registry_removed=($null -ne $oldValue)
 runner_registry_now_absent=($null -eq $registryAfter)
 app_data_untouched=$true
 youtube_api_calls=0
}|ConvertTo-Json -Depth 5 -Compress
