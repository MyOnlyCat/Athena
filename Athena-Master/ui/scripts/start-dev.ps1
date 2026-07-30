[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$SkipBrowser,
    [ValidateRange(5, 300)]
    [int]$StartupTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$uiRoot = Split-Path -Parent $scriptsRoot
$masterRoot = Split-Path -Parent $uiRoot
$apiRoot = Join-Path $masterRoot "api"
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

    Write-Step "Applying database migrations..."
    Invoke-InDirectory -Path $apiRoot -Action {
        & $venvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "alembic upgrade head failed."
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
        [void](Get-SystemPython)
        Write-Host "UI_ROOT=$uiRoot"
        Write-Host "API_ROOT=$apiRoot"
        Write-Host "NODE=$nodePath"
        Write-Host "NPM=$npmPath"
        Write-Host "API_URL=$apiUrl"
        Write-Host "UI_URL=$uiUrl"
        Write-Host "MIGRATIONS=alembic upgrade head"
        Write-Host "WORKERS=1"
        Write-Host "SELF_TEST_OK"
        exit 0
    }

    $environmentNames = @(
        "ATHENA_MASTER_ENVIRONMENT",
        "ATHENA_MASTER_DATABASE_URL",
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
        [Environment]::SetEnvironmentVariable("ATHENA_MASTER_ENVIRONMENT", "development", "Process")
        [Environment]::SetEnvironmentVariable(
            "ATHENA_MASTER_DATABASE_URL",
            "sqlite+aiosqlite:///./data/athena-master.db",
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
