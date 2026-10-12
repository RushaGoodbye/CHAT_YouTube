# Stage verified 0.7.23 Windows installer on AlexPC. Never execute.
# No execution, no UAC, no app shutdown or YouTube changes.
$ErrorActionPreference="Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$token=[string]$env:RG_ARTIFACT_READ_TOKEN
if([string]::IsNullOrWhiteSpace($token)){throw "Missing scoped GitHub Actions read token"}
$id=11741610813
$expectedArtifactHash="f5fa30e91a1adf1a6b653d64625a724420f8433fd56d7abbeed6861877395dd4"
$version="0.7.23"
$expectedInstallerName="RG_YouTube_Control_Setup_0.7.23.exe"
$root=Join-Path $env:TEMP "rg-youtube-stage-0723"
New-Item -ItemType Directory -Force -Path $root | Out-Null
$outer=Join-Path $root 'official-ci-artifact.zip'
$dest=Join-Path (Join-Path $env:USERPROFILE 'Downloads') $expectedInstallerName
$staged=$dest+".staging"
try {
  $url="https://api.github.com/repos/RushaGoodbye/CHAT_YouTube/actions/artifacts/$id/zip"
  $headers=@{"Authorization"="Bearer $token";"Accept"="application/vnd.github+json";"User-Agent"="RG-YouTube-Control-Verified-Installer"}
  Invoke-WebRequest -Uri $url -Headers $headers -OutFile $outer -MaximumRedirection 5 -TimeoutSec 360 -UseBasicParsing
  $outerHash=(Get-FileHash -LiteralPath $outer -Algorithm SHA256).Hash.ToLowerInvariant()
  if($outerHash -ne $expectedArtifactHash){throw "GitHub artifact SHA256 mismatch"}
  $archive=[IO.Compression.ZipFile]::OpenRead($outer)
  try {
    $manifestEntry=$archive.Entries | Where-Object {$_.FullName -eq 'latest.json'} | Select-Object -First 1
    $setupEntry=$archive.Entries | Where-Object {$_.FullName -eq $expectedInstallerName} | Select-Object -First 1
    $checksumEntry=$archive.Entries | Where-Object {$_.FullName -eq "$expectedInstallerName.sha256"} | Select-Object -First 1
    if(-not $manifestEntry -or -not $setupEntry -or -not $checksumEntry){throw "CI artifact missing installer/manifest/checksum"}
    function Read-ZipText($entry) {
      $stream=$entry.Open()
      $reader=New-Object IO.StreamReader($stream,[Text.Encoding]::UTF8,$true)
      try{return $reader.ReadToEnd()} finally {$reader.Dispose();$stream.Dispose()}
    }
    $manifest=Read-ZipText $manifestEntry | ConvertFrom-Json
    if($manifest.version -ne $version -or $manifest.installer_name -ne $expectedInstallerName){throw "Version or installer mismatch"}
    $expectedHash=((Read-ZipText $checksumEntry) -split '\s+')[0].Trim().ToLowerInvariant()
    if($expectedHash -notmatch '^[0-9a-f]{64}$'){throw "Invalid installer SHA256"}
    $download=Join-Path $root $expectedInstallerName
    $file=[IO.File]::Create($download)
    $stream=$setupEntry.Open()
    try{$stream.CopyTo($file)}finally{$file.Dispose();$stream.Dispose()}
  } finally {$archive.Dispose()}
  $realHash=(Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant()
  if($realHash -ne $expectedHash){throw "Installer SHA256 mismatch"}
  Copy-Item -LiteralPath $download -Destination $staged -Force -ErrorAction Stop
  Move-Item -LiteralPath $staged -Destination $dest -Force -ErrorAction Stop
  [pscustomobject]@{
    schema='RG_YOUTUBE_STAGE_INSTALLER_0723_V1'
    ready=$true
    version=$version
    destination=$dest
    installer_bytes=(Get-Item -LiteralPath $dest).Length
    installer_sha256=$realHash
    github_artifact_id=$id
    artifact_sha256_verified=$true
    installer_sha256_verified=$true
    app_untouched=$true
    installer_not_launched=$true
    youtube_api_calls=0
  }|ConvertTo-Json -Depth 5 -Compress
} finally {
  if(Test-Path -LiteralPath $staged){Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue}
  if(Test-Path -LiteralPath $outer){Remove-Item -LiteralPath $outer -Force -ErrorAction SilentlyContinue}
}
