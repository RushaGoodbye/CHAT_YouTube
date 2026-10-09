$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# RG SAM2 892 HYDRA FIX V4 - read existing fully isolated F: SAM2 environment.
# No downloads of Torch/model, no pip, no original video/audio/XML changes.
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$shadow=Join-Path $root 'oss_shadow'
$base=Join-Path $shadow 'sam2_native_windows_892_v1'
$python=Join-Path $root 'oss_envs\rg_sam2_native_shadow_v1\Scripts\python.exe'
$script=Join-Path $shadow 'scripts\sam2_native_mask_892_shadow_v1.py'
$staged=$script+'.hydra_v4.tmp.py'
$gold=Join-Path $shadow 'positive_892_015841_v1\keyframes\892_CIGARETTE_POTENTIAL_049.jpg'
$model=Join-Path $base 'sam2.1_hiera_tiny.pt'
$config=Join-Path $base 'sam2_repo\sam2\configs\sam2.1\sam2.1_hiera_t.yaml'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$out=Join-Path $base 'review\RG_SAM2_892_SINGLE_FRAME_MASK_REVIEW_V1.zip'
$report=Join-Path $base 'review\report.json'
$pyCommit='5e0ee33b56613dbecf711cea6378959c72deee76'
Write-Host '=== RG SAM2 892 HYDRA ABSOLUTE CONFIG HOTFIX V4 ==='
Write-Host 'NO PIP / NO MODEL DOWNLOAD / NO STUDIO UPDATE'
foreach($f in @($python,$gold,$model,$config,$hold)){
    if(!(Test-Path -LiteralPath $f -PathType Leaf)){
        throw ('Required existing file not found: '+$f)
    }
}
$h=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($h.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $h.do_not_publish -ne $true -or
   $h.primary_xml_withheld -ne $true -or
   $h.delivered_xml_withheld -ne $true){
    throw '886_5 semantic HOLD is not verified; stop'
}
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
if((Test-Path -LiteralPath (Join-Path $app 'RG_EDITED_886_5.xml') -PathType Leaf) -or
   (Test-Path -LiteralPath (Join-Path $app '886\RG_EDITED_886_5.xml') -PathType Leaf)){
    throw '886_5 unexpectedly present in publishable XML locations'
}
if((Test-Path -LiteralPath $report -PathType Leaf) -and
   (Test-Path -LiteralPath $out -PathType Leaf)){
    $prior=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
    if($prior.schema -eq 'RG_SAM2_892_IMAGE_MASK_SHADOW_V1' -and
       $prior.release_allowed -eq $false -and
       $prior.automatic_blur_allowed -eq $false){
        Write-Host 'RG SAM2 SHADOW RESULT ALREADY EXISTS - NOTHING OVERWRITTEN'
        [ordered]@{
           status='EXISTING_MASK_REVIEW'
           archive=$out
           studio_modified=$false
           release_allowed=$false
        } | ConvertTo-Json -Depth 3
        return
    }
    throw 'Partial or unverified earlier review folder exists; refuse overwrite'
}
$active=Get-CimInstance Win32_Process | Where-Object {
   ($_.Name -match '^pythonw?\.exe$') -and
   ($_.CommandLine -like '*rg_production_wrapper.py*' -or
    $_.CommandLine -like '*rg_multi_dialogue.py*' -or
    $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production Auto Edit job is active; do not compete for GPU'}
$nv=Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue
if($null -eq $nv){$nv=Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue}
if($null -eq $nv){throw 'NVIDIA SMI not available'}
$g=@(& $nv.Source '--query-gpu=memory.free' '--format=csv,noheader,nounits' 2>$null)
if($LASTEXITCODE -ne 0 -or $g.Count -lt 1){throw 'Cannot verify free GPU memory'}
$freeMB=[int]([string]$g[0]).Trim()
if($freeMB -lt 6000){throw ('RTX GPU memory too busy: '+$freeMB+' MB free')}
$env:PYTHONNOUSERSITE='1'
$env:PYTHONPATH=$null
$env:SAM2_BUILD_CUDA='0'
# Stage only one experimental Python script under F:/oss_shadow. No pip install.
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$pyCommit/rg_remote_control/open_source_v1/sam2_native_mask_892_shadow_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $staged
$code=Get-Content -LiteralPath $staged -Raw -Encoding UTF8
if($code.IndexOf('initialize_config_dir(',[System.StringComparison]::Ordinal) -lt 0 -or
   $code.IndexOf('--config-check',[System.StringComparison]::Ordinal) -lt 0 -or
   $code.IndexOf('automatic_blur_allowed=False',[System.StringComparison]::Ordinal) -lt 0 -or
   $code.IndexOf('release_allowed=False',[System.StringComparison]::Ordinal) -lt 0){
    throw 'Pinned Hydra hotfix script lacks mandatory fail-closed source invariants'
}
& $python -I -m py_compile $staged
if($LASTEXITCODE -ne 0){throw 'Pinned Hydra hotfix Python syntax failed before replacing shadow script'}
Move-Item -LiteralPath $staged -Destination $script -Force
Write-Host 'RG SAM2|PINNED_SOURCE_AND_PYTHON_SYNTAX: PASS'
& $python -I -u $script --self-test
if($LASTEXITCODE -ne 0){throw 'Mask synthetic QA failed; no model GPU run'}
& $python -I -u $script --env-check
if($LASTEXITCODE -ne 0){throw 'Isolated venv assertion failed'}
& $python -I -u $script --cuda-check
if($LASTEXITCODE -ne 0){throw 'Pre-installed isolated CUDA/SAM2 dependency validation failed'}
Write-Host '=== RG SAM2 HYDRA SOURCE YAML CONFIG CHECK - NO MODEL RUN ==='
& $python -I -u $script --config-check
if($LASTEXITCODE -ne 0){throw 'Hydra absolute YAML compose failed; no GPU mask trial'}
Write-Host '=== RG SAM2 892 RTX SINGLE FRAME MASK GPU TEST ==='
& $python -I -u $script --run
if($LASTEXITCODE -ne 0){throw 'SAM2 single-frame mask failed; Studio unchanged'}
if(!(Test-Path -LiteralPath $out -PathType Leaf) -or
   !(Test-Path -LiteralPath $report -PathType Leaf)){
    throw 'Mask output ZIP or report missing'
}
$r=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.schema -ne 'RG_SAM2_892_IMAGE_MASK_SHADOW_V1' -or
   $r.release_allowed -ne $false -or
   $r.automatic_blur_allowed -ne $false -or
   $r.studio_modified -ne $false -or
   $r.original_audio_modified -ne $false){
    throw 'Mask QA shadow safety contract failed'
}
Write-Host '=== RG SAM2 REAL CIGARETTE HYDRA V4 RESULT ==='
[ordered]@{
  status='MASK_CANDIDATES_READY_FOR_VISUAL_REVIEW'
  stream='892'
  timecode='01:58:41'
  candidates=@($r.candidates).Count
  archive=$out
  source_audio_unchanged=$true
  studio_modified=$false
  release_allowed=$false
  quarantine_8865_unchanged=$true
} | ConvertTo-Json -Depth 4
