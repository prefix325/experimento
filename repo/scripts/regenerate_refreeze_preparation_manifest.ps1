[CmdletBinding()]
param(
    [string] $ExpectedFormalSha256 = 'c8affff60f9e64af02698ef1b03a0ea4a2fdf07d8ef73d52de1e38bba7bf2a66',
    [string] $ExpectedMethodFreezeId = 'TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

function Assert-Equal([string] $Name, $Actual, $Expected) {
    if ([string]$Actual -ne [string]$Expected) {
        throw "$Name mismatch. Expected '$Expected', found '$Actual'."
    }
}

function Get-RelativeWorkspacePath([string] $Workspace, [string] $Path) {
    $separator = [IO.Path]::DirectorySeparatorChar
    $workspaceFull = [IO.Path]::GetFullPath($Workspace).TrimEnd($separator) + $separator
    $workspaceUri = [Uri]::new($workspaceFull)
    $pathUri = [Uri]::new([IO.Path]::GetFullPath($Path))
    return [Uri]::UnescapeDataString(
        $workspaceUri.MakeRelativeUri($pathUri).ToString()
    )
}

$repo = Get-RepoRoot
$workspace = Get-WorkspaceRoot
$configRoot = Join-Path $repo 'experiments/tep/local_llm/config'
$manifests = Join-Path $workspace 'manifests'
$preparationPath = Join-Path $manifests 'preparation.json'
$preparationMarkdownPath = Join-Path $manifests 'preparation.md'
$historyRoot = Join-Path $manifests 'history'
$formalPath = Join-Path $configRoot 'formal.json'
$localGatePath = Join-Path $configRoot 'local_execution_gate.json'
$conformancePath = Join-Path $manifests 'method_refreeze_implementation_conformance_20260815.json'

foreach ($required in @(
    $preparationPath, $formalPath, $localGatePath, $conformancePath
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required provenance artifact is missing: $required"
    }
}

$oldPreparation = Get-Content -LiteralPath $preparationPath -Raw | ConvertFrom-Json
$formal = Get-Content -LiteralPath $formalPath -Raw | ConvertFrom-Json
$localGate = Get-Content -LiteralPath $localGatePath -Raw | ConvertFrom-Json
$conformance = Get-Content -LiteralPath $conformancePath -Raw | ConvertFrom-Json
$formalSha256 = Get-Sha256 $formalPath
$oldPreparationSha256 = Get-Sha256 $preparationPath
$oldExpectedFormalSha256 = [string]$oldPreparation.configuration_sha256.'formal.json'

Assert-Equal 'formal.json SHA-256' $formalSha256 $ExpectedFormalSha256
Assert-Equal 'formal method_freeze_id' $formal.method_freeze_id $ExpectedMethodFreezeId
Assert-Equal 'formal status' $formal.status 'FORMAL_REFROZEN_FULL_WINDOW_REFRESH'
Assert-Equal 'local gate method_freeze_id' $localGate.method_freeze_id $ExpectedMethodFreezeId
Assert-Equal 'local gate formal_sha256' $localGate.formal_sha256 $formalSha256
Assert-Equal 'local gate status' $localGate.gate_status 'REAL START READY'
Assert-Equal 'local gate implementation conformance' $localGate.implementation_conformance 'PASS'
Assert-Equal 'local gate technical acceptance' $localGate.technical_acceptance 'PASS'
Assert-Equal 'conformance method_freeze_id' $conformance.method_freeze_id $ExpectedMethodFreezeId
Assert-Equal 'conformance formal_sha256' $conformance.formal_sha256 $formalSha256
Assert-Equal 'conformance verdict' $conformance.verdict 'PASS'

$acceptancePath = Join-Path $workspace (
    [string]$localGate.technical_acceptance_artifact -replace '/', [IO.Path]::DirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $acceptancePath -PathType Leaf)) {
    throw "Technical acceptance artifact is missing: $acceptancePath"
}
$acceptance = Get-Content -LiteralPath $acceptancePath -Raw | ConvertFrom-Json
$acceptanceSha256 = Get-Sha256 $acceptancePath
Assert-Equal 'technical acceptance SHA-256' $acceptanceSha256 $localGate.technical_acceptance_artifact_sha256
Assert-Equal 'technical acceptance method_freeze_id' $acceptance.method_freeze_id $ExpectedMethodFreezeId
Assert-Equal 'technical acceptance verdict' $acceptance.verdict 'PASS'
Assert-Equal 'technical acceptance inference_count' $acceptance.inference_count 1

$artifactSpecs = @(
    [pscustomobject]@{ Key = 'prompt_template'; File = 'prompt_template.txt'; Expected = $formal.artifacts.prompt_template.sha256 },
    [pscustomobject]@{ Key = 'output_schema'; File = 'output_schema.json'; Expected = $formal.artifacts.output_schema.sha256 },
    [pscustomobject]@{ Key = 'representation_contract'; File = 'representation_contract.json'; Expected = $formal.artifacts.representation_contract.sha256 },
    [pscustomobject]@{ Key = 'evaluation_contract'; File = 'evaluation_contract.json'; Expected = $formal.artifacts.evaluation_contract.sha256 },
    [pscustomobject]@{ Key = 'formal_run_selection'; File = 'formal_run_selection.json'; Expected = $formal.artifacts.formal_run_selection.sha256 },
    [pscustomobject]@{ Key = 'formal_normal_holdout_selection'; File = 'formal_normal_holdout_selection.json'; Expected = $formal.artifacts.formal_normal_holdout_selection.sha256 },
    [pscustomobject]@{ Key = 'dpca_reference'; File = 'dpca_reference.json'; Expected = $formal.artifacts.dpca_reference.sha256 },
    [pscustomobject]@{ Key = 'dpca_artifact'; File = 'dpca_reference_model.npz'; Expected = $formal.artifacts.dpca_artifact.sha256 },
    [pscustomobject]@{ Key = 'h3_evidence_reference'; File = 'h3_evidence_reference.json'; Expected = $formal.artifacts.h3_evidence_reference.sha256 }
)
$artifactHashes = [ordered]@{}
$artifactFiles = [ordered]@{}
foreach ($spec in $artifactSpecs) {
    $path = Join-Path $configRoot $spec.File
    $actual = Get-Sha256 $path
    Assert-Equal "frozen artifact $($spec.File)" $actual $spec.Expected
    $acceptanceExpected = $acceptance.frozen_artifacts_verified.($spec.Key)
    Assert-Equal "technical acceptance artifact $($spec.Key)" $actual $acceptanceExpected
    $artifactHashes[$spec.Key] = $actual
    $artifactFiles[$spec.Key] = $spec.File
}

Assert-Equal 'conformance representation contract' $artifactHashes.representation_contract $conformance.frozen_method.representation_contract_sha256
Assert-Equal 'conformance evaluation contract' $artifactHashes.evaluation_contract $conformance.frozen_method.evaluation_contract_sha256
Assert-Equal 'conformance DPCA reference' $artifactHashes.dpca_reference $conformance.frozen_method.dpca_reference_sha256
Assert-Equal 'conformance DPCA model' $artifactHashes.dpca_artifact $conformance.frozen_method.dpca_model_sha256

$modelPath = Join-Path (Join-Path $workspace 'models') ([string]$formal.llm.model_file)
$modelSha256 = Get-Sha256 $modelPath
Assert-Equal 'model hash in formal.json' $modelSha256 $formal.llm.model_sha256
Assert-Equal 'model hash in technical acceptance' $modelSha256 $acceptance.model_sha256
Assert-Equal 'model hash in conformance' $modelSha256 $conformance.frozen_method.model_sha256

$configurationHashes = [ordered]@{}
foreach ($name in @('smoke.json', 'pilot.json', 'formal.json', 'output_schema.json')) {
    $configurationHashes[$name] = Get-Sha256 (Join-Path $configRoot $name)
}

$datasetFiles = @()
foreach ($file in @($oldPreparation.dataset_files)) {
    $relative = [string]$file.relative_path
    $path = Join-Path (Join-Path $workspace 'data') (
        $relative -replace '/', [IO.Path]::DirectorySeparatorChar
    )
    $actual = Get-Sha256 $path
    Assert-Equal "binary dataset integrity $relative" $actual $file.sha256
    $datasetFiles += [ordered]@{
        role = $file.role
        relative_path = $relative
        sha256 = $actual
        bytes = (Get-Item -LiteralPath $path).Length
        rows = $file.rows
    }
}
$datasetManifestPath = Join-Path $workspace 'data/prepared_manifest.json'
$datasetManifestSha256 = Get-Sha256 $datasetManifestPath
Assert-Equal 'prepared dataset manifest' $datasetManifestSha256 $oldPreparation.dataset_manifest_sha256

$docker = Get-DockerExe
$imageTag = [string]$oldPreparation.docker_image_tag
$imageId = (& $docker image inspect $imageTag --format '{{.Id}}').Trim()
Assert-ExitCode 'Docker image identity inspection'
$imageDigest = (& $docker image inspect $imageTag --format '{{index .RepoDigests 0}}').Trim()
Assert-ExitCode 'Docker image digest inspection'
Assert-Equal 'Docker image ID vs previous preparation' $imageId $oldPreparation.docker_image_id
Assert-Equal 'Docker image digest vs previous preparation' $imageDigest $oldPreparation.docker_image_digest
Assert-Equal 'Docker image ID vs technical acceptance' $imageId $acceptance.container_image_id
Assert-Equal 'Docker image digest vs technical acceptance' $imageDigest $acceptance.container_image_digest
$dockerVersion = (& $docker version --format '{{.Server.Version}}').Trim()
Assert-ExitCode 'Docker version inspection'

$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor
$computer = Get-CimInstance Win32_ComputerSystem
$gpuCsv = nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits
$gpuParts = $gpuCsv -split ',' | ForEach-Object { $_.Trim() }

$localGateSha256 = Get-Sha256 $localGatePath
$conformanceSha256 = Get-Sha256 $conformancePath
$createdAt = (Get-Date).ToUniversalTime().ToString('o')
$gitCommit = (git -C $repo rev-parse HEAD).Trim()
$gitTree = (git -C $repo rev-parse 'HEAD^{tree}').Trim()
$gitBranch = (git -C $repo rev-parse --abbrev-ref HEAD).Trim()
$gitDirty = [bool](git -C $repo status --porcelain)

New-Item -ItemType Directory -Force -Path $historyRoot | Out-Null
$oldCreated = ([DateTime]$oldPreparation.created_at).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$archiveName = "preparation-$oldCreated-$($oldPreparationSha256.Substring(0, 12)).json"
$archivePath = Join-Path $historyRoot $archiveName
if (Test-Path -LiteralPath $archivePath) {
    Assert-Equal 'existing historical preparation archive' (Get-Sha256 $archivePath) $oldPreparationSha256
} else {
    Copy-Item -LiteralPath $preparationPath -Destination $archivePath
    Assert-Equal 'new historical preparation archive' (Get-Sha256 $archivePath) $oldPreparationSha256
}
if (Test-Path -LiteralPath $preparationMarkdownPath -PathType Leaf) {
    $markdownArchive = Join-Path $historyRoot (
        "preparation-$oldCreated-$($oldPreparationSha256.Substring(0, 12)).md"
    )
    if (-not (Test-Path -LiteralPath $markdownArchive)) {
        Copy-Item -LiteralPath $preparationMarkdownPath -Destination $markdownArchive
    }
}

$preparation = [ordered]@{
    schema_version = '3.0.0-refreeze-preparation'
    manifest_id = "TEP-REFREEZE-PREPARATION-$($createdAt -replace '[-:.]', '')"
    status = 'FORMAL_REFREEZE_PREPARATION_CURRENT'
    created_at = $createdAt
    method_freeze_id = $ExpectedMethodFreezeId
    formal_sha256 = $formalSha256
    supersedes = [ordered]@{
        historical_manifest = Get-RelativeWorkspacePath $workspace $archivePath
        old_preparation_sha256 = $oldPreparationSha256
        old_formal_json_expected_sha256 = $oldExpectedFormalSha256
        new_method_freeze_id = $ExpectedMethodFreezeId
        reason = 'STALE_PREPARATION_MANIFEST'
    }
    provenance = [ordered]@{
        official_entrypoint = 'scripts/prepare_online.ps1 -ManifestOnlyRefreeze'
        generator = 'scripts/regenerate_refreeze_preparation_manifest.ps1'
        mode = 'MANIFEST_ONLY_BINARY_HASHING_NO_SCIENTIFIC_EXECUTION'
        git_commit = $gitCommit
        git_tree = $gitTree
        git_branch = $gitBranch
        git_dirty = $gitDirty
    }
    git_commit = $gitCommit
    git_tree = $gitTree
    git_branch = $gitBranch
    git_dirty = $gitDirty
    docker_version = $dockerVersion
    docker_image_tag = $imageTag
    docker_image_id = $imageId
    docker_image_digest = $imageDigest
    llama_cpp_base_digest = $oldPreparation.llama_cpp_base_digest
    llama_cpp_version = $oldPreparation.llama_cpp_version
    runtime_identity = [ordered]@{
        source = 'previous preparation bound to identical immutable image; revalidated by technical acceptance'
        technical_acceptance_artifact = Get-RelativeWorkspacePath $workspace $acceptancePath
        technical_acceptance_sha256 = $acceptanceSha256
        network_mode = $acceptance.network_mode
        gpu_offload_pass = $acceptance.gpu_offload.pass
    }
    model_name = $formal.llm.model_name
    model_file = $formal.llm.model_file
    model_quantization = $formal.llm.quantization
    model_size_bytes = (Get-Item -LiteralPath $modelPath).Length
    model_sha256 = $modelSha256
    model_license = $oldPreparation.model_license
    model_origin = $oldPreparation.model_origin
    dataset_manifest_sha256 = $datasetManifestSha256
    dataset_files = $datasetFiles
    dataset_integrity = [ordered]@{
        mode = 'BINARY_SHA256_ONLY'
        files_hashed = $datasetFiles.Count
        dataset_files_parsed = 0
        scientific_values_examined = $false
    }
    configuration_sha256 = $configurationHashes
    prompt_template_sha256 = $artifactHashes.prompt_template
    frozen_artifacts = [ordered]@{
        files = $artifactFiles
        sha256 = $artifactHashes
    }
    governance = [ordered]@{
        technical_acceptance = [ordered]@{
            artifact = Get-RelativeWorkspacePath $workspace $acceptancePath
            sha256 = $acceptanceSha256
            verdict = $acceptance.verdict
            method_freeze_id = $acceptance.method_freeze_id
        }
        implementation_conformance = [ordered]@{
            artifact = Get-RelativeWorkspacePath $workspace $conformancePath
            sha256 = $conformanceSha256
            manifest_id = $conformance.manifest_id
            verdict = $conformance.verdict
            method_freeze_id = $conformance.method_freeze_id
            formal_sha256 = $conformance.formal_sha256
        }
        local_execution_gate = [ordered]@{
            artifact = Get-RelativeWorkspacePath $workspace $localGatePath
            sha256 = $localGateSha256
            status = $localGate.gate_status
            method_freeze_id = $localGate.method_freeze_id
            formal_sha256 = $localGate.formal_sha256
        }
    }
    hardware = [ordered]@{
        windows = $os.Caption
        windows_version = $os.Version
        windows_build = $os.BuildNumber
        cpu = ($cpu.Name -join '; ')
        physical_cores = ($cpu | Measure-Object NumberOfCores -Sum).Sum
        logical_threads = ($cpu | Measure-Object NumberOfLogicalProcessors -Sum).Sum
        ram_gb = [math]::Round($computer.TotalPhysicalMemory / 1GB, 2)
        gpu = $gpuParts[0]
        nvidia_driver = $gpuParts[1]
        vram_mib = [int]$gpuParts[2]
        cuda_visible_in_container = $oldPreparation.hardware.cuda_visible_in_container
        wsl = $oldPreparation.hardware.wsl
        docker_desktop = $oldPreparation.hardware.docker_desktop
        x_free_gb = [math]::Round((Get-Volume -DriveLetter X).SizeRemaining / 1GB, 2)
    }
    network_mode = 'none'
    consistency = [ordered]@{
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
        binary_dataset_integrity_match = $true
    }
    execution_attestation = [ordered]@{
        process_started = $false
        docker_run_executed = $false
        formal_lots_started = 0
        dpca_engine_started = $false
        llm_inference_count = 0
        dataset_files_parsed = 0
    }
}

$temporaryPath = "$preparationPath.tmp"
$preparation | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
Move-Item -LiteralPath $temporaryPath -Destination $preparationPath -Force

@(
    '# Refreeze preparation manifest',
    '',
    "- Status: $($preparation.status)",
    "- Method freeze: $ExpectedMethodFreezeId",
    "- Formal SHA-256: $formalSha256",
    "- Previous manifest SHA-256: $oldPreparationSha256",
    "- Historical manifest: $archivePath",
    "- Technical acceptance: $acceptanceSha256",
    "- Implementation conformance: $conformanceSha256",
    "- Local execution gate: $localGateSha256",
    "- Model: $modelSha256",
    '- Dataset handling: binary SHA-256 only; no scientific values parsed',
    '- Scientific execution: not started'
) | Set-Content -LiteralPath $preparationMarkdownPath -Encoding UTF8

[ordered]@{
    status = 'PREPARATION_MANIFEST_REGENERATED'
    manifest = $preparationPath
    manifest_sha256 = Get-Sha256 $preparationPath
    historical_manifest = $archivePath
    old_preparation_sha256 = $oldPreparationSha256
    old_formal_json_expected_sha256 = $oldExpectedFormalSha256
    new_method_freeze_id = $ExpectedMethodFreezeId
    formal_sha256 = $formalSha256
    dataset_files_hashed = $datasetFiles.Count
    dataset_files_parsed = 0
    docker_run_executed = $false
    formal_lots_started = 0
    dpca_engine_started = $false
    llm_inference_count = 0
} | ConvertTo-Json -Depth 6
