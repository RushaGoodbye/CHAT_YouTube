$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Recovery V2 changes SHADOW code only. No pip install. No production changes.
$python='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$scriptDir=Join-Path $shadow 'scripts'
$src='\\Desktop-v7gg0en\record\886.mp4'
$ffmpeg='C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE'
$ref='daf58c959835f05979c845e70a79ebd3f9836f1b'
Write-Host '=== RG NORFAIR REAL MOTION RECOVERY V2 PREFLIGHT ==='
foreach($path in @($python,$src,$ffmpeg)){
  if(!(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required file missing: $path"}
}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production backend is active - shadow probe blocked'}
& $python -X utf8 -c "from importlib.metadata import version; import numpy, cv2, norfair; assert version('norfair')=='2.3.0'; assert version('opencv-python')=='4.11.0.86'; print('ISOLATED_DEPENDENCIES: PASS')"
if($LASTEXITCODE -ne 0){throw 'Existing Norfair/OpenCV environment failed; nothing was reinstalled'}
$evidence='F:\RG_AUTO_EDIT\RG Auto Edit Data\release_backups\PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648\RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json'
if(!(Test-Path -LiteralPath $evidence -PathType Leaf)){throw 'Original cigarette evidence missing'}
New-Item -Path $scriptDir -ItemType Directory -Force | Out-Null
$base="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1"
foreach($name in @('norfair_real_motion_8865_v1.py','norfair_real_motion_synthetic.py')){
  Invoke-WebRequest -Uri "$base/$name" -UseBasicParsing -OutFile (Join-Path $scriptDir $name)
}
& $python -m py_compile (Join-Path $scriptDir 'norfair_real_motion_8865_v1.py') (Join-Path $scriptDir 'norfair_real_motion_synthetic.py')
if($LASTEXITCODE -ne 0){throw 'Corrected shadow scripts failed syntax check'}
Write-Host '=== RG NORFAIR REAL MOTION V2 SYNTHETIC REGRESSION ==='
& $python -u -X utf8 (Join-Path $scriptDir 'norfair_real_motion_synthetic.py')
if($LASTEXITCODE -ne 0){throw 'Corrected synthetic test failed; original video remains untouched'}
Write-Host '=== RG NORFAIR REAL VIDEO 886_5 SHADOW V2 ==='
$started=(Get-Date).ToUniversalTime()
& $python -u -X utf8 (Join-Path $scriptDir 'norfair_real_motion_8865_v1.py')
if($LASTEXITCODE -ne 0){throw 'Shadow real-frame probe stopped, no production modification'}
$report=Join-Path $shadow 'norfair_886_5_real_motion_v1.json'
if(!(Test-Path -LiteralPath $report -PathType Leaf)){throw 'Real-frame report missing'}
$file=Get-Item -LiteralPath $report
if($file.LastWriteTimeUtc -lt $started.AddSeconds(-3)){throw 'Stale real-frame report, refusing success'}
$r=Get-Content -LiteralPath $report -Raw -Encoding utf8 | ConvertFrom-Json
if($r.schema -ne 'RG_OSS_NORFAIR_REAL_MOTION_SHADOW_V1' -or
   $r.summary.status -ne 'REAL_FRAMES_ANALYZED' -or
   $r.production_modified -ne $false -or $r.premiere_xml_modified -ne $false -or
   $r.audio_modified -ne $false -or $r.blur_modified -ne $false -or
   $r.stream_reprocessed -ne $false -or
   $r.decision -ne 'SHADOW_ONLY_NO_AUTOMATIC_BLUR_CLEARANCE'){
  throw 'Safety contract failed; report not accepted'
}
Write-Host '=== RG NORFAIR REAL MOTION V2 RESULT ==='
[ordered]@{
  status='PASS'
  contour=$r.contour
  frames=$r.summary.frame_probe.frame_count
  candidate_matched_frames=$r.summary.candidate_template_track.matched_frames
  candidate_missing_frames=$r.summary.candidate_template_track.unmatched_frames
  norfair_one_id=$r.summary.norfair_observations.one_id_continuity
  cigarette_confirmed_each_frame=$false
  production_changed=$false
  installation_performed=$false
  report=$report
} | ConvertTo-Json -Depth 5
