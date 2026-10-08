$ErrorActionPreference='Stop'

$moduleCommit='22c3672753524597b04637e315aa2ca89b8746fd'
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
$data='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$module=Join-Path $app 'rg_cigarette_blur.py'
$config=Join-Path $app 'rg_auto_edit_config.json'
$tmp=Join-Path $env:TEMP 'rg_cigarette_blur_short_stable_v2.py'
$test=Join-Path $env:TEMP 'rg_cigarette_blur_short_stable_v2_test.py'

if(!(Test-Path $runtime)){throw 'Auto Edit runtime missing'}
if(!(Test-Path $module)){throw 'Live rg_cigarette_blur.py missing'}
if(!(Test-Path $config)){throw 'Live rg_auto_edit_config.json missing'}

$active=Get-CimInstance Win32_Process | Where-Object {
  (($_.Name -eq 'python.exe') -or ($_.Name -eq 'pythonw.exe')) -and
  (($_.CommandLine -like '*rg_production_wrapper.py*') -or
   ($_.CommandLine -like '*rg_multi_dialogue.py*') -or
   ($_.CommandLine -like '*rg_auto_edit_one_button.py*') -or
   ($_.CommandLine -like '*rg_cigarette_detector_worker.py*'))
}
if($active){throw 'Production backend is active. Stop/pause the current Auto Edit job before applying this hotfix.'}

$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$moduleCommit/rg_remote_control/cigarette_blur_v1/rg_cigarette_blur.py"
Invoke-WebRequest $url -OutFile $tmp -UseBasicParsing
$src=Get-Content $tmp -Raw
if($src -notmatch 'RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2'){throw 'SHORT_STABLE module version missing'}
if($src -notmatch 'SHORT_STABLE'){throw 'SHORT_STABLE confirmation rule missing'}
& $runtime -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'Patched cigarette module compile failed'}

$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$backup=Join-Path $data "release_backups\PRE_CIGARETTE_SHORT_STABLE_V2_$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item $module (Join-Path $backup 'rg_cigarette_blur.py') -Force
Copy-Item $config (Join-Path $backup 'rg_auto_edit_config.json') -Force

try {
  Copy-Item $tmp $module -Force

  $cfg=Get-Content $config -Raw | ConvertFrom-Json
  if($null -eq $cfg.cigarette_blur){throw 'cigarette_blur config section missing'}
  $cfg.cigarette_blur.version='RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2'
  $cfg.cigarette_blur | Add-Member -NotePropertyName short_stable_min_span_sec -NotePropertyValue 0.05 -Force
  $cfg.cigarette_blur | Add-Member -NotePropertyName short_stable_max_gap_sec -NotePropertyValue 0.12 -Force
  $cfg.cigarette_blur | Add-Member -NotePropertyName short_stable_min_iou -NotePropertyValue 0.72 -Force
  $cfg.cigarette_blur.mandatory=$true
  $cfg.cigarette_blur.fail_closed=$true
  $cfg.cigarette_blur.whole_frame_blur_forbidden=$true
  $json=$cfg | ConvertTo-Json -Depth 100
  [System.IO.File]::WriteAllText($config,$json,(New-Object System.Text.UTF8Encoding($false)))

  $py=@"
import json,sys
sys.path.insert(0, r'$app')
import rg_cigarette_blur as m

opts={
    'confidence':0.08,
    'single_hit_strong_confidence':0.34,
    'min_track_hits':2,
    'min_track_span_sec':0.10,
    'short_stable_min_span_sec':0.05,
    'short_stable_max_gap_sec':0.12,
    'short_stable_min_iou':0.72,
    'slice_fps':10.0,
    'track_max_gap_sec':0.65,
    'start_pad_sec':0.12,
    'end_hold_sec':0.22,
    'bbox_padding_px':18,
    'bbox_padding_ratio':0.35,
}
stable=[{'id':1,'hits':[
    {'t':9559.54667,'score':0.1029994860291481,'class':'smoking cigarette','bbox':[462,532,493,563]},
    {'t':9559.61334,'score':0.09050984680652618,'class':'smoking cigarette','bbox':[463,532,493,563]},
]}]
unstable=[{'id':2,'hits':[
    {'t':10.0,'score':0.11,'class':'smoking cigarette','bbox':[100,100,130,130]},
    {'t':10.0667,'score':0.10,'class':'smoking cigarette','bbox':[180,180,210,210]},
]}]
a1,r1=m._confirm_tracks(stable,opts,[(9500.0,9600.0)])
a2,r2=m._confirm_tracks(unstable,opts,[(0.0,20.0)])
result={
    'version':m.VERSION,
    'stable_short_track_accepted':len(a1)==1 and a1[0].get('confirmation')=='SHORT_STABLE',
    'stable_short_track_intervals':len(a1[0].get('intervals') or []) if a1 else 0,
    'unstable_short_track_rejected':len(a2)==0 and len(r2)==1,
}
result['passed']=all([result['stable_short_track_accepted'],result['stable_short_track_intervals']>0,result['unstable_short_track_rejected']])
print(json.dumps(result,ensure_ascii=False))
raise SystemExit(0 if result['passed'] else 2)
"@
  [System.IO.File]::WriteAllText($test,$py,(New-Object System.Text.UTF8Encoding($false)))
  $out=& $runtime -u -X utf8 $test
  if($LASTEXITCODE -ne 0){throw "SHORT_STABLE self-test failed: $out"}

  Write-Host 'CIGARETTE SHORT TRACK HOTFIX CONTROL: PASS'
  Write-Host '=== CIGARETTE SHORT TRACK HOTFIX RESULT ==='
  @{
    status='PASS'
    module_version='RG_CIGARETTE_BLUR_V1_SHORT_STABLE_V2'
    backup=$backup
    fail_closed=$true
    mandatory=$true
    whole_frame_blur_forbidden=$true
    production_active=$false
    selftest=($out | ConvertFrom-Json)
    next='RETRY_FAILED_DIALOGUE_886_5'
  } | ConvertTo-Json -Depth 8
}
catch {
  Copy-Item (Join-Path $backup 'rg_cigarette_blur.py') $module -Force
  Copy-Item (Join-Path $backup 'rg_auto_edit_config.json') $config -Force
  throw
}
finally {
  Remove-Item $tmp,$test -Force -ErrorAction SilentlyContinue
}
