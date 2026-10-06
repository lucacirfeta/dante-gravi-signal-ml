param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [Parameter(Mandatory=$true)][string]$ConfigSha256,
    [Parameter(Mandatory=$true)][string]$SourceFreeze,
    [Parameter(Mandatory=$true)][string]$ModuleSha256,
    [Parameter(Mandatory=$true)][string]$EntrySha256,
    [Parameter(Mandatory=$true)][string]$LauncherSha256,
    [Parameter(Mandatory=$true)][string]$LogDirectory,
    [switch]$Worker,
    [switch]$SmokeOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion.Major -eq 5) {
    foreach ($name in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Management','CimCmdlets')) {
        Import-Module -Name (Join-Path $PSHOME ('Modules\'+$name+'\'+$name+'.psd1')) -ErrorAction Stop
    }
}
function Assert-Pin([string]$Path, [string]$Sha) {
    if ($Sha -notmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() -ne $Sha) {
        throw "Frozen Linux preparation SHA mismatch: $Path"
    }
}
function Wsl-Path([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -notmatch '^[A-Za-z]:\\' -or $full -match '["\r\n]') {
        throw 'Absolute local drive path without command quoting required'
    }
    return '/mnt/' + $full.Substring(0,1).ToLower() + $full.Substring(2).Replace('\','/')
}
function Log([string]$Text) {
    [IO.File]::AppendAllText((Join-Path $LogDirectory 'launcher.log'),
        ([DateTime]::UtcNow.ToString('o')+' '+$Text+"`n"))
}
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
$LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
foreach ($path in @($RepositoryRoot,$ConfigPath,$LogDirectory,$PSCommandPath)) {
    [void](Wsl-Path $path)
}
if (-not $ConfigPath.StartsWith($RepositoryRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
    $LogDirectory.StartsWith($RepositoryRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
    $SourceFreeze -notmatch '^[0-9a-f]{40}$') { throw 'Invalid preparation scope' }
Assert-Pin $PSCommandPath $LauncherSha256
Assert-Pin $ConfigPath $ConfigSha256
Assert-Pin (Join-Path $RepositoryRoot 'src/dante_workflow/linux_workspace.py') $ModuleSha256
Assert-Pin (Join-Path $RepositoryRoot 'scripts/prepare_dante_workflow_linux.py') $EntrySha256
if (-not $Worker) {
    if (Test-Path -LiteralPath $LogDirectory) { throw 'Existing launch namespace preserved' }
    [void](New-Item -ItemType Directory -Path $LogDirectory)
    $bound = @{}
    foreach ($key in $PSBoundParameters.Keys) { $bound[$key] = $PSBoundParameters[$key] }
    $bound | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDirectory 'launch.json')
    Log "LAUNCH_REQUEST_PID=$PID SMOKE_ONLY=$SmokeOnly"
    $shell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $parts = @('"'+$shell+'"','-NoProfile','-NonInteractive','-WindowStyle','Hidden',
        '-ExecutionPolicy','Bypass','-File','"'+$PSCommandPath+'"','-Worker')
    foreach ($name in @('RepositoryRoot','ConfigPath','ConfigSha256','SourceFreeze',
        'ModuleSha256','EntrySha256','LauncherSha256','LogDirectory')) {
        $parts += '-'+$name
        $parts += '"'+(Get-Variable -Name $name -ValueOnly)+'"'
    }
    if ($SmokeOnly) { $parts += '-SmokeOnly' }
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine=($parts -join ' '); CurrentDirectory=$RepositoryRoot
    }
    Log "CIM_RETURN_CODE=$($created.ReturnValue) WORKER_PID=$($created.ProcessId)"
    if ($created.ReturnValue -ne 0) { throw 'Detached preparation worker creation failed' }
    Write-Output "DETACHED_WORKER_PID=$($created.ProcessId)"
    exit 0
}
$claim = [IO.File]::Open((Join-Path $LogDirectory 'worker.claim'),
    [IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try {
    Log "WORKER_PID=$PID SMOKE_ONLY=$SmokeOnly"
    $arguments = @('-d','Ubuntu','--','/home/atafe/miniconda/envs/dante_env/bin/python','-B')
    if ($SmokeOnly) {
        # Real WSL foreground lifetime exceeds the observed15s daemon idle stop.
        $code = 'import os,time;print(os.getpid(),flush=True);time.sleep(25);print(12345,flush=True)'
        $arguments += '-c'
        $arguments += ('"'+$code+'"')
    } else {
        $arguments += '"'+(Wsl-Path (Join-Path $RepositoryRoot 'scripts/prepare_dante_workflow_linux.py'))+'"'
        foreach ($pair in @(
            @('--config',(Wsl-Path $ConfigPath)),
            @('--config-sha256',$ConfigSha256),@('--source-freeze',$SourceFreeze)
        )) {
            $arguments += $pair[0]
            $arguments += ('"'+$pair[1]+'"')
        }
    }
    $options = @{
        FilePath=(Join-Path $env:SystemRoot 'System32/wsl.exe'); ArgumentList=$arguments
        WindowStyle='Hidden'; PassThru=$true
        RedirectStandardOutput=(Join-Path $LogDirectory 'worker.stdout.log')
        RedirectStandardError=(Join-Path $LogDirectory 'worker.stderr.log')
    }
    Log ('WSL_ARGUMENTS_JSON='+($arguments | ConvertTo-Json -Compress))
    $process = Start-Process @options
    [void]$process.Handle
    Log "WSL_LAUNCHER_PID=$($process.Id)"
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    if ($null -eq $exitCode) { throw 'Observed WSL exit unavailable' }
    Log "PREPARATION_EXIT_CODE=$exitCode SMOKE_ONLY=$SmokeOnly"
    exit $exitCode
} catch {
    Log ('WORKER_FAILURE_NO_RETRY='+$_.Exception.Message)
    exit 1
} finally { $claim.Dispose() }
