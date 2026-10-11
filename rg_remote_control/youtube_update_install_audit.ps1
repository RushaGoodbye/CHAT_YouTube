# Read-only audit of update 0.7.15: what EXE was received and what Windows runs.
$ErrorActionPreference='Stop'
$installed='C:\Program Files\RG YouTube Control\RG YouTube Control.exe'
$uninstall='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A84C24D2-6A48-4F42-9B8C-6F1A8EBDBD2B}_is1'
$roots=@("$env:USERPROFILE\Downloads", "$env:LOCALAPPDATA\RGYouTubeControl\updates", "$env:TEMP")
$files=@()
foreach($root in $roots){
 if(-not (Test-Path -LiteralPath $root)){continue}
 foreach($f in @(Get-ChildItem -LiteralPath $root -File -ErrorAction SilentlyContinue | Where-Object {$_.Name -match '^RG_YouTube_Control_(Setup|Update)_0\.7\.(13|14|15)\.(exe|zip)$'})){
  $files += [pscustomobject]@{name=$f.Name;bytes=$f.Length;modified=$f.LastWriteTime.ToString('o');directory=$root;sha256=if($f.Name -match '0\.7\.15'){(Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash.ToLower()}else{''}}
 }
}
$installedFile=Get-Item -LiteralPath $installed -ErrorAction SilentlyContinue
$app=Get-ItemProperty -LiteralPath $uninstall -ErrorAction SilentlyContinue
$programs=@()
try{$programs=@(Get-CimInstance Win32_Process -Filter "Name='RG YouTube Control.exe'" -ErrorAction SilentlyContinue | Select-Object -First 4 -Property ProcessId,Name,ExecutablePath,CreationDate)}catch{}
[pscustomobject]@{
 schema='RG_YOUTUBE_UPDATE_INSTALL_AUDIT_V1'
 installed_exists=($null -ne $installedFile)
 installed_modified=if($installedFile){$installedFile.LastWriteTime.ToString('o')}else{''}
 installed_bytes=if($installedFile){$installedFile.Length}else{0}
 installed_fileversion=if($installedFile){$installedFile.VersionInfo.FileVersion}else{''}
 registry_version=if($app){[string]$app.DisplayVersion}else{''}
 downloads_and_staged_installers=@($files)
 current_processes=$programs
 user=$env:USERNAME
}|ConvertTo-Json -Depth 6 -Compress
