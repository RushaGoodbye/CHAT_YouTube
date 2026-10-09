$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# RG Auto Edit - YuNet REAL 892 isolated visual QA only.
# No pip/no install, no Studio, XML, audio, original video or 886_5 hold changes.
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$py='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_sam2_native_shadow_v1\Scripts\python.exe'
$video=Join-Path $root 'positive_892_015841_v1\892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4'
$track=Join-Path $root 'sam2_video_track_892_015841_v2_full_mask\RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$modelDir=Join-Path $root 'model_cache_yunet_v1'
$model=Join-Path $modelDir 'face_detection_yunet_2023mar.onnx'
$modelSha='8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
$pyCommit='2b00ef5a72302804de256fccd3d773abb0dab9f5'
$script=Join-Path $root 'scripts\yunet_mouth_landmarks_892_shadow_v1.py'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$pyCommit/rg_remote_control/open_source_v1/yunet_mouth_landmarks_892_shadow_v1.py"
$uriModel='https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'
$out=Join-Path $root 'yunet_mouth_892_real_60frame_shadow_v1\RG_892_YUNET_MOUTH_SHADOW_RESULT_V1.zip'
Write-Host '=== RG YUNET FACE LANDMARKS | REAL 892 60 FRAMES | SHADOW ONLY ==='
Write-Host 'NO STUDIO / NO PREMIERE XML / NO AUDIO / NO VIDEO CHANGES'
foreach($file in @($py,$video,$track,$hold)){
 if(!(Test-Path -LiteralPath $file -PathType Leaf)){throw ('Missing required input: '+$file)}
}
$h=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($h.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $h.do_not_publish -ne $true -or $h.primary_xml_withheld -ne $true -or
   $h.delivered_xml_withheld -ne $true){throw '886_5 microphone quarantine invalid'}
if(Test-Path -LiteralPath $out -PathType Leaf){
 Write-Host 'EXISTING_YUNET_SHADOW_ZIP_NO_REPROCESS'
 Write-Host $out
 return
}
$drive=[System.IO.DriveInfo]::new('F:\')
if(!$drive.IsReady -or $drive.AvailableFreeSpace -lt 750MB){throw 'F: free space/drive unavailable'}
if(!(Test-Path -LiteralPath $modelDir -PathType Container)){
 New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
}
if(Test-Path -LiteralPath $model -PathType Leaf){
 if((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash.ToLower() -ne $modelSha){
   throw 'YuNet cache hash mismatch: stop rather than overwriting'
 }
}else{
 Write-Host 'Fetching 232589-byte MIT-licensed OpenCV YuNet model to F: isolated model_cache...'
 $candidate=$model+'.download'
 if(Test-Path -LiteralPath $candidate){throw 'Interrupted model download exists - do not overwrite'}
 Invoke-WebRequest -Uri $uriModel -OutFile $candidate -UseBasicParsing
 if((Get-Item -LiteralPath $candidate).Length -ne 232589 -or
     (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLower() -ne $modelSha){
   Remove-Item -LiteralPath $candidate -Force
   throw 'Downloaded object is not the pinned official YuNet model (not Git LFS pointer)'
 }
 Move-Item -LiteralPath $candidate -Destination $model
}
$dir=Split-Path $script -Parent
if(!(Test-Path -LiteralPath $dir -PathType Container)){
 New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$tmp=$script+'.pinned.tmp'
if(Test-Path -LiteralPath $tmp){throw 'Interrupted source download already exists'}
Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
$content=Get-Content -LiteralPath $tmp -Raw -Encoding UTF8
foreach($marker in @(
 'RG_YUNET_892_REAL_MOUTH_LANDMARKS_SHADOW_V1',
 '886_5 microphone quarantine',
 'MODEL_SHA=',
 'TRACK_SHA=',
 'VIDEO_SHA=',
 'production_release_allowed',
 'mouth_from_yunet'
)){
 if($content.IndexOf($marker,[System.StringComparison]::OrdinalIgnoreCase) -lt 0){
   Remove-Item -LiteralPath $tmp -Force
   throw ('Missing pinned model/read-only script safety marker: '+$marker)
 }
}
# Python -m py_compile accepts arbitrary filename, so validate its contents
# by parse-only builtin compile without touching C: or running input code.
& $py -I -c "from pathlib import Path; compile(Path(r'$tmp').read_text(encoding='utf-8'), r'$tmp', 'exec'); print('YUNET_PINNED_PYTHON_PARSE: PASS')"
if($LASTEXITCODE -ne 0){throw 'YuNet source parser check failed'}
Move-Item -LiteralPath $tmp -Destination $script -Force
& $py -I -u $script --self-test
if($LASTEXITCODE -ne 0){throw 'YuNet mouth landmark semantic selftest failed'}
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:PYTHONNOUSERSITE='1'
$env:PYTHONPATH=$null
$env:TMP=Join-Path $root 'tmp_yunet_v1'
$env:TEMP=$env:TMP
if(!(Test-Path -LiteralPath $env:TMP -PathType Container)){
 New-Item -ItemType Directory -Path $env:TMP -Force | Out-Null
}
& $py -I -u $script --run
if($LASTEXITCODE -ne 0){throw 'YuNet 60-frame real face landmark diagnostic STOPPED; production unchanged'}
if(!(Test-Path -LiteralPath $out -PathType Leaf)){throw 'YuNet diagnostic result archive absent'}
Write-Host '=== YUNET REAL 892 QA READY (REVIEW REQUIRED) ==='
[ordered]@{
 status='REAL_892_60FRAME_YUNET_MOUTH_QA_READY'
 result_zip=$out
 studio_modified=$false
 premiere_xml_modified=$false
 audio_modified=$false
 video_modified=$false
 release_allowed=$false
 quarantine_886_5_unchanged=$true
} | ConvertTo-Json -Depth 3
