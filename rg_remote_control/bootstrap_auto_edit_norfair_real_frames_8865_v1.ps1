$ErrorActionPreference='Stop'
$python='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$scriptDir=Join-Path $shadow 'scripts'
$video='\\Desktop-v7gg0en\record\886.mp4'
$ffmpeg='C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE'
$ref='7490bb0e46b25d30f5b4c82b4e9858de60ed3d2d'
Write-Host '=== RG NORFAIR 886_5 REAL FRAMES PREFLIGHT ==='
foreach($required in @($python,$ffmpeg,$video)){
  if(!(Test-Path -LiteralPath $required -PathType Leaf)){throw "Missing source or isolated runtime file: $required"}
}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing is active - shadow test blocked to avoid GPU/CPU/SMB contention'}
$evidence='F:\RG_AUTO_EDIT\RG Auto Edit Data\release_backups\PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648\RG_EDITED_886_5_CIGARETTE_BLUR_DETECTIONS.json'
if(!(Test-Path -LiteralPath $evidence -PathType Leaf)){throw 'Saved evidence missing; no installation attempted'}
Write-Host 'Installing pinned OpenCV ONLY into isolated Norfair venv'
& $python -m pip install --disable-pip-version-check --no-input --only-binary=:all: --retries 1 --timeout 30 'opencv-python==4.11.0.86'
if($LASTEXITCODE -ne 0){throw 'Isolated OpenCV install failed; production runtime unchanged'}
New-Item -Path $scriptDir -ItemType Directory -Force | Out-Null
$base="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1"
foreach($name in @('norfair_real_motion_8865_v1.py','norfair_real_motion_synthetic.py')){
  Invoke-WebRequest -Uri "$base/$name" -OutFile (Join-Path $scriptDir $name) -UseBasicParsing
}
& $python -m py_compile (Join-Path $scriptDir 'norfair_real_motion_8865_v1.py') (Join-Path $scriptDir 'norfair_real_motion_synthetic.py')
if($LASTEXITCODE -ne 0){throw 'Real-motion code syntax error'}
& $python -u -X utf8 (Join-Path $scriptDir 'norfair_real_motion_synthetic.py')
if($LASTEXITCODE -ne 0){throw 'Real-motion synthetic regression failed. Actual user video not accessed.'}
Write-Host '=== RG NORFAIR 886_5 REAL VIDEO SHADOW TEST ==='
Write-Host 'Reads a small section of 886.mp4, extracts temporary image frames on F:, writes diagnostics only.'
& $python -u -X utf8 (Join-Path $scriptDir 'norfair_real_motion_8865_v1.py')
if($LASTEXITCODE -ne 0){throw 'Real-video shadow probe failed; existing Premiere XML and audio remain untouched'}
$report=Join-Path $shadow 'norfair_886_5_real_motion_v1.json'
if(!(Test-Path -LiteralPath $report -PathType Leaf)){throw 'Real video benchmark report missing'}
$r=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.production_modified -ne $false -or $r.premiere_xml_modified -ne $false -or
   $r.audio_modified -ne $false -or $r.blur_modified -ne $false -or
   $r.stream_reprocessed -ne $false -or $r.decision -ne 'SHADOW_ONLY_NO_AUTOMATIC_BLUR_CLEARANCE'){
  throw 'Read-only contract failed; report must not be trusted'
}
Write-Host '=== RG NORFAIR 886_5 REAL VIDEO SHADOW COMPLETE ==='
[ordered]@{
  status='PASS'
  shadow_only=$true
  sampled_frames=$r.summary.frame_probe.frame_count
  matched_template_frames=$r.summary.candidate_template_track.matched_frames
  unmatched_frames=$r.summary.candidate_template_track.unmatched_frames
  max_estimated_motion_px=$r.summary.candidate_template_track.max_displacement_px
  norfair_one_id_continuity=$r.summary.norfair_observations.one_id_continuity
  cigarette_every_frame_confirmed=$false
  production_modified=$false
  report=$report
} | ConvertTo-Json -Depth 5
