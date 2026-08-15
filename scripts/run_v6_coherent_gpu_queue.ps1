$ErrorActionPreference = "Stop"

$repo = "C:\Users\atafe\PycharmProjects\dante-gravi-signal-ml"
$python = "C:\Users\atafe\AppData\Local\Programs\Python\Python311\python.exe"
$log = Join-Path $repo "logs\v6_coherent_gpu_queue.log"
$status = Join-Path $repo "logs\v6_coherent_gpu_queue.status"

Set-Location -LiteralPath $repo

function Write-Status([string]$message) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $message" | Tee-Object -FilePath $status
    "$timestamp $message" | Out-File -FilePath $log -Append
}

function Invoke-ScientificStep(
    [string]$name,
    [string[]]$arguments
) {
    Write-Status "START $name"
    # Windows PowerShell 5.1 promotes native stderr to a NativeCommandError
    # when ErrorActionPreference is Stop. Scientific dependencies such as
    # PyTorch legitimately emit warnings on stderr, so that behaviour killed
    # the queue before the Python exit code could be inspected.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $python @arguments *>> $log
    $stepExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($stepExitCode -ne 0) {
        Write-Status "FAILED $name exit=$stepExitCode"
        exit $stepExitCode
    }
    Write-Status "DONE $name"
}

Write-Status "WAIT whitening PID 25936"
while (Get-Process -Id 25936 -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 20
}
Write-Status "WHITENING PROCESS EXITED"

$whiteningArtifact = Join-Path $repo (
    "data\production\aggregated\" +
    "whitening_context_sensitivity_o4a_idxq4-64_queryq4-64.json"
)
if (-not (Test-Path -LiteralPath $whiteningArtifact -PathType Leaf)) {
    Write-Status "FAILED whitening artifact missing"
    exit 20
}
$whitening = Get-Content -LiteralPath $whiteningArtifact -Raw |
    ConvertFrom-Json
if (
    $whitening.representation.variant -ne "idxq4-64_queryq4-64" -or
    -not $whitening.reproduction_pad4_vs_stored.passed -or
    [int]$whitening.reproduction_pad4_vs_stored.n_failed -ne 0
) {
    Write-Status "FAILED whitening artifact validation"
    exit 21
}
Write-Status "VALIDATED whitening coherent representation and pad4 anchor"

Invoke-ScientificStep "P5 dsd-index-stability" @(
    "-u", "-m", "src.pipeline_v2_production.dsd_index_stability",
    "--run", "O4a",
    "--n-candidates", "40",
    "--n-background", "1300",
    "--n-draws", "4",
    "--seed", "42"
)

Invoke-ScientificStep "P4 dsd-k-sensitivity" @(
    "-u", "-m", "src.pipeline_v2_production.dsd_k_sensitivity",
    "--run", "O4a",
    "--n-candidates", "40",
    "--k-values", "512", "1024", "1216", "2048",
    "--seed", "42"
)

Invoke-ScientificStep "P10 pca-baseline" @(
    "-u", "-m", "src.pipeline_v2_production.pca_baseline",
    "--run", "O4a",
    "--n-candidates", "40",
    "--n-background", "1300",
    "--seed", "42"
)

Invoke-ScientificStep "V3 multiscale coherent survivors" @(
    "-u", "-m", "src.pipeline_v3_multiscale.multiscale_candidates",
    "--run", "O4a"
)

Invoke-ScientificStep "B1 dsd-absorption" @(
    "-u", "-m", "src.pipeline_v2_production.dsd_absorption_threshold",
    "--run", "O4a",
    "--morphology", "Blip",
    "--amplitude", "12",
    "--duration", "1",
    "--n-background", "300",
    "--seed", "42"
)

Invoke-ScientificStep "blind-spot centered coherent Q64" @(
    "-u", "-m", "src.pipeline_v2_production.blind_spot_map",
    "--run", "O4a",
    "--n-realizations", "8",
    "--seed", "42"
)

Invoke-ScientificStep "background-cohesion coherent classes" @(
    "-u", "-m", "src.pipeline_v2_production.background_cohesion_test",
    "--run", "O4a",
    "--n_segments", "3000",
    "--n_draws", "5",
    "--seed", "42"
)

Write-Status "START P9 astrophysical-injection in WSL"
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& wsl.exe bash (
    "/mnt/c/Users/atafe/PycharmProjects/dante-gravi-signal-ml/" +
    "scripts/run_p9_coherent_q64.sh"
) *>> $log
$p9ExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($p9ExitCode -ne 0) {
    Write-Status "FAILED P9 astrophysical-injection exit=$p9ExitCode"
    exit $p9ExitCode
}
Write-Status "DONE P9 astrophysical-injection"
Write-Status "COMPLETE coherent GPU queue"
