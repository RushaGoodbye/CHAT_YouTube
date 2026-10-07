$ErrorActionPreference='Stop'
$commit='503249dad5ae7510154824f554745dfdc6c11015'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_operations_ui_status.py'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'apply_auto_edit_operations_ui_status_hotfix_v1'){throw 'UI status hotfix action missing'}
if($src -notmatch 'ui_restart'){throw 'Post-GOLDEN UI restart hook missing'}

& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}
Write-Host 'UI STATUS HOTFIX CONTROL: PASS'

$nas='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control\task_runner.py'
$local='C:\RG_AGENT\bundle_cache\rg_remote_control\task_runner.py'
Copy-Item $tmp $nas -Force
Copy-Item $tmp $local -Force

$id='operations-ui-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$req='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\requests'
$res="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\results\$id.json"
$err="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\errors\$id.json"

@{
  request_id=$id
  action='apply_auto_edit_operations_ui_status_hotfix_v1'
  args=@{}
  timeout_seconds=300
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $req "$id.json")

$deadline=(Get-Date).AddMinutes(5)
while(!(Test-Path $res) -and !(Test-Path $err) -and (Get-Date) -lt $deadline){Start-Sleep 2}

if(Test-Path $err){
  Write-Host '=== UI HOTFIX ERROR ==='
  Get-Content $err -Raw
  exit 2
}
if(!(Test-Path $res)){throw 'UI hotfix timeout'}

Write-Host '=== UI HOTFIX RESULT ==='
Get-Content $res -Raw

$state='F:\RG_AUTO_EDIT\RG Auto Edit Data\OPERATIONS_V1_STATE.json'
if(Test-Path $state){
  try{$ops=Get-Content $state -Raw | ConvertFrom-Json}catch{$ops=$null}
  if($ops -and $ops.status -eq 'GOLDEN_STABLE'){
    $rid='operations-ui-restart-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
    $rres="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\results\$rid.json"
    $rerr="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\errors\$rid.json"
    @{
      request_id=$rid
      action='restart_auto_edit_studio_ui'
      args=@{}
      timeout_seconds=180
    } | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $req "$rid.json")
    $d=(Get-Date).AddMinutes(3)
    while(!(Test-Path $rres) -and !(Test-Path $rerr) -and (Get-Date) -lt $d){Start-Sleep 2}
    if(Test-Path $rres){
      Write-Host '=== UI RESTART ==='
      Get-Content $rres -Raw
    } elseif(Test-Path $rerr){
      Write-Host '=== UI RESTART DEFERRED ==='
      Get-Content $rerr -Raw
    }
  } else {
    Write-Host 'UI restart will happen automatically after 886 validation PASS and GOLDEN promotion.'
  }
}
