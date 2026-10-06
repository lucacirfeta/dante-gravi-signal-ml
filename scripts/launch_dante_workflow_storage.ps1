param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$ConfigSha256,
    [Parameter(Mandatory=$true)][string]$ProbeSha256,
    [Parameter(Mandatory=$true)][string]$RunnerSha256,
    [Parameter(Mandatory=$true)][string]$SupervisorSha256,
    [Parameter(Mandatory=$true)][string]$EntrySha256,
    [Parameter(Mandatory=$true)][string]$LauncherSha256,
    [Parameter(Mandatory=$true)][string]$LogDirectory,
    [switch]$Worker,
    [switch]$SmokeOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# A Codex-bundled pwsh can pass a PSModulePath that excludes Windows PowerShell
# modules. Load the stable system-shell modules explicitly in the detached worker.
if ($PSVersionTable.PSVersion.Major -eq 5) {
    foreach ($name in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Management','CimCmdlets')) {
        Import-Module -Name (Join-Path $PSHOME ('Modules\'+$name+'\'+$name+'.psd1')) -ErrorAction Stop
    }
}

function Assert-Pin([string]$Path, [string]$Sha) {
    if ($Sha -notmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() -ne $Sha) {
        throw "Frozen launcher SHA mismatch: $Path"
    }
}
function Wsl-Path([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -notmatch '^[A-Za-z]:\\' -or $full -match '["\r\n]') {
        throw 'Only absolute local drive paths without command quoting allowed'
    }
    return '/mnt/' + $full.Substring(0,1).ToLower() + $full.Substring(2).Replace('\','/')
}
function Log([string]$Text) {
    [IO.File]::AppendAllText((Join-Path $LogDirectory 'launcher.log'),
        ([DateTime]::UtcNow.ToString('o') + ' ' + $Text + "`n"))
}
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
$LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
foreach ($path in @($RepositoryRoot,$ConfigPath,$LogDirectory,$PSCommandPath)) {
    [void](Wsl-Path $path)
}
if (-not $ConfigPath.StartsWith($RepositoryRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Configuration must be inside repository'
}
if ($LogDirectory.StartsWith($RepositoryRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Runtime logs must be outside repository'
}
Assert-Pin $PSCommandPath $LauncherSha256
Assert-Pin $ConfigPath $ConfigSha256
Assert-Pin (Join-Path $RepositoryRoot 'src/dante_workflow/storage_probe.py') $ProbeSha256
Assert-Pin (Join-Path $RepositoryRoot 'scripts/benchmark_dante_workflow_storage.py') $RunnerSha256
Assert-Pin (Join-Path $RepositoryRoot 'src/dante_workflow/storage_supervisor.py') $SupervisorSha256
Assert-Pin (Join-Path $RepositoryRoot 'scripts/supervise_dante_workflow_storage.py') $EntrySha256

if (-not $Worker) {
    if (Test-Path -LiteralPath $LogDirectory) { throw 'Existing launch namespace is immutable' }
    [void](New-Item -ItemType Directory -Path $LogDirectory)
    $bound = @{}
    foreach ($key in $PSBoundParameters.Keys) { $bound[$key] = $PSBoundParameters[$key] }
    $bound['launcher_parent_pid'] = $PID
    $bound | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory 'launch.json')
    Log "LAUNCH_REQUEST_PID=$PID SMOKE_ONLY=$SmokeOnly"
    $shell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $parts = @('"'+$shell+'"','-NoProfile','-NonInteractive','-WindowStyle','Hidden',
        '-ExecutionPolicy','Bypass','-File','"'+$PSCommandPath+'"','-Worker')
    foreach ($name in @('RepositoryRoot','ConfigPath','ConfigSha256','ProbeSha256',
        'RunnerSha256','SupervisorSha256','EntrySha256','LauncherSha256','LogDirectory')) {
        $parts += '-'+$name
        $parts += '"'+(Get-Variable -Name $name -ValueOnly)+'"'
    }
    if ($SmokeOnly) { $parts += '-SmokeOnly' }
    # WMI provider creates the worker outside the Codex/launcher process tree.
    # No recurring task, scheduler registration, retry, or machine shutdown.
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = ($parts -join ' ')
        CurrentDirectory = $RepositoryRoot
    }
    Log "CIM_RETURN_CODE=$($created.ReturnValue) WORKER_PID=$($created.ProcessId)"
    if ($created.ReturnValue -ne 0) { throw 'Detached worker creation failed' }
    Write-Output "DETACHED_WORKER_PID=$($created.ProcessId)"
    exit 0
}

$claim = [IO.File]::Open((Join-Path $LogDirectory 'worker.claim'),
    [IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {
    Log "WORKER_PID=$PID SMOKE_ONLY=$SmokeOnly"
    if ($SmokeOnly) {
        Log 'LIFECYCLE_FIXTURE_READY_NO_IO'
        Start-Sleep -Seconds 12
        Log 'LIFECYCLE_FIXTURE_EXIT_CODE=0 NO_IO_OR_SCIENCE'
        exit 0
    }
    $arguments = @('-d','Ubuntu','--',
        '/home/atafe/miniconda/envs/dante_env/bin/python','-B',
        ('"'+(Wsl-Path (Join-Path $RepositoryRoot 'scripts/supervise_dante_workflow_storage.py'))+'"'))
    foreach ($pair in @(
        @('--repository-root',(Wsl-Path $RepositoryRoot)),
        @('--config',(Wsl-Path $ConfigPath)),@('--config-sha256',$ConfigSha256),
        @('--probe-sha256',$ProbeSha256),@('--runner-sha256',$RunnerSha256),
        @('--supervisor-sha256',$SupervisorSha256),
        @('--log-directory',(Wsl-Path (Join-Path $LogDirectory 'python')))
    )) {
        $arguments += $pair[0]
        $arguments += '"'+$pair[1]+'"'
    }
    $startOptions = @{
        FilePath = (Join-Path $env:SystemRoot 'System32/wsl.exe')
        ArgumentList = $arguments
        WindowStyle = 'Hidden'
        PassThru = $true
        RedirectStandardOutput = (Join-Path $LogDirectory 'worker.stdout.log')
        RedirectStandardError = (Join-Path $LogDirectory 'worker.stderr.log')
    }
    Log ('WSL_ARGUMENTS_JSON=' + ($arguments | ConvertTo-Json -Compress))
    $process = Start-Process @startOptions
    [void]$process.Handle
    Log "WSL_LAUNCHER_PID=$($process.Id)"
    $process.WaitForExit()
    $code = $process.ExitCode
    if ($null -eq $code) { throw 'Observed WSL exit unavailable' }
    Log "SUPERVISOR_EXIT_CODE=$code"
    exit $code
} catch {
    Log ('WORKER_FAILURE_NO_RETRY=' + $_.Exception.Message)
    exit 1
} finally {
    $claim.Dispose()
}
