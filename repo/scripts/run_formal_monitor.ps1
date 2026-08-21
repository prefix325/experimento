[CmdletBinding()]
param(
    [switch] $Mock,
    [switch] $SimulateOnly,
    [string] $StateDirectory = '',
    [ValidateRange(1, 65535)]
    [int] $Port = 8765
)

$repo = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $repo
$pythonPath = @(
    (Join-Path $repo 'experiments\tep\local_llm\src'),
    $repo
) -join [System.IO.Path]::PathSeparator
$env:PYTHONPATH = $pythonPath

$arguments = @(
    '-m', 'tools.formal_monitor.monitor',
    '--host', '127.0.0.1',
    '--port', [string]$Port,
    '--repo-root', $repo,
    '--workspace-root', $workspace
)
if ($Mock) {
    $arguments += '--mock'
}
if ($SimulateOnly) {
    if (-not $Mock) {
        throw '-SimulateOnly requires -Mock.'
    }
    $arguments += '--simulate-only'
}
if (-not [string]::IsNullOrWhiteSpace($StateDirectory)) {
    $arguments += @('--state-dir', $StateDirectory)
}

& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Formal monitor exited with code $LASTEXITCODE"
}
