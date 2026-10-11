# Keep the independent AlexPC agent as the single GUI launcher at logon.
# Back up and remove only the redundant per-user RG YouTube Control Startup shortcut.
$ErrorActionPreference='Stop'
$startup=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$appLink=Join-Path $startup 'RG YouTube Control.lnk'
$agentLink=Join-Path $startup 'RG AlexPC Agent.lnk'
$installed='C:\Program Files\RG YouTube Control\RG YouTube Control.exe'
$agent='C:\RG_AGENT\alexpc_agent.py'
$python='C:\Users\fauto\AppData\Local\Python\pythoncore-3.12-64\pythonw.exe'
if(-not(Test-Path -LiteralPath $installed -PathType Leaf)){throw 'Installed GUI not found'}
if(-not(Test-Path -LiteralPath $agentLink -PathType Leaf)){throw 'Independent agent Startup shortcut missing'}
$ws=New-Object -ComObject WScript.Shell
$ag=$ws.CreateShortcut($agentLink)
if(-not ([string]$ag.TargetPath).Equals($python,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected agent Startup shortcut target'}
if([string]$ag.Arguments -notlike "*$agent*"){throw 'Unexpected agent Startup shortcut arguments'}
$active=@(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { [string]$_.CommandLine -like "*$agent*" })
if($active.Count -lt 1){throw 'Independent agent is not active; retain GUI Startup fallback'}
$backup=''
$removed=$false
if(Test-Path -LiteralPath $appLink -PathType Leaf){
 $gui=$ws.CreateShortcut($appLink)
 if(-not ([string]$gui.TargetPath).Equals($installed,[StringComparison]::OrdinalIgnoreCase)){throw 'GUI Startup shortcut points to an unexpected executable'}
 $root=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\single-gui-startup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
 New-Item -Path $root -ItemType Directory -Force | Out-Null
 $backup=Join-Path $root 'RG YouTube Control.lnk'
 Move-Item -LiteralPath $appLink -Destination $backup -ErrorAction Stop
 $removed=$true
}
[pscustomobject]@{
 schema='RG_YOUTUBE_SINGLE_GUI_STARTUP_V1'
 agent_process_active=($active.Count -gt 0)
 agent_startup_verified=$true
 redundant_gui_startup_removed=$removed
 original_link_backup=$backup
 gui_installed_exe=$installed
 gui_process_untouched=$true
 desktop_shortcut_untouched=$true
 program_data_untouched=$true
 youtube_api_calls=0
}|ConvertTo-Json -Depth 5 -Compress
