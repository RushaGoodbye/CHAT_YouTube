# Read-only preflight for RG YouTube autonomous repair on AlexPC.
$ErrorActionPreference = 'Stop'
$results = [ordered]@{ host=$env:COMPUTERNAME; python=$false; ollama=$false; model=$false; runner=$false }
try {
  $py = & python --version 2>&1
  if ($LASTEXITCODE -eq 0) { $results.python = $true; $results.python_version = "$py" }
} catch { $results.python_error = $_.Exception.Message }
try {
  $models = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
  $results.ollama = $true
  $names = @($models.models | ForEach-Object { $_.name })
  $results.model = [bool](@($names | Where-Object { $_ -eq 'qwen3:8b' -or $_ -like 'qwen3:8b-*' }).Count)
  $results.available_models = $names
} catch { $results.ollama_error = $_.Exception.Message }
try {
  $services = @(Get-Service | Where-Object { $_.Name -like '*actions.runner*' })
  $results.runner = [bool](@($services | Where-Object Status -eq 'Running').Count)
  $results.runner_services = @($services | ForEach-Object { "$($_.Name):$($_.Status)" })
} catch { $results.runner_error = $_.Exception.Message }
$results | ConvertTo-Json -Depth 4
if (-not ($results.python -and $results.ollama -and $results.model -and $results.runner)) {
  Write-Host 'PREFLIGHT: INCOMPLETE - no changes were made.'
  exit 2
}
Write-Host 'PREFLIGHT: PASS - no changes were made.'
