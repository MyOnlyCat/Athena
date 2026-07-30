$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$uiRoot = Split-Path -Parent $scriptsRoot
$launcherPath = Join-Path $uiRoot "start-dev.cmd"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Expected launcher does not exist: $launcherPath"
}

$originalLocation = Get-Location
try {
    Set-Location -LiteralPath ([System.IO.Path]::GetTempPath())
    $output = (& $launcherPath --self-test 2>&1 | Out-String)
    $exitCode = $LASTEXITCODE
}
finally {
    Set-Location -LiteralPath $originalLocation
}

if ($exitCode -ne 0) {
    throw "Launcher self-test exited with code ${exitCode}:`n$output"
}

if ($output -notmatch "SELF_TEST_OK") {
    throw "Launcher self-test did not report success:`n$output"
}

Write-Host "PASS: launcher resolves the repository and validates prerequisites from any directory."
