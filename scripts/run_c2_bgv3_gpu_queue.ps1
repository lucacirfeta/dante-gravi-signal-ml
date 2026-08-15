$ErrorActionPreference = "Stop"

$repo = "C:\Users\atafe\PycharmProjects\dante-gravi-signal-ml"
$python = "C:\Users\atafe\AppData\Local\Programs\Python\Python311\python.exe"
$p5Pid = 3500
$log = Join-Path $repo "logs\c2_bgv3_gpu_queue.log"
$status = Join-Path $repo "logs\c2_bgv3_gpu_queue.status"
$representation = "idxq4-64_queryq4-64"

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

Write-Status "WAIT P5 PID $p5Pid"
while (Get-Process -Id $p5Pid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 20
}
Write-Status "P5 PROCESS EXITED"

$p5Path = Join-Path $repo (
    "data\production\aggregated\" +
    "dsd_index_stability_o4a_$representation.json"
)
if (-not (Test-Path -LiteralPath $p5Path -PathType Leaf)) {
    Write-Status "FAILED P5 artifact missing"
    exit 20
}
$p5 = Get-Content -LiteralPath $p5Path -Raw | ConvertFrom-Json
if (
    $p5.representation -ne $representation -or
    [int]$p5.n_candidates -ne 160 -or
    -not (Test-Path -LiteralPath $p5.candidate_token_cache) -or
    -not (Test-Path -LiteralPath $p5.background_token_cache) -or
    -not (Test-Path -LiteralPath $p5.background_ledger)
) {
    Write-Status "FAILED P5 artifact/cache validation"
    exit 21
}
Write-Status "VALIDATED P5 split caches and GPS ledger"
Invoke-ScientificStep "VERIFY P5 artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "p5"
)

Invoke-ScientificStep "P4 dsd-k-sensitivity" @(
    "-u", "-m", "src.pipeline_v2_production.dsd_k_sensitivity",
    "--run", "O4a",
    "--n-candidates", "40",
    "--k-values", "512", "1024", "1216", "2048",
    "--seed", "42"
)
Invoke-ScientificStep "VERIFY P4 artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "p4"
)

Invoke-ScientificStep "P10 pca-baseline" @(
    "-u", "-m", "src.pipeline_v2_production.pca_baseline",
    "--run", "O4a",
    "--n-candidates", "40",
    "--n-background", "1300",
    "--seed", "42"
)
Invoke-ScientificStep "VERIFY P10 artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "p10"
)

Invoke-ScientificStep "V3 multiscale bgv3 classes" @(
    "-u", "-m", "src.pipeline_v3_multiscale.multiscale_candidates",
    "--run", "O4a"
)
Invoke-ScientificStep "VERIFY multiscale artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "multiscale"
)

Invoke-ScientificStep "background-cohesion bgv3 classes" @(
    "-u", "-m", "src.pipeline_v2_production.background_cohesion_test",
    "--run", "O4a",
    "--n_segments", "3000",
    "--n_draws", "5",
    "--seed", "42"
)
Invoke-ScientificStep "VERIFY background-cohesion artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "cohesion"
)

Invoke-ScientificStep "whitening-context bgv3 calibration" @(
    "-u", "-m", "src.pipeline_v2_production.whitening_context_sensitivity",
    "--run", "O4a",
    "--n-candidates", "15",
    "--n-background", "5000",
    "--seed", "42"
)
Invoke-ScientificStep "VERIFY whitening artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "whitening"
)

Write-Status "START P9 astrophysical-injection bgv3 in WSL"
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
Write-Status "DONE P9 astrophysical-injection bgv3"
Invoke-ScientificStep "VERIFY P9 artifact contract" @(
    "scripts\verify_c2_bgv3_artifacts.py", "--stage", "p9"
)
Write-Status "COMPLETE C2 bgv3 GPU queue"
