# Trusted, fail-closed Ollama Windows repair. Existing model folder and RG programs untouched.
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$server=Join-Path $root 'lib\ollama\llama-server.exe'
$oldCli=Join-Path $root 'ollama.exe'
if(-not (Test-Path -LiteralPath $oldCli -PathType Leaf)){throw 'Existing Ollama CLI is absent'}
if(Test-Path -LiteralPath $server -PathType Leaf){throw 'llama-server already exists; repair not needed'}
$release=Invoke-RestMethod -Uri 'https://api.github.com/repos/ollama/ollama/releases/latest' -Headers @{'User-Agent'='RG-YouTube-Control-QA';'Accept'='application/vnd.github+json'} -TimeoutSec 45
$asset=@($release.assets | Where-Object {$_.name -eq 'OllamaSetup.exe'}) | Select-Object -First 1
if(-not $asset){throw "Ollama latest release $($release.tag_name) has no official OllamaSetup.exe"}
$url=[string]$asset.browser_download_url
if($url -notmatch '^https://github\.com/ollama/ollama/releases/download/v[0-9][^/]+/OllamaSetup\.exe$'){throw 'Unexpected upstream Ollama asset URL'}
$digest=[string]$asset.digest
if($digest -notmatch '^sha256:[a-fA-F0-9]{64}$'){throw 'Official Ollama release has no SHA256 digest; abort'}
$size=[long]$asset.size
if($size -lt 2000000 -or $size -gt 5000000000){throw 'Unexpected upstream installer size'}
$free=(Get-PSDrive -Name C).Free
if($free -lt ($size * 2 + 1200000000)){throw "Insufficient C: free space for safe repair: available=$free installer=$size"}
$backup=Join-Path $env:LOCALAPPDATA ('RGYouTubeControl\diagnostics\ollama-repair-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -Path $backup -ItemType Directory -Force | Out-Null
$setup=Join-Path $backup 'OllamaSetup.exe'
Write-Host "OFFICIAL_OLLAMA_RELEASE $($release.tag_name)"
Write-Host "DOWNLOAD_ASSET_BYTES $size"
Write-Host "INSTALLER_SHA256_EXPECTED $($digest.Substring(7))"
Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing -TimeoutSec 1800
$actual=(Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
if($actual -ne $digest.Substring(7).ToLowerInvariant()){Remove-Item -LiteralPath $setup -Force;throw 'Official installer SHA256 mismatch; abort'}
Write-Host "OFFICIAL_INSTALLER_SHA256_PASS"
$modelPath=Join-Path $env:USERPROFILE '.ollama\models'
$modelExists=Test-Path -LiteralPath $modelPath
# Stop only Ollama, never GitHub Runner, GUI, model directory or user files.
Get-Process -Name 'ollama','ollama app' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$proc=Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT','/SP-','/SUPPRESSMSGBOXES','/NORESTART') -Wait -PassThru
if($proc.ExitCode -notin @(0,3010)){throw "Official Ollama installer exited with $($proc.ExitCode)"}
$expectedDirs=@((Join-Path $root 'lib\ollama'),(Join-Path $root 'lib'))
$serverFound=@()
foreach($d in $expectedDirs){
 if(Test-Path -LiteralPath $d){
   $serverFound+=@(Get-ChildItem -Path $d -File -Recurse -Filter 'llama-server.exe' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -First 5)
 }
}
if(-not $serverFound){throw 'Installer completed but llama-server is still missing; see diagnostic file'}
$modelsPreserved=(-not $modelExists) -or (Test-Path -LiteralPath $modelPath)
$tag=[string]$release.tag_name
$report=[ordered]@{
 schema='RG_OLLAMA_REPAIR_V1';status='FILES_RESTORED';official_release=$tag
 digest_verified=$true;installer_bytes=$size
 server_files=@($serverFound|Select-Object -Unique)
 model_folder_preserved=$modelsPreserved;backup=$backup
 run_as=$env:USERNAME;youtube_api_calls=0
}
$report | ConvertTo-Json -Depth 6 -Compress
if(-not $modelsPreserved){throw 'Unexpected missing model directory after repair'}
