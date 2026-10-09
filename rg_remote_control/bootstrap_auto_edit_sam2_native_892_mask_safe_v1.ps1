$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Pre-parse complete pinned SAM2 native Windows shadow installer before invoking.
# Will DOWNLOAD a separate torch 2.8 CUDA venv and SAM2.1 tiny on F: on first run.
# Never installs via production interpreter or changes Studio.
$commit='6fe3fe454d0a4993dbc52179ab4595c8c0c7ec45'
$url="https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/$commit/rg_remote_control/bootstrap_auto_edit_sam2_native_892_mask_v1.ps1"
Write-Host '=== RG SAM2 NATIVE WINDOWS MASK PILOT FULL POWERSHELL STATIC GATE ==='
$download=Invoke-WebRequest -UseBasicParsing -Uri $url
$src=[string]$download.Content
if([string]::IsNullOrWhiteSpace($src)){throw 'Empty pinned installer; nothing executed'}
$tokens=$null
$errors=$null
[System.Management.Automation.Language.Parser]::ParseInput($src,[ref]$tokens,[ref]$errors) | Out-Null
if($errors -and $errors.Count -gt 0){
    foreach($problem in $errors){
        Write-Host ('PARSER ERROR line {0}: {1}' -f $problem.Extent.StartLineNumber,$problem.Message)
    }
    throw 'SAM2 pinned PowerShell installer parser failed. Nothing executed.'
}
$required=@(
    "$"+"trialCommit='a420213d99a075adb86945aa6bb20c0b02c8fac1'",
    "$"+"sourceCommit='98fcb164bf880f70799c324c283c758c4d20bf82'",
    'include-system-site-packages',
    "SAM2_BUILD_CUDA='0'",
    "'torch==2.8.0+cu126'",
    "Automatic_blur_allowed",
    "do_not_publish",
    "RG SAM2 WINDOWS SINGLE REAL CIGARETTE MASK PILOT RESULT"
)
# A couple of guards use case-insensitive containment as text only.
foreach($want in $required){
    if($src.IndexOf($want,[System.StringComparison]::OrdinalIgnoreCase) -lt 0){
        throw ('SAM2 source contract missing text: '+$want)
    }
}
Write-Host 'RG SAM2 POWERSHELL COMPLETE SOURCE SYNTAX: PASS'
Write-Host 'RG SAM2|NEXT=ISOLATED CUDA PYTORCH + META TINY CHECKPOINT DOWNLOAD ON F'
Invoke-Expression $src
