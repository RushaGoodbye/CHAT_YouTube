$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# No package installs, no source video editing, no Studio modifications.
# Real SAM2 tiny video propagation shadow test: stream 892, clip local 12..14s.
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$shadow=Join-Path $root 'oss_shadow'
$py=Join-Path $root 'oss_envs\rg_sam2_native_shadow_v1\Scripts\python.exe'
$program=Join-Path $shadow 'scripts\sam2_video_track_892_full_mask_v2.py'
$programTemp=$program+'.downloading'
$source='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\positive_892_015841_v1\892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$model=Join-Path $shadow 'sam2_native_windows_892_v1\sam2.1_hiera_tiny.pt'
$yaml=Join-Path $shadow 'sam2_native_windows_892_v1\sam2_repo\sam2\configs\sam2.1\sam2.1_hiera_t.yaml'
$output=Join-Path $shadow 'sam2_video_track_892_015841_v2_full_mask\RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip'
$commit='af55e1e776602981301bc3278148439cb2e3b437'
Write-Host '=== RG SAM2 892 DYNAMIC FULL-MASK 13-FRAME QA V2 ==='
Write-Host '2 seconds, 6 fps, isolated F: environment, NO PIP OR STUDIO UPDATE'
foreach($file in @($py,$source,$hold,$model,$yaml)){
    if(!(Test-Path -LiteralPath $file -PathType Leaf)){
        throw ('Missing verified input: '+$file)
    }
}
$h=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($h.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $h.do_not_publish -ne $true -or
   $h.primary_xml_withheld -ne $true -or
   $h.delivered_xml_withheld -ne $true){
    throw '886_5 HOLD not valid, no video run'
}
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
if((Test-Path -LiteralPath (Join-Path $app 'RG_EDITED_886_5.xml') -PathType Leaf) -or
   (Test-Path -LiteralPath (Join-Path $app '886\RG_EDITED_886_5.xml') -PathType Leaf)){
    throw '886_5 present in publishable location, refuse'
}
$active=Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^pythonw?\.exe$') -and
    ($_.CommandLine -like '*rg_production_wrapper.py*' -or
     $_.CommandLine -like '*rg_multi_dialogue.py*' -or
     $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production Studio process active; do not contend for the GPU'}
$cmd=Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue
if($null -eq $cmd){$cmd=Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue}
if($null -eq $cmd){throw 'NVIDIA SMI not accessible'}
$gpu=@(& $cmd.Source '--query-gpu=memory.free' '--format=csv,noheader,nounits' 2>$null)
if($LASTEXITCODE -ne 0 -or $gpu.Count -eq 0){throw 'No NVIDIA GPU free VRAM data'}
$free=[int]([string]$gpu[0]).Trim()
if($free -lt 7000){throw ('Insufficient VRAM (MB): '+$free)}
$drive=[System.IO.DriveInfo]::new('F:\')
if(!$drive.IsReady -or $drive.AvailableFreeSpace -lt 4GB){
    throw 'F: temporary space insufficient'
}
if(Test-Path -LiteralPath $output -PathType Leaf){
    Write-Host '=== EXISTING SAM2 SHADOW RESULT - NO RECALCULATION ==='
    [ordered]@{
        status='EXISTING_REVIEW_ZIP'
        review_zip=$output
        production_modified=$false
        release_allowed=$false
    } | ConvertTo-Json -Depth 3
    return
}
if(!(Test-Path -LiteralPath (Split-Path -Parent $program) -PathType Container)){
    New-Item -ItemType Directory -Path (Split-Path -Parent $program) -Force | Out-Null
}
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/open_source_v1/sam2_video_track_892_shadow_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $programTemp
$content=Get-Content -LiteralPath $programTemp -Raw -Encoding UTF8
foreach($guard in @(
    'RG_SAM2_892_REAL_VIDEO_TRACK_SHADOW_V2_FULL_MASK',
    'offload_video_to_cpu=True',
    'offload_state_to_cpu=True',
    'automatic_blur_allowed=False',
    'release_allowed=False',
    'FRAMES=13',
    'START_FRAME=360',
    'EVERY_N_FRAME=5',
    'FULL_MASK_%02d_1920x1080.png',
    'crop_follows_detected_mask_centroid=True',
    'full_resolution_binary_masks_saved=True'
)){
    if(-not $content.Contains([string]$guard)){
        throw ('Pinned SAM2 video QA invariant absent: '+$guard)
    }
}
& $py -I -m py_compile $programTemp
if($LASTEXITCODE -ne 0){throw 'Pinned motion source Python parse failed; no GPU run'}
Move-Item -LiteralPath $programTemp -Destination $program -Force
& $py -I -u $program --self-test
if($LASTEXITCODE -ne 0){throw 'Synthetic motion/host leakage test failed'}
$env:PYTHONNOUSERSITE='1'
$env:PYTHONPATH=$null
$env:SAM2_BUILD_CUDA='0'
Write-Host '=== RG SAM2 892 VIDEO PROPAGATION REAL CUDA TEST ==='
& $py -I -u $program --run
if($LASTEXITCODE -ne 0){
    throw 'SAM2 video propagation failed; production Studio untouched'
}
if(!(Test-Path -LiteralPath $output -PathType Leaf)){
    throw 'Missing bounded tracking ZIP report'
}
Write-Host '=== RG SAM2 892 2-SECOND DYNAMIC MASK QA RESULT ==='
[ordered]@{
    status='HUMAN_VISUAL_REVIEW_REQUIRED'
    archive=$output
    source_video_modified=$false
    audio_modified=$false
    premiere_XML_modified=$false
    studio_modified=$false
    release_allowed=$false
    quarantine_8865_unchanged=$true
} | ConvertTo-Json -Depth 4
