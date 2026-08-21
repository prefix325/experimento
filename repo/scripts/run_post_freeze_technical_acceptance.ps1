[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [switch] $ResearcherAuthorized,
    [ValidateRange(60, 1800)]
    [int] $HardTimeoutSeconds = 600
)

# Compatibility entry point. The superseded data-mounted acceptance path is
# intentionally removed: only the fixed synthetic, GPU-required path remains.
& (Join-Path $PSScriptRoot 'run_post_refreeze_technical_acceptance.ps1') `
    -ResearcherAuthorized:$ResearcherAuthorized `
    -HardTimeoutSeconds $HardTimeoutSeconds
