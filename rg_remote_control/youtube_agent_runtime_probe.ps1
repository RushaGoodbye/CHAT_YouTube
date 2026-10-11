$ErrorActionPreference='Stop'
$agent='C:\RG_AGENT\alexpc_agent.py'
$processes=@()
foreach($p in @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='RG YouTube Control.exe'" -ErrorAction SilentlyContinue)){
  $cmd=[string]$p.CommandLine
  $kind=if($cmd -match 'alexpc_agent\.py'){'alexpc-agent'}elseif($cmd -match 'RG YouTube Control\.exe'){'installed-gui'}elseif($cmd -match 'youtube_nas_agent\.py'){'nas-agent'}else{'other-python'}
  $processes += [pscustomobject]@{pid=$p.ProcessId;parent_pid=$p.ParentProcessId;name=$p.Name;kind=$kind;path=[string]$p.ExecutablePath}
}
$lines=@()
if(Test-Path -LiteralPath $agent){
  $n=0
  foreach($line in @(Get-Content -LiteralPath $agent -ErrorAction Stop)){
    $n++
    if($line -match '(?i)(RG YouTube Control\.exe|run_app\.py|Start-Process|subprocess\.Popen|os\.system|explorer\.exe|pythonw\.exe|CreateProcess|schtasks)'){
      $kind=if($line -match '(?i)RG YouTube Control\.exe|run_app\.py'){'gui-reference'}elseif($line -match '(?i)subprocess\.Popen|CreateProcess|os\.system'){'process-launch'}else{'launcher-reference'}
      $lines += [pscustomobject]@{line=$n;type=$kind}
    }
  }
}
[pscustomobject]@{
schema='RG_YOUTUBE_AGENT_RUNTIME_PROBE_V1'
at=(Get-Date).ToUniversalTime().ToString('o')
agent_exists=(Test-Path -LiteralPath $agent -PathType Leaf)
pythonw_related_processes=@($processes)
agent_process_references=@($lines)
}|ConvertTo-Json -Depth 6 -Compress
