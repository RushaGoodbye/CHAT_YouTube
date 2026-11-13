# RG AlexPC read-only host health. Intended for interactive Windows PowerShell.
# Does not read credentials, modify files, restart services or invoke external scripts.
$ErrorActionPreference = 'Stop'
$report = [ordered]@{
    schema = 'RG_ALEXPC_READONLY_HEALTH_V1'
    checked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    read_only = $true
    status = 'UNKNOWN'
    platform = 'Windows'
    runner_listener_present = $false
    auto_edit_f_root_present = $false
    auto_edit_runner_f_present = $false
    github_runner_c_present = $false
    f_drive_free_gb = $null
    errors = @()
}
try {
    $report.auto_edit_f_root_present = Test-Path -LiteralPath 'F:\RG_AUTO_EDIT' -PathType Container
    $report.auto_edit_runner_f_present = Test-Path -LiteralPath 'F:\RG_AUTO_EDIT\RG_AutoEdit_Runner' -PathType Container
    $report.github_runner_c_present = Test-Path -LiteralPath 'C:\RG_GITHUB_RUNNER' -PathType Container
    $runner = @(Get-Process -Name 'Runner.Listener' -ErrorAction SilentlyContinue)
    $report.runner_listener_present = ($runner.Count -gt 0)
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='F:'" -ErrorAction Stop
    if ($null -ne $disk -and $null -ne $disk.FreeSpace) {
        $report.f_drive_free_gb = [math]::Round([double]$disk.FreeSpace / 1GB, 1)
    }
    $report.status = if ($report.auto_edit_f_root_present -and $report.runner_listener_present) {'HOST_PRESENT'} else {'ATTENTION'}
} catch {
    $report.errors = @('READONLY_CHECK_FAILED:' + $_.Exception.GetType().Name)
    $report.status = 'UNKNOWN'
}
$report | ConvertTo-Json -Depth 3 -Compress
if ($report.status -eq 'UNKNOWN') { exit 2 }
