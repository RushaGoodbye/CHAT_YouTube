$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Real footage model baseline: cigarette 892 positive and mic 886 negative.
# Never modifies existing Studio files, XML, original video/audio or HOLD.
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$py='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$source='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\positive_892_015841_v1\892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4'
$negative='\\Desktop-v7gg0en\record\886.mp4'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$script=Join-Path $root 'scripts\benchmark_cigarette_892_vs_886_v1.py'
$report='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\cigarette_892_positive_vs_886_microphone_v1\summary.json'
$zip='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow\cigarette_892_positive_vs_886_microphone_v1\RG_CIGARETTE_892_VS_886_YOLOWORLD_BASELINE_v1.zip'
$commit='84b60acf7c3c9389b7eb0e23776984d2d2c27254'
Write-Host '=== RG AUTO EDIT REAL CIGARETTE PAIR BASELINE PREFLIGHT ==='
foreach($file in @($py,$source,$negative,$hold)){
    if(!(Test-Path -LiteralPath $file -PathType Leaf)){
        throw ('Required file absent: '+$file)
    }
}
if((Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5.xml' -PathType Leaf) -or
   (Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.xml' -PathType Leaf)){
    throw '886_5 quarantine invalid: XML unexpectedly present in ready folders'
}
$active=Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^pythonw?\.exe$') -and
    ($_.CommandLine -like '*rg_production_wrapper.py*' -or
     $_.CommandLine -like '*rg_multi_dialogue.py*' -or
     $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production Auto Edit worker running; avoid competing for GPU'}
$folder=Split-Path -Parent $script
if(!(Test-Path -LiteralPath $folder -PathType Container)){
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
}
$uri="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/open_source_v1/benchmark_cigarette_892_vs_886_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $script
& $py -X utf8 -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Baseline script Python syntax failed; source videos not accessed'}
& $py -X utf8 -u $script --self-test
if($LASTEXITCODE -ne 0){throw 'Offline pair comparator self-test failed; GPU not used'}
Write-Host '=== RG 892 REAL POSITIVE VS 886 KNOWN MIC NEGATIVE RTX BENCHMARK ==='
Write-Host 'Only existing YOLOWorld model; no installation and no production changes.'
& $py -X utf8 -u $script --run
if($LASTEXITCODE -ne 0){throw 'Shadow benchmark stopped; inspect STOPPED reason. No Studio release.'}
if(!(Test-Path -LiteralPath $report -PathType Leaf) -or
   !(Test-Path -LiteralPath $zip -PathType Leaf)){
    throw 'Missing verified shadow baseline report or ZIP'
}
$r=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.schema -ne 'RG_CIGARETTE_892_POSITIVE_886_MICROPHONE_PAIR_BASELINE_V1' -or
   $r.positive_candidates_semantically_verified -ne $false -or
   $r.independent_semantic_verifier_run -ne $false -or
   $r.production_approved -ne $false -or
   $r.studio_modified -ne $false -or
   $r.quarantine_886_5_modified -ne $false){
    throw 'Shadow report safety contract mismatch'
}
Write-Host '=== RG CIGARETTE TWO REAL CASES FINAL RESULT ==='
[ordered]@{
   status=$r.status
   positive_892_raw_hits=$r.positive_raw_detection_count
   positive_892_candidate_frames=$r.positive_reported_candidate_frames
   negative_886_raw_hits=$r.negative_raw_detection_count
   negative_886_false_positive=$r.negative_any_cigarette_prediction_is_known_false_positive
   source_video_modified=$false
   audio_modified=$false
   premiere_xml_modified=$false
   studio_updated=$false
   release_allowed=$false
   output_zip=$zip
} | ConvertTo-Json -Depth 3
