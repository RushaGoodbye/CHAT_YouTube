# Read-only RG YouTube Control Windows inventory. No application launches or mutations.
$ErrorActionPreference = "Stop"
$matchApp = 'RG YouTube Control|RGYouTubeControl|CHAT_YouTube|run_app\.py|RG_YOUTUBE|RG-YouTube'
function SafeText($v) { if ($null -eq $v) { return "" }; return [string]$v }
function ReadRegistryInstallations {
  $items = @()
  $paths = @(
    'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'Registry::HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
  )
  foreach($path in $paths){
    try {
      foreach($app in @(Get-ItemProperty -Path $path -ErrorAction SilentlyContinue)){
        if ((SafeText $app.DisplayName) -match 'RG YouTube Control') {
          $items += [pscustomobject]@{
            display_name=SafeText $app.DisplayName
            display_version=SafeText $app.DisplayVersion
            install_location=SafeText $app.InstallLocation
            uninstall_string=SafeText $app.UninstallString
            registry_path=SafeText $app.PSPath
          }
        }
      }
    } catch {}
  }
  return @($items)
}
$processes=@()
try {
  $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
  $byPid=@{}
  foreach($p in $all){$byPid[[int]$p.ProcessId]=$p}
  foreach($p in $all){
    $name=SafeText $p.Name
    $cmd=SafeText $p.CommandLine
    $exe=SafeText $p.ExecutablePath
    if($name -match 'RG YouTube Control' -or $cmd -match $matchApp -or $exe -match $matchApp){
      $parent=$byPid[[int]$p.ParentProcessId]
      $processes += [pscustomobject]@{
        pid=[int]$p.ProcessId
        parent_pid=[int]$p.ParentProcessId
        parent_name=if($parent){SafeText $parent.Name}else{""}
        name=$name
        exe=$exe
        command_line=$cmd.Substring(0,[Math]::Min(600,$cmd.Length))
        created=SafeText $p.CreationDate
      }
    }
  }
} catch { $process_error=$_.Exception.Message }
$shortcuts=@()
try {
  $ws=New-Object -ComObject WScript.Shell
  $dirs=@(
    "$env:USERPROFILE\Desktop",
    "$env:PUBLIC\Desktop",
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"
  ) | Select-Object -Unique
  foreach($d in $dirs){
    if(-not (Test-Path -LiteralPath $d)){continue}
    foreach($file in @(Get-ChildItem -Path $d -Filter '*.lnk' -File -ErrorAction SilentlyContinue)){
      if($file.Name -notmatch '(?i)RG|YouTube|Раша'){continue}
      try {
        $link=$ws.CreateShortcut($file.FullName)
        $shortcuts += [pscustomobject]@{shortcut=$file.FullName;target=SafeText $link.TargetPath;arguments=SafeText $link.Arguments;working_dir=SafeText $link.WorkingDirectory}
      } catch {}
    }
  }
} catch {$shortcut_error=$_.Exception.Message}
$tasks=@()
try {
  foreach($task in @(Get-ScheduledTask -ErrorAction Stop)){
    $actions=@($task.Actions|ForEach-Object { ((SafeText $_.Execute)+' '+(SafeText $_.Arguments)).Trim() })
    $joined=$actions -join ' | '
    if($task.TaskName -match '(?i)RG|YouTube' -or $joined -match $matchApp){
      $info=$null
      try {$info=Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue} catch {}
      $tasks += [pscustomobject]@{
        name=$task.TaskName; path=$task.TaskPath; state=SafeText $task.State
        actions=$actions; last_run=if($info){SafeText $info.LastRunTime}else{""}
        last_result=if($info){$info.LastTaskResult}else{$null}
      }
    }
  }
} catch {$task_error=$_.Exception.Message}
$runkeys=@()
foreach($key in @('HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run')){
  try {
    $props=Get-ItemProperty -Path $key -ErrorAction Stop
    foreach($prop in $props.PSObject.Properties){
      if($prop.Name -match '^PS'){continue}
      if($prop.Name -match '(?i)RG|YouTube' -or (SafeText $prop.Value) -match $matchApp){
        $runkeys += [pscustomobject]@{key=$key;name=$prop.Name;command=SafeText $prop.Value}
      }
    }
  } catch {}
}
$source_versions=@()
foreach($path in @("$env:USERPROFILE\CHAT_YouTube-main","$env:USERPROFILE\CHAT_YouTube","C:\RG_YOUTUBE_CONTROL","C:\Program Files\RG YouTube Control","$env:LOCALAPPDATA\Programs\RG YouTube Control")){
  $project=Join-Path $path 'pyproject.toml'
  $exe=Join-Path $path 'RG YouTube Control.exe'
  $version=""
  if(Test-Path -LiteralPath $project){
    $x=Select-String -LiteralPath $project -Pattern '^version = "([^"]+)"' -ErrorAction SilentlyContinue | Select-Object -First 1
    if($x){$version=$x.Matches[0].Groups[1].Value}
  }
  $source_versions += [pscustomobject]@{
    path=$path; exists=(Test-Path -LiteralPath $path); source_version=$version
    exe_exists=(Test-Path -LiteralPath $exe)
    exe_modified=if(Test-Path -LiteralPath $exe){(Get-Item -LiteralPath $exe).LastWriteTime.ToString('o')}else{""}
  }
}
[pscustomobject]@{
  schema="RG_YOUTUBE_RUNTIME_READONLY_V1"
  at=(Get-Date).ToUniversalTime().ToString('o')
  machine=$env:COMPUTERNAME
  user=$env:USERNAME
  installations=@(ReadRegistryInstallations)
  running_processes=@($processes)
  shortcuts=@($shortcuts)
  scheduled_tasks=@($tasks)
  registry_run=@($runkeys)
  sources=@($source_versions)
  diagnostic_errors=[pscustomobject]@{
    process=SafeText $process_error
    shortcut=SafeText $shortcut_error
    tasks=SafeText $task_error
  }
} | ConvertTo-Json -Depth 10 -Compress
