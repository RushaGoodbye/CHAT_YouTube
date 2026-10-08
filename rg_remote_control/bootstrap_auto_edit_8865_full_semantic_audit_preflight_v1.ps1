$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$py='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_envs\rg_norfair_shadow_v1\Scripts\python.exe'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$folder=Join-Path $shadow 'scripts'
$script=Join-Path $folder 'audit_886_5_dialogue_preflight_v1.py'
$out=Join-Path $shadow 'audit_plans\886_5_semantic_cigarette_preflight_v1.json'
$hold='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$root='F:\RG_AUTO_EDIT\RG Auto Edit App\RG_EDITED_886_5.xml'
$ready='F:\RG_AUTO_EDIT\RG Auto Edit App\886\RG_EDITED_886_5.xml'
$ref='0bea2ccd81ab7479c65d4f6f96a57f31f9aa4a1e'
Write-Host '=== RG 886_5 FULL DIALOGUE AUDIT PREPARATION ==='
if(!(Test-Path -LiteralPath $py -PathType Leaf)){throw 'Separate F: Python environment absent - no install attempted'}
if(!(Test-Path -LiteralPath $shadow -PathType Container)){throw 'Shadow storage missing'}
if(!(Test-Path -LiteralPath $hold -PathType Leaf)){throw '886_5 semantic HOLD missing. Do not release dialogue'}
if((Test-Path -LiteralPath $root -PathType Leaf) -or
   (Test-Path -LiteralPath $ready -PathType Leaf)){
  throw '886_5 unexpectedly reappeared in ready folder. Read-only audit blocked.'
}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production worker active, wait for idle before reading 886_5 data'}
New-Item -ItemType Directory -Path $folder -Force | Out-Null
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/open_source_v1/audit_886_5_dialogue_preflight_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $script
& $py -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Dialogue source-map script syntax error'}
& $py -X utf8 -u $script --self-test
if($LASTEXITCODE -ne 0){throw 'Dialogue source-map regression failed before examining local files'}
$started=(Get-Date).ToUniversalTime()
& $py -X utf8 -u $script --output $out
if($LASTEXITCODE -ne 0){throw 'Read-only dialogue audit planning failed. Do not change 886_5 HOLD.'}
if(!(Test-Path -LiteralPath $out -PathType Leaf)){throw 'Audit plan JSON missing'}
if((Get-Item -LiteralPath $out).LastWriteTimeUtc -lt $started.AddSeconds(-3)){
  throw 'Audit plan was not freshly generated'
}
$r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json
if($r.schema -ne 'RG_886_5_REAL_CIGARETTE_AUDIT_PREFLIGHT_V1' -or
   $r.contour -ne 'auto_edit' -or
   $r.production_release_allowed -ne $false -or
   $r.semantic_inference_run -ne $false -or
   $r.xml_modified -ne $false -or
   $r.audio_modified -ne $false -or
   $r.hold_left_unchanged -ne $true){
    throw 'Read-only audit contract mismatch'
}
if((Test-Path -LiteralPath $root -PathType Leaf) -or
   (Test-Path -LiteralPath $ready -PathType Leaf)){
    throw '886_5 improperly became discoverable during audit'
}
Write-Host '=== RG 886_5 FULL DIALOGUE AUDIT PREFLIGHT COMPLETE ==='
[ordered]@{
  status=$r.status
  dialogue_duration_seconds=$r.source_inventory.duration_seconds
  video_clip_count=$r.source_inventory.video_clip_count
  source_mapped_clips=$r.source_inventory.mapped_clip_count
  known_negative_microphone_hits=$r.known_negative_microphone.raw_hit_count
  original_audio_modified=$false
  release_allowed=$false
  program_updated=$false
  full_dialogue_detected=$false
  report=$out
} | ConvertTo-Json -Depth 5
