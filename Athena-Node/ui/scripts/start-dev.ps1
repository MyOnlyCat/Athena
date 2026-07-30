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
$repositoryRoot = Split-Path -Parent $uiRoot
$apiRoot = Join-Path $repositoryRoot "api"
$apiUrl = "http://127.0.0.1:8000"
$apiHealthUrl = "$apiUrl/api/v1/health"
$uiUrl = "http://localhost:5173"
$uiProxyHealthUrl = "$uiUrl/api/v1/health"

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host "[Athena] $Message" -ForegroundColor Cyan
}

function Assert-FileExists {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file does not exist: $Path"
    }
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

    throw "Python 3.12 or newer was not found. Install Python and enable the py launcher or PATH entry."
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
        Write-Step "UI dependencies are ready."
        return
    }

    Write-Step "Installing UI dependencies with npm ci..."
    Invoke-InDirectory -Path $uiRoot -Action {
        & $NpmPath ci | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE."
        }
    }
}

function Prepare-ApiDependencies {
    $venvRoot = Join-Path $apiRoot ".venv"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $dataRoot = Join-Path $apiRoot "data"

    if (-not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
        Write-Step "Creating the API data directory..."
        [void](New-Item -ItemType Directory -Path $dataRoot)
    }

    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $systemPython = Get-SystemPython
        Write-Step "Creating API virtual environment..."
        & $systemPython.FilePath @($systemPython.PrefixArguments) -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Python virtual environment creation failed with exit code $LASTEXITCODE."
        }
    }

    $dependenciesReady = Invoke-InDirectory -Path $apiRoot -Action {
        & $venvPython -c "import app, cryptography, fastapi, sqlalchemy, uvicorn" 2>$null |
            Out-Null
        return $LASTEXITCODE -eq 0
    }

    if (-not $dependenciesReady) {
        Write-Step "Installing API dependencies..."
        Invoke-InDirectory -Path $apiRoot -Action {
            & $venvPython -m pip install -e ".[dev]" | Out-Host
            if ($LASTEXITCODE -ne 0) {
                throw "API dependency installation failed with exit code $LASTEXITCODE."
            }
        }
    }
    else {
        Write-Step "API dependencies are ready."
    }

    return [string]$venvPython
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $client = New-Object System.Net.Sockets.TcpClient
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
        return $health.status -eq "ok" -and $health.service -eq "athena-node-api"
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
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Probe
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (& $Probe) {
            Write-Step "$Name is ready."
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready within $StartupTimeoutSeconds seconds. Review its service window."
}

function ConvertTo-EncodedCommand {
    param([Parameter(Mandatory = $true)][string]$Command)
    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
}

function Start-ApiService {
    param([Parameter(Mandatory = $true)][string]$PythonPath)
    $escapedPython = $PythonPath.Replace("'", "''")
    $command = "`$Host.UI.RawUI.WindowTitle = 'Athena API'; & '$escapedPython' -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000"
    $encodedCommand = ConvertTo-EncodedCommand -Command $command
    $environmentNames = @(
        "ATHENA_ENVIRONMENT",
        "ATHENA_JWT_SECRET",
        "ATHENA_CREDENTIAL_KEY",
        "ATHENA_BOOTSTRAP_USERNAME",
        "ATHENA_BOOTSTRAP_PASSWORD"
    )
    $savedEnvironment = @{}
    try {
        foreach ($name in $environmentNames) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        }
        [Environment]::SetEnvironmentVariable("ATHENA_ENVIRONMENT", "development", "Process")
        [Environment]::SetEnvironmentVariable(
            "ATHENA_JWT_SECRET",
            "athena-local-development-secret-2026",
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "ATHENA_CREDENTIAL_KEY",
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            "Process"
        )
        [Environment]::SetEnvironmentVariable("ATHENA_BOOTSTRAP_USERNAME", "admin", "Process")
        [Environment]::SetEnvironmentVariable(
            "ATHENA_BOOTSTRAP_PASSWORD",
            "change-me-now",
            "Process"
        )

        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-NoExit", "-EncodedCommand", $encodedCommand) `
            -WorkingDirectory $apiRoot
    }
    finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
        }
    }
}

function Start-UiService {
    param([Parameter(Mandatory = $true)][string]$NpmPath)
    $escapedNpm = $NpmPath.Replace("'", "''")
    $command = "`$Host.UI.RawUI.WindowTitle = 'Athena UI'; & '$escapedNpm' run dev"
    $encodedCommand = ConvertTo-EncodedCommand -Command $command
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-NoExit", "-EncodedCommand", $encodedCommand) `
        -WorkingDirectory $uiRoot
}

try {
    Assert-FileExists -Path (Join-Path $uiRoot "package.json")
    Assert-FileExists -Path (Join-Path $apiRoot "pyproject.toml")
    $nodePath = Get-ApplicationCommand -Name "node"
    $npmPath = Get-ApplicationCommand -Name "npm"

    if ($SelfTest) {
        $venvPython = Join-Path $apiRoot ".venv\Scripts\python.exe"
        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            if (-not (Test-PythonVersion -FilePath $venvPython)) {
                throw "The API virtual environment does not use Python 3.12 or newer."
            }
        }
        else {
            [void](Get-SystemPython)
        }
        Write-Host "UI_ROOT=$uiRoot"
        Write-Host "API_ROOT=$apiRoot"
        Write-Host "NODE=$nodePath"
        Write-Host "NPM=$npmPath"
        Write-Host "SELF_TEST_OK"
        exit 0
    }

    if (Test-ApiReady) {
        Write-Step "Reusing the API already running at $apiUrl."
    }
    else {
        if (Test-TcpPort -HostName "127.0.0.1" -Port 8000) {
            throw "Port 8000 is occupied by a service that is not the Athena API."
        }
        $venvPython = Prepare-ApiDependencies
        Write-Step "Starting API in a new window..."
        Start-ApiService -PythonPath $venvPython
        Wait-ForService -Name "API" -Probe { Test-ApiReady }
    }

    if (Test-UiReady) {
        Write-Step "Reusing the UI already running at $uiUrl."
    }
    else {
        if (Test-TcpPort -HostName "127.0.0.1" -Port 5173) {
            throw "Port 5173 is occupied by a service that is not the Athena UI."
        }
        Prepare-UiDependencies -NpmPath $npmPath
        Write-Step "Starting UI in a new window..."
        Start-UiService -NpmPath $npmPath
        Wait-ForService -Name "UI" -Probe { Test-UiReady }
    }

    if (-not $SkipBrowser) {
        Write-Step "Opening $uiUrl"
        Start-Process $uiUrl
    }

    Write-Host ""
    Write-Host "Athena development environment is ready." -ForegroundColor Green
    Write-Host "UI:  $uiUrl"
    Write-Host "API: $apiHealthUrl"
    Write-Host "Login: admin / change-me-now"
    exit 0
}
catch {
    Write-Host ""
    Write-Host "Athena development environment failed to start." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
