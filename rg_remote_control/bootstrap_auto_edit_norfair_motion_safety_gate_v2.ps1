$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$python='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$scriptDir=Join-Path $shadow 'scripts'
$originalBenchmark=Join-Path $scriptDir 'norfair_motion_challenge_v1.py'
$updated=Join-Path $scriptDir 'norfair_motion_safety_gate_v2.py'
$output=Join-Path $shadow 'norfair_motion_safety_gate_v2.json'
$ref='4eefaaa7ee20b65a241666a6d7b8ac122e96ef88'
Write-Host '=== RG NORFAIR SAFETY GATE V2 PREFLIGHT ==='
foreach($p in @($python,$originalBenchmark)){
  if(!(Test-Path -LiteralPath $p -PathType Leaf)){throw "Existing shadow dependency missing: $p"}
}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing active; test skipped to avoid contention'}
& $python -X utf8 -c "from importlib.metadata import version; import cv2, norfair; assert version('norfair')=='2.3.0' and version('opencv-python')=='4.11.0.86'; print('ISOLATED_LIBRARY_CHECK: PASS')"
if($LASTEXITCODE -ne 0){throw 'Shadow libraries unavailable; no reinstall attempted'}
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1/norfair_motion_safety_gate_v2.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $updated
& $python -m py_compile $updated
if($LASTEXITCODE -ne 0){throw 'V2 shadow syntax invalid; no production files changed'}
$started=(Get-Date).ToUniversalTime()
& $python -u -X utf8 $updated --output $output
if($LASTEXITCODE -ne 0){throw 'V2 safety gate regression failed; production is unchanged'}
if(!(Test-Path -LiteralPath $output -PathType Leaf)){throw 'V2 safety report missing'}
$item=Get-Item -LiteralPath $output
if($item.LastWriteTimeUtc -lt $started.AddSeconds(-3)){throw 'Stale report, cannot accept'}
$r=Get-Content -LiteralPath $output -Raw -Encoding utf8 | ConvertFrom-Json
if($r.schema -ne 'RG_OSS_CIGARETTE_MOTION_GATE_V2' -or
   $r.contour -ne 'auto_edit' -or
   $r.status -ne 'SYNTHETIC_SAFETY_BENCHMARK_COMPLETED' -or
   $r.zero_known_false_positives -ne $true -or
   $r.all_cases_automatic_release -ne $false -or
   @($r.cases).Count -ne 4 -or
   $r.production_approved -ne $false -or
   $r.original_audio_modified -ne $false -or
   $r.production_xml_modified -ne $false -or
   $r.mandatory_cigarette_blur_modified -ne $false -or
   $r.source_video_read -ne $false){
  throw 'Fail-closed challenge contract mismatch'
}
Write-Host '=== RG NORFAIR SAFETY GATE V2 COMPLETE ==='
[ordered]@{
 status='SAFETY_REGRESSION_PASS'
 changed_production=$false
 packages_installed=$false
 cases=@($r.cases | Select-Object case,correct_position_frames,missed_visible_frames,false_matches_when_absent,abstained_frames,automatic_blur_release)
 zero_known_false_positives=$r.zero_known_false_positives
 production_approved=$false
 report=$output
} | ConvertTo-Json -Depth 7
