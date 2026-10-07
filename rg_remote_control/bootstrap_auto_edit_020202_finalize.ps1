$ErrorActionPreference='Stop'
$taskCommit='094fe403304bef1eb9b487fc2af79aca04759a72'
$agentCommit='27cd11748ba75f9aff88827ba7488964245288df'

$taskUrl="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$taskCommit/rg_remote_control/task_runner.py"
$agentUrl="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$agentCommit/rg_remote_control/alexpc_agent.py"

$tmpTask=Join-Path $env:TEMP 'rg_task_runner_020202_finalize.py'
$tmpAgent=Join-Path $env:TEMP 'rg_alexpc_agent_syncfix.py'

Invoke-WebRequest $taskUrl -OutFile $tmpTask
Invoke-WebRequest $agentUrl -OutFile $tmpAgent

$taskText=Get-Content $tmpTask -Raw
$agentText=Get-Content $tmpAgent -Raw
if($taskText -notmatch 'finalize_auto_edit_020202_stable'){throw 'Missing 0.20.20.2 finalize action'}
if($agentText -notmatch '_bundle_control_files_changed'){throw 'Missing AlexPC agent control-file sync fix'}

$nasControl='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control'
$localControl='C:\RG_AGENT\bundle_cache\rg_remote_control'
$localAgent='C:\RG_AGENT\alexpc_agent.py'

New-Item -ItemType Directory -Force $nasControl,$localControl | Out-Null
Copy-Item $tmpTask (Join-Path $nasControl 'task_runner.py') -Force
Copy-Item $tmpTask (Join-Path $localControl 'task_runner.py') -Force
Copy-Item $tmpAgent (Join-Path $nasControl 'alexpc_agent.py') -Force
Copy-Item $tmpAgent (Join-Path $localControl 'alexpc_agent.py') -Force

if(Test-Path $localAgent){
  Copy-Item $localAgent ($localAgent+'.pre020202.bak') -Force
}
Copy-Item $tmpAgent $localAgent -Force

$id='finalize-020202-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$reqDir='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\requests'
$resultPath="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\results\$id.json"
$errorPath="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\errors\$id.json"

@{
  request_id=$id
  action='finalize_auto_edit_020202_stable'
  args=@{}
  timeout_seconds=1800
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $reqDir "$id.json")

$deadline=(Get-Date).AddMinutes(20)
while(!(Test-Path $resultPath) -and !(Test-Path $errorPath) -and (Get-Date) -lt $deadline){
  Start-Sleep 3
}

if(Test-Path $errorPath){
  Write-Host '=== FINALIZE ERROR ==='
  Get-Content $errorPath -Raw
  exit 2
}
if(!(Test-Path $resultPath)){
  throw 'Finalize timeout'
}

Write-Host '=== FINALIZE RESULT ==='
$resultText=Get-Content $resultPath -Raw
$resultText

$resultJson=$resultText | ConvertFrom-Json
if(-not $resultJson.ok){throw 'Finalize returned ok=false'}

# Activate the upgraded long-running NAS-first agent only after finalize completed.
$statusPath='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\status\alexpc_agent.json'
$oldPid=$null
if(Test-Path $statusPath){
  try{$oldPid=[int]((Get-Content $statusPath -Raw | ConvertFrom-Json).pid)}catch{}
}
if($oldPid){
  try{Stop-Process -Id $oldPid -Force -ErrorAction Stop}catch{}
}
Start-Sleep 1
try{schtasks /Run /TN "RG_ALEXPC_AGENT_KEEPALIVE" | Out-Null}catch{}

$agentDeadline=(Get-Date).AddSeconds(30)
$newStatus=$null
while((Get-Date) -lt $agentDeadline){
  Start-Sleep 2
  if(Test-Path $statusPath){
    try{
      $candidate=Get-Content $statusPath -Raw | ConvertFrom-Json
      if($candidate.state -eq 'ready' -and (!$oldPid -or [int]$candidate.pid -ne $oldPid)){
        $newStatus=$candidate
        break
      }
    }catch{}
  }
}

Write-Host '=== AGENT STATUS ==='
if(Test-Path $statusPath){Get-Content $statusPath -Raw}
if(-not $newStatus){throw 'AlexPC agent did not restart into READY state with a new PID'}
if((Get-Content $localAgent -Raw) -notmatch '_bundle_control_files_changed'){
  throw 'AlexPC agent autosync fix is not installed locally'
}
Write-Host 'AGENT AUTOSYNC FIX: OK'
Write-Host 'RG AUTO EDIT 0.20.20.2 FINALIZATION COMPLETE'
