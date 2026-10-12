# Live patch independent AlexPC agent only; preserve YouTube GUI and other services.
$ErrorActionPreference='Stop'
$local='C:\RG_AGENT\alexpc_agent.py'
$source=Join-Path (Get-Location) 'rg_remote_control\alexpc_agent.py'
$pythonw='C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\pythonw.exe'
$expectedOldSha='fff931309fa24351efb796ab09f019b8aa7ab4876c2fcd99f074bc1b0995265f'
if($env:COMPUTERNAME.ToUpperInvariant() -ne 'ALEXPC'){throw 'Wrong host'}
if(-not(Test-Path -LiteralPath $local -PathType Leaf)){throw 'Agent missing'}
if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw 'Verified source missing'}
if(-not(Test-Path -LiteralPath $pythonw -PathType Leaf)){throw 'Pythonw missing'}
$beforeHash=(Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash.ToLower()
$newHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower()
$newText=Get-Content -LiteralPath $source -Raw
if($newText -notmatch 'GUI_START_POLICY_MANUAL_V1'){throw 'Manual launch policy absent'}
$fn=($newText -split 'def ensure_youtube_gui\(\) -> dict:',2)[1] -split 'def ensure_ollama\(\) -> dict:',2
if($fn.Count -ne 2 -or $fn[0] -match '(?i)subprocess\.Popen|run_app\.py'){throw 'GUI auto launcher still in function'}
if($newText -notmatch '"ollama": ensure_ollama'){throw 'Ollama heartbeat not preserved'}
if($beforeHash -ne $expectedOldSha -and $beforeHash -ne $newHash){throw ('Unexpected agent build, stop for safety: '+$beforeHash)}
$statusPath='C:\RG_AGENT\state\agent_status.json'
if(Test-Path -LiteralPath $statusPath){
  $status=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
  if($status.state -eq 'busy'){throw 'NAS agent is busy; will not interrupt work'}
}
$running=@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
 Where-Object { [string]$_.CommandLine -match '(?i)C:\\RG_AGENT\\alexpc_agent\.py' })
if($running.Count -ne 1){throw ('Expected one agent process, got '+$running.Count)}
$beforeGui=@(Get-CimInstance Win32_Process -Filter "Name='RG YouTube Control.exe'" |
 ForEach-Object {[int]$_.ProcessId})
$backupRoot=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\gui-manual-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$backup=Join-Path $backupRoot 'alexpc_agent_before.py'
Copy-Item -LiteralPath $local -Destination $backup -Force
$stage=$local+'.manual.new'
Copy-Item -LiteralPath $source -Destination $stage -Force
if((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash.ToLower() -ne $newHash){
 throw 'Staged agent SHA256 mismatch'
}
if($beforeHash -ne $newHash){
  Move-Item -LiteralPath $stage -Destination $local -Force
}else{
  Remove-Item -LiteralPath $stage -Force
}
if((Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash.ToLower() -ne $newHash){
 throw 'Patched agent SHA256 mismatch'
}
# Restart ONLY the RG AlexPC agent; never terminate the desktop GUI,
# GitHub runner, Ollama, or NAS services.
Stop-Process -Id ([int]$running[0].ProcessId) -Force -ErrorAction Stop
Start-Sleep -Milliseconds 1200
Start-Process -FilePath $pythonw -ArgumentList '"C:\RG_AGENT\alexpc_agent.py"' -WorkingDirectory 'C:\RG_AGENT' -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 6
$afterAgent=@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
 Where-Object { [string]$_.CommandLine -match '(?i)C:\\RG_AGENT\\alexpc_agent\.py' })
if($afterAgent.Count -ne 1){throw ('Agent did not restart successfully: '+$afterAgent.Count)}
$afterGui=@(Get-CimInstance Win32_Process -Filter "Name='RG YouTube Control.exe'" |
 ForEach-Object {[int]$_.ProcessId})
$statusAfter=$null
$policy=''
for($check=0;$check -lt 20;$check++){
  if(Test-Path -LiteralPath $statusPath){
    $statusAfter=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $policy=[string]$statusAfter.services.youtube_gui.launch_policy
    if($policy -eq 'manual'){break}
  }
  Start-Sleep -Seconds 2
}
if($policy -ne 'manual'){throw ('Agent did not activate manual policy: '+$policy)}
if((@($beforeGui | Sort-Object) -join ',') -ne (@($afterGui | Sort-Object) -join ',')){
 throw 'GUI PID changed unexpectedly; inspect before further edits'
}
[pscustomobject]@{
 schema='RG_YOUTUBE_MANUAL_GUI_FIX_V1'
 status='PASS'
 old_agent_pid=[int]$running[0].ProcessId
 new_agent_pid=[int]$afterAgent[0].ProcessId
 agent_sha256=$newHash
 backup=$backup
 launch_policy=$policy
 gui_running_count=$afterGui.Count
 gui_pid_unchanged=$true
 ollama_service_preserved=($null -ne $statusAfter.services.ollama)
 nas_agent_running=$true
 github_runner_untouched=$true
 user_startup_shortcuts_untouched=$true
 youtube_api_calls=0
} | ConvertTo-Json -Depth 5 -Compress
