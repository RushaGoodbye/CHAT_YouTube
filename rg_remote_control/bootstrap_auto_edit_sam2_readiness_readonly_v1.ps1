$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# RG Auto Edit / SAM 2 read-only system capabilities probe.
# NEVER installs, upgrades, invokes WSL, starts CUDA workloads or modifies any files.
Write-Host '=== RG AUTO EDIT SAM2 READINESS PREFLIGHT ==='
$root='F:\RG_AUTO_EDIT\RG Auto Edit Data'
$app='F:\RG_AUTO_EDIT\RG Auto Edit App'
$oss=Join-Path $root 'oss_envs'
$version=[ordered]@{
  schema='RG_SAM2_READINESS_PREFLIGHT_V1'
  date_utc=(Get-Date).ToUniversalTime().ToString('o')
  contour='auto_edit'
  os=[Environment]::OSVersion.VersionString
  powershell=$PSVersionTable.PSVersion.ToString()
  production_runtime_modified=$false
  packages_installed=$false
  cuda_workload_started=$false
  wsl_started=$false
}
$checks=[ordered]@{
  f_data_present=(Test-Path -LiteralPath $root -PathType Container)
  app_present=(Test-Path -LiteralPath $app -PathType Container)
  existing_norfair_shadow=(Test-Path -LiteralPath (Join-Path $oss 'rg_norfair_shadow_v1\Scripts\python.exe') -PathType Leaf)
  gpu_name=$null
  gpu_driver=$null
  vram_total_mb=$null
  vram_free_mb=$null
  nvidia_smi_ok=$false
  wsl_exe_present=$false
  registered_wsl_distros=@()
  wsl_gpu_access='NOT_TESTED'
  sam2_torch_environment='NOT_TESTED'
}
$cmd=Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if($null -eq $cmd) {$cmd=Get-Command nvidia-smi -ErrorAction SilentlyContinue}
if($null -ne $cmd){
  try {
    $data=@(& $cmd.Source '--query-gpu=name,driver_version,memory.total,memory.free' '--format=csv,noheader,nounits' 2>$null)
    if($LASTEXITCODE -eq 0 -and $data.Count -gt 0){
      $line=($data[0] | Out-String).Trim()
      $cols=@($line -split '\s*,\s*')
      if($cols.Count -eq 4){
        $checks.gpu_name=$cols[0]
        $checks.gpu_driver=$cols[1]
        $checks.vram_total_mb=[int]($cols[2])
        $checks.vram_free_mb=[int]($cols[3])
        $checks.nvidia_smi_ok=$true
      }
    }
  } catch { $checks.nvidia_smi_ok=$false }
}
$checks.wsl_exe_present=($null -ne (Get-Command wsl.exe -ErrorAction SilentlyContinue))
$wslKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
if(Test-Path -LiteralPath $wslKey){
  $rows=@()
  foreach($item in @(Get-ChildItem -LiteralPath $wslKey -ErrorAction SilentlyContinue)){
    $p=Get-ItemProperty -LiteralPath $item.PSPath -ErrorAction SilentlyContinue
    if($null -ne $p -and $p.DistributionName){
      $rows+=([ordered]@{
        name=[string]$p.DistributionName
        version=if($null -ne $p.Version){[int]$p.Version}else{$null}
        state='REGISTERED_ONLY_NOT_BOOTED'
      })
    }
  }
  $checks.registered_wsl_distros=@($rows)
}
$disk=[ordered]@{drive='F:';free_gb=$null;probe_ok=$false}
try {
  $drive=[System.IO.DriveInfo]::new('F:\')
  if($drive.IsReady){
    $disk.free_gb=[Math]::Round($drive.AvailableFreeSpace / 1GB,2)
    $disk.probe_ok=$true
  }
} catch {}
$linuxReady=(@($checks.registered_wsl_distros | Where-Object {$_.version -eq 2}).Count -gt 0)
$gpuReady=$checks.nvidia_smi_ok -and ($checks.vram_total_mb -ge 8192)
$status=if($checks.f_data_present -and $checks.app_present -and $linuxReady -and $gpuReady){
  'ELIGIBLE_FOR_WSL_CUDA_SMOKE_NOT_INSTALLED'
}else{
  'PREREQUISITES_INCOMPLETE_OR_UNVERIFIED'
}
$result=[ordered]@{
  schema=$version.schema
  status=$status
  hardware=$checks
  free_space=$disk
  production_runtime_modified=$false
  packages_installed=$false
  cuda_workload_started=$false
  wsl_started=$false
  real_cigarette_segmentation_tested=$false
  note='Registered WSL2 and Windows nvidia-smi do not prove GPU access inside WSL. SAM 2 NOT INSTALLED.'
  next='Only proceed to isolated SAM 2 test after WSL2 GPU and torch/torchvision compatibility checks.'
}
Write-Host '=== RG AUTO EDIT SAM2 READINESS RESULT ==='
$result | ConvertTo-Json -Depth 8
