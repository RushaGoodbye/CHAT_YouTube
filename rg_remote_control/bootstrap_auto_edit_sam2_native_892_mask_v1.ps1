$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# SAM 2.1 tiny independent native Windows GPU mask pilot, strictly shadow ONLY.
# Will install an independent Torch 2.8 cu126 wheel set + SAM2 on F:.
# DO NOT change production runtime, Studio files, XML, audio or WSL.
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$shadow=Join-Path $root 'oss_shadow'
$base=Join-Path $shadow 'sam2_native_windows_892_v1'
$envdir=Join-Path $root 'oss_envs\rg_sam2_native_shadow_v1'
$isoPy=Join-Path $envdir 'Scripts\python.exe'
$productionPy='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$selfTestPy=Join-Path $root 'oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$code=Join-Path $shadow 'scripts\sam2_native_mask_892_shadow_v1.py'
$gold=Join-Path $shadow 'positive_892_015841_v1\keyframes\892_CIGARETTE_POTENTIAL_049.jpg'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$checkpoint=Join-Path $base 'sam2.1_hiera_tiny.pt'
$sourceZip=Join-Path $base 'sam2_official_source_98fcb164.zip'
$repoDir=Join-Path $base 'sam2_repo'
$sourceCommit='98fcb164bf880f70799c324c283c758c4d20bf82'
$trialCommit='0e9e3348b4287cb71b8eebeccd2ce63504b904b2'
Write-Host '=== RG SAM2.1 TINY 892 NATIVE SHADOW STRICT PREFLIGHT ==='
foreach($f in @($productionPy,$selfTestPy,$gold,$hold)){
    if(!(Test-Path -LiteralPath $f -PathType Leaf)){throw ('Missing prerequisite: '+$f)}
}
$h=Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
if($h.schema -ne 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -or
   $h.do_not_publish -ne $true -or
   $h.primary_xml_withheld -ne $true -or
   $h.delivered_xml_withheld -ne $true){
    throw '886_5 quarantine invalid; stop without GPU workloads'
}
if((Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5.xml' -PathType Leaf) -or
   (Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.xml' -PathType Leaf)){
    throw '886_5 appeared in ready Studio location; stop'
}
$active=Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^pythonw?\.exe$') -and
    ($_.CommandLine -like '*rg_production_wrapper.py*' -or
     $_.CommandLine -like '*rg_multi_dialogue.py*' -or
     $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production Auto Edit processing active; run shadow GPU test while idle'}
$free=[System.IO.DriveInfo]::new('F:\').AvailableFreeSpace
if($free -lt 20GB){throw 'Need 20 GB F: free for genuinely isolated Torch CUDA environment'}
$cmd=Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue
if($null -eq $cmd){$cmd=Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue}
if($null -eq $cmd){throw 'NVIDIA SMI unavailable'}
$gpu=@(& $cmd.Source '--query-gpu=memory.free' '--format=csv,noheader,nounits' 2>$null)
if($LASTEXITCODE -ne 0 -or $gpu.Count -lt 1){throw 'Cannot verify available GPU memory'}
$gpuFree=[int]([string]$gpu[0]).Trim()
if($gpuFree -lt 8000){throw "Need 8 GB free VRAM, currently $gpuFree MB"}
$meta=Join-Path $shadow 'positive_892_015841_v1\manifest.json'
if(!(Test-Path -LiteralPath $meta -PathType Leaf)){throw '892 real positive manifest absent'}
$m=Get-Content -LiteralPath $meta -Raw -Encoding UTF8 | ConvertFrom-Json
if($m.schema -ne 'RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1' -or
   $m.original_timecode -ne '01:58:41' -or
   $m.cigarette_semantically_confirmed -ne $false -or
   $m.studio_modified -ne $false){
    throw 'Unexpected 892 reference manifest'
}
$stageScripts=Split-Path $code -Parent
if(!(Test-Path -LiteralPath $stageScripts -PathType Container)){
  New-Item -ItemType Directory -Path $stageScripts -Force | Out-Null
}
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$trialCommit/rg_remote_control/open_source_v1/sam2_native_mask_892_shadow_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $code
& $selfTestPy -X utf8 -m py_compile $code
if($LASTEXITCODE -ne 0){throw 'Pilot Python syntax failed before any installations'}
& $selfTestPy -X utf8 -u $code --self-test
if($LASTEXITCODE -ne 0){throw 'Pilot mask synthetic negative tests failed before installs'}
Write-Host 'RG SAM2|GOLD_AND_CODE_QA: PASS'
Write-Host 'RG SAM2|CREATING_INDEPENDENT_ENV_F (Torch install may download >2 GB)'
# All pip caches, temporary files and model outputs stay on F:. No production site .pth.
New-Item -ItemType Directory -Path $base -Force | Out-Null
$tempDir=Join-Path $base 'temp'
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$env:TMP=$tempDir
$env:TEMP=$tempDir
$env:TMPDIR=$tempDir
$env:PIP_CACHE_DIR=Join-Path $base 'pipcache'
$env:PYTHONNOUSERSITE='1'
$env:PYTHONPATH=$null
$env:SAM2_BUILD_CUDA='0'
$env:SAM2_BUILD_ALLOW_ERRORS='0'
if(!(Test-Path -LiteralPath $isoPy -PathType Leaf)){
   & $productionPy -m venv --copies $envdir
   if($LASTEXITCODE -ne 0){throw 'Separate no-system-site-packages venv creation failed'}
}
if(!(Test-Path -LiteralPath $isoPy -PathType Leaf)){throw 'Separate Python missing'}
$cfg=Join-Path $envdir 'pyvenv.cfg'
if(!(Test-Path -LiteralPath $cfg -PathType Leaf)){throw 'Independent environment has no pyvenv.cfg'}
$cfgText=Get-Content -LiteralPath $cfg -Raw
if($cfgText -notmatch '(?im)^\s*include-system-site-packages\s*=\s*false\s*$'){
   throw 'Separate venv references external site-packages - fail closed'
}
$site=Join-Path $envdir 'Lib\site-packages'
if(Test-Path -LiteralPath $site -PathType Container){
    foreach($f in @(Get-ChildItem -LiteralPath $site -Filter '*.pth' -File -ErrorAction SilentlyContinue)){
       $content=Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue
       if($content -match '(?i)RG Auto Edit Runtime\\venv|rg_runtime_readonly'){
           throw ('Separate venv leaks production site packages: '+$f.Name)
       }
    }
}
$probe='import sys,site; p=sys.prefix.lower(); assert "rg_sam2_native_shadow_v1" in p; assert not site.ENABLE_USER_SITE; assert not any("rg auto edit runtime/venv/lib/site-packages" in x.lower().replace(chr(92),"/") for x in sys.path); print("RG_SAM2_VENV_ISOLATION: PASS")'
& $isoPy -I -c $probe
if($LASTEXITCODE -ne 0){throw 'Independent Python environment isolation check failed'}
& $isoPy -I -m pip --version
if($LASTEXITCODE -ne 0){throw 'Isolated pip unavailable'}
# Only isolated interpreter used below. This intentionally duplicates Torch wheels.
& $isoPy -I -m pip install --disable-pip-version-check --no-input --retries 2 --timeout 90 --index-url 'https://download.pytorch.org/whl/cu126' 'torch==2.8.0+cu126' 'torchvision==0.23.0+cu126'
if($LASTEXITCODE -ne 0){throw 'Isolated CUDA Torch installation failed. Production torch unchanged.'}
& $isoPy -I -m pip install --disable-pip-version-check --no-input --retries 2 --timeout 90 'numpy==2.2.6' 'opencv-python-headless==4.12.0.88' 'hydra-core==1.3.2' 'iopath==0.1.10' 'pillow==11.3.0' 'tqdm==4.67.1' 'setuptools==80.9.0' 'wheel==0.45.1'
if($LASTEXITCODE -ne 0){throw 'Isolated dependency install failed; Studio unaffected'}
# Official source frozen at inspected upstream commit; do not use unpinned PyPI sam2.
if(!(Test-Path -LiteralPath (Join-Path $repoDir 'sam2\build_sam.py') -PathType Leaf)){
    if(!(Test-Path -LiteralPath $sourceZip -PathType Leaf)){
        $tmpZip=$sourceZip+'.downloading'
        Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/facebookresearch/sam2/zip/$sourceCommit" -OutFile $tmpZip
        if((Get-Item -LiteralPath $tmpZip).Length -lt 150000){
            throw 'Official pinned SAM2 archive unexpectedly short'
        }
        Move-Item -LiteralPath $tmpZip -Destination $sourceZip -Force
    }
    $extract=Join-Path $base 'sam2_extract'
    if(!(Test-Path -LiteralPath $extract -PathType Container)){
        Expand-Archive -LiteralPath $sourceZip -DestinationPath $extract -Force
    }
    $srcFolder=Join-Path $extract ('sam2-'+$sourceCommit)
    if(!(Test-Path -LiteralPath (Join-Path $srcFolder 'sam2\build_sam.py') -PathType Leaf)){
        throw 'Official SAM2 pinned archive folder not found'
    }
    if(!(Test-Path -LiteralPath $repoDir -PathType Container)){
        Move-Item -LiteralPath $srcFolder -Destination $repoDir
    }
}
if(!(Test-Path -LiteralPath (Join-Path $repoDir 'sam2\configs\sam2.1\sam2.1_hiera_t.yaml') -PathType Leaf)){
    throw 'Pinned official SAM2.1 tiny config missing, abort'
}
& $isoPy -I -m pip install --disable-pip-version-check --no-input --no-deps --no-build-isolation $repoDir
if($LASTEXITCODE -ne 0){throw 'Native SAM2 source install failed; use WSL feasibility next, production unchanged'}
& $isoPy -I -m pip check
if($LASTEXITCODE -ne 0){throw 'Isolated dependency consistency FAIL; no GPU experiment'}
# Native imports and CUDA compute only after all dependency checks pass.
& $isoPy -I -c 'import torch, torchvision, sam2, cv2; assert torch.cuda.is_available(); print("RG_SAM2_NATIVE_IMPORT_CUDA_PASS",torch.__version__,torchvision.__version__,torch.cuda.get_device_name(0))'
if($LASTEXITCODE -ne 0){throw 'Native Windows SAM2 CUDA import unsupported in this isolated environment'}
if(!(Test-Path -LiteralPath $checkpoint -PathType Leaf)){
    Write-Host 'RG SAM2|DOWNLOAD_OFFICIAL_SAM2.1_TINY_CHECKPOINT'
    $tmpModel=$checkpoint+'.downloading'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt' -OutFile $tmpModel
    $bytes=(Get-Item -LiteralPath $tmpModel).Length
    if($bytes -lt 50000000 -or $bytes -gt 500000000){
        throw 'Official tiny model checkpoint unexpected file length'
    }
    Move-Item -LiteralPath $tmpModel -Destination $checkpoint
}
Write-Host '=== RG SAM2 892 REAL POSITIVE SINGLE FRAME MASK GPU TEST ==='
& $isoPy -I -u $code --run
if($LASTEXITCODE -ne 0){throw 'SAM2 image mask trial unsuccessful. Studio and source untouched.'}
$report=Join-Path $base 'review\report.json'
if(!(Test-Path -LiteralPath $report -PathType Leaf)){throw 'Expected mask QA report not produced'}
$reviewZip=Join-Path $base 'review\RG_SAM2_892_SINGLE_FRAME_MASK_REVIEW_V1.zip'
if(!(Test-Path -LiteralPath $reviewZip -PathType Leaf)){throw 'Validated single-ZIP mask review missing'}
$r=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.schema -ne 'RG_SAM2_892_IMAGE_MASK_SHADOW_V1' -or
   $r.automatic_blur_allowed -ne $false -or
   $r.release_allowed -ne $false -or
   $r.studio_modified -ne $false -or
   $r.original_audio_modified -ne $false){
   throw 'SAM2 output violates fail-closed release contract'
}
Write-Host '=== RG SAM2 WINDOWS SINGLE REAL CIGARETTE MASK PILOT RESULT ==='
[ordered]@{
  status='MASK_CANDIDATES_READY_FOR_VISUAL_REVIEW'
  masks=@($r.candidates).Count
  report=$report
  review_folder=(Join-Path $base 'review')
  review_zip=$reviewZip
  production_torch_modified=$false
  premiere_xml_modified=$false
  original_audio_modified=$false
  automatic_blur_allowed=$false
  stream_8865_hold_unchanged=$true
} | ConvertTo-Json -Depth 5
