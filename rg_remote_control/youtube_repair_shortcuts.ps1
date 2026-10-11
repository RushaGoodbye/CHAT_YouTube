# Restore a single authoritative installed RG YouTube Control shortcut set.
# No application termination, no removal of sources, no YouTube API.
$ErrorActionPreference='Stop'
$exe='C:\Program Files\RG YouTube Control\RG YouTube Control.exe'
if(-not (Test-Path -LiteralPath $exe -PathType Leaf)){throw "Installed RG YouTube Control EXE is missing"}
$app=Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A84C24D2-6A48-4F42-9B8C-6F1A8EBDBD2B}_is1' -ErrorAction Stop
$installedVersion=[string]$app.DisplayVersion
if(-not $installedVersion){throw "Installed version is missing from registry"}
if(([version]$installedVersion) -lt ([version]'0.7.11')){throw "Installed version is older than 0.7.11"}
if(-not ([string]$app.InstallLocation).StartsWith('C:\Program Files\RG YouTube Control',[StringComparison]::OrdinalIgnoreCase)){throw "Unexpected installation directory"}
$desktop=Join-Path $env:USERPROFILE 'Desktop\RG YouTube Control.lnk'
$programs=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$shortcuts=@(
  $desktop,
  (Join-Path $programs 'RG YouTube Control.lnk'),
  (Join-Path $programs 'Startup\RG YouTube Control.lnk')
)
$backupRoot=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\shortcut-backup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -Path $backupRoot -ItemType Directory -Force | Out-Null
$ws=New-Object -ComObject WScript.Shell
$results=@()
foreach($path in $shortcuts){
  $parent=Split-Path $path -Parent
  New-Item -Path $parent -ItemType Directory -Force | Out-Null
  $previous=$null
  if(Test-Path -LiteralPath $path){
    $old=$ws.CreateShortcut($path)
    $previous=[pscustomobject]@{target=[string]$old.TargetPath;arguments=[string]$old.Arguments;working_dir=[string]$old.WorkingDirectory}
    $dest=Join-Path $backupRoot ((($path -replace '[^A-Za-z0-9]', '_') -replace '_+','_')+'.lnk')
    Copy-Item -LiteralPath $path -Destination $dest -Force
  }
  $s=$ws.CreateShortcut($path)
  $s.TargetPath=$exe
  $s.Arguments=''
  $s.WorkingDirectory=Split-Path $exe -Parent
  $s.IconLocation="$exe,0"
  $s.Description='RG YouTube Control - installed Windows application'
  $s.Save()
  $verified=$ws.CreateShortcut($path)
  if(-not ([string]$verified.TargetPath).Equals($exe,[StringComparison]::OrdinalIgnoreCase)){
    throw "Shortcut verification failed: $path"
  }
  $results += [pscustomobject]@{
    shortcut=$path;before=$previous;after_target=[string]$verified.TargetPath
    after_arguments=[string]$verified.Arguments;verified=$true
  }
}
[pscustomobject]@{
  schema='RG_YOUTUBE_SHORTCUT_FIX_V1'
  machine=$env:COMPUTERNAME
  installed_version=$installedVersion
  installation=$exe
  backup_directory=$backupRoot
  fixed=$results.Count
  shortcuts=@($results)
  active_processes_untouched=$true
  no_uninstall=$true
  youtube_api_calls=0
}|ConvertTo-Json -Depth 8 -Compress
