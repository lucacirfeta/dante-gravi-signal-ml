param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (Test-Path -LiteralPath $EvidenceDirectory) { throw 'Existing fixture evidence preserved' }
[void](New-Item -ItemType Directory -Path $EvidenceDirectory)
$shell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$launcher = Join-Path $RepositoryRoot 'scripts/launch_dante_workflow_storage.ps1'
$names = @{
    ConfigPath = 'config/dante_workflow_storage_probe_v2.json'
    ProbeSha256 = 'src/dante_workflow/storage_probe.py'
    RunnerSha256 = 'scripts/benchmark_dante_workflow_storage.py'
    SupervisorSha256 = 'src/dante_workflow/storage_supervisor.py'
    EntrySha256 = 'scripts/supervise_dante_workflow_storage.py'
    LauncherSha256 = 'scripts/launch_dante_workflow_storage.ps1'
}
$values = @{ RepositoryRoot=$RepositoryRoot }
foreach ($key in $names.Keys) {
    $path = Join-Path $RepositoryRoot $names[$key]
    if ($key -eq 'ConfigPath') {
        $values['ConfigPath'] = $path
        $values['ConfigSha256'] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    } else { $values[$key] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() }
}
function Arguments([string]$Directory, [switch]$WrongPin) {
    $parts = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        '"'+$launcher+'"','-SmokeOnly','-LogDirectory','"'+$Directory+'"')
    foreach ($key in $values.Keys) {
        $value = $values[$key]
        if ($WrongPin -and $key -eq 'ConfigSha256') { $value = '0'*64 }
        $parts += '-'+$key
        $parts += '"'+$value+'"'
    }
    return $parts
}
$tokens=$null; $parseErrors=$null
[void][Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'Parser errors' }
Write-Output 'CHECK1_PARSE_PASS'
$invalid = Join-Path $EvidenceDirectory 'invalid'
$options = @{
    FilePath=$shell; ArgumentList=(Arguments $invalid -WrongPin)
    WindowStyle='Hidden'; PassThru=$true
    RedirectStandardOutput=(Join-Path $EvidenceDirectory 'invalid.stdout.log')
    RedirectStandardError=(Join-Path $EvidenceDirectory 'invalid.stderr.log')
}
$parent = Start-Process @options
$parent.WaitForExit()
if ($parent.ExitCode -eq 0 -or (Test-Path -LiteralPath $invalid)) { throw 'Bad pin accepted' }
Write-Output 'CHECK2_WRONG_PIN_REJECTED_NO_NAMESPACE'
$valid = Join-Path $EvidenceDirectory 'valid'
$options.ArgumentList = Arguments $valid
$options.RedirectStandardOutput = Join-Path $EvidenceDirectory 'parent.stdout.log'
$options.RedirectStandardError = Join-Path $EvidenceDirectory 'parent.stderr.log'
$parent = Start-Process @options
$parent.WaitForExit()
if ($parent.ExitCode -ne 0) { throw 'Launcher parent failed' }
Write-Output "CHECK3_PARENT_ACTUAL_EXIT_CODE=$($parent.ExitCode) PID=$($parent.Id)"
$deadline = [DateTime]::UtcNow.AddSeconds(20)
do {
    $log = Get-Content -LiteralPath (Join-Path $valid 'launcher.log') -Raw
    if ($log -match 'WORKER_PID=(\d+) SMOKE_ONLY=True') { break }
    Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $deadline)
if ($log -notmatch 'WORKER_PID=(\d+) SMOKE_ONLY=True') { throw 'Detached worker never started' }
$workerPid = [int]$Matches[1]
$worker = [Diagnostics.Process]::GetProcessById($workerPid)
[void]$worker.Handle  # Capture a live handle, not a PID lookup after process exit.
$child = Get-CimInstance Win32_Process -Filter "ProcessId=$workerPid"
$creator = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)"
if ($creator.Name -ne 'WmiPrvSE.exe' -or
    (Get-Process -Id $parent.Id -ErrorAction SilentlyContinue)) { throw 'Worker still owned by caller' }
Write-Output "CHECK4_DETACHED_PARENT=$($creator.Name) PID=$($creator.ProcessId) WORKER=$workerPid"
if (-not $worker.WaitForExit(30000)) { throw 'Fixture timed out; preserve evidence and process' }
Write-Output "FIXTURE_NATIVE_EXIT_OBSERVED=$($worker.ExitCode)"
if ($null -eq $worker.ExitCode -or $worker.ExitCode -ne 0) { throw 'Detached fixture failed' }
$log = Get-Content -LiteralPath (Join-Path $valid 'launcher.log') -Raw
if ($log -notmatch 'LIFECYCLE_FIXTURE_EXIT_CODE=0 NO_IO_OR_SCIENCE') { throw 'No fixture completion' }
Write-Output "CHECK5_WORKER_SURVIVED_CALLER_EXIT ACTUAL_OS_EXIT_CODE=$($worker.ExitCode)"
$options.RedirectStandardOutput = Join-Path $EvidenceDirectory 'duplicate.stdout.log'
$options.RedirectStandardError = Join-Path $EvidenceDirectory 'duplicate.stderr.log'
$duplicate = Start-Process @options
$duplicate.WaitForExit()
if ($duplicate.ExitCode -eq 0) { throw 'Existing namespace relaunched' }
Write-Output 'CHECK6_DUPLICATE_REJECTED'
Write-Output '6_WINDOWS_LIFECYCLE_CHECKS_PASS FIXTURE_ONLY_NO_IO_OR_SCIENCE'
