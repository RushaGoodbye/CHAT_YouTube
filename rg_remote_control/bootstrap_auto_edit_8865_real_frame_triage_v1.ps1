$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$python='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$scripts=Join-Path $shadow 'scripts'
$review=Join-Path $scripts 'triage_886_5_real_frames_v1.py'
$preflight=Join-Path $scripts 'audit_886_5_dialogue_preflight_v1.py'
$root=Join-Path $shadow 'real_8865_semantic_review_v1'
$manifest=Join-Path $root 'review_manifest.json'
$zip=Join-Path $root 'RG_886_5_REAL_CIGARETTE_VISUAL_TRIAGE.zip'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$media='\\Desktop-v7gg0en\record\886.mp4'
$ffmpeg='C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE'
$ref='c9acad90580fc431d43a60b6a868d6bb5e6e4c37'
$oldRef='0bea2ccd81ab7479c65d4f6f96a57f31f9aa4a1e'
Write-Host '=== RG 886_5 REAL SOURCE VISUAL TRIAGE PREFLIGHT ==='
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Separate Norfair/OpenCV environment absent'}
if(!(Test-Path -LiteralPath $shadow -PathType Container)){throw 'OSS F: shadow folder missing'}
if(!(Test-Path -LiteralPath $hold -PathType Leaf)){throw '886_5 quarantine marker missing'}
if(!(Test-Path -LiteralPath $ffmpeg -PathType Leaf)){throw 'Expected FFmpeg read-only binary missing'}
if(!(Test-Path -LiteralPath $media -PathType Leaf)){throw 'Original 886.mp4 video unavailable'}
if((Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5.xml' -PathType Leaf) -or
   (Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.xml' -PathType Leaf)){
  throw 'Unsafe: 886_5 reappeared in Studio ready locations'
}
$h=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($h.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $h.do_not_publish -ne $true -or
   $h.primary_xml_withheld -ne $true -or
   $h.delivered_xml_withheld -ne $true){
  throw '886_5 semantic hold contract changed'
}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing active - defer real video sampling'}
New-Item -ItemType Directory -Path $scripts -Force | Out-Null
$src="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1/triage_886_5_real_frames_v1.py"
$old="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$oldRef/rg_remote_control/open_source_v1/audit_886_5_dialogue_preflight_v1.py"
# No pip installs, CUDA, or modifications to Studio.
Invoke-WebRequest -UseBasicParsing -Uri $src -OutFile $review
Invoke-WebRequest -UseBasicParsing -Uri $old -OutFile $preflight
& $python -X utf8 -m py_compile $review $preflight
if($LASTEXITCODE -ne 0){throw 'Review code failed Python syntax validation'}
& $python -X utf8 -u $review --self-test
if($LASTEXITCODE -ne 0){throw 'Media provenance/negative map regression failed; original video not sampled'}
Write-Host '=== RG 886_5 VERIFIED SOURCE RANGES AND REAL FRAME SAMPLING ==='
& $python -X utf8 -u $review
if($LASTEXITCODE -ne 0){throw 'Read-only real visual triage failed; Studio unchanged'}
if(!(Test-Path -LiteralPath $manifest -PathType Leaf)){throw 'Triage manifest missing'}
$r=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.schema -ne 'RG_886_5_SOURCE_CIGARETTE_TRIAGE_V1' -or
   $r.stream -ne '886' -or
   $r.dialogue -ne '886_5' -or
   $r.release_allowed -ne $false -or
   $r.semantic_review_complete -ne $false -or
   $r.xml_modified -ne $false -or
   $r.original_audio_modified -ne $false -or
   $r.source_video_modified -ne $false){
    throw 'Fail-closed triage contract mismatch'
}
if((Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5.xml' -PathType Leaf) -or
   (Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.xml' -PathType Leaf)){
  throw '886_5 unexpectedly published during diagnostic scan'
}
Write-Host '=== RG 886_5 REAL VISUAL TRIAGE FINAL RESULT ==='
[ordered]@{
 status=$r.status
 original_dialogue_seconds=$r.source_mapping.timeline_duration
 original_video_source_clips=$r.source_mapping.source_clips
 media_clip_counts=$r.source_mapping.media_clip_counts
 unresolved_source_references=$r.source_mapping.unresolved_count
 source_windows=@($r.source_mapping.ranges).Count
 sampled_frames=$r.sampled_frames
 contact_sheets=$r.contact_sheets
 zip_ready=(Test-Path -LiteralPath $zip -PathType Leaf)
 zip=$zip
 manifest=$manifest
 installed_packages=$false
 original_video_modified=$false
 original_audio_modified=$false
 production_modified=$false
 safe_to_publish=$false
 remark='Sampling is only visual triage, not continuous semantic cigarette validation.'
} | ConvertTo-Json -Depth 6
