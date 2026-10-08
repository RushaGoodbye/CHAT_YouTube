$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# RG Auto Edit 886_5 microphone false-positive recovery.
# Restores clean XML using exact known pre-blur backup; quarantines delivered
# file; invalidates semantic QA; never allows release automatically.
$python='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
$shadow='F:\RG_AUTO_EDIT\RG Auto Edit Data\oss_shadow'
$src=Join-Path $shadow 'scripts\quarantine_8865_mic_false_blur_v1.py'
$ref='14111efadabc1b265414b8345aaf9608f95af166'
Write-Host '=== RG 886_5 MIC FALSE BLUR RECOVERY PREFLIGHT ==='
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Production Python missing; no actions attempted'}
if(!(Test-Path -LiteralPath $app -PathType Container)){throw 'RG Auto Edit App folder missing'}
if(!(Test-Path -LiteralPath $shadow -PathType Container)){throw 'F: OSS shadow folder unavailable'}
$active=Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -match '^pythonw?\.exe$') -and
  ($_.CommandLine -like '*rg_production_wrapper.py*' -or
   $_.CommandLine -like '*rg_multi_dialogue.py*' -or
   $_.CommandLine -like '*rg_auto_edit_one_button.py*')
}
if($active){throw 'Production processing is active; local repair is blocked'}
$old='F:\RG_AUTO_EDIT\RG Auto Edit Data\release_backups\PRE_886_5_CIGARETTE_XML_REPAIR_20261008_175648'
if(!(Test-Path -LiteralPath (Join-Path $old 'RG_EDITED_886_5.xml') -PathType Leaf)){
  throw 'Known clean preblur XML backup missing - stop without modifying Studio'
}
$primary=Join-Path $app 'RG_EDITED_886_5.xml'
$delivery=Join-Path $app '886\RG_EDITED_886_5.xml'
$hold=Join-Path $app '886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
if(Test-Path -LiteralPath $hold -PathType Leaf){
  if(!(Test-Path -LiteralPath $delivery -PathType Leaf)){
    $r=Get-Content -LiteralPath $hold -Raw -Encoding utf8 | ConvertFrom-Json
    if($r.schema -eq 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -and
       $r.do_not_publish -eq $true){
      Write-Host '=== RG 886_5 MIC BLUR QUARANTINE ALREADY ACTIVE ==='
      [ordered]@{
        status='ALREADY_QUARANTINED'
        delivered_file_withheld=$true
        xml_for_publication_ready=$false
        semantic_hold=$hold
        processing_started=$false
      } | ConvertTo-Json -Depth 3
      return
    }
  }
  throw 'Existing semantic hold unexpected or delivery still present; no changes made'
}
if(!(Test-Path -LiteralPath $primary -PathType Leaf)){throw 'Primary dialogue XML missing'}
if(!(Test-Path -LiteralPath $delivery -PathType Leaf)){throw 'Published 886_5 copy missing; no repair attempted'}
$expected='32a47526e49507299db894bfb7300a7255074cd8881a3115c1f8a4bbc9569963'
$primaryHash=(Get-FileHash -LiteralPath $primary -Algorithm SHA256).Hash.ToLowerInvariant()
$deliveryHash=(Get-FileHash -LiteralPath $delivery -Algorithm SHA256).Hash.ToLowerInvariant()
if($primaryHash -ne $expected -or $deliveryHash -ne $expected){
  throw '886_5 XML was changed after known QA; refusing automatic restore'
}
$dest=Split-Path $src -Parent
if(!(Test-Path -LiteralPath $dest -PathType Container)){
  New-Item -Path $dest -ItemType Directory -Force | Out-Null
}
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/quarantine_8865_mic_false_blur_v1.py"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $src
& $python -m py_compile $src
if($LASTEXITCODE -ne 0){throw 'Quarantine script compile check failed; user data unchanged'}
& $python -X utf8 -u $src --self-test
if($LASTEXITCODE -ne 0){throw 'Quarantine strict XML regression failed; user data unchanged'}
Write-Host '=== RG 886_5 MIC FALSE BLUR FULL XML READ-ONLY PREFLIGHT ==='
& $python -X utf8 -u $src --preflight
if($LASTEXITCODE -ne 0){throw '886_5 XML differs from known clean pre-blur state; no mutation performed. Inspect PREFLIGHT STOPPED reason.'}
Write-Host '=== RG 886_5 MIC FALSE BLUR QUARANTINE APPLY ==='
& $python -X utf8 -u $src --apply
if($LASTEXITCODE -ne 0){throw 'Quarantine fail-closed or unexpected. Follow STOPPED reason, do not rerun blindly.'}
if(!(Test-Path -LiteralPath $hold -PathType Leaf)){
  throw 'Semantic hold marker missing after apparent recovery'
}
if(Test-Path -LiteralPath $delivery -PathType Leaf){
  throw 'Old published 886_5 still present - release must be blocked'
}
$r=Get-Content -LiteralPath $hold -Raw -Encoding utf8 | ConvertFrom-Json
if($r.do_not_publish -ne $true -or
   $r.status -ne 'QUARANTINED_NOT_READY_FOR_PUBLICATION' -or
   $r.original_source_audio_modified -ne $false){
   throw 'Post-repair semantic hold is not valid'
}
Write-Host '=== RG 886_5 MIC FALSE BLUR FINAL CONTROL ==='
[ordered]@{
  status='QUARANTINED_AND_MICROPHONE_BLUR_REMOVED'
  original_audio_unchanged=$true
  original_video_unchanged=$true
  three_misplaced_blur_effects_removed=$true
  delivered_xml_withheld=$true
  semantic_cigarette_verification='REQUIRED_BEFORE_PUBLICATION'
  full_stream_reprocessed=$false
  holding_file=$hold
  backup=$r.backup_directory
} | ConvertTo-Json -Depth 5
