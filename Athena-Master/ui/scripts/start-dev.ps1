[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$SkipBrowser,
    [switch]$UseTestPostgres,
    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$uiRoot = Split-Path -Parent $scriptsRoot
$masterRoot = Split-Path -Parent $uiRoot
$apiRoot = Join-Path $masterRoot "api"
$testComposePath = Join-Path $masterRoot "deploy\compose.test.yaml"
$internalPostgresConfigPath = Join-Path $apiRoot "tests\internal-postgres.env"
$defaultDevelopmentSchema = "athena_dev"
$apiUrl = "http://127.0.0.1:8001"
$apiHealthUrl = "$apiUrl/api/v1/health"
$uiUrl = "http://127.0.0.1:5174"
$uiProxyHealthUrl = "$uiUrl/api/v1/health"

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[Athena Master] $Message" -ForegroundColor Cyan
}

function Get-ApplicationCommand {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $command) {
        throw "Required command '$Name' was not found in PATH."
    }
    return $command.Source
}

function Assert-PostgresUrl {
    param([Parameter(Mandatory = $true)][string]$DatabaseUrl)
    if (-not $DatabaseUrl.StartsWith(
        "postgresql+asyncpg://",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "ATHENA_MASTER_DATABASE_URL must use postgresql+asyncpg."
    }
}

function Assert-PostgresSchema {
    param([Parameter(Mandatory = $true)][string]$DatabaseSchema)
    if ($DatabaseSchema -notmatch '\A[A-Za-z_][A-Za-z0-9_]{0,62}\z') {
        throw "ATHENA_MASTER_DATABASE_SCHEMA must be a safe PostgreSQL identifier."
    }
}

function Get-InternalPostgresConfiguration {
    if (-not (Test-Path -LiteralPath $internalPostgresConfigPath -PathType Leaf)) {
        throw (
            "Internal PostgreSQL configuration is missing. Copy " +
            "api\tests\internal-postgres.env.example to internal-postgres.env " +
            "and fill it locally, or set ATHENA_MASTER_DATABASE_URL."
        )
    }
    $lines = @(Get-Content -LiteralPath $internalPostgresConfigPath -Encoding UTF8)
    $urlAssignments = @(
        $lines | Where-Object { $_ -match '^\s*ATHENA_TEST_POSTGRES_URL\s*=' }
    )
    $schemaAssignments = @(
        $lines | Where-Object { $_ -match '^\s*ATHENA_MASTER_DATABASE_SCHEMA\s*=' }
    )
    if ($urlAssignments.Count -ne 1 -or $schemaAssignments.Count -ne 1) {
        throw (
            "Internal PostgreSQL configuration must define URL and schema exactly once " +
            "(URL entries: $($urlAssignments.Count), schema entries: $($schemaAssignments.Count))."
        )
    }

    $databaseUrl = ($urlAssignments[0] -split '=', 2)[1].Trim()
    $databaseSchema = ($schemaAssignments[0] -split '=', 2)[1].Trim()
    Assert-PostgresUrl -DatabaseUrl $databaseUrl
    Assert-PostgresSchema -DatabaseSchema $databaseSchema
    return [pscustomobject]@{
        DatabaseUrl = $databaseUrl
        DatabaseSchema = $databaseSchema
    }
}

function Start-TestPostgres {
    if (-not (Test-Path -LiteralPath $testComposePath -PathType Leaf)) {
        throw "Test PostgreSQL Compose file is missing: $testComposePath"
    }
    $dockerPath = Get-ApplicationCommand -Name "docker"
    $testPort = [Environment]::GetEnvironmentVariable(
        "ATHENA_TEST_POSTGRES_PORT",
        "Process"
    )
    if ([string]::IsNullOrWhiteSpace($testPort)) {
        $testPort = "55432"
    }
    $parsedPort = 0
    if (-not [int]::TryParse($testPort, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
        throw "ATHENA_TEST_POSTGRES_PORT must be a TCP port between 1 and 65535."
    }

    Write-Step "Starting disposable PostgreSQL..."
    $composeOutput = & $dockerPath compose -f $testComposePath up -d --wait postgres-test
    if ($LASTEXITCODE -ne 0) {
        throw "Test PostgreSQL Compose startup failed with exit code $LASTEXITCODE."
    }
    if ($null -ne $composeOutput) {
        $composeOutput | Write-Host
    }
    return "postgresql+asyncpg://athena_test:athena_test@127.0.0.1:$parsedPort/athena_test"
}

function Test-PythonVersion {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$PrefixArguments = @()
    )
    & $FilePath @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-SystemPython {
    $pyCommand = Get-Command -Name "py.exe" -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $pyCommand -and (Test-PythonVersion -FilePath $pyCommand.Source -PrefixArguments @("-3"))) {
        return [pscustomobject]@{
            FilePath = $pyCommand.Source
            PrefixArguments = @("-3")
        }
    }

    $pythonCommand = Get-Command -Name "python.exe" -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $pythonCommand -and (Test-PythonVersion -FilePath $pythonCommand.Source)) {
        return [pscustomobject]@{
            FilePath = $pythonCommand.Source
            PrefixArguments = @()
        }
    }

    throw "Python 3.12 or newer was not found."
}

function Invoke-InDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    $originalLocation = Get-Location
    try {
        Set-Location -LiteralPath $Path
        & $Action
    }
    finally {
        Set-Location -LiteralPath $originalLocation
    }
}

function Prepare-UiDependencies {
    param([Parameter(Mandatory = $true)][string]$NpmPath)
    if (Test-Path -LiteralPath (Join-Path $uiRoot "node_modules") -PathType Container) {
        return
    }
    Write-Step "Installing UI dependencies..."
    Invoke-InDirectory -Path $uiRoot -Action {
        & $NpmPath ci
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE."
        }
    }
}

function Prepare-Api {
    $venvRoot = Join-Path $apiRoot ".venv"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $dataRoot = Join-Path $apiRoot "data"
    if (-not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
        [void](New-Item -ItemType Directory -Path $dataRoot)
    }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $systemPython = Get-SystemPython
        Write-Step "Creating API virtual environment..."
        & $systemPython.FilePath @($systemPython.PrefixArguments) -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Python virtual environment creation failed."
        }
    }

    $dependenciesReady = Invoke-InDirectory -Path $apiRoot -Action {
        & $venvPython -c "import app, alembic, fastapi, sqlalchemy, uvicorn" 2>$null |
            Out-Null
        return $LASTEXITCODE -eq 0
    }
    if (-not $dependenciesReady) {
        Write-Step "Installing API dependencies..."
        Invoke-InDirectory -Path $apiRoot -Action {
            & $venvPython -m pip install -e ".[dev]"
            if ($LASTEXITCODE -ne 0) {
                throw "API dependency installation failed."
            }
        }
    }

    $databaseSchema = [Environment]::GetEnvironmentVariable(
        "ATHENA_MASTER_DATABASE_SCHEMA",
        "Process"
    )
    Assert-PostgresSchema -DatabaseSchema $databaseSchema
    Write-Step "Preparing PostgreSQL development schema..."
    Invoke-InDirectory -Path $apiRoot -Action {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $schemaOutput = (
                & $venvPython -m app.cli.postgres_schema ensure $databaseSchema 2>&1 |
                    Out-String
            )
            $schemaExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        if ($schemaExitCode -ne 0) {
            throw "PostgreSQL development schema preparation failed; output was withheld."
        }
    }

    Write-Step "Applying database migrations..."
    Invoke-InDirectory -Path $apiRoot -Action {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $migrationOutput = (& $venvPython -m alembic upgrade head 2>&1 | Out-String)
            $migrationExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        if ($migrationExitCode -ne 0) {
            throw "alembic upgrade head failed; output was withheld."
        }
    }
    return [string]$venvPython
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Test-ApiReady {
    try {
        $health = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 2
        return $health.status -eq "ok" -and $health.service -eq "athena-master-api"
    }
    catch {
        return $false
    }
}

function Test-UiReady {
    try {
        $page = Invoke-WebRequest -Uri $uiUrl -UseBasicParsing -TimeoutSec 2
        $health = Invoke-RestMethod -Uri $uiProxyHealthUrl -TimeoutSec 2
        return $page.StatusCode -eq 200 -and $health.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Wait-ForService {
    param([string]$Name, [scriptblock]$Probe)
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (& $Probe) {
            Write-Step "$Name is ready."
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready within $StartupTimeoutSeconds seconds."
}

function ConvertTo-EncodedCommand {
    param([Parameter(Mandatory = $true)][string]$Command)
    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
}

function Start-ApiService {
    param([Parameter(Mandatory = $true)][string]$PythonPath)
    $escapedPython = $PythonPath.Replace("'", "''")
    $command = "`$Host.UI.RawUI.WindowTitle = 'Athena Master API'; & '$escapedPython' -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 1"
    $encodedCommand = ConvertTo-EncodedCommand -Command $command
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-NoExit", "-EncodedCommand", $encodedCommand) `
        -WorkingDirectory $apiRoot
}

function Start-UiService {
    param([Parameter(Mandatory = $true)][string]$NpmPath)
    $escapedNpm = $NpmPath.Replace("'", "''")
    $command = "`$Host.UI.RawUI.WindowTitle = 'Athena Master UI'; & '$escapedNpm' run dev"
    $encodedCommand = ConvertTo-EncodedCommand -Command $command
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-NoExit", "-EncodedCommand", $encodedCommand) `
        -WorkingDirectory $uiRoot
}

try {
    $nodePath = Get-ApplicationCommand -Name "node"
    $npmPath = Get-ApplicationCommand -Name "npm"
    if (-not (Test-Path -LiteralPath (Join-Path $apiRoot "pyproject.toml"))) {
        throw "Master API project is missing."
    }

    if ($SelfTest) {
        $existingVenvPython = Join-Path $apiRoot ".venv\Scripts\python.exe"
        if (-not (
            (Test-Path -LiteralPath $existingVenvPython -PathType Leaf) -and
            (Test-PythonVersion -FilePath $existingVenvPython)
        )) {
            [void](Get-SystemPython)
        }
        Write-Host "UI_ROOT=$uiRoot"
        Write-Host "API_ROOT=$apiRoot"
        Write-Host "NODE=$nodePath"
        Write-Host "NPM=$npmPath"
        Write-Host "API_URL=$apiUrl"
        Write-Host "UI_URL=$uiUrl"
        Write-Host "MIGRATIONS=alembic upgrade head"
        Write-Host "DATABASE=explicit-postgresql+asyncpg"
        Write-Host "INTERNAL_POSTGRES_CONFIG=$internalPostgresConfigPath"
        Write-Host "DEFAULT_DATABASE_SCHEMA=$defaultDevelopmentSchema"
        Write-Host "TEST_POSTGRES_COMPOSE=$testComposePath"
        Write-Host "WORKERS=1"
        Write-Host "SELF_TEST_OK"
        exit 0
    }

    $environmentNames = @(
        "ATHENA_MASTER_ENVIRONMENT",
        "ATHENA_MASTER_DATABASE_URL",
        "ATHENA_MASTER_DATABASE_SCHEMA",
        "ATHENA_MASTER_JWT_SECRET",
        "ATHENA_MASTER_CREDENTIAL_KEY",
        "ATHENA_MASTER_BOOTSTRAP_USERNAME",
        "ATHENA_MASTER_BOOTSTRAP_PASSWORD",
        "ATHENA_MASTER_DATA_DIR"
    )
    $savedEnvironment = @{}
    foreach ($name in $environmentNames) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    try {
        $databaseSchema = [Environment]::GetEnvironmentVariable(
            "ATHENA_MASTER_DATABASE_SCHEMA",
            "Process"
        )
        if ($UseTestPostgres) {
            $databaseUrl = Start-TestPostgres
            if ([string]::IsNullOrWhiteSpace($databaseSchema)) {
                $databaseSchema = $defaultDevelopmentSchema
            }
        }
        else {
            $databaseUrl = [Environment]::GetEnvironmentVariable(
                "ATHENA_MASTER_DATABASE_URL",
                "Process"
            )
            if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
                $databaseUrl = [Environment]::GetEnvironmentVariable(
                    "ATHENA_TEST_POSTGRES_URL",
                    "Process"
                )
                if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
                    $internalConfiguration = Get-InternalPostgresConfiguration
                    $databaseUrl = $internalConfiguration.DatabaseUrl
                    if ([string]::IsNullOrWhiteSpace($databaseSchema)) {
                        $databaseSchema = $internalConfiguration.DatabaseSchema
                    }
                    Write-Step "Using local internal PostgreSQL development configuration."
                }
                elseif ([string]::IsNullOrWhiteSpace($databaseSchema)) {
                    $databaseSchema = $defaultDevelopmentSchema
                }
            }
        }
        if ([string]::IsNullOrWhiteSpace($databaseSchema)) {
            $databaseSchema = "public"
        }
        Assert-PostgresUrl -DatabaseUrl $databaseUrl
        Assert-PostgresSchema -DatabaseSchema $databaseSchema

        [Environment]::SetEnvironmentVariable("ATHENA_MASTER_ENVIRONMENT", "development", "Process")
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_DATABASE_URL",
            $databaseUrl,
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_DATABASE_SCHEMA",
            $databaseSchema,
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_JWT_SECRET",
            "athena-master-local-development-secret-2026",
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_CREDENTIAL_KEY",
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_BOOTSTRAP_USERNAME",
            "admin",
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_BOOTSTRAP_PASSWORD",
            "change-me-now-123",
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_DATA_DIR",
            (Join-Path $apiRoot "data"),
            "Process"
        )

        if (-not (Test-ApiReady)) {
            if (Test-TcpPort -HostName "127.0.0.1" -Port 8001) {
                throw "Port 8001 is occupied by a service that is not Athena Master API."
            }
            $venvPython = Prepare-Api
            Write-Step "Starting API..."
            Start-ApiService -PythonPath $venvPython
            Wait-ForService -Name "API" -Probe { Test-ApiReady }
        }

        if (-not (Test-UiReady)) {
            if (Test-TcpPort -HostName "127.0.0.1" -Port 5174) {
                throw "Port 5174 is occupied by a service that is not Athena Master UI."
            }
            Prepare-UiDependencies -NpmPath $npmPath
            Write-Step "Starting UI..."
            Start-UiService -NpmPath $npmPath
            Wait-ForService -Name "UI" -Probe { Test-UiReady }
        }
    }
    finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
        }
    }

    if (-not $SkipBrowser) {
        Start-Process $uiUrl
    }
    Write-Host "Athena Master development environment is ready." -ForegroundColor Green
    Write-Host "UI: $uiUrl"
    Write-Host "API: $apiHealthUrl"
    Write-Host "Login: admin / change-me-now-123"
    exit 0
}
catch {
    Write-Host "Athena Master development environment failed to start." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
