$ErrorActionPreference="Stop"
$root=Join-Path $env:LOCALAPPDATA 'RGYouTubeControl\diagnostics'
$entries=@()
foreach($d in @(Get-ChildItem -LiteralPath $root -Directory -Filter 'ollama-repair-*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 5)){
 $setup=Join-Path $d.FullName 'OllamaSetup.exe'
 $f=Get-Item -LiteralPath $setup -ErrorAction SilentlyContinue
 $entries += [pscustomobject]@{folder=$d.FullName;installer_exists=($null -ne $f);installer_bytes=if($f){$f.Length}else{0};modified=if($f){$f.LastWriteTime.ToString('o')}else{''}}
}
$bits=@()
try{Import-Module BitsTransfer -ErrorAction Stop;foreach($j in @(Get-BitsTransfer -ErrorAction SilentlyContinue)){
 if([string]$j.DisplayName -like '*RG_Ollama*'){$bits += [pscustomobject]@{id=[string]$j.JobId;state=[string]$j.JobState;bytes_total=$j.BytesTotal;bytes_transferred=$j.BytesTransferred;error=[string]$j.ErrorDescription}}
}}catch{}
[pscustomobject]@{
 schema='RG_OLLAMA_DOWNLOAD_STATE_V1'
 partial_installer_candidates=$entries
 model_dir_present=(Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.ollama\models'))
 server_present=(Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\lib\ollama\llama-server.exe'))
 bits_jobs=$bits
}|ConvertTo-Json -Depth 6 -Compress
