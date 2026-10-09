$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Read-only real positive cigarette training reference from user stream 892
# at 01:58:41. No Studio updates, video/audio/XML edits, GPU installs or publish.
$py='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$video='\\Desktop-v7gg0en\record\892.mp4'
$ffmpeg='C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$script=Join-Path $shadow 'scripts\extract_cigarette_gold_892_v1.py'
$out=Join-Path $shadow 'positive_892_015841_v1'
$archive=Join-Path $out 'RG_892_CIGARETTE_GOLD_015841.zip'
$manifest=Join-Path $out 'manifest.json'
$sourceRef='0087f899fa3d66154450a50b9952d40ad4561c89'
Write-Host '=== RG 892 REAL CIGARETTE GOLD VIDEO SOURCE PREFLIGHT ==='
if(!(Test-Path -LiteralPath $py -PathType Leaf)){
    throw 'Existing isolated F: OpenCV Python environment is unavailable'
}
if(!(Test-Path -LiteralPath $shadow -PathType Container)){
    throw 'Existing F: oss_shadow directory not found'
}
if(!(Test-Path -LiteralPath $ffmpeg -PathType Leaf)){
    throw 'Verified existing FFmpeg path not found - original media untouched'
}
if(!(Test-Path -LiteralPath $video -PathType Leaf)){
    throw "892.mp4 not found at existing network recording folder: $video. Please provide its real path; no media changed."
}
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
if(!(Test-Path -LiteralPath $hold -PathType Leaf)){
    throw '886_5 semantic hold marker missing - refuse any further source processing'
}
$holdStatus=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($holdStatus.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $holdStatus.do_not_publish -ne $true -or
   $holdStatus.primary_xml_withheld -ne $true -or
   $holdStatus.delivered_xml_withheld -ne $true){
    throw '886_5 semantic hold marker is not in the verified quarantine state'
}
if((Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5.xml' -PathType Leaf) -or
   (Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.xml' -PathType Leaf)){
    throw '886_5 is unexpectedly back in ready folder. Stop for quarantine review.'
}
$active=Get-CimInstance Win32_Process | Where-Object {
   ($_.Name -match '^pythonw?\.exe$') -and
   ($_.CommandLine -like '*rg_production_wrapper.py*' -or
    $_.CommandLine -like '*rg_multi_dialogue.py*' -or
    $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'RG Auto Edit production processor active; avoid competing for disk while it runs'}
$folder=Split-Path $script -Parent
if(!(Test-Path -LiteralPath $folder -PathType Container)){
  New-Item -ItemType Directory -Path $folder -Force | Out-Null
}
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$sourceRef/rg_remote_control/open_source_v1/extract_cigarette_gold_892_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $script
& $py -X utf8 -m py_compile $script
if($LASTEXITCODE -ne 0){throw '892 real review script compile failed, no media changes'}
& $py -X utf8 -u $script --self-test
if($LASTEXITCODE -ne 0){throw '892 review pre-write test failed; no media changes'}
Write-Host '=== RG 892 SOURCE VIDEO 24 SEC READ ONLY GOLD CAPTURE ==='
& $py -X utf8 -u $script --source $video --ffmpeg $ffmpeg --out $out
if($LASTEXITCODE -ne 0){throw 'Read-only extraction failed. Do not change Studio files.'}
if(!(Test-Path -LiteralPath $archive -PathType Leaf) -or
   !(Test-Path -LiteralPath $manifest -PathType Leaf)){
    throw 'Expected 892 archive or manifest is missing'
}
$r=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$hash=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if($r.schema -ne 'RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1' -or
   $r.stream -ne '892' -or $r.original_timecode -ne '01:58:41' -or
   $r.cigarette_semantically_confirmed -ne $false -or
   $r.release_allowed -ne $false -or
   $r.original_audio_modified -ne $false -or
   $r.studio_modified -ne $false -or
   $r.archive_sha256 -ne $hash){
    throw '892 read-only capture postflight mismatch; original footage unchanged'
}
Write-Host '=== RG 892 POSITIVE CIGARETTE EXAMPLE READY FOR HUMAN REVIEW ==='
[ordered]@{
  status='REAL_POSITIVE_CANDIDATE_CAPTURE_READY'
  stream='892'
  timecode='01:58:41'
  captured_seconds=24
  sampled_frames=$r.sampled_frame_count
  contact_sheets=$r.contact_sheet_count
  keyframes_full_resolution=$r.keyframe_count
  archive=$archive
  archive_mb=$r.archive_size_mb
  source_media_modified=$false
  original_audio_modified=$false
  886_5_quarantine_unchanged=$true
  studio_modified=$false
  verified_real_cigarette='PENDING_VISUAL_REVIEW'
} | ConvertTo-Json -Depth 5
