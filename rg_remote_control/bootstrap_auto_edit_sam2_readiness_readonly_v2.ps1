$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# RG Auto Edit SAM2 v2 READ-ONLY Windows readiness inventory.
# No package installs, no WSL invocation, no imports or CUDA workloads,
# no filesystem mutations, no source video reading, no changes to Studio.
Write-Host '=== RG AUTO EDIT SAM2 READ ONLY HARDWARE + ISOLATION CHECK V2 ==='
$root = 'F:\RG_AUTO_EDIT\RG Auto Edit Data'
$app = 'F:\RG_AUTO_EDIT\RG Auto Edit App'
$runtime = 'F:\RG_AUTO_EDIT\RG Auto Edit Runtime'
$shadow = Join-Path $root 'oss_shadow'
$positiveClip = Join-Path $shadow 'positive_892_015841_v1\892_015841_POSITIVE_REVIEW_24s_NO_AUDIO.mp4'
$positiveMeta = Join-Path $shadow 'positive_892_015841_v1\manifest.json'
$hold = Join-Path $app '886\RG_EDITED_886_5.SEMANTIC_HOLD.json'
$prodPython = Join-Path $runtime 'venv\Scripts\python.exe'
$site = Join-Path $runtime 'venv\Lib\site-packages'
$siglipSite = Join-Path $root 'oss_envs\rg_siglip_independent_shadow_v1\Lib\site-packages'
function Get-InstalledPkgVersion([string]$package) {
    if (!(Test-Path -LiteralPath $site -PathType Container)) { return $null }
    $escaped = [regex]::Escape($package)
    $items = @(Get-ChildItem -LiteralPath $site -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match ('^' + $escaped + '-(.*)\.dist-info$') })
    if ($items.Count -eq 0) { return $null }
    $versions = @()
    foreach ($entry in $items) {
        $meta = Join-Path $entry.FullName 'METADATA'
        if (Test-Path -LiteralPath $meta -PathType Leaf) {
            $row = @(Get-Content -LiteralPath $meta -TotalCount 40 -ErrorAction SilentlyContinue |
                Where-Object { $_ -like 'Version: *' } | Select-Object -First 1)
            if ($row.Count) { $versions += $row[0].Substring(9).Trim() }
            else { $versions += $entry.Name }
        } else { $versions += $entry.Name }
    }
    return ($versions -join ';')
}
$checks = [ordered]@{
    f_data_present = (Test-Path -LiteralPath $root -PathType Container)
    app_present = (Test-Path -LiteralPath $app -PathType Container)
    shadow_present = (Test-Path -LiteralPath $shadow -PathType Container)
    production_python_present = (Test-Path -LiteralPath $prodPython -PathType Leaf)
    positive_892_review_mp4_present = (Test-Path -LiteralPath $positiveClip -PathType Leaf)
    positive_892_manifest_valid = $false
    negative_8865_semantic_hold_valid = $false
    forbidden_8865_ready_xml_present = $false
    torch_version_metadata = $null
    torchvision_version_metadata = $null
    sam2_metadata = $null
    siglip_shadow_prod_site_pth = $false
    siglip_shadow_prod_site_pth_names = @()
    gpu_name = $null
    gpu_driver = $null
    vram_total_mb = $null
    vram_free_mb = $null
    nvidia_smi_present = $false
    nvidia_smi_query_pass = $false
    wsl_exe_present = ($null -ne (Get-Command 'wsl.exe' -ErrorAction SilentlyContinue))
    wsl_registered_for_current_user = @()
    wsl_cuda_access = 'NOT_TESTED_NO_WSL_LAUNCH'
    native_windows_sam2_import = 'NOT_TESTED_NO_PYTHON_IMPORT'
    sam2_checkpoint_found_in_known_shadow_locations = @()
}
if (Test-Path -LiteralPath $positiveMeta -PathType Leaf) {
    try {
        $m = Get-Content -LiteralPath $positiveMeta -Raw -Encoding UTF8 | ConvertFrom-Json
        $checks.positive_892_manifest_valid = (
            $m.schema -eq 'RG_AUTO_EDIT_892_CIGARETTE_REAL_GOLD_CAPTURE_V1' -and
            $m.stream -eq '892' -and
            $m.original_timecode -eq '01:58:41' -and
            $m.studio_modified -eq $false -and
            $m.cigarette_semantically_confirmed -eq $false
        )
    } catch { $checks.positive_892_manifest_valid = $false }
}
if (Test-Path -LiteralPath $hold -PathType Leaf) {
    try {
        $h = Get-Content -LiteralPath $hold -Raw -Encoding UTF8 | ConvertFrom-Json
        $checks.negative_8865_semantic_hold_valid = (
            $h.schema -eq 'RG_886_5_MICROPHONE_FALSE_POSITIVE_QUARANTINE_V1' -and
            $h.do_not_publish -eq $true -and
            $h.primary_xml_withheld -eq $true -and
            $h.delivered_xml_withheld -eq $true
        )
    } catch { $checks.negative_8865_semantic_hold_valid = $false }
}
$checks.forbidden_8865_ready_xml_present = (
    (Test-Path -LiteralPath (Join-Path $app 'RG_EDITED_886_5.xml') -PathType Leaf) -or
    (Test-Path -LiteralPath (Join-Path $app '886\RG_EDITED_886_5.xml') -PathType Leaf)
)
$checks.torch_version_metadata = Get-InstalledPkgVersion 'torch'
$checks.torchvision_version_metadata = Get-InstalledPkgVersion 'torchvision'
$checks.sam2_metadata = Get-InstalledPkgVersion 'sam2'
if (Test-Path -LiteralPath $siglipSite -PathType Container) {
    $pthNames = @()
    foreach ($pth in @(Get-ChildItem -LiteralPath $siglipSite -Filter '*.pth' -File -ErrorAction SilentlyContinue)) {
        try {
            $body = Get-Content -LiteralPath $pth.FullName -Raw -ErrorAction Stop
            if ($body -match '(?i)RG_AUTO_EDIT[\\/]+RG Auto Edit Runtime[\\/]+venv') {
                $pthNames += $pth.Name
            }
        } catch {}
    }
    $checks.siglip_shadow_prod_site_pth_names = @($pthNames)
    $checks.siglip_shadow_prod_site_pth = (@($pthNames).Count -gt 0)
}
$nv = Get-Command 'nvidia-smi.exe' -ErrorAction SilentlyContinue
if ($null -eq $nv) { $nv = Get-Command 'nvidia-smi' -ErrorAction SilentlyContinue }
if ($null -ne $nv) {
    $checks.nvidia_smi_present = $true
    try {
        $rows = @(& $nv.Source '--query-gpu=name,driver_version,memory.total,memory.free' '--format=csv,noheader,nounits' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $rows.Count -gt 0) {
            $cols = @(([string]$rows[0]).Trim() -split '\s*,\s*')
            if ($cols.Count -eq 4) {
                $checks.gpu_name = $cols[0]
                $checks.gpu_driver = $cols[1]
                $checks.vram_total_mb = [int]$cols[2]
                $checks.vram_free_mb = [int]$cols[3]
                $checks.nvidia_smi_query_pass = $true
            }
        }
    } catch {
        $checks.nvidia_smi_query_pass = $false
    }
}
$wslKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
if (Test-Path -LiteralPath $wslKey) {
    foreach ($entry in @(Get-ChildItem -LiteralPath $wslKey -ErrorAction SilentlyContinue)) {
        $p = Get-ItemProperty -LiteralPath $entry.PSPath -ErrorAction SilentlyContinue
        if ($null -ne $p -and $p.DistributionName) {
            $checks.wsl_registered_for_current_user += [ordered]@{
                distribution = [string]$p.DistributionName
                version = if ($null -ne $p.Version) { [int]$p.Version } else { $null }
                note = 'REGISTRATION_ONLY_NOT_STARTED'
            }
        }
    }
}
$potential = @(
    (Join-Path $root 'models\sam2\sam2.1_hiera_tiny.pt'),
    (Join-Path $shadow 'sam2\checkpoints\sam2.1_hiera_tiny.pt'),
    (Join-Path $shadow 'sam2\checkpoints\sam2.1_hiera_small.pt')
)
foreach ($p in $potential) {
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        $checks.sam2_checkpoint_found_in_known_shadow_locations += $p
    }
}
$disk = [ordered]@{drive='F:'; probe_ok=$false; free_gb=$null}
try {
    $drive = [System.IO.DriveInfo]::new('F:\')
    if ($drive.IsReady) {
        $disk.probe_ok=$true
        $disk.free_gb=[math]::Round($drive.AvailableFreeSpace/1GB,2)
    }
} catch {}
$wsl2 = @($checks.wsl_registered_for_current_user | Where-Object { $_.version -eq 2 }).Count -gt 0
$hardware = ($checks.nvidia_smi_query_pass -and $checks.vram_total_mb -ge 8000 -and $checks.vram_free_mb -ge 3500)
$space = ($disk.probe_ok -and $disk.free_gb -ge 8)
$gold = (
    $checks.positive_892_review_mp4_present -and $checks.positive_892_manifest_valid -and
    $checks.negative_8865_semantic_hold_valid -and -not $checks.forbidden_8865_ready_xml_present
)
$state = if (-not $gold) {
    'STOP_GOLD_CLIP_OR_886_QUARANTINE_CHECK'
} elseif (-not $hardware -or -not $space) {
    'DEFER_INSUFFICIENT_GPU_MEMORY_OR_DISK_SPACE'
} elseif ($wsl2) {
    'WINDOWS_GPU_AND_WSL2_REGISTRATION_PRESENT_GPU_INSIDE_WSL_UNTESTED'
} else {
    'WINDOWS_GPU_READY_WSL2_NOT_REGISTERED_NATIVE_PATH_NEEDS_FEASIBILITY'
}
$result=[ordered]@{
    schema='RG_AUTO_EDIT_SAM2_READONLY_PREFLIGHT_V2'
    status=$state
    date_utc=(Get-Date).ToUniversalTime().ToString('o')
    contour='auto_edit'
    powershell=$PSVersionTable.PSVersion.ToString()
    hardware=$checks
    disk=$disk
    action_taken='READ_ONLY_INVENTORY'
    packages_installed=$false
    package_versions_changed=$false
    production_python_imported=$false
    production_runtime_modified=$false
    source_video_opened=$false
    source_video_modified=$false
    audio_modified=$false
    XML_modified=$false
    cuda_workload_started=$false
    wsl_started=$false
    sam2_installed=$false
    sam2_mask_proof_complete=$false
    cigarette_semantic_identity_approved=$false
    publish_8865_allowed=$false
    note='Hardware preflight only. WSL registration, installed Torch metadata and checkpoint paths are not evidence SAM2 can segment a real cigarette or that blurred pixels are correct.'
}
Write-Host '=== RG AUTO EDIT SAM2 READ ONLY PREFLIGHT V2 RESULT ==='
$result | ConvertTo-Json -Depth 9
