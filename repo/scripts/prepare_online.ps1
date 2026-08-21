[CmdletBinding()]
param(
    [string] $ImageTag = 'psqza-tep-local:dev',
    [switch] $SkipModelDownload,
    [switch] $ManifestOnlyRefreeze
)

. (Join-Path $PSScriptRoot 'common.ps1')

if ($ManifestOnlyRefreeze) {
    & (Join-Path $PSScriptRoot 'regenerate_refreeze_preparation_manifest.ps1')
    return
}

function Get-WslVersionText {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = 'wsl.exe'
    $startInfo.Arguments = '--version'
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [Text.Encoding]::Unicode
    $process = [Diagnostics.Process]::Start($startInfo)
    $output = $process.StandardOutput.ReadToEnd()
    $errorOutput = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "WSL version query failed: $errorOutput"
    }
    return $output.Trim()
}

$repo = Get-RepoRoot
$workspace = Get-WorkspaceRoot
$docker = Get-DockerExe
$source = Join-Path $workspace 'data\source_artifact_31752037426'
$normal = Join-Path $workspace 'data\normal\blind'
$test = Join-Path $workspace 'data\test\blind'
$truth = Join-Path $workspace 'data\test\ground_truth'
$datasetManifest = Join-Path $workspace 'data\prepared_manifest.json'
$models = Join-Path $workspace 'models'
$manifests = Join-Path $workspace 'manifests'
$modelFile = 'qwen2.5-7b-instruct-q4_k_m.gguf'
$modelPath = Join-Path $models $modelFile
$modelOrigin = 'https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF'
$part1File = 'qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf'
$part2File = 'qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf'
$part1Url = "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/${part1File}?download=true"
$part2Url = "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/${part2File}?download=true"
$licensePath = Join-Path $models 'Qwen2.5-7B-Instruct-LICENSE'
$licenseUrl = 'https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/LICENSE?download=true'

foreach ($directory in @($normal, $test, $truth, $models, $manifests)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

if (-not (Test-Path -LiteralPath $source)) {
    throw "Source CSV artifact is missing: $source"
}

Write-Host 'Checking WSL2, Docker, and NVIDIA...'
wsl --status | Out-Host
& $docker version | Out-Host
nvidia-smi | Out-Host

Write-Host 'Building pinned experiment image...'
& $docker build --progress plain -f (Join-Path $repo 'experiments\tep\local_llm\Dockerfile') -t $ImageTag $repo
Assert-ExitCode 'Docker build'

Write-Host 'Running unit tests inside the image...'
& $docker run --rm --network none --entrypoint /opt/venv/bin/pytest $ImageTag -q /opt/tep/tests
Assert-ExitCode 'Unit tests'

Write-Host 'Validating GPU inside a networkless CUDA container...'
& $docker run --rm --network none --gpus all nvidia/cuda@sha256:14c0ac83369e3918d37416986eac6863ffe2a24938d0a337d910fc8ac05cb55d nvidia-smi
Assert-ExitCode 'GPU container test'

Write-Host 'Preparing physically separated blind data and ground truth...'
& $docker run --rm --network none `
    -v "${source}:/source:ro" `
    -v "${workspace}\data:/prepared:rw" `
    $ImageTag prepare-data `
    --source /source `
    --normal-out /prepared/normal/blind `
    --test-out /prepared/test/blind `
    --ground-truth-out /prepared/test/ground_truth `
    --manifest-out /prepared/prepared_manifest.json
Assert-ExitCode 'Dataset preparation'

if (-not $SkipModelDownload) {
    if (-not (Test-Path -LiteralPath $modelPath)) {
        Write-Host "Downloading PROVISIONAL split smoke model to $models ..."
        $part1Path = Join-Path $models $part1File
        $part2Path = Join-Path $models $part2File
        curl.exe --fail -L -C - --retry 8 --retry-delay 5 --output $part1Path $part1Url
        Assert-ExitCode 'Model part 1 download'
        curl.exe --fail -L -C - --retry 8 --retry-delay 5 --output $part2Path $part2Url
        Assert-ExitCode 'Model part 2 download'
        if ((Get-Item -LiteralPath $part1Path).Length -ne 3993201344 -or (Get-Item -LiteralPath $part2Path).Length -ne 689872288) {
            throw 'Downloaded model part sizes do not match official metadata.'
        }
        & $docker pull 'ghcr.io/ggml-org/llama.cpp@sha256:b3f2fe665cfea7aa12be4c464d47f833a7919edcc69d7c15c56c42d113a027e7'
        Assert-ExitCode 'llama.cpp merge-tool image pull'
        & $docker run --rm --network none -v "${models}:/models:rw" --entrypoint /app/llama-gguf-split `
            'ghcr.io/ggml-org/llama.cpp@sha256:b3f2fe665cfea7aa12be4c464d47f833a7919edcc69d7c15c56c42d113a027e7' `
            --merge "/models/$part1File" "/models/$modelFile"
        Assert-ExitCode 'GGUF merge'
        Remove-Item -LiteralPath $part1Path, $part2Path -Force
    }
    if (-not (Test-Path -LiteralPath $licensePath)) {
        curl.exe -L --retry 5 --output $licensePath $licenseUrl
        Assert-ExitCode 'Model license download'
    }
}

if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "Model is absent: $modelPath"
}

Write-Host 'Generating preparation manifest and hashes...'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor
$computer = Get-CimInstance Win32_ComputerSystem
$gpuCsv = nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits
$gpuParts = $gpuCsv -split ',' | ForEach-Object { $_.Trim() }
$imageId = (& $docker image inspect $ImageTag --format '{{.Id}}').Trim()
$imageDigest = (& $docker image inspect $ImageTag --format '{{index .RepoDigests 0}}').Trim()
$dockerVersion = (& $docker version --format '{{.Server.Version}}').Trim()
$runtime = (& $docker run --rm --network none --gpus all $ImageTag runtime-version | ConvertFrom-Json).llama_cpp_version
$dataManifestObject = Get-Content -LiteralPath $datasetManifest -Raw | ConvertFrom-Json
$modelHash = Get-Sha256 $modelPath
$configHashes = [ordered]@{}
foreach ($name in @('smoke.json', 'pilot.json', 'formal.json', 'output_schema.json')) {
    $configHashes[$name] = Get-Sha256 (Join-Path $repo "experiments\tep\local_llm\config\$name")
}
$promptHash = Get-Sha256 (Join-Path $repo 'experiments\tep\local_llm\config\prompt_template.txt')

$preparation = [ordered]@{
    schema_version = '1.0.0-development'
    status = 'DEVELOPMENT_ONLY'
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    git_commit = (git -C $repo rev-parse HEAD).Trim()
    git_dirty = [bool](git -C $repo status --porcelain)
    docker_version = $dockerVersion
    docker_image_tag = $ImageTag
    docker_image_id = $imageId
    docker_image_digest = $imageDigest
    llama_cpp_base_digest = 'sha256:6b0bf4974521b2c16a498c7dd0715f4eb077725f1483e0ee0f617679005b1e1f'
    llama_cpp_version = $runtime
    model_name = 'Qwen/Qwen2.5-7B-Instruct-GGUF'
    model_file = $modelFile
    model_quantization = 'Q4_K_M'
    model_size_bytes = (Get-Item -LiteralPath $modelPath).Length
    model_sha256 = $modelHash
    model_license = 'Apache-2.0'
    model_origin = $modelOrigin
    dataset_manifest_sha256 = Get-Sha256 $datasetManifest
    dataset_files = $dataManifestObject.files
    configuration_sha256 = $configHashes
    prompt_template_sha256 = $promptHash
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
        cuda_visible_in_container = '13.3'
        wsl = Get-WslVersionText
        docker_desktop = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop').DisplayVersion
        x_free_gb = [math]::Round((Get-Volume -DriveLetter X).SizeRemaining / 1GB, 2)
    }
    network_mode = 'none'
}

$manifestPath = Join-Path $manifests 'preparation.json'
$preparation | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$humanPath = Join-Path $manifests 'preparation.md'
@(
    '# Online preparation manifest',
    '',
    "- Status: DEVELOPMENT_ONLY",
    "- Git commit: $($preparation.git_commit)",
    "- Docker image: $ImageTag ($imageId)",
    "- Docker digest: $imageDigest",
    "- Model: $modelFile ($modelHash)",
    "- Dataset manifest: $($preparation.dataset_manifest_sha256)",
    "- GPU: $($preparation.hardware.gpu), $($preparation.hardware.vram_mib) MiB",
    "- Network mode for experiment runs: none"
) | Set-Content -LiteralPath $humanPath -Encoding UTF8

Write-Host "Preparation complete: $manifestPath"
