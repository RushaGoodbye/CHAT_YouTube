$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Contact sheets of original 886_5 frames. Does not infer or certify cigarette masks.
$python='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$scripts=Join-Path $shadow 'scripts'
$ffmpeg='C:\Program Files (x86)\Common Files\AutoPod\ffmpeg\bin\ffmpeg.EXE'
$video='\\Desktop-v7gg0en\record\886.mp4'
$output=Join-Path $shadow 'review_886_5'
$ref='17316df6488b14b40df70f5c0c713d197913f728'
Write-Host '=== RG 886_5 REAL CIGARETTE FRAME REVIEW PREFLIGHT ==='
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Separate Norfair Python environment missing'}
if(!(Test-Path -LiteralPath $shadow -PathType Container)){throw 'Shadow data directory missing'}
if(!(Test-Path -LiteralPath $ffmpeg -PathType Leaf)){throw 'Known FFmpeg binary missing'}
if(!(Test-Path -LiteralPath $video -PathType Leaf)){throw 'Original stream video missing'}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing active; read-only video review deferred'}
& $python -X utf8 -c "from importlib.metadata import version; import cv2, numpy; assert version('opencv-python')=='4.11.0.86'; print('EXISTING_OPENCV_ENV: PASS')"
if($LASTEXITCODE -ne 0){throw 'OpenCV environment invalid; no new installation attempted'}
$previous=Join-Path $scripts 'norfair_real_motion_8865_v1.py'
if(!(Test-Path -LiteralPath $previous -PathType Leaf)){throw 'Previous read-only evidence module missing'}
$entry=Join-Path $scripts 'real_cigarette_review_8865_v1.py'
$smoke=Join-Path $scripts 'real_cigarette_review_synthetic.py'
$base="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1"
foreach($filename in @('real_cigarette_review_8865_v1.py','real_cigarette_review_synthetic.py')){
  Invoke-WebRequest -UseBasicParsing -Uri "$base/$filename" -OutFile (Join-Path $scripts $filename)
}
& $python -m py_compile $entry $smoke
if($LASTEXITCODE -ne 0){throw 'Review module Python syntax error'}
Write-Host '=== RG 886_5 REAL REVIEW SYNTHETIC TEST ==='
& $python -u -X utf8 $smoke
if($LASTEXITCODE -ne 0){throw 'Review layout source-immutability smoke failed; original stream not opened'}
$manifest=Join-Path $output 'review_manifest.json'
if(Test-Path -LiteralPath $manifest -PathType Leaf){
  $r=Get-Content -LiteralPath $manifest -Raw -Encoding utf8 | ConvertFrom-Json
  if($r.schema -ne 'RG_CIGARETTE_8865_REAL_GROUND_TRUTH_REVIEW_V1' -or
     $r.status -ne 'VISUAL_REVIEW_READY' -or
     $r.production_approved -ne $false -or
     $r.source_audio_modified -ne $false -or
     $r.production_xml_modified -ne $false -or
     $r.mandatory_blur_modified -ne $false -or
     @($r.sheets).Count -ne 4){
      throw 'Existing review manifest differs from pinned safe format; refusing overwrite'
  }
  foreach($sheet in @($r.sheets)){
    if(!(Test-Path -LiteralPath $sheet.path -PathType Leaf)){throw "Saved review sheet missing: $($sheet.path)"}
    $hash=(Get-FileHash -LiteralPath $sheet.path -Algorithm SHA256).Hash.ToLowerInvariant()
    if($hash -ne $sheet.sha256){throw "Saved review sheet corrupted: $($sheet.path)"}
  }
  Write-Host '=== RG 886_5 REAL REVIEW ALREADY AVAILABLE ==='
}else{
  Write-Host '=== RG 886_5 ORIGINAL FRAME SAMPLE (READ ONLY) ==='
  & $python -u -X utf8 $entry --output-dir $output
  if($LASTEXITCODE -ne 0){throw 'Real-frame review stopped, no production changes'}
}
if(!(Test-Path -LiteralPath $manifest -PathType Leaf)){throw 'Review manifest missing'}
$r=Get-Content -LiteralPath $manifest -Raw -Encoding utf8 | ConvertFrom-Json
if($r.status -ne 'VISUAL_REVIEW_READY' -or
   $r.production_approved -ne $false -or
   $r.source_audio_modified -ne $false -or
   $r.source_video_modified -ne $false -or
   $r.production_xml_modified -ne $false -or
   $r.mandatory_blur_modified -ne $false -or
   @($r.sheets).Count -ne 4){
   throw 'Review pack output failed read-only contract'
}
Write-Host '=== RG 886_5 REAL FRAME REVIEW PACK COMPLETE ==='
[ordered]@{
  status='VISUAL_REVIEW_READY'
  frames=$r.frame_count
  contact_sheets=@($r.sheets | ForEach-Object {$_.path})
  folder=$output
  actual_cigarette_ground_truth_labels=0
  production_modified=$false
  libraries_installed=$false
  next='Open contact sheet JPGs and inspect; upload contact sheet to ChatGPT for visual review'
} | ConvertTo-Json -Depth 5
