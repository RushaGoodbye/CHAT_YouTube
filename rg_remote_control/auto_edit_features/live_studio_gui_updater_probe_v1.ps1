# Read-only Studio GUI and updater process verification on actual AlexPC.
# No launch, lock deletion, process termination, queue edit or config changes.
$ErrorActionPreference = 'Stop'
$root = 'F:\RG_AUTO_EDIT\RG Auto Edit App'
$data = 'F:\RG_AUTO_EDIT\RG Auto Edit Data'
if ($env:COMPUTERNAME.ToUpperInvariant() -ne 'ALEXPC') {
    throw 'Probe must run on actual AlexPC'
}
$rows = @(Get-CimInstance Win32_Process | Where-Object {
    $path = [string]$_.ExecutablePath
    $cmd = [string]$_.CommandLine
    ($cmd -match 'rg_studio_main\.py' -and $path -notmatch 'RG_GITHUB_RUNNER|RG_YT_AGENT_RUNNER') -or
    ($_.Name -match '^RG.Auto.Edit.*\.exe$' -and $path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase))
})
$ui = @()
foreach ($item in $rows) {
    $p = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
    if ($null -ne $p) {
        $handle = [long]$p.MainWindowHandle
        $response = $null
        if ($handle -ne 0) {
            try { $response = [bool]$p.Responding } catch { $response = $null }
        }
        $ui += [ordered]@{
            pid = [int]$item.ProcessId
            window_handle_present = ($handle -ne 0)
            responding = $response
            memory_mb = [math]::Round([double]$p.WorkingSet64 / 1MB,1)
        }
    }
}
$state = [ordered]@{}
foreach ($item in @('update_supervisor_state.json','boot_ok.json','pending_boot_validation.json','release_state.json')) {
    $path = Join-Path $data $item
    $r = [ordered]@{ exists = (Test-Path -LiteralPath $path) }
    if ($r.exists) {
        try {
            $doc = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($key in @('status','state','phase','version','target_version','updated_at','error')) {
                $value = $doc.PSObject.Properties[$key]
                if ($null -ne $value -and $null -ne $value.Value) {
                    $r[$key] = ([string]$value.Value).Substring(0,[math]::Min(180,([string]$value.Value).Length))
                }
            }
        } catch {
            $r['unreadable'] = $true
        }
    }
    $state[$item] = $r
}
$versionFile = Join-Path $root 'rg_studio_version.py'
$version = $null
if (Test-Path -LiteralPath $versionFile) {
    $v = Get-Content -LiteralPath $versionFile -Raw -Encoding UTF8
    if ($v -match "STUDIO_VERSION\s*=\s*['""]([^'""]+)['""]") { $version = $Matches[1] }
}
$gui_status = if ($ui.Count -eq 0) {
    'NOT_RUNNING_NO_LAUNCH'
} elseif ($ui.Count -gt 1) {
    'DUPLICATE_GUI_PROCESSES_NEED_REVIEW'
} elseif ($ui[0].window_handle_present -and $ui[0].responding -eq $true) {
    'VISIBLE_WINDOW_RESPONDING'
} elseif ($ui[0].window_handle_present -and $ui[0].responding -eq $false) {
    'WINDOW_NOT_RESPONDING'
} else {
    'RUNNING_WINDOW_NOT_VISIBLE_TO_RUNNER'
}
$result = [ordered]@{
    schema = 'RG_LIVE_STUDIO_GUI_UPDATER_PROBE_V1'
    read_only = $true
    version = $version
    gui_status = $gui_status
    studio_process_count = $ui.Count
    processes = $ui
    updater_states = $state
    gui_started = $false
    processes_stopped = 0
    lock_files_modified = 0
    media_writes = 0
    xml_writes = 0
    queue_writes = 0
}
Write-Output ('RG_LIVE_GUI_UPDATER|' + ($result | ConvertTo-Json -Compress -Depth 5))
