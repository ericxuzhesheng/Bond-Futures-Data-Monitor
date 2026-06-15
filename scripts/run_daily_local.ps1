param(
    [string]$RepoRoot = "",
    [string]$PythonPath = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
} else {
    $RepoRoot = Resolve-Path $RepoRoot
}

Set-Location $RepoRoot

$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "daily-monitor-$timestamp.log"

$exitCode = 1
$resolvedPython = $PythonPath
try {
    $pythonCommand = Get-Command $PythonPath -ErrorAction Stop
    $resolvedPython = $pythonCommand.Source
} catch {
    "[$(Get-Date -Format o)] Failed to resolve PythonPath '$PythonPath': $($_.Exception.Message)" | Out-File -FilePath $logPath -Encoding utf8
    exit 1
}

"[$(Get-Date -Format o)] Starting Bond Futures Data Monitor in $RepoRoot" | Out-File -FilePath $logPath -Encoding utf8
"[$(Get-Date -Format o)] Python: $resolvedPython" | Out-File -FilePath $logPath -Encoding utf8 -Append
"[$(Get-Date -Format o)] User: $env:USERDOMAIN\$env:USERNAME" | Out-File -FilePath $logPath -Encoding utf8 -Append
"[$(Get-Date -Format o)] Command: $resolvedPython -m bond_futures_monitor.cli run --date today" | Out-File -FilePath $logPath -Encoding utf8 -Append

try {
    $env:PYTHONUNBUFFERED = "1"
    # Python logs progress/warnings to stderr. Under the script-level
    # $ErrorActionPreference = "Stop", merging stderr via 2>&1 turns the first
    # warning line (e.g. the harmless Tushare yc_cb permission notice) into a
    # terminating error and aborts an otherwise healthy run. Relax the
    # preference for the child process so the pipeline runs to completion and
    # $LASTEXITCODE reflects Python's real exit code.
    $ErrorActionPreference = "Continue"
    & $resolvedPython -m bond_futures_monitor.cli run --date today 2>&1 | ForEach-Object {
        $_ | Out-File -FilePath $logPath -Encoding utf8 -Append
    }
    $exitCode = $LASTEXITCODE
} catch {
    $exitCode = 1
    "[$(Get-Date -Format o)] PowerShell wrapper error: $($_.Exception.Message)" | Out-File -FilePath $logPath -Encoding utf8 -Append
} finally {
    "[$(Get-Date -Format o)] Finished with exit code $exitCode" | Out-File -FilePath $logPath -Encoding utf8 -Append
}

exit $exitCode
