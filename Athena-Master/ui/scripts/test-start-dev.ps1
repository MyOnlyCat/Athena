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

foreach ($expected in @(
    "SELF_TEST_OK",
    "API_URL=http://127.0.0.1:8001",
    "UI_URL=http://127.0.0.1:5174",
    "MIGRATIONS=alembic upgrade head",
    "WORKERS=1"
)) {
    if ($output -notmatch [regex]::Escape($expected)) {
        throw "Launcher self-test did not report '$expected':`n$output"
    }
}

Write-Host "PASS: Master launcher resolves both projects and declares migration, proxy, and single-worker boundaries."
