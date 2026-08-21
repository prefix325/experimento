[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'common.ps1')
$smokeLatest = Join-Path (Get-WorkspaceRoot) 'results\smoke\LATEST.txt'
if (-not (Test-Path -LiteralPath $smokeLatest)) {
    throw 'A successful smoke test is required before the pilot.'
}
$smokePath = (Get-Content -LiteralPath $smokeLatest -Raw).Trim()
if (-not (Test-Path -LiteralPath (Join-Path $smokePath 'evaluation\metrics.json'))) {
    throw 'The latest smoke test has no completed evaluation.'
}
Invoke-ExperimentRun -Mode 'pilot' -ConfigFile 'pilot.json'
