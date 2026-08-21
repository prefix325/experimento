[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [switch] $ResearcherAuthorized,
    [ValidateRange(60, 1800)]
    [int] $HardTimeoutSeconds = 600
)

. (Join-Path $PSScriptRoot 'common.ps1')

if (-not $ResearcherAuthorized) {
    throw 'Explicit -ResearcherAuthorized is required for the single synthetic acceptance.'
}

$repo = Get-RepoRoot
$workspace = Get-WorkspaceRoot
$configRoot = Join-Path $repo 'experiments\tep\local_llm\config'
$sourceRoot = Join-Path $repo 'experiments\tep\local_llm\src'
$configPath = Join-Path $configRoot 'formal.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.status -ne 'FORMAL_REFROZEN_FULL_WINDOW_REFRESH' -or $config.methodology_frozen -ne $true) {
    throw 'Synthetic acceptance requires the authoritative refrozen method.'
}
if ($config.scientific_execution_permitted -ne $false) {
    throw 'Synthetic acceptance is valid only before scientific execution is authorized.'
}
if ([int]$config.llm.n_gpu_layers -eq 0) {
    throw 'Synthetic acceptance requires nonzero GPU offload.'
}

$manifest = Get-PreparationManifest
$docker = Get-DockerExe
$imageId = (& $docker image inspect $manifest.docker_image_tag --format '{{.Id}}').Trim()
Assert-ExitCode 'Docker image inspection'
if ($imageId -ne $manifest.docker_image_id) {
    throw "Docker image ID mismatch. Expected $($manifest.docker_image_id), found $imageId"
}
$imageDigest = (& $docker image inspect $manifest.docker_image_tag --format '{{index .RepoDigests 0}}').Trim()
Assert-ExitCode 'Docker image digest inspection'
if ($imageDigest -ne $manifest.docker_image_digest) {
    throw "Docker image digest mismatch. Expected $($manifest.docker_image_digest), found $imageDigest"
}
$modelPath = Join-Path $workspace "models\$($config.llm.model_file)"
$modelHash = Get-Sha256 $modelPath
if ($modelHash -ne $config.llm.model_sha256) {
    throw "Model hash mismatch. Expected $($config.llm.model_sha256), found $modelHash"
}

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$experimentId = "post-freeze-operational-amendment-001-acceptance-$timestamp"
$results = Join-Path $workspace "results\technical_acceptance\$experimentId"
New-Item -ItemType Directory -Force -Path $results | Out-Null

$arguments = @(
    'run', '--rm', '--name', $experimentId,
    '--gpus', 'all', '--network', 'none', '--read-only',
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--tmpfs', '/tmp:rw,nosuid,nodev,size=2g',
    '-v', "${sourceRoot}:/opt/tep/src:ro",
    '-v', "${configRoot}:/opt/tep/config:ro",
    '-v', "$(Split-Path -Parent $modelPath):/models:ro",
    '-v', "${results}:/results:rw",
    '-e', "DOCKER_IMAGE_ID=$imageId",
    '-e', "DOCKER_IMAGE_DIGEST=$imageDigest",
    $manifest.docker_image_tag,
    'technical-acceptance',
    '--config', '/opt/tep/config/formal.json',
    '--results', '/results',
    '--models', '/models',
    '--prompt', '/opt/tep/config/prompt_template.txt',
    '--schema', '/opt/tep/config/output_schema.json',
    '--operational-amendment',
    '/opt/tep/config/post_freeze_operational_amendment_001.json'
)
$quoted = $arguments | ForEach-Object {
    if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
}
$exactCommand = $docker + ' ' + ($quoted -join ' ')
$commandBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($exactCommand))
$insertAt = [Array]::IndexOf($arguments, $manifest.docker_image_tag)
$arguments = @($arguments[0..($insertAt - 1)]) + @(
    '-e', "TECHNICAL_ACCEPTANCE_DOCKER_COMMAND_B64=$commandBase64"
) + @($arguments[$insertAt..($arguments.Count - 1)])

$stdout = Join-Path $results 'docker.stdout.log'
$stderr = Join-Path $results 'docker.stderr.log'
$process = Start-Process -FilePath $docker -ArgumentList $arguments -PassThru -NoNewWindow `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$finished = $process.WaitForExit($HardTimeoutSeconds * 1000)
if (-not $finished) {
    & $docker stop --time 10 $experimentId | Out-Null
    $failure = [ordered]@{
        status = 'POST_FREEZE_OPERATIONAL_AMENDMENT_SYNTHETIC_ACCEPTANCE'
        verdict = 'FAIL'
        inference_count = $null
        inference_count_upper_bound = 1
        error = "HARD_TIMEOUT_AFTER_${HardTimeoutSeconds}_SECONDS"
        docker_command = $exactCommand
        ZERO_TARGET_ACCESS = $true
        ZERO_FAULTFREE_TESTING_ACCESS = $true
        formal_scientific_execution_started = $false
    }
    $failure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $results 'technical_acceptance.json') -Encoding UTF8
    throw "Synthetic acceptance exceeded hard timeout; container stopped. Result: $results"
}
$process.WaitForExit()
$process.Refresh()
$exitCode = $process.ExitCode
if ($null -eq $exitCode) {
    $exitCode = 'UNAVAILABLE'
}
if ([string]$exitCode -ne '0') {
    throw "Synthetic acceptance failed with exit code $exitCode. Result: $results"
}
$artifactPath = Join-Path $results 'technical_acceptance.json'
if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
    throw "Synthetic acceptance did not write its machine-readable artifact: $results"
}
$artifact = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
if (
    $artifact.verdict -ne 'PASS' -or
    [int]$artifact.inference_count -ne 1 -or
    [int]$artifact.requested_max_output_tokens -ne 1024 -or
    $artifact.output_parser_result -ne 'PASS' -or
    $artifact.finish_reason -eq 'length' -or
    $artifact.gpu_offload.pass -ne $true -or
    $artifact.network_none_verified -ne $true -or
    $artifact.ZERO_TARGET_ACCESS -ne $true -or
    $artifact.ZERO_FAULTFREE_TESTING_ACCESS -ne $true
) {
    throw "Synthetic acceptance artifact did not satisfy every gate: $results"
}
Write-Host "POST_FREEZE_OPERATIONAL_AMENDMENT_SYNTHETIC_ACCEPTANCE PASS: $results"
