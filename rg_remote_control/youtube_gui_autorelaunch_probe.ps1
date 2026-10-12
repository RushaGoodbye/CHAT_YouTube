# Read only. Identify GUI launcher(s), local AlexPC agent version, and startup entries.
$ErrorActionPreference='Stop'
$local='C:\RG_AGENT\alexpc_agent.py'
$repo=Join-Path (Get-Location) 'rg_remote_control\alexpc_agent.py'
$objects=@()
$all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
$byPid=@{}
foreach($p in $all){$byPid[[int]$p.ProcessId]=$p}
foreach($p in $all){
  $cmd=[string]$p.CommandLine
  if($p.Name -eq 'RG YouTube Control.exe' -or $cmd -match '(?i)alexpc_agent\.py|RG_YOUTUBE_NAS_AGENT|RG YouTube Control'){
    $parent=$byPid[[int]$p.ParentProcessId]
    $objects += [pscustomobject]@{
      pid=$p.ProcessId
      name=$p.Name
      parent_name=if($parent){[string]$parent.Name}else{''}
      parent_pid=$p.ParentProcessId
      command_line=$cmd.Substring(0,[Math]::Min(400,$cmd.Length))
    }
  }
}
$startup=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$vbs=Join-Path $startup 'RG_YOUTUBE_NAS_AGENT.vbs'
$files=@()
foreach($file in @($local,$repo,$vbs)){
  if(Test-Path -LiteralPath $file -PathType Leaf){
    $contents=Get-Content -LiteralPath $file -Raw -ErrorAction Stop
    $files += [pscustomobject]@{
      name=$file
      size=(Get-Item -LiteralPath $file).Length
      sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower()
      has_periodic_gui_launcher=($contents -match '"youtube_gui": ensure_youtube_gui')
      has_gui_launch_call=($contents -match 'subprocess\.Popen\(' -and $contents -match 'RG YouTube Control')
      has_manual_gui_marker=($contents -match 'GUI_START_POLICY_MANUAL_V1')
      vbs_executable_reference=if($file -like '*.vbs'){ ($contents -replace '[\r\n]+',' ').Substring(0,[Math]::Min(650,($contents -replace '[\r\n]+',' ').Length)) }else{''}
    }
  }
}
[pscustomobject]@{
 schema='RG_YOUTUBE_GUI_AUTORELAUNCH_PROBE_V1'
 files=@($files)
 processes=@($objects)
 program_startup_link=(Test-Path -LiteralPath (Join-Path $startup 'RG YouTube Control.lnk'))
 agent_startup_link=(Test-Path -LiteralPath (Join-Path $startup 'RG AlexPC Agent.lnk'))
 youtube_api_calls=0
 mutations=0
} | ConvertTo-Json -Depth 6 -Compress
