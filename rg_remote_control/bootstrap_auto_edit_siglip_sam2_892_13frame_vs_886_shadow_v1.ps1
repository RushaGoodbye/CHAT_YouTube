$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# One real GPU semantic benchmark, existing independently isolated SigLIP env.
# Never installs packages or edits Studio, Premiere XML, audio or original MP4.
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$py='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_siglip_independent_shadow_v1\Scripts\python.exe'
$script=Join-Path $root 'scripts\siglip_sam2_892_13frame_vs_886_negative_shadow_v1.py'
$stage=$script+'.pinned.tmp'
$gold=Join-Path $root 'positive_892_015841_v1\892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4'
$masks=Join-Path $root 'sam2_video_track_892_015841_v2_full_mask\RG_SAM2_892_REAL_MOTION_FULL_MASK_V2.zip'
$negative=Join-Path $root 'siglip_cigarette_independent_892_886_v1\RG_SIGLIP_892_886_CIGARETTE_SHADOW_V1.zip'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$out=Join-Path $root 'siglip_sam2_892_vs_886_real_13frame_shadow_v1\RG_SIGLIP_SAM2_892_13FRAME_VS_886_NEGATIVE_SHADOW_V1.zip'
$commit='d9842e0826b2b87d08fb8442a0cae0bc69e869d6'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/open_source_v1/siglip_sam2_892_13frame_vs_886_negative_shadow_v1.py"
Write-Host '=== RG SIGLIP 892 13 REAL FRAMES + 3 NEGATIVE CONTROLS SHADOW ==='
Write-Host 'NO PIP / NO MODEL DOWNLOAD / NO PRODUCTION VIDEO OR XML CHANGES'
foreach($f in @($py,$gold,$masks,$negative,$hold)){
    if(!(Test-Path -LiteralPath $f -PathType Leaf)){throw ('Missing existing verified prerequisite: '+$f)}
}
$h=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($h.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $h.do_not_publish -ne $true -or
   $h.primary_xml_withheld -ne $true -or
   $h.delivered_xml_withheld -ne $true){throw '886_5 HOLD invalid; refuse new analysis'}
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
if((Test-Path -LiteralPath (Join-Path $app 'RG_EDITED_886_5.xml') -PathType Leaf) -or
   (Test-Path -LiteralPath (Join-Path $app '886\RG_EDITED_886_5.xml') -PathType Leaf)){
    throw '886_5 publishable XML unexpectedly present; STOP'
}
if(Test-Path -LiteralPath $out -PathType Leaf){
    Write-Host 'RG_SIGLIP_13FRAME|EXISTING_RESULT_NO_RECALCULATION'
    [ordered]@{status='REVIEW_ZIP_ALREADY_EXISTS';archive=$out;release_allowed=$false} | ConvertTo-Json
    return
}
$active=Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^pythonw?\.exe$') -and
    ($_.CommandLine -like '*rg_production_wrapper.py*' -or
     $_.CommandLine -like '*rg_multi_dialogue.py*' -or
     $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production auto-edit job active; refuse competing for RTX GPU'}
$nv=Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue
if($null -eq $nv){$nv=Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue}
if($null -eq $nv){throw 'NVIDIA GPU probe not found'}
$g=@(& $nv.Source '--query-gpu=memory.free' '--format=csv,noheader,nounits' 2>$null)
if($LASTEXITCODE -ne 0 -or $g.Count -lt 1){throw 'GPU memory check failed'}
$mb=[int]([string]$g[0]).Trim()
if($mb -lt 6500){throw ('Insufficient free GPU VRAM for independent classifier: '+$mb+' MB')}
$drive=[System.IO.DriveInfo]::new('F:\')
if(!$drive.IsReady -or $drive.AvailableFreeSpace -lt 2GB){throw 'Insufficient free space on F:'}
$dir=Split-Path $script -Parent
if(!(Test-Path -LiteralPath $dir -PathType Container)){New-Item -ItemType Directory -Path $dir -Force | Out-Null}
if(-not $url.EndsWith('/rg_remote_control/open_source_v1/siglip_sam2_892_13frame_vs_886_negative_shadow_v1.py',
                       [System.StringComparison]::Ordinal)){throw 'Wrong source file name'}
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $stage
$content=Get-Content -LiteralPath $stage -Raw -Encoding UTF8
$guards=@(
  'RG_SIGLIP_SAM2_892_THIRTEEN_VS_THREE_REAL_NEGATIVE_SHADOW_V1',
  "TRACK_SHA=",
  "NEG_SHA=",
  "SOURCE_SHA=",
  'local_files_only=True',
  '886_5 HOLD',
  'N=13',
  'NEGATIVES=(',
  'automatic_blur_allowed=False',
  'cigarette_only_blur_allowed=False',
  'RG_SIGLIP_SAM2_892_13FRAME_VS_886_NEGATIVE_SHADOW_V1.zip'
)
foreach($guard in $guards){
    if($content.IndexOf([string]$guard,[StringComparison]::OrdinalIgnoreCase) -lt 0){
        throw ('Pinned independent semantic source missing invariant: '+$guard)
    }
}
& $py -I -m py_compile $stage
if($LASTEXITCODE -ne 0){throw 'Pinned Python parser stopped run'}
Move-Item -LiteralPath $stage -Destination $script -Force
& $py -I -u $script --self-test
if($LASTEXITCODE -ne 0){throw 'Offline true-cigarette-hand semantic regression stopped run'}
$tmp=Join-Path $root 'tmp_siglip_independent_v1'
if(!(Test-Path -LiteralPath $tmp -PathType Container)){New-Item -ItemType Directory -Path $tmp -Force | Out-Null}
$env:TMP=$tmp
$env:TEMP=$tmp
$env:HF_HOME=Join-Path $root 'hf_siglip_independent_cache'
$env:HF_HUB_CACHE=Join-Path $env:HF_HOME 'hub'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:PYTHONNOUSERSITE='1'
$env:PYTHONPATH=$null
Write-Host 'RG SIGLIP|PINNED_SOURCE_OFFLINE_QA_PASS'
& $py -I -u $script --run
if($LASTEXITCODE -ne 0){throw 'SigLIP 16 real references test failed; no production edits made'}
if(!(Test-Path -LiteralPath $out -PathType Leaf)){throw '16-reference evidence ZIP not produced'}
Write-Host '=== RG SIGLIP 892/886 16 REAL FRAMES REVIEW RESULT ==='
[ordered]@{
  status='16_REAL_SEMANTIC_CANDIDATES_READY_FOR_REVIEW'
  archive=$out
  video_modified=$false
  audio_modified=$false
  XML_modified=$false
  Studio_modified=$false
  release_allowed=$false
  quarantine_886_5_unchanged=$true
} | ConvertTo-Json -Depth 4
