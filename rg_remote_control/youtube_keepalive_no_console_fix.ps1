# Narrow fix: no new console when GitHub runner keepalive launches run.cmd.
$ErrorActionPreference='Stop'
$path='C:\RG_GITHUB_RUNNER\runner_keepalive.ps1'
$launcher='C:\RG_GITHUB_RUNNER\run.cmd'
if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw 'Keepalive script missing'}
if(-not(Test-Path -LiteralPath $launcher -PathType Leaf)){throw 'GitHub runner startup script missing'}
$original=Get-Content -LiteralPath $path -Raw -Encoding UTF8
$anchor="Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c','cd /d C:\RG_GITHUB_RUNNER && call run.cmd' -WindowStyle Hidden"
$occurrences=([regex]::Matches($original,[regex]::Escape($anchor))).Count
if($occurrences -ne 1){throw "Expected one known console-launch line, found $occurrences; no changes"}
$replacement=@'
$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = 'C:\Windows\System32\cmd.exe'
$startInfo.Arguments = '/d /c "cd /d C:\RG_GITHUB_RUNNER && call run.cmd"'
$startInfo.WorkingDirectory = 'C:\RG_GITHUB_RUNNER'
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
[void][System.Diagnostics.Process]::Start($startInfo)
'@
$modified=$original.Replace($anchor,$replacement)
$tokens=$null;$parseErrors=$null
[void][System.Management.Automation.Language.Parser]::ParseInput($modified,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count -gt 0){throw "PowerShell syntax validation failed; no changes"}
$backupDir=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\keepalive-backup-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -Path $backupDir -ItemType Directory -Force | Out-Null
$backup=Join-Path $backupDir 'runner_keepalive.ps1'
Copy-Item -LiteralPath $path -Destination $backup -ErrorAction Stop
$temporary="$path.tmp"
[IO.File]::WriteAllText($temporary,$modified,(New-Object System.Text.UTF8Encoding($false)))
try{Move-Item -LiteralPath $temporary -Destination $path -Force -ErrorAction Stop}
catch{
 if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue}
 throw
}
$check=Get-Content -LiteralPath $path -Raw
if(-not $check.Contains('CreateNoWindow = $true')){throw 'Post-write verification failed; backup retained'}
[pscustomobject]@{
 schema='RG_KEEPALIVE_NO_CONSOLE_V1'
 patch_applied=$true
 source_backup=$backup
 create_no_window=$true
 scheduled_task_untouched=$true
 runner_termination_requested=$false
 app_untouched=$true
 youtube_api_calls=0
}|ConvertTo-Json -Compress
