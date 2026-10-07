$ErrorActionPreference='Stop'
$commit='f4740d237d25327a4d873e225df9cd6518e6081e'
$base="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control"

$tmp=Join-Path $env:TEMP 'RG_AUTO_EDIT_OPERATIONS_V1'
New-Item -ItemType Directory -Force $tmp | Out-Null
New-Item -ItemType Directory -Force (Join-Path $tmp 'operations_v1') | Out-Null

Invoke-WebRequest "$base/task_runner.py" -OutFile (Join-Path $tmp 'task_runner.py')
Invoke-WebRequest "$base/alexpc_agent.py" -OutFile (Join-Path $tmp 'alexpc_agent.py')
Invoke-WebRequest "$base/operations_v1/rg_operations_guard.py" -OutFile (Join-Path $tmp 'operations_v1\rg_operations_guard.py')

$taskText=Get-Content (Join-Path $tmp 'task_runner.py') -Raw
$agentText=Get-Content (Join-Path $tmp 'alexpc_agent.py') -Raw
$guardText=Get-Content (Join-Path $tmp 'operations_v1\rg_operations_guard.py') -Raw
if($taskText -notmatch 'apply_auto_edit_operations_v1'){throw 'OPERATIONS task runner missing'}
if($taskText -notmatch 'finalize_auto_edit_020203_operations_stable'){throw 'OPERATIONS finalizer missing'}
if($agentText -notmatch '_bundle_control_files_changed'){throw 'Agent autosync fix missing'}
if($guardText -notmatch 'RG_OPERATIONS_GUARD_V1'){throw 'Operations guard missing'}

$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'
if(!(Test-Path $runtime)){throw 'RG Auto Edit Runtime Python missing'}

& $runtime -m py_compile (Join-Path $tmp 'task_runner.py')
if($LASTEXITCODE -ne 0){throw 'task_runner.py compile failed'}
& $runtime -m py_compile (Join-Path $tmp 'alexpc_agent.py')
if($LASTEXITCODE -ne 0){throw 'alexpc_agent.py compile failed'}
& $runtime -m py_compile (Join-Path $tmp 'operations_v1\\rg_operations_guard.py')
if($LASTEXITCODE -ne 0){throw 'rg_operations_guard.py compile failed'}

Write-Host 'CONTROL LAYER COMPILE: PASS'

$nas='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control'
$local='C:\RG_AGENT\bundle_cache\rg_remote_control'
New-Item -ItemType Directory -Force $nas,$local,(Join-Path $nas 'operations_v1'),(Join-Path $local 'operations_v1') | Out-Null

Copy-Item (Join-Path $tmp 'task_runner.py') (Join-Path $nas 'task_runner.py') -Force
Copy-Item (Join-Path $tmp 'task_runner.py') (Join-Path $local 'task_runner.py') -Force
Copy-Item (Join-Path $tmp 'alexpc_agent.py') (Join-Path $nas 'alexpc_agent.py') -Force
Copy-Item (Join-Path $tmp 'alexpc_agent.py') (Join-Path $local 'alexpc_agent.py') -Force
Copy-Item (Join-Path $tmp 'operations_v1\rg_operations_guard.py') (Join-Path $nas 'operations_v1\rg_operations_guard.py') -Force
Copy-Item (Join-Path $tmp 'operations_v1\rg_operations_guard.py') (Join-Path $local 'operations_v1\rg_operations_guard.py') -Force

$localAgent='C:\RG_AGENT\alexpc_agent.py'
if(Test-Path $localAgent){Copy-Item $localAgent ($localAgent+'.pre_operations_v1.bak') -Force}
Copy-Item (Join-Path $tmp 'alexpc_agent.py') $localAgent -Force

$status='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\status\alexpc_agent.json'
$oldPid=$null
if(Test-Path $status){
  try{$oldPid=[int]((Get-Content $status -Raw | ConvertFrom-Json).pid)}catch{}
}
if($oldPid){try{Stop-Process -Id $oldPid -Force -ErrorAction Stop}catch{}}
Start-Sleep 1
schtasks /Run /TN "RG_ALEXPC_AGENT_KEEPALIVE" | Out-Null

$agentDeadline=(Get-Date).AddSeconds(45)
$newAgent=$null
while((Get-Date) -lt $agentDeadline){
  Start-Sleep 2
  if(Test-Path $status){
    try{
      $s=Get-Content $status -Raw | ConvertFrom-Json
      if($s.state -eq 'ready' -and (!$oldPid -or [int]$s.pid -ne $oldPid)){$newAgent=$s;break}
    }catch{}
  }
}
if(-not $newAgent){throw 'New NAS-first agent did not reach READY'}

Write-Host 'AGENT AUTOSYNC: OK'

$id='operations-v1-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$req='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\requests'
$res="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\results\$id.json"
$err="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\errors\$id.json"

@{
  request_id=$id
  action='apply_auto_edit_operations_v1'
  args=@{}
  timeout_seconds=1800
} | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $req "$id.json")

$deadline=(Get-Date).AddMinutes(30)
while(!(Test-Path $res) -and !(Test-Path $err) -and (Get-Date) -lt $deadline){Start-Sleep 3}

if(Test-Path $err){
  Write-Host '=== OPERATIONS INSTALL ERROR ==='
  Get-Content $err -Raw
  exit 2
}
if(!(Test-Path $res)){throw 'OPERATIONS install timeout'}

Write-Host '=== OPERATIONS INSTALL ==='
Get-Content $res -Raw

$state='F:\RG_AUTO_EDIT\RG Auto Edit Data\OPERATIONS_V1_STATE.json'
$startDeadline=(Get-Date).AddSeconds(90)
while((Get-Date) -lt $startDeadline){
  Start-Sleep 3
  if(Test-Path $state){
    try{
      $o=Get-Content $state -Raw | ConvertFrom-Json
      if($o.status -eq 'PRODUCTION_VALIDATION_RUNNING'){break}
    }catch{}
  }
}

Write-Host '=== OPERATIONS STATE ==='
if(Test-Path $state){Get-Content $state -Raw}

Write-Host '=== CURRENT GOLDEN ==='
$stable='F:\RG_AUTO_EDIT\RG Auto Edit Data\CURRENT_STABLE.json'
if(Test-Path $stable){Get-Content $stable -Raw}

Write-Host 'OPERATIONS 1-8 INSTALLED. FULL 886 VALIDATION IS APP-CONTROLLED.'
