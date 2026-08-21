[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'common.ps1')
Invoke-ExperimentRun -Mode 'smoke' -ConfigFile 'smoke.json'
