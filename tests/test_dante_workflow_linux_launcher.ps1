param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (Test-Path -LiteralPath $EvidenceDirectory) { throw 'Fixture evidence already exists' }
[void](New-Item -ItemType Directory -Path $EvidenceDirectory)
$shell=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$launcher=Join-Path $RepositoryRoot 'scripts/launch_dante_workflow_linux.ps1'
$config=Join-Path $RepositoryRoot 'config/dante_workflow_linux_workspace_v2.json'
$values=@{
    RepositoryRoot=$RepositoryRoot; ConfigPath=$config
    ConfigSha256=(Get-FileHash -LiteralPath $config).Hash.ToLower()
    SourceFreeze=(& git -C $RepositoryRoot rev-parse HEAD)
    ModuleSha256=(Get-FileHash -LiteralPath (Join-Path $RepositoryRoot 'src/dante_workflow/linux_workspace.py')).Hash.ToLower()
    EntrySha256=(Get-FileHash -LiteralPath (Join-Path $RepositoryRoot 'scripts/prepare_dante_workflow_linux.py')).Hash.ToLower()
    LauncherSha256=(Get-FileHash -LiteralPath $launcher).Hash.ToLower()
}
function Arguments([string]$Directory,[switch]$WrongPin) {
    $parts=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        '"'+$launcher+'"','-SmokeOnly','-LogDirectory','"'+$Directory+'"')
    foreach($key in $values.Keys) {
        $value=$values[$key]
        if($WrongPin -and $key -eq 'ConfigSha256') { $value='0'*64 }
        $parts += '-'+$key
        $parts += '"'+$value+'"'
    }
    return $parts
}
$tokens=$null; $parseErrors=$null
[void][Management.Automation.Language.Parser]::ParseFile($launcher,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count) { throw 'Launcher parse errors' }
Write-Output 'CHECK1_PARSE_PASS'
$invalid=Join-Path $EvidenceDirectory 'invalid'
$options=@{
    FilePath=$shell; ArgumentList=(Arguments $invalid -WrongPin)
    WindowStyle='Hidden'; PassThru=$true
    RedirectStandardOutput=(Join-Path $EvidenceDirectory 'invalid.stdout.log')
    RedirectStandardError=(Join-Path $EvidenceDirectory 'invalid.stderr.log')
}
$parent=Start-Process @options
$parent.WaitForExit()
if($parent.ExitCode -eq 0 -or (Test-Path -LiteralPath $invalid)) { throw 'Wrong pin accepted' }
Write-Output 'CHECK2_WRONG_PIN_REJECTED'
$valid=Join-Path $EvidenceDirectory 'valid'
$options.ArgumentList=Arguments $valid
$options.RedirectStandardOutput=Join-Path $EvidenceDirectory 'parent.stdout.log'
$options.RedirectStandardError=Join-Path $EvidenceDirectory 'parent.stderr.log'
$parent=Start-Process @options
$parent.WaitForExit()
if($parent.ExitCode -ne 0) { throw 'Launcher parent failed' }
Write-Output "CHECK3_PARENT_ACTUAL_EXIT_CODE=$($parent.ExitCode)"
$deadline=[DateTime]::UtcNow.AddSeconds(20)
do {
    $log=Get-Content -LiteralPath (Join-Path $valid 'launcher.log') -Raw
    if($log -match 'WORKER_PID=(\d+) SMOKE_ONLY=True') { break }
    Start-Sleep -Milliseconds 200
} while([DateTime]::UtcNow -lt $deadline)
if($log -notmatch 'WORKER_PID=(\d+) SMOKE_ONLY=True') { throw 'Worker not observed' }
$workerPid=[int]$Matches[1]
$worker=[Diagnostics.Process]::GetProcessById($workerPid)
[void]$worker.Handle
$child=Get-CimInstance Win32_Process -Filter "ProcessId=$workerPid"
$creator=Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)"
if($creator.Name -ne 'WmiPrvSE.exe' -or (Get-Process -Id $parent.Id -ErrorAction SilentlyContinue)) {
    throw 'Worker not detached from caller'
}
Write-Output 'CHECK4_DETACHED_WMI_OWNER'
if(-not $worker.WaitForExit(45000)) { throw 'Fixture timed out; preserve process/evidence' }
if($null -eq $worker.ExitCode -or $worker.ExitCode -ne 0) { throw 'Worker fixture failed' }
$log=Get-Content -LiteralPath (Join-Path $valid 'launcher.log') -Raw
$stdout=Get-Content -LiteralPath (Join-Path $valid 'worker.stdout.log') -Raw
if($log -notmatch 'PREPARATION_EXIT_CODE=0 SMOKE_ONLY=True' -or $stdout -notmatch '12345') {
    throw 'No actual WSL fixture completion'
}
Write-Output "CHECK5_FOREGROUND_WSL_SURVIVED_IDLE_INTERVAL ACTUAL_OS_EXIT_CODE=$($worker.ExitCode)"
$options.RedirectStandardOutput=Join-Path $EvidenceDirectory 'duplicate.stdout.log'
$options.RedirectStandardError=Join-Path $EvidenceDirectory 'duplicate.stderr.log'
$duplicate=Start-Process @options
$duplicate.WaitForExit()
if($duplicate.ExitCode -eq 0) { throw 'Existing namespace relaunched' }
Write-Output 'CHECK6_DUPLICATE_REJECTED'
Write-Output '6_LINUX_LAUNCHER_CHECKS_PASS NO_IO_OR_SCIENTIFIC_STAGE'
