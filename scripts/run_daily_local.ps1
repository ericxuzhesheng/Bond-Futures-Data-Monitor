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

"[$(Get-Date -Format o)] Starting Bond Futures Data Monitor in $RepoRoot" | Out-File -FilePath $logPath -Encoding utf8
& $PythonPath -m bond_futures_monitor.cli run --date today *>> $logPath
$exitCode = $LASTEXITCODE
"[$(Get-Date -Format o)] Finished with exit code $exitCode" | Out-File -FilePath $logPath -Encoding utf8 -Append

exit $exitCode
