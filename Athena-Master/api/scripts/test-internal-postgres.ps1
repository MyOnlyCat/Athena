[CmdletBinding()]
param(
    [string]$EnvironmentFile = (
        Join-Path (Split-Path -Parent $PSScriptRoot) "tests\internal-postgres.env"
    ),
    [string[]]$PytestArguments = @("-q")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$apiRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $apiRoot ".venv\Scripts\python.exe"
$runId = [Guid]::NewGuid().ToString("N")
$testRunParent = [IO.Path]::GetFullPath((Join-Path $apiRoot "data\test-runs"))
$testRunDirectory = [IO.Path]::GetFullPath((Join-Path $testRunParent $runId))

if ([IO.Path]::GetDirectoryName($testRunDirectory) -ne $testRunParent) {
    throw "Refusing to use a test run directory outside the expected backend path."
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Master API virtual environment was not found. Run the development setup first."
}

$previousUrl = [Environment]::GetEnvironmentVariable("ATHENA_TEST_POSTGRES_URL", "Process")
$databaseUrl = $previousUrl
if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
    if (-not (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)) {
        throw (
            "ATHENA_TEST_POSTGRES_URL is required. Set it in the process or copy " +
            "tests\internal-postgres.env.example to tests\internal-postgres.env."
        )
    }
    $assignments = @(
        Get-Content -LiteralPath $EnvironmentFile -Encoding UTF8 |
            Where-Object { $_ -match '^\s*ATHENA_TEST_POSTGRES_URL\s*=' }
    )
    if ($assignments.Count -ne 1) {
        throw "Test environment file must define ATHENA_TEST_POSTGRES_URL exactly once."
    }
    $parts = $assignments[0] -split '=', 2
    $databaseUrl = $parts[1].Trim()
}
if (-not $databaseUrl.StartsWith("postgresql+asyncpg://", [StringComparison]::OrdinalIgnoreCase)) {
    throw "ATHENA_TEST_POSTGRES_URL must use postgresql+asyncpg."
}

$locationPushed = $false
$exitCode = 1

try {
    New-Item -ItemType Directory -Path $testRunDirectory -Force | Out-Null
    [Environment]::SetEnvironmentVariable(
        "ATHENA_TEST_POSTGRES_URL",
        $databaseUrl,
        "Process"
    )
    Push-Location -LiteralPath $apiRoot
    $locationPushed = $true
    $runnerArguments = @(
        "--basetemp=$testRunDirectory"
        "-p"
        "no:cacheprovider"
    ) + $PytestArguments
    & $python -m pytest @runnerArguments
    $exitCode = $LASTEXITCODE
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
    [Environment]::SetEnvironmentVariable(
        "ATHENA_TEST_POSTGRES_URL",
        $previousUrl,
        "Process"
    )
    if (Test-Path -LiteralPath $testRunDirectory) {
        Remove-Item -LiteralPath $testRunDirectory -Recurse -Force
    }
}

exit $exitCode
