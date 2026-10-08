$ErrorActionPreference='Stop'
$runtime='F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe'
$script=Join-Path $env:TEMP 'RG_886_RESUME_DECISION_V1.py'
$report=Join-Path $env:TEMP 'RG_886_RESUME_DECISION_V1.txt'
$url='https://raw.githubusercontent.com/RushaGoodbye/CHAT_YouTube/889f1bc4c5b4109ab80495b2dc1029def8248189/rg_remote_control/inspect_auto_edit_886_resume_decision_v1.py'
if(!(Test-Path -LiteralPath $runtime)){throw "RG Auto Edit Runtime not found: $runtime"}
Invoke-WebRequest -Uri $url -OutFile $script -UseBasicParsing
& $runtime -m py_compile $script
if($LASTEXITCODE -ne 0){throw 'Read-only 886 decision audit compile failed'}
& $runtime -u -X utf8 $script | Out-File -LiteralPath $report -Encoding utf8 -Width 4096
if($LASTEXITCODE -ne 0){throw 'Read-only 886 decision audit failed'}
Write-Host '=== RG 886 RESUME DECISION RESULT ==='
$raw=Get-Content -LiteralPath $report -Raw -Encoding utf8
$index=$raw.IndexOf('{')
if($index -lt 0){throw 'Audit JSON missing'}
$d=$raw.Substring($index) | ConvertFrom-Json
Write-Host ('CURRENT PRIMARY XMLS: '+(@($d.current_primary_xmls | ForEach-Object { $_.name }) -join ', '))
Write-Host ('RESUME GUARD PRESENT: '+$d.installed_resume_source.guard_present)
Write-Host ('RESUME DECISION CODE FOUND: '+(-not [string]::IsNullOrEmpty($d.installed_resume_source.resume_code_excerpt)))
Write-Host ('MANIFEST RECORDS: '+@($d.run_manifest).Count)
Write-Host ('CIGARETTE QA RECORDS: '+@($d.cigarette_886_5_reports).Count)
Write-Host ('REPORT FILE: '+$report)
Write-Host 'Please attach REPORT FILE to ChatGPT. No processing was started.'
