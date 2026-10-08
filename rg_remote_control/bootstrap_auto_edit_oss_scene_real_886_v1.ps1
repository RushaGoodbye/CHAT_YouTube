$ErrorActionPreference='Stop'
# RG Auto Edit OSS Shadow V1. Real 886 sample, read-only; never opens production runtime.
$envRoot='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_oss_pilot_v1'
$python=Join-Path $envRoot 'Scripts\python.exe'
$base='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$adapter=Join-Path $base 'scripts\scene_suggest.py'
$video='\\Desktop-v7gg0en\record\886.mp4'
$start=9554.0
$length=12.0
$output=Join-Path $base 'scene_886_9554000_9566000.json'
Write-Host '=== RG OSS REAL SCENE SHADOW 886 PREFLIGHT ==='
foreach($required in @($python,$adapter,$video)){
  if(!(Test-Path -LiteralPath $required -PathType Leaf)){throw "Required file unavailable: $required"}
}
# Prevent competing with an active resource-intensive production backend.
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -in @('python.exe','pythonw.exe')) -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing active - skip scene sample without interference'}
& $python -c "from importlib.metadata import version; import cv2, psutil; assert version('scenedetect')=='0.7.1'; print('PILOT_IMPORT_VERIFY: PASS')"
if($LASTEXITCODE -ne 0){throw 'Isolated pilot Python dependencies failed'}
& $python -u -X utf8 $adapter --video $video --start-sec $start --duration-sec $length --output $output
if($LASTEXITCODE -ne 0){throw 'PySceneDetect sample failed. No production file changed.'}
if(!(Test-Path -LiteralPath $output -PathType Leaf)){throw 'Shadow JSON output missing'}
$d=Get-Content -LiteralPath $output -Raw -Encoding utf8 | ConvertFrom-Json
if($d.status -ne 'SHADOW_PASS' -or $d.production_applied -ne $false -or
   $d.xml_modified -ne $false -or $d.source_audio_modified -ne $false -or
   $d.cigarette_blur_modified -ne $false -or $d.dialogue_end_auto_applied -ne $false){
  throw 'Scene output failed read-only safety contract'
}
Write-Host '=== RG OSS REAL SCENE SHADOW 886 RESULT ==='
[ordered]@{
 status='PASS'
 stream=886
 window_start_sec=$start
 window_length_sec=$length
 scenes=$d.scene_count
 candidates=$d.candidate_count
 production_modified=$false
 cigarette_blur_modified=$false
 dialogue_automatically_cut=$false
 output=$output
} | ConvertTo-Json -Depth 5
