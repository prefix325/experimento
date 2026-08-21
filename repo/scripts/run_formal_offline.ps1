[CmdletBinding()]
param(
    [string] $RunBlock = '',
    [string] $ResultsDirectory = ''
)

. (Join-Path $PSScriptRoot 'common.ps1')

$repo = Get-RepoRoot
$configPath = Join-Path $repo 'experiments\tep\local_llm\config\formal.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.methodology_frozen -ne $true) {
    throw 'Formal execution is blocked: formal.json is not methodologically frozen.'
}
if ($config.scientific_execution_permitted -ne $true) {
    throw 'Formal execution is blocked: scientific_execution_permitted is false.'
}

$manifest = Get-PreparationManifest
Assert-PreparedResources $manifest

Write-Host 'FORMAL OFFLINE EXECUTION PRECHECK'
Write-Host "Model: $($manifest.model_file)"
Write-Host "Model SHA-256: $($manifest.model_sha256)"
Write-Host "Docker image ID: $($manifest.docker_image_id)"
Write-Host "Docker image digest: $($manifest.docker_image_digest)"
Write-Host "Git commit: $($manifest.git_commit)"
Write-Host "Configuration SHA-256: $($manifest.configuration_sha256.'formal.json')"
Write-Host "Dataset manifest SHA-256: $($manifest.dataset_manifest_sha256)"
foreach ($file in $manifest.dataset_files) {
    Write-Host "Dataset $($file.relative_path): $($file.sha256)"
}
Write-Host "GPU: $($manifest.hardware.gpu)"
Write-Host "Timestamp: $((Get-Date).ToUniversalTime().ToString('o'))"

Invoke-ExperimentRun -Mode 'formal' -ConfigFile 'formal.json' -RunBlock $RunBlock -ResultsDirectory $ResultsDirectory
