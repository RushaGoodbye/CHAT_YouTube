$ErrorActionPreference='Stop'
$commit='a66098882fe4b10f6e56fd1d4c1e47dad3549cfa'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/task_runner.py"
$tmp=Join-Path $env:TEMP 'rg_task_runner_post_cigarette_audit_v1.py'
$runtime='F:\\RG_AUTO_EDIT\\RG Auto Edit Runtime\\venv\\Scripts\\python.exe'

Invoke-WebRequest $url -OutFile $tmp
$src=Get-Content $tmp -Raw
if($src -notmatch 'reconcile_auto_edit_post_cigarette_v1'){throw 'Post-cigarette reconcile action missing'}
if($src -notmatch 'RG_CIGARETTE_VALIDATOR_HOTFIX_V1'){throw 'Cigarette validator hotfix missing from control layer'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'task_runner compile failed'}
Write-Host 'POST-CIGARETTE RECONCILE CONTROL: PASS'

$nas='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\BUNDLE\rg_remote_control\task_runner.py'
$local='C:\RG_AGENT\bundle_cache\rg_remote_control\task_runner.py'
Copy-Item $tmp $nas -Force
Copy-Item $tmp $local -Force

$id='post-cig-reconcile-'+(Get-Date -Format 'yyyyMMdd-HHmmss')
$req='\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\requests'
$res="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\results\$id.json"
$err="\\AlexLosServer\docker\RG_NAS_MCP\ALEXPC\auto_edit\errors\$id.json"

@{
  request_id=$id
  action='reconcile_auto_edit_post_cigarette_v1'
  args=@{}
  timeout_seconds=300
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $req "$id.json")

$deadline=(Get-Date).AddMinutes(5)
while(!(Test-Path $res) -and !(Test-Path $err) -and (Get-Date) -lt $deadline){Start-Sleep 2}

if(Test-Path $err){
  Write-Host '=== POST-CIGARETTE RECONCILE ERROR ==='
  Get-Content $err -Raw
  exit 2
}
if(!(Test-Path $res)){throw 'Post-cigarette reconcile timeout'}

Write-Host '=== POST-CIGARETTE RECONCILE RESULT ==='
Get-Content $res -Raw
