$ErrorActionPreference = 'Stop'
$source='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$data='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$oss=Join-Path $data 'oss_shadow'
$envRoot=Join-Path $data 'oss_envs\rg_oss_pilot_v1'
$python=Join-Path $envRoot 'Scripts\python.exe'
$scripts=Join-Path $oss 'scripts'
if(!(Test-Path -LiteralPath $source)){throw 'RG Auto Edit source Python runtime not found'}
if(!(Test-Path -LiteralPath $data)){throw 'F: RG Auto Edit Data missing'}
if($envRoot -like 'F:\RG_AUTO_EDIT\RG Auto Edit Runtime*'){throw 'Refusing modification of live runtime'}
New-Item -Path $scripts -ItemType Directory -Force | Out-Null
if(!(Test-Path -LiteralPath $python)){
  & $source -m venv $envRoot
  if($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $python)){throw 'Failed to create isolated OSS venv'}
}
Write-Host 'RG OSS PILOT: isolated installation on F:'
& $python -m pip install --no-input --disable-pip-version-check --only-binary=:all: --retries 1 --timeout 30 'scenedetect==0.7.1' 'psutil>=6,<8'
if($LASTEXITCODE -ne 0){throw 'OSS dependency install failed; production runtime untouched'}
$sourceRef='221e57f40a11fe535816541167c975e3569c8396'
$base="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$sourceRef/rg_remote_control/open_source_v1"
foreach($name in @('catalog.json','oss_audit.py','scene_suggest.py','health_shadow.py')){
  Invoke-WebRequest -Uri "$base/$name" -OutFile (Join-Path $scripts $name) -UseBasicParsing
}
foreach($name in @('oss_audit.py','scene_suggest.py','health_shadow.py')){
  & $python -m py_compile (Join-Path $scripts $name)
  if($LASTEXITCODE -ne 0){throw "OSS adapter compile failed: $name"}
}
& $python -c "from importlib.metadata import version; assert version('scenedetect')=='0.7.1'; import cv2, psutil, scenedetect; print('OSS_IMPORT_SMOKE: PASS')"
if($LASTEXITCODE -ne 0){throw 'OSS import smoke failed; live Auto Edit unaffected'}
$auditFile=Join-Path $oss 'rg_oss_runtime_audit_v1.json'
$healthFile=Join-Path $oss 'rg_oss_health_v1.json'
$freezeFile=Join-Path $oss 'rg_oss_packages_v1.txt'
& $python -X utf8 (Join-Path $scripts 'oss_audit.py') | Out-File -LiteralPath $auditFile -Encoding utf8 -Width 4096
if($LASTEXITCODE -ne 0){throw 'OSS audit failed'}
& $python -X utf8 (Join-Path $scripts 'health_shadow.py') | Out-File -LiteralPath $healthFile -Encoding utf8 -Width 4096
if($LASTEXITCODE -ne 0){throw 'OSS health probe failed'}
& $python -m pip freeze | Out-File -LiteralPath $freezeFile -Encoding utf8
if($LASTEXITCODE -ne 0){throw 'OSS lock inventory failed'}
$audit=Get-Content -LiteralPath $auditFile -Raw -Encoding utf8 | ConvertFrom-Json
if($audit.contour -ne 'auto_edit'){throw 'OSS audit contour mismatch'}
if($audit.safety.cigarette_mandatory -ne $true -or $audit.safety.cigarette_fail_closed -ne $true -or $audit.safety.whole_frame_blur_forbidden -ne $true){
  throw 'LIVE CIGARETTE SAFETY CHECK FAILED. Isolated pilot installed; no live changes made.'
}
Write-Host '=== RG OSS SHADOW PILOT RESULT ==='
[ordered]@{
  status='PASS'
  contour='auto_edit'
  production_runtime_modified=$false
  production_blur_modified=$false
  installed_scene_detect='0.7.1'
  isolated_python=$python
  scripts_path=$scripts
  audit_file=$auditFile
  health_file=$healthFile
  packages_file=$freezeFile
  next='OPTIONAL_READ_ONLY_SCENE_SAMPLE'
} | ConvertTo-Json -Depth 5
