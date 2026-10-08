$ErrorActionPreference='Stop'
$mainPy='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$data='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$venv=Join-Path $data 'oss_envs\rg_norfair_shadow_v1'
$ossPy=Join-Path $venv 'Scripts\python.exe'
$ossRoot=Join-Path $data 'oss_shadow'
$adapter=Join-Path $ossRoot 'scripts\norfair_saved_hits_8865.py'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/c63ef72118b83af21ca6278fc305c2a3343fc8f3/rg_remote_control/open_source_v1/norfair_saved_hits_8865.py'
Write-Host '=== RG NORFAIR 886_5 ISOLATED PREFLIGHT ==='
if(!(Test-Path -LiteralPath $mainPy -PathType Leaf)){throw 'RG source Python missing; no changes made'}
if(!(Test-Path -LiteralPath $data -PathType Container)){throw 'RG Data F: missing'}
$evidence=Join-Path $data 'release_backups\PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648\RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json'
$current='F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json'
$qa='F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5_CIGARETTE_BLUR_QA.json'
foreach($path in @($evidence,$current,$qa)){
  if(!(Test-Path -LiteralPath $path -PathType Leaf)){
    throw "886_5 evidence missing; no installation attempted: $path"
  }
}
# No production or existing PySceneDetect venv modules may be replaced.
if(!(Test-Path -LiteralPath $ossPy -PathType Leaf)){
  & $mainPy -m venv $venv
  if($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $ossPy)){
    throw 'Unable to create separate Norfair shadow virtual environment'
  }
}
Write-Host 'Installing Norfair 2.3.0 in independent F: shadow venv (never production)'
& $ossPy -m pip install --disable-pip-version-check --no-input --retries 1 --timeout 25 'norfair==2.3.0'
if($LASTEXITCODE -ne 0){throw 'Norfair shadow installation failed; no production files touched'}
& $ossPy -c "from importlib.metadata import version; import numpy; from norfair import Tracker,Detection; assert version('norfair')=='2.3.0'; print('RG_NORFAIR_IMPORT: PASS')"
if($LASTEXITCODE -ne 0){throw 'Norfair library import failed in isolated venv'}
New-Item -ItemType Directory -Path (Split-Path $adapter -Parent) -Force | Out-Null
Invoke-WebRequest -Uri $url -OutFile $adapter -UseBasicParsing
& $ossPy -m py_compile $adapter
if($LASTEXITCODE -ne 0){throw 'Norfair shadow adapter syntax error; no production files touched'}
& $ossPy -u -X utf8 $adapter
if($LASTEXITCODE -ne 0){throw 'Norfair shadow evidence check stopped; see STOPPED block above'}
$report=Join-Path $ossRoot 'norfair_886_5_v1.json'
if(!(Test-Path -LiteralPath $report -PathType Leaf)){throw 'Norfair shadow output was not created'}
$r=Get-Content -LiteralPath $report -Raw -Encoding utf8 | ConvertFrom-Json
if($r.production_adopted -ne $false -or $r.xml_modified -ne $false -or
   $r.audio_modified -ne $false -or $r.cigarette_blur_modified -ne $false){
  throw 'Norfair shadow safety contract failed'
}
Write-Host '=== RG NORFAIR 886_5 SHADOW PILOT COMPLETE ==='
[ordered]@{
 status=$r.tracker.status
 matched_one_object=$r.tracker.matched_one_object
 original_hit_count=$r.inputs.original_detection_count
 production_modified=$false
 original_audio_modified=$false
 blur_modified=$false
 environment=$ossPy
 report=$report
 next='Do not adopt Norfair in production without multi-frame video benchmark'
} | ConvertTo-Json -Depth 4
