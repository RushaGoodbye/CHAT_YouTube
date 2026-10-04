param(
    [string]$RemoteUser = "rgremote"
)

$ErrorActionPreference = "Stop"

$cap = Get-WindowsCapability -Online |
    Where-Object Name -like 'OpenSSH.Server*' |
    Select-Object -First 1

if (-not $cap) {
    throw "OpenSSH.Server capability not found"
}
if ($cap.State -ne "Installed") {
    Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}

Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

if (-not (Get-LocalUser -Name $RemoteUser -ErrorAction SilentlyContinue)) {
    Write-Host "Create the dedicated local user '$RemoteUser' before continuing."
    exit 2
}

$rule = Get-NetFirewallRule -Name "RGRemote-SSH-From-NAS" -ErrorAction SilentlyContinue
if (-not $rule) {
    New-NetFirewallRule -Name "RGRemote-SSH-From-NAS" `
        -DisplayName "RG Remote SSH from NAS" `
        -Enabled True -Direction Inbound -Protocol TCP `
        -Action Allow -LocalPort 22 | Out-Null
}

Write-Host "OPENSSH_READY"
Write-Host "Next: put the NAS public key into the dedicated user's authorized_keys."
