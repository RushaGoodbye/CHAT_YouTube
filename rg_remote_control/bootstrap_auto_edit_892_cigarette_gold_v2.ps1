$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Pinned RG Auto Edit 892 cigarette-positive evidence extraction.
# Validate COMPLETE Windows PowerShell syntax BEFORE any source reading or writes.
# No production Studio updates, no audio/XML modifications.
$PinnedCommit = '38742a881a6ce2decb35289aec7a206a54a492f7'
$ScriptPath = 'rg_remote_control/bootstrap_auto_edit_892_cigarette_gold_v1.ps1'
$Url = "https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$PinnedCommit/$ScriptPath"
Write-Host '=== RG 892 BOOTSTRAP WINDOWS POWERSHELL PARSER VALIDATION ==='
$Reply = Invoke-WebRequest -Uri $Url -UseBasicParsing
$ScriptText = [string]$Reply.Content
if ([string]::IsNullOrWhiteSpace($ScriptText)) {
    throw 'Pinned extraction script returned empty content. Nothing executed.'
}
$Tokens = $null
$ParseErrors = $null
[System.Management.Automation.Language.Parser]::ParseInput(
    $ScriptText, [ref]$Tokens, [ref]$ParseErrors) | Out-Null
if ($ParseErrors -and $ParseErrors.Count -gt 0) {
    foreach ($ParseError in $ParseErrors) {
        Write-Host ('POWERSHELL SYNTAX ERROR line {0}: {1}' -f $ParseError.Extent.StartLineNumber, $ParseError.Message)
    }
    throw 'Pinned 892 bootstrap failed full PowerShell parser validation; no media accessed.'
}
if (-not $ScriptText.Contains("'886_5_quarantine_unchanged'=")) {
    throw 'Quarantine verification output key unexpectedly changed. Stop before extraction.'
}
if (-not $ScriptText.Contains("sourceRef='0087f899fa3d66154450a50b9952d40ad4561c89'")) {
    throw 'Pinned Python extractor reference unexpectedly changed. Stop before extraction.'
}
Write-Host 'RG 892 POWERSHELL COMPLETE SYNTAX: PASS'
Write-Host '=== RG 892 VERIFIED READ-ONLY EXTRACTION BOOTSTRAP ==='
Invoke-Expression $ScriptText
