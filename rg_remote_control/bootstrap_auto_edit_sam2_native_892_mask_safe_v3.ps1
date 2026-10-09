param(
    [switch]$ValidateOnly,
    [string]$SourceFile = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Fail-closed pinned SAM 2.1 native Windows pilot. Validate source before
# installing anything. -ValidateOnly -SourceFile allows OFFLINE CI QA.
$commit = '5800486ba9c8a77bffdb6c66597ffcccfa6e3fd2'
$scriptPath = 'rg_remote_control/bootstrap_auto_edit_sam2_native_892_mask_v1.ps1'
Write-Host '=== RG SAM2 NATIVE WINDOWS SAFE BOOTSTRAP V3 ==='
if (-not [string]::IsNullOrWhiteSpace($SourceFile)) {
    if (-not $ValidateOnly) {
        throw 'Local source override is permitted only with -ValidateOnly. No code executed.'
    }
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
        throw 'Local script to validate does not exist. Nothing executed.'
    }
    $src = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $SourceFile).Path)
} else {
    $url = "https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/$scriptPath"
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url
    $src = [string]$response.Content
}
if ([string]::IsNullOrWhiteSpace($src)) {
    throw 'Pinned SAM2 pilot script is empty. Nothing executed.'
}
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseInput(
    $src, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors -and $parseErrors.Count -gt 0) {
    foreach ($problem in $parseErrors) {
        Write-Host ('PARSE ERROR line {0}: {1}' -f $problem.Extent.StartLineNumber, $problem.Message)
    }
    throw 'Full SAM2 pilot PowerShell parser gate failed. Nothing executed.'
}
# Each condition is added separately. Do NOT join PowerShell + expressions in
# a comma-separated @() literal; the v1 wrapper accidentally combined guards.
$requirements = [System.Collections.Generic.List[string]]::new()
$requirements.Add('$trialCommit=''fa2432890eea9070459586017b51750401a6959f''')
$requirements.Add('$sourceCommit=''98fcb164bf880f70799c324c283c758c4d20bf82''')
$requirements.Add('include-system-site-packages')
$requirements.Add("SAM2_BUILD_CUDA='0'")
$requirements.Add("'torch==2.8.0+cu126'")
$requirements.Add('automatic_blur_allowed')
$requirements.Add('do_not_publish')
$requirements.Add('RG SAM2 WINDOWS SINGLE REAL CIGARETTE MASK PILOT RESULT')
$requirements.Add('Independent Python environment isolation check failed')
$requirements.Add('review_zip=$reviewZip')
$requirements.Add('& $isoPy -I -u $code --env-check')
$requirements.Add('& $isoPy -I -u $code --cuda-check')
if ($requirements.Count -ne 12) {
    throw 'SAM2 V3 safety condition count incorrect. Nothing executed.'
}
$checked = 0
foreach ($required in $requirements) {
    if ([string]::IsNullOrWhiteSpace($required)) {
        throw 'Empty SAM2 source invariant. Nothing executed.'
    }
    if ($src.IndexOf($required, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw ('SAM2 source contract missing: ' + $required)
    }
    $checked += 1
}
if ($checked -ne 12) {
    throw 'SAM2 V3 source invariants were not checked individually.'
}
# Regress the actual Windows Python -c inline quote failure in the prior run.
if ($src -match '(?im)^\s*&\s*\$isoPy\s+-I\s+-c\b') {
    throw 'Unsafe Windows PowerShell Python -c call found, refuse to run'
}
Write-Host ('RG SAM2 PINNED SOURCE SYNTAX AND {0} SAFETY CHECKS: PASS' -f $checked)
if ($ValidateOnly) {
    Write-Host 'RG SAM2 SAFE WRAPPER V3 OFFLINE CHECK: PASS - NO INSTALL OR GPU TEST'
    return
}
Write-Host '=== RG SAM2.1 NATIVE WINDOWS PILOT (ISOLATED F: ENVIRONMENT) ==='
Write-Host 'First run may download multiple GB; will not change Studio or original videos.'
Invoke-Expression $src
