[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 500)]
    [int] $RunOrdinal,
    [Parameter(Mandatory = $true)]
    [ValidateSet('target', 'normal_holdout')]
    [string] $Cohort,
    [Parameter(Mandatory = $true)]
    [ValidateSet('llm', 'dpca')]
    [string] $Detector,
    [Parameter(Mandatory = $true)]
    [string] $ResultsDirectory,
    [switch] $ConstructOnly
)

. (Join-Path $PSScriptRoot 'common.ps1')

$repo = Get-RepoRoot
$workspace = Get-WorkspaceRoot
$configPath = Join-Path $repo 'experiments\tep\local_llm\config\formal.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.methodology_frozen -ne $true) {
    throw 'Formal batch execution is blocked: methodology_frozen is false.'
}
$gateReport = Get-FormalOperationalGateReport `
    $repo $workspace -AllowBlocked:$ConstructOnly

$manifest = Get-PreparationManifest
$preparationReport = if ($ConstructOnly) {
    Assert-RefreezePreparationManifest $manifest
} else {
    Assert-PreparedResources $manifest
    [ordered]@{
        preparation_manifest_current = $true
        formal_hash_match = $true
        method_freeze_match = $true
        technical_acceptance_match = $true
    }
}
$docker = Get-DockerExe
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $workspace 'results\formal'))
$results = [System.IO.Path]::GetFullPath($ResultsDirectory)
if (-not $results.StartsWith($allowedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Formal batch results must remain inside $allowedRoot"
}
$formalCwd = Split-Path -Parent $results
foreach ($operationalDirectory in @($formalCwd, $results)) {
    New-Item -ItemType Directory -Force -Path $operationalDirectory | Out-Null
    if (-not (Test-Path -LiteralPath $operationalDirectory -PathType Container)) {
        throw "Formal operational directory is unavailable: $operationalDirectory"
    }
}

$normal = Join-Path $workspace 'data\normal\blind'
$test = if ($Cohort -eq 'target') {
    Join-Path $workspace 'data\test\blind'
} else {
    Join-Path $workspace 'data\normal_holdout\blind'
}
$models = Join-Path $workspace 'models'
$experimentId = "tep-formal-batch-$Cohort-$Detector-$('{0:D3}' -f $RunOrdinal)"
$envArgs = Get-ContainerEnvironmentArgs $manifest $experimentId
$blockArgs = if ($Detector -eq 'llm') {
    @('--run-block', [string]$RunOrdinal)
} else {
    @('--dpca-run-block', [string]$RunOrdinal)
}
$operationalAmendmentArgs = if ($Detector -eq 'llm') {
    @(
        '--operational-amendment',
        '/opt/tep/config/post_freeze_operational_amendment_001.json'
    )
} else {
    @()
}
$arguments = @(
    'run', '--rm', '--gpus', 'all', '--network', 'none', '--read-only',
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--tmpfs', '/tmp:rw,nosuid,nodev,size=2g',
    '-v', "${normal}:/data/normal:ro",
    '-v', "${test}:/data/test:ro",
    '-v', "${models}:/models:ro",
    '-v', "${results}:/results:rw",
    '-v', "${repo}\experiments\tep\local_llm\src:/opt/tep/src:ro",
    '-v', "${repo}\experiments\tep\local_llm\config:/opt/tep/config:ro",
    '-v', "${repo}\experiments\tep\local_llm\config:/governance/repo/experiments/tep/local_llm/config:ro",
    '-v', "${workspace}\manifests:/governance/manifests:ro",
    '-v', "${workspace}\results\technical_acceptance:/governance/results/technical_acceptance:ro",
    '-e', 'PYTHONPATH=/opt/tep/src'
) + $envArgs + @(
    $manifest.docker_image_tag,
    'run-detectors',
    '--config', '/opt/tep/config/formal.json',
    '--results', '/results',
    '--normal', '/data/normal',
    '--test', '/data/test',
    '--models', '/models',
    '--cohort', $Cohort,
    '--detector', $Detector,
    '--governance-repo-root', '/governance/repo',
    '--governance-workspace-root', '/governance',
    '--methodological-amendment', '/opt/tep/config/post_freeze_methodological_amendment_002.json'
) + $blockArgs + $operationalAmendmentArgs

if ($ConstructOnly) {
    [ordered]@{
        gate_status = $gateReport.status
        gate_checks = $gateReport.checks
        preparation_checks = $preparationReport
        formal_hash_match = $preparationReport.formal_hash_match
        preparation_manifest_current = $preparationReport.preparation_manifest_current
        method_freeze_match = $preparationReport.method_freeze_match
        technical_acceptance_match = $preparationReport.technical_acceptance_match
        historical_scientific_execution_permitted = $config.scientific_execution_permitted
        formal_powershell_command = @(
            'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', $MyInvocation.MyCommand.Path,
            '-RunOrdinal', [string]$RunOrdinal,
            '-Cohort', $Cohort,
            '-Detector', $Detector,
            '-ResultsDirectory', $results,
            '-ConstructOnly'
        )
        cwd = $formalCwd
        cwd_exists = (Test-Path -LiteralPath $formalCwd -PathType Container)
        results_directory = $results
        results_directory_exists = (Test-Path -LiteralPath $results -PathType Container)
        docker_executable = $docker
        docker_arguments = $arguments
        docker_executed = $false
        formal_run_started = $false
        process_started = $false
        formal_lots_started = 0
        llm_inference_count = 0
        dataset_files_opened = 0
    } | ConvertTo-Json -Depth 8
    return
}

& $docker @arguments
Assert-ExitCode "Formal $Cohort $Detector simulationRun batch $RunOrdinal"
