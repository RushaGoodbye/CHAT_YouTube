$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$python='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$script=Join-Path $shadow 'scripts\norfair_motion_challenge_v1.py'
$out=Join-Path $shadow 'norfair_motion_challenge_v1.json'
$ref='04f5d78b7a86a011bf8a4dd885f48391b0241e0a'
Write-Host '=== RG AUTO EDIT NORFAIR CHALLENGE PREFLIGHT ==='
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Existing isolated Norfair python missing. No installation attempted.'}
if(!(Test-Path -LiteralPath $shadow -PathType Container)){throw 'Shadow data folder unavailable'}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing active, no concurrent shadow benchmark'}
& $python -X utf8 -c "from importlib.metadata import version; import numpy, cv2, norfair; assert version('norfair')=='2.3.0'; assert version('opencv-python')=='4.11.0.86'; print('NORFAIR_SHADOW_ENV: PASS')"
if($LASTEXITCODE -ne 0){throw 'Version incompatibility in existing shadow environment'}
$src="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1/norfair_motion_challenge_v1.py"
Invoke-WebRequest -Uri $src -UseBasicParsing -OutFile $script
& $python -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Motion challenge syntax failed; no production touched'}
$started=(Get-Date).ToUniversalTime()
Write-Host '=== RG NORFAIR SHADOW MOTION/OVERLAP TEST ==='
& $python -u -X utf8 $script --output $out
if($LASTEXITCODE -ne 0){throw 'Challenge did not complete. No production touched'}
if(!(Test-Path -LiteralPath $out -PathType Leaf)){throw 'Motion challenge report missing'}
$item=Get-Item -LiteralPath $out
if($item.LastWriteTimeUtc -lt $started.AddSeconds(-3)){throw 'Stale report is not acceptable'}
$r=Get-Content -LiteralPath $out -Raw -Encoding utf8 | ConvertFrom-Json
if($r.schema -ne 'RG_OSS_NORFAIR_MOTION_CHALLENGE_V1' -or
   $r.contour -ne 'auto_edit' -or $r.status -ne 'BENCHMARK_COMPLETE' -or
   @($r.cases).Count -ne 4 -or $r.production_approved -ne $false -or
   $r.premiere_xml_modified -ne $false -or $r.audio_modified -ne $false -or
   $r.cigarette_blur_modified -ne $false){
  throw 'Challenge output failed fail-closed safety checks'
}
Write-Host '=== RG NORFAIR MOTION CHALLENGE COMPLETE ==='
[ordered]@{
 status='BENCHMARK_COMPLETE'
 cases=@($r.cases | Select-Object case,truth_visible_frames,correct_position_frames,missed_visible_frames,incorrect_visible_matches,false_matches_when_absent,candidate_valid_for_case)
 all_cases_passed=$r.all_cases_passed
 production_approved=$false
 packages_installed=$false
 original_video_read=$false
 original_audio_modified=$false
 production_modified=$false
 report=$out
} | ConvertTo-Json -Depth 6
