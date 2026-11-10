$ErrorActionPreference='Stop'
$old='C:\Program Files\RG Auto Edit Studio'
$backup='F:\RG_AUTO_EDIT\RG Auto Edit Data\RG_REPAIR_BACKUPS\RG_F_ONLY_MIGRATION_20261110_194439_9e2c52\old_C_ProgramFiles_RG_Auto_Edit_Studio'
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\pythonw.exe'
$principal=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if(!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator_required'}
if(!(Test-Path $app) -or !(Test-Path $runtime) -or !(Test-Path $backup)){throw 'F_backup_missing'}
if(!(Test-Path $old)){Write-Output 'OLD_C_STUDIO_ALREADY_ABSENT';exit 0}
$item=Get-Item -LiteralPath $old -Force
if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Refuse_to_delete_junction'}
$files=@(Get-ChildItem -LiteralPath $old -File -Recurse)
if($files.Count -ne 13){throw 'Unexpected_old_install_file_count'}
foreach($file in $files){
  $relative=$file.FullName.Substring($old.Length).TrimStart('\')
  $copy=Join-Path $backup $relative
  if(!(Test-Path $copy)){throw "Missing_backup_$relative"}
  if((Get-FileHash $file.FullName -Algorithm SHA256).Hash -ne (Get-FileHash $copy -Algorithm SHA256).Hash){throw "Hash_mismatch_$relative"}
}
$processes=@(Get-CimInstance Win32_Process|Where-Object{$_.CommandLine -match 'rg_studio_main.py|rg_fullstream_worker_v3|RG Auto Edit Studio.exe'})
if($processes.Count){throw 'Studio_still_running'}
Remove-Item -LiteralPath $old -Force -Recurse
if(Test-Path $old){throw 'Old_C_install_still_present'}
Write-Output 'RG_OLD_C_INSTALL_REMOVED_PASS'
Write-Output "Backup: $backup"
