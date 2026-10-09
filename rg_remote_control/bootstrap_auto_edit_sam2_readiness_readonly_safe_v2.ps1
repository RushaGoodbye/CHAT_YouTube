$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# One-shot pinned SAM2 Windows capability check; strictly read-only.
# Validate full downloaded PowerShell AST BEFORE invoking capability inventory.
$ref = '7c85d933e08dcbb94d4d56b24ea7536cdcaf7077'
$url = "https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$ref/rg_remote_control/bootstrap_auto_edit_sam2_readiness_readonly_v2.ps1"
Write-Host '=== RG SAM2 READ ONLY BOOTSTRAP STATIC PARSER GATE ==='
$response = Invoke-WebRequest -UseBasicParsing -Uri $url
$source = [string]$response.Content
if ([string]::IsNullOrWhiteSpace($source)) {
    throw 'Empty pinned SAM2 readiness script; nothing executed'
}
$tokens = $null
$errorsFound = $null
[System.Management.Automation.Language.Parser]::ParseInput(
    $source, [ref]$tokens, [ref]$errorsFound) | Out-Null
if ($errorsFound -and $errorsFound.Count -gt 0) {
    foreach ($errorItem in $errorsFound) {
        Write-Host ('SYNTAX FAILURE line {0}: {1}' -f $errorItem.Extent.StartLineNumber, $errorItem.Message)
    }
    throw 'Pinned SAM2 V2 readiness PowerShell syntax invalid. Nothing executed'
}
$guard = @(
   "schema='RG_AUTO_EDIT_SAM2_READONLY_PREFLIGHT_V2'",
   "action_taken='READ_ONLY_INVENTORY'",
   'packages_installed=$false',
   'source_video_modified=$false',
   'publish_8865_allowed=$false'
)
foreach ($required in $guard) {
    if (-not $source.Contains($required)) {
        throw ('Pinned SAM2 V2 invariant absent: '+$required)
    }
}
Write-Host 'RG SAM2 POWERSHELL FULL SYNTAX: PASS'
Write-Host '=== RG SAM2 READ ONLY INVENTORY START ==='
Invoke-Expression $source
