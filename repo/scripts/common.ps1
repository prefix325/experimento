Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-WorkspaceRoot {
    return (Split-Path -Parent (Get-RepoRoot))
}

function Get-DockerExe {
    $candidate = 'X:\Docker\DockerDesktop\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $candidate) {
        $env:Path = "$(Split-Path -Parent $candidate);$env:Path"
        return $candidate
    }
    $command = Get-Command docker -ErrorAction Stop
    return $command.Source
}

function Get-Sha256([string] $Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file not found: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-ExitCode([string] $Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE"
    }
}

function Get-FormalOperationalGateReport(
    [string] $RepoRoot,
    [string] $WorkspaceRoot,
    [switch] $AllowBlocked
) {
    $sourceRoot = Join-Path $RepoRoot 'experiments\tep\local_llm\src'
    $pythonPath = @($sourceRoot, $RepoRoot) -join [System.IO.Path]::PathSeparator
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $pythonPath
        $output = & python -m tools.formal_monitor.gates `
            --repo-root $RepoRoot --workspace-root $WorkspaceRoot 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
    $text = ($output -join [Environment]::NewLine)
    if ($exitCode -ne 0 -and -not $AllowBlocked) {
        throw "Formal operational gate rejected execution (exit $exitCode): $text"
    }
    try {
        $report = $text | ConvertFrom-Json
    } catch {
        throw "Formal operational gate returned invalid JSON: $text"
    }
    $requiredChecks = @(
        'methodological_gate',
        'operational_amendment_gate',
        'implementation_conformance',
        'technical_acceptance',
        'gpu_offload_acceptance',
        'offline_network_none_acceptance',
        'local_research_execution_authorization'
    )
    foreach ($name in $requiredChecks) {
        if (-not ($report.checks.PSObject.Properties.Name -contains $name)) {
            throw "Formal operational gate is missing required check: $name"
        }
        if ($report.checks.$name -ne $true -and -not $AllowBlocked) {
            throw "Formal operational gate check failed: $name"
        }
    }
    if (
        -not $AllowBlocked -and
        ($report.ready -ne $true -or $report.status -ne 'REAL START READY')
    ) {
        throw "Formal operational gate status is inconsistent: $($report.status)"
    }
    return $report
}

function Get-PreparationManifest {
    $path = Join-Path (Get-WorkspaceRoot) 'manifests\preparation.json'
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Preparation manifest missing: $path. Run .\scripts\prepare_online.ps1 first."
    }
    return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}

function Assert-RefreezePreparationManifest($Manifest) {
    $workspace = Get-WorkspaceRoot
    $repo = Get-RepoRoot
    $configRoot = Join-Path $repo 'experiments/tep/local_llm/config'
    $methodFreezeId = 'TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH'
    $formalPath = Join-Path $configRoot 'formal.json'
    $formalHash = Get-Sha256 $formalPath

    if ($Manifest.status -ne 'FORMAL_REFREEZE_PREPARATION_CURRENT') {
        throw "Preparation manifest is not current: $($Manifest.status)"
    }
    if ($Manifest.method_freeze_id -ne $methodFreezeId) {
        throw "Preparation method freeze mismatch: $($Manifest.method_freeze_id)"
    }
    if (
        $Manifest.formal_sha256 -ne $formalHash -or
        $Manifest.configuration_sha256.'formal.json' -ne $formalHash
    ) {
        throw 'Preparation formal.json hash continuity failed.'
    }

    $artifactFiles = $Manifest.frozen_artifacts.files
    $artifactHashes = $Manifest.frozen_artifacts.sha256
    foreach ($key in @(
        'prompt_template', 'output_schema', 'representation_contract',
        'evaluation_contract', 'formal_run_selection',
        'formal_normal_holdout_selection', 'dpca_reference',
        'dpca_artifact', 'h3_evidence_reference'
    )) {
        $path = Join-Path $configRoot ([string]$artifactFiles.$key)
        if ((Get-Sha256 $path) -ne $artifactHashes.$key) {
            throw "Preparation frozen artifact mismatch: $key"
        }
    }

    $modelPath = Join-Path (Join-Path $workspace 'models') ([string]$Manifest.model_file)
    if ((Get-Sha256 $modelPath) -ne $Manifest.model_sha256) {
        throw 'Preparation model hash continuity failed.'
    }

    $acceptancePath = Join-Path $workspace (
        [string]$Manifest.governance.technical_acceptance.artifact -replace '/', [IO.Path]::DirectorySeparatorChar
    )
    $conformancePath = Join-Path $workspace (
        [string]$Manifest.governance.implementation_conformance.artifact -replace '/', [IO.Path]::DirectorySeparatorChar
    )
    $localGatePath = Join-Path $workspace (
        [string]$Manifest.governance.local_execution_gate.artifact -replace '/', [IO.Path]::DirectorySeparatorChar
    )
    $governanceArtifacts = @(
        [pscustomobject]@{ Path = $acceptancePath; Expected = $Manifest.governance.technical_acceptance.sha256 },
        [pscustomobject]@{ Path = $conformancePath; Expected = $Manifest.governance.implementation_conformance.sha256 },
        [pscustomobject]@{ Path = $localGatePath; Expected = $Manifest.governance.local_execution_gate.sha256 }
    )
    foreach ($artifact in $governanceArtifacts) {
        if ((Get-Sha256 $artifact.Path) -ne $artifact.Expected) {
            throw "Preparation governance artifact mismatch: $($artifact.Path)"
        }
    }

    $acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json
    $conformance = Get-Content -LiteralPath $conformancePath -Raw | ConvertFrom-Json
    $localGate = Get-Content -LiteralPath $localGatePath -Raw | ConvertFrom-Json
    if (
        $acceptance.verdict -ne 'PASS' -or
        $acceptance.method_freeze_id -ne $methodFreezeId -or
        $conformance.verdict -ne 'PASS' -or
        $conformance.method_freeze_id -ne $methodFreezeId -or
        $conformance.formal_sha256 -ne $formalHash -or
        $localGate.gate_status -ne 'REAL START READY' -or
        $localGate.method_freeze_id -ne $methodFreezeId -or
        $localGate.formal_sha256 -ne $formalHash
    ) {
        throw 'Preparation governance continuity failed.'
    }

    $docker = Get-DockerExe
    $imageId = (& $docker image inspect $Manifest.docker_image_tag --format '{{.Id}}').Trim()
    Assert-ExitCode 'Preparation Docker image identity'
    $imageDigest = (& $docker image inspect $Manifest.docker_image_tag --format '{{index .RepoDigests 0}}').Trim()
    Assert-ExitCode 'Preparation Docker image digest'
    if (
        $imageId -ne $Manifest.docker_image_id -or
        $imageDigest -ne $Manifest.docker_image_digest
    ) {
        throw 'Preparation Docker image continuity failed.'
    }

    return [ordered]@{
        preparation_manifest_current = $true
        formal_hash_match = $true
        method_freeze_match = $true
        technical_acceptance_match = $true
        implementation_conformance_match = $true
        local_execution_gate_match = $true
        model_match = $true
        prompt_match = $true
        contracts_match = $true
        run_selections_match = $true
        dpca_reference_match = $true
        docker_image_match = $true
    }
}

function Assert-PreparedResources($Manifest) {
    $workspace = Get-WorkspaceRoot
    $docker = Get-DockerExe
    $null = Assert-RefreezePreparationManifest $Manifest
    $actualImage = & $docker image inspect $Manifest.docker_image_tag --format '{{.Id}}' 2>$null
    Assert-ExitCode 'Docker image inspection'
    if ($actualImage.Trim() -ne $Manifest.docker_image_id) {
        throw "Docker image ID mismatch. Expected $($Manifest.docker_image_id), found $actualImage"
    }

    $actualDigest = (& $docker image inspect $Manifest.docker_image_tag --format '{{index .RepoDigests 0}}').Trim()
    if ($actualDigest -ne $Manifest.docker_image_digest) {
        throw "Docker image digest mismatch. Expected $($Manifest.docker_image_digest), found $actualDigest"
    }

    $repo = Get-RepoRoot
    foreach ($name in @('smoke.json', 'pilot.json', 'formal.json', 'output_schema.json')) {
        $actualConfigHash = Get-Sha256 (Join-Path $repo "experiments\tep\local_llm\config\$name")
        if ($actualConfigHash -ne $Manifest.configuration_sha256.$name) {
            throw "Configuration hash mismatch for $name"
        }
    }
    $actualPromptHash = Get-Sha256 (Join-Path $repo 'experiments\tep\local_llm\config\prompt_template.txt')
    if ($actualPromptHash -ne $Manifest.prompt_template_sha256) {
        throw 'Prompt template hash mismatch'
    }

    $modelPath = Join-Path $workspace "models\$($Manifest.model_file)"
    $modelHash = Get-Sha256 $modelPath
    if ($modelHash -ne $Manifest.model_sha256) {
        throw "Model hash mismatch. Expected $($Manifest.model_sha256), found $modelHash"
    }

    foreach ($file in $Manifest.dataset_files) {
        $path = Join-Path (Join-Path $workspace 'data') ($file.relative_path -replace '/', '\')
        $actual = Get-Sha256 $path
        if ($actual -ne $file.sha256) {
            throw "Dataset hash mismatch for $($file.relative_path)"
        }
    }
}

function Get-ContainerEnvironmentArgs($Manifest, [string] $ExperimentId) {
    $repo = Get-RepoRoot
    $dirty = if (git -C $repo status --porcelain) { 'true' } else { 'false' }
    return @(
        '-e', "EXPERIMENT_ID=$ExperimentId",
        '-e', "GIT_COMMIT=$($Manifest.git_commit)",
        '-e', "GIT_DIRTY=$dirty",
        '-e', "DOCKER_VERSION=$($Manifest.docker_version)",
        '-e', "DOCKER_IMAGE_ID=$($Manifest.docker_image_id)",
        '-e', "DOCKER_IMAGE_DIGEST=$($Manifest.docker_image_digest)",
        '-e', "LLAMA_CPP_VERSION=$($Manifest.llama_cpp_version)",
        '-e', "MODEL_SHA256=$($Manifest.model_sha256)",
        '-e', "DATASET_SHA256=$($Manifest.dataset_manifest_sha256)",
        '-e', "HOST_CPU=$($Manifest.hardware.cpu)",
        '-e', "HOST_RAM=$($Manifest.hardware.ram_gb) GB",
        '-e', "HOST_GPU=$($Manifest.hardware.gpu)",
        '-e', "HOST_VRAM=$($Manifest.hardware.vram_mib) MiB",
        '-e', "NVIDIA_DRIVER=$($Manifest.hardware.nvidia_driver)",
        '-e', "CUDA_RUNTIME=$($Manifest.hardware.cuda_visible_in_container)"
    )
}

function Invoke-ExperimentRun(
    [string] $Mode,
    [string] $ConfigFile,
    [string] $RunBlock = '',
    [string] $ResultsDirectory = ''
) {
    $workspace = Get-WorkspaceRoot
    $repo = Get-RepoRoot
    $docker = Get-DockerExe
    $manifest = Get-PreparationManifest
    Assert-PreparedResources $manifest

    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $experimentId = "tep-local-$Mode-$timestamp"
    $allowedResultsRoot = [System.IO.Path]::GetFullPath((Join-Path $workspace "results\$Mode"))
    if ([string]::IsNullOrWhiteSpace($ResultsDirectory)) {
        $results = Join-Path $allowedResultsRoot $experimentId
    } else {
        $results = [System.IO.Path]::GetFullPath($ResultsDirectory)
        if (-not $results.StartsWith($allowedResultsRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Resume directory must be inside $allowedResultsRoot"
        }
        $experimentId = Split-Path -Leaf $results
    }
    New-Item -ItemType Directory -Force -Path $results | Out-Null

    $normal = Join-Path $workspace 'data\normal\blind'
    $normalHoldout = Join-Path $workspace 'data\normal_holdout\blind'
    $test = Join-Path $workspace 'data\test\blind'
    $truth = Join-Path $workspace 'data\test\ground_truth'
    $models = Join-Path $workspace 'models'
    $envArgs = Get-ContainerEnvironmentArgs $manifest $experimentId

    $gpuArgs = @('--gpus', 'all')
    $baseDetectorArgs = @(
        'run', '--rm', '--network', 'none'
    ) + $gpuArgs + @(
        '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=2g',
        '-v', "${normal}:/data/normal:ro",
        '-v', "${test}:/data/test:ro",
        '-v', "${normalHoldout}:/data/normal_holdout:ro",
        '-v', "${models}:/models:ro",
        '-v', "${results}:/results:rw"
    ) + $envArgs
    if ($Mode -eq 'formal') {
        $baseDetectorArgs += @(
            '-v', "${repo}\experiments\tep\local_llm\src:/opt/tep/src:ro",
            '-v', "${repo}\experiments\tep\local_llm\config:/opt/tep/config:ro"
        )
    }
    $blockArgs = @()
    if (-not [string]::IsNullOrWhiteSpace($RunBlock)) {
        $blockArgs = @('--run-block', $RunBlock)
    }
    $amendmentArgs = @()
    if ($Mode -eq 'formal') {
        $amendmentArgs = @(
            '--methodological-amendment',
            '/opt/tep/config/post_freeze_methodological_amendment_002.json'
        )
    }
    $targetDetectorArgs = $baseDetectorArgs + @(
        $manifest.docker_image_tag,
        'run-detectors', '--config', "/opt/tep/config/$ConfigFile",
        '--results', '/results/target', '--test', '/data/test', '--cohort', 'target'
    ) + $blockArgs + $amendmentArgs
    & $docker @targetDetectorArgs
    Assert-ExitCode "$Mode target detector run"

    $normalDetectorArgs = $baseDetectorArgs + @(
        $manifest.docker_image_tag,
        'run-detectors', '--config', "/opt/tep/config/$ConfigFile",
        '--results', '/results/normal_holdout', '--test', '/data/normal_holdout',
        '--cohort', 'normal_holdout'
    ) + $blockArgs + $amendmentArgs
    & $docker @normalDetectorArgs
    Assert-ExitCode "$Mode normal-holdout detector run"

    $targetComplete = Join-Path $results 'target\detectors_complete.json'
    $normalComplete = Join-Path $results 'normal_holdout\detectors_complete.json'
    if (-not (Test-Path -LiteralPath $targetComplete) -or -not (Test-Path -LiteralPath $normalComplete)) {
        $latest = Join-Path $workspace "results\$Mode\LATEST.txt"
        Set-Content -LiteralPath $latest -Value $results -Encoding UTF8
        Write-Host "Checkpoint block complete; formal cohorts remain partial: $results"
        Write-Host "Resume with -ResultsDirectory '$results'"
        return
    }

    $evaluationArgs = @(
        'run', '--rm', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m',
        '-v', "${truth}:/ground_truth:ro",
        '-v', "${results}:/results:rw"
    ) + $envArgs + @(
        $manifest.docker_image_tag,
        'evaluate', '--config', "/opt/tep/config/$ConfigFile",
        '--results', '/results/target', '--ground-truth', '/ground_truth',
        '--normal-results', '/results/normal_holdout'
    )
    if ($Mode -eq 'formal') {
        $evaluationArgs += @(
            '--methodological-amendment',
            '/opt/tep/config/post_freeze_methodological_amendment_002.json'
        )
    }
    & $docker @evaluationArgs
    Assert-ExitCode "$Mode evaluation run"

    $latest = Join-Path $workspace "results\$Mode\LATEST.txt"
    Set-Content -LiteralPath $latest -Value $results -Encoding UTF8
    Write-Host "Completed $Mode run: $results"
}
