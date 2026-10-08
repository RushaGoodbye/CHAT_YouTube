$ErrorActionPreference='Stop'
$commit='22c3672753524597b04637e315aa2ca89b8746fd'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_retry_886_5.py'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$nas='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control\task_runner.py'
$local='C:\RG_AGENT\bundle_cache\rg_remote_control\task_runner.py'
$req='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\requests'
$resDir='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\results'
$errDir='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\errors'

Invoke-WebRequest $url -OutFile $tmp -UseBasicParsing
$src=Get-Content $tmp -Raw
foreach($needle in @('apply_auto_edit_resume_protection_hotfix','start_auto_edit_recovery_queue')){
  if($src -notmatch [regex]::Escape($needle)){throw "Required action missing: $needle"}
}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}
Copy-Item $tmp $nas -Force
Copy-Item $tmp $local -Force

function Invoke-RgAction([string]$action,[hashtable]$args,[int]$timeout=600){
  $id="retry-8865-"+$action+"-"+(Get-Date -Format 'yyyyMMdd-HHmmssfff')
  $res=Join-Path $resDir "$id.json"
  $err=Join-Path $errDir "$id.json"
  @{
    request_id=$id
    action=$action
    args=$args
    timeout_seconds=$timeout
  } | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $req "$id.json")
  $deadline=(Get-Date).AddSeconds($timeout+60)
  while(!(Test-Path $res) -and !(Test-Path $err) -and (Get-Date) -lt $deadline){Start-Sleep 2}
  if(Test-Path $err){throw (Get-Content $err -Raw)}
  if(!(Test-Path $res)){throw "$action timeout"}
  return (Get-Content $res -Raw | ConvertFrom-Json)
}

Write-Host 'RETRY 886_5 CONTROL: PREPARE'
$guard=Invoke-RgAction 'apply_auto_edit_resume_protection_hotfix' @{} 300
Write-Host 'RESUME PROTECTION: PASS'

$launch=Invoke-RgAction 'start_auto_edit_recovery_queue' @{streams=@('886');protect_completed_prefix=4} 300
$payload=$launch
if($null -ne $launch.result){$payload=$launch.result}
$statusFile=[string]$payload.status_file
if([string]::IsNullOrWhiteSpace($statusFile)){throw 'Recovery status_file missing'}

Write-Host '886_5 RETRY: STARTED'
Write-Host ("STATUS FILE: "+$statusFile)

$deadline=(Get-Date).AddHours(12)
$state=$null
while((Get-Date) -lt $deadline){
  if(Test-Path $statusFile){
    try{$state=Get-Content $statusFile -Raw | ConvertFrom-Json}catch{$state=$null}
    if($null -ne $state -and $state.running -eq $false){break}
  }
  Start-Sleep 5
}
if($null -eq $state -or $state.running -ne $false){throw 'Retry monitor timeout; recovery job may still be running'}

$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
$det=Join-Path $app 'RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json'
$qa=Join-Path $app 'RG_EDITED_886_5_CIGARETTE_BLUR_QA.json'
if(!(Test-Path $det)){
  $alt=Join-Path $app '886\RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json'
  if(Test-Path $alt){$det=$alt}
}
if(!(Test-Path $qa)){
  $alt=Join-Path $app '886\RG_EDITED_886_5_CIGARETTE_BLUR_QA.json'
  if(Test-Path $alt){$qa=$alt}
}

$d=$null;$q=$null
if(Test-Path $det){$d=Get-Content $det -Raw | ConvertFrom-Json}
if(Test-Path $qa){$q=Get-Content $qa -Raw | ConvertFrom-Json}

$row=$null
if($null -ne $state.rows){$row=$state.rows | Where-Object {$_.stream -eq '886'} | Select-Object -First 1}

$out=[ordered]@{
  status=if($state.overall_ok -eq $true){'PASS'}else{'FAIL'}
  stream='886'
  protected_dialogues='1-4'
  retried_from_dialogue=5
  queue_overall_ok=$state.overall_ok
  queue_row=$row
  cigarette_detection_file=if(Test-Path $det){$det}else{$null}
  cigarette_qa_file=if(Test-Path $qa){$qa}else{$null}
  cigarette_detection=if($null -ne $d){[ordered]@{
    passed=$d.passed
    status=$d.status
    raw_detection_count=$d.raw_detection_count
    confirmed_track_count=$d.confirmed_track_count
    rejected_track_count=$d.rejected_track_count
    unconfirmed_detection_count=$d.unconfirmed_detection_count
    interval_count=$d.interval_count
    failures=$d.failures
    confirmations=@($d.tracks | ForEach-Object {$_.confirmation} | Where-Object {$_} | Select-Object -Unique)
  }}else{$null}
  cigarette_qa=if($null -ne $q){[ordered]@{
    passed=$q.passed
    overlay_count=$q.overlay_count
    expected_overlay_count=$q.expected_overlay_count
    failures=$q.failures
  }}else{$null}
  mandatory=$true
  fail_closed=$true
  whole_frame_blur_forbidden=$true
}
Write-Host '=== RETRY 886_5 FINAL RESULT ==='
$out | ConvertTo-Json -Depth 10
