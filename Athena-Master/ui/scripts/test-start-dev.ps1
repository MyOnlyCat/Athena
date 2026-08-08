$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$uiRoot = Split-Path -Parent $scriptsRoot
$masterRoot = Split-Path -Parent $uiRoot
$apiRoot = Join-Path $masterRoot "api"
$launcherPath = Join-Path $uiRoot "start-dev.cmd"
$testComposePath = Join-Path $masterRoot "deploy\compose.test.yaml"

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
    "DATABASE=explicit-postgresql+asyncpg",
    "INTERNAL_POSTGRES_CONFIG=$apiRoot\tests\internal-postgres.env",
    "DEFAULT_DATABASE_SCHEMA=athena_dev",
    "TEST_POSTGRES_COMPOSE=$testComposePath",
    "WORKERS=1"
)) {
    if ($output -notmatch [regex]::Escape($expected)) {
        throw "Launcher self-test did not report '$expected':`n$output"
    }
}

function Get-FreeTcpPort {
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Wait-ForProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Probe,
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($null -ne $Process -and $Process.HasExited) {
            throw "$Name process exited with code $($Process.ExitCode)."
        }
        try {
            if (& $Probe) {
                return
            }
        }
        catch {
            # The service may accept TCP before its application is ready.
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds."
}

function Stop-OwnedProcess {
    param([System.Diagnostics.Process]$Process)
    if ($null -eq $Process -or $Process.HasExited) {
        return
    }
    Stop-Process -Id $Process.Id -Force
    try {
        Wait-Process -Id $Process.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
    catch {
        # The process is already force-stopped; cleanup continues below.
    }
}

function Invoke-MasterSchemaOperation {
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][ValidateSet("create", "drop")][string]$Operation,
        [Parameter(Mandatory = $true)][string]$Schema
    )
    if ($Schema -notmatch '\Aathena_smoke_[0-9a-f]{32}\z') {
        throw "Refusing an unsafe Master startup smoke schema."
    }
    $schemaOperation = if ($Operation -eq "create") {
        "create-smoke"
    }
    else {
        "drop-smoke"
    }
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $schemaOutput = (
            & $PythonPath -m app.cli.postgres_schema $schemaOperation $Schema 2>&1 |
                Out-String
        )
        $schemaExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($schemaExitCode -ne 0) {
        throw "Master startup smoke schema $Operation failed; output was withheld."
    }
}

function Protect-SensitiveOutput {
    param([Parameter(Mandatory = $true)][string]$Text)
    $protected = [regex]::Replace(
        $Text,
        'postgresql(?:\+asyncpg)?://[^\s''"]+',
        '<redacted-postgres-url>',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    foreach ($sensitive in @(
        "athena-master-startup-smoke-secret-2026",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "SmokeAdminPassword123"
    )) {
        $protected = $protected.Replace($sensitive, "<redacted>")
    }
    return $protected
}

$pythonPath = Join-Path $apiRoot ".venv\Scripts\python.exe"
$vitePath = Join-Path $uiRoot "node_modules\vite\bin\vite.js"
$nodePath = (Get-Command -Name "node" -CommandType Application -ErrorAction Stop).Source
foreach ($requiredPath in @($pythonPath, $vitePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Startup smoke-test dependency is missing: $requiredPath"
    }
}

$smokeRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "athena-master-startup-$([Guid]::NewGuid().ToString('N'))"
$smokeRoot = [System.IO.Path]::GetFullPath($smokeRoot)
[void](New-Item -ItemType Directory -Path $smokeRoot)
$dataRoot = Join-Path $smokeRoot "data"
[void](New-Item -ItemType Directory -Path $dataRoot)
$apiPort = Get-FreeTcpPort
do {
    $uiPort = Get-FreeTcpPort
} while ($uiPort -eq $apiPort)
do {
    $postgresPort = Get-FreeTcpPort
} while ($postgresPort -eq $apiPort -or $postgresPort -eq $uiPort)
$apiUrl = "http://127.0.0.1:$apiPort"
$uiUrl = "http://127.0.0.1:$uiPort"
$apiOutput = Join-Path $smokeRoot "api.out.log"
$apiError = Join-Path $smokeRoot "api.err.log"
$uiOutput = Join-Path $smokeRoot "ui.out.log"
$uiError = Join-Path $smokeRoot "ui.err.log"
$apiProcess = $null
$uiProcess = $null
$dockerPath = $null
$ownsTestPostgres = $false
$testComposeProject = "athena-master-smoke-$([Guid]::NewGuid().ToString('N'))"
$testDatabaseUrl = $null
$smokeSchema = "athena_smoke_$([Guid]::NewGuid().ToString('N').ToLowerInvariant())"
$smokeSchemaCreated = $false
$operationFailed = $false
$schemaCleanupFailed = $false
$postgresCleanupFailed = $false
$environmentNames = @(
    "ATHENA_MASTER_ENVIRONMENT",
    "ATHENA_MASTER_DATABASE_URL",
    "ATHENA_MASTER_DATABASE_SCHEMA",
    "ATHENA_MASTER_JWT_SECRET",
    "ATHENA_MASTER_CREDENTIAL_KEY",
    "ATHENA_MASTER_BOOTSTRAP_USERNAME",
    "ATHENA_MASTER_BOOTSTRAP_PASSWORD",
    "ATHENA_MASTER_DATA_DIR",
    "ATHENA_MASTER_API_TARGET",
    "ATHENA_TEST_POSTGRES_PORT"
)
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $testDatabaseUrl = [Environment]::GetEnvironmentVariable(
        "ATHENA_TEST_POSTGRES_URL",
        "Process"
    )
    if ([string]::IsNullOrWhiteSpace($testDatabaseUrl)) {
        if (-not (Test-Path -LiteralPath $testComposePath -PathType Leaf)) {
            throw "Test PostgreSQL Compose file is missing: $testComposePath"
        }
        $dockerCommand = Get-Command -Name "docker" -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
        $dockerPath = $dockerCommand.Source
        [Environment]::SetEnvironmentVariable(
            "ATHENA_TEST_POSTGRES_PORT",
            "$postgresPort",
            "Process"
        )
        $ownsTestPostgres = $true
        $composeOutput = & $dockerPath compose `
            --project-name $testComposeProject `
            -f $testComposePath `
            up -d --wait postgres-test
        if ($LASTEXITCODE -ne 0) {
            throw "Disposable PostgreSQL startup failed with exit code $LASTEXITCODE."
        }
        if ($null -ne $composeOutput) {
            $composeOutput | Write-Host
        }
        $testDatabaseUrl = (
            "postgresql+asyncpg://athena_test:athena_test@" +
            "127.0.0.1:$postgresPort/athena_test"
        )
    }
    if (-not $testDatabaseUrl.StartsWith(
        "postgresql+asyncpg://",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "ATHENA_TEST_POSTGRES_URL must use postgresql+asyncpg."
    }

    [Environment]::SetEnvironmentVariable("ATHENA_MASTER_ENVIRONMENT", "test", "Process")
    [Environment]::SetEnvironmentVariable(
        "ATHENA_MASTER_DATABASE_URL",
        $testDatabaseUrl,
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "ATHENA_MASTER_DATABASE_SCHEMA",
        $smokeSchema,
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "ATHENA_MASTER_JWT_SECRET",
        "athena-master-startup-smoke-secret-2026",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "ATHENA_MASTER_CREDENTIAL_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "ATHENA_MASTER_BOOTSTRAP_USERNAME",
        "smoke-admin",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "ATHENA_MASTER_BOOTSTRAP_PASSWORD",
        "SmokeAdminPassword123",
        "Process"
    )
    [Environment]::SetEnvironmentVariable("ATHENA_MASTER_DATA_DIR", $dataRoot, "Process")
    [Environment]::SetEnvironmentVariable("ATHENA_MASTER_API_TARGET", $apiUrl, "Process")

    Invoke-MasterSchemaOperation `
        -PythonPath $pythonPath `
        -Operation "create" `
        -Schema $smokeSchema
    $smokeSchemaCreated = $true

    Push-Location -LiteralPath $apiRoot
    try {
        $savedErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $migrationOutput = (& $pythonPath -m alembic upgrade head 2>&1 | Out-String)
            $migrationExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $savedErrorActionPreference
        }
        if ($migrationExitCode -ne 0) {
            throw "Master migration smoke test failed; output was withheld."
        }
    }
    finally {
        Pop-Location
    }

    $apiProcess = Start-Process -FilePath $pythonPath `
        -ArgumentList @(
            "-m", "uvicorn", "app.main:create_app", "--factory",
            "--host", "127.0.0.1", "--port", "$apiPort", "--workers", "1",
            "--no-access-log"
        ) `
        -WorkingDirectory $apiRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $apiOutput `
        -RedirectStandardError $apiError `
        -PassThru
    Wait-ForProbe -Name "Master API" -Process $apiProcess -Probe {
        $health = Invoke-RestMethod -Uri "$apiUrl/api/v1/health" -TimeoutSec 2
        return (
            $health.status -eq "ok" -and
            $health.service -eq "athena-master-api" -and
            $health.database -eq "ok"
        )
    }

    $loginBody = @{
        username = "smoke-admin"
        password = "SmokeAdminPassword123"
    } | ConvertTo-Json
    $login = Invoke-RestMethod `
        -Uri "$apiUrl/api/v1/auth/login" `
        -Method Post `
        -ContentType "application/json" `
        -Body $loginBody `
        -TimeoutSec 5
    if ([string]::IsNullOrWhiteSpace([string]$login.access_token)) {
        throw "Bootstrap administrator login did not return an access token."
    }

    $uiProcess = Start-Process -FilePath $nodePath `
        -ArgumentList @(
            $vitePath, "--host", "127.0.0.1", "--port", "$uiPort", "--strictPort"
        ) `
        -WorkingDirectory $uiRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $uiOutput `
        -RedirectStandardError $uiError `
        -PassThru
    Wait-ForProbe -Name "Master UI" -Process $uiProcess -Probe {
        $page = Invoke-WebRequest -Uri $uiUrl -UseBasicParsing -TimeoutSec 2
        $proxiedHealth = Invoke-RestMethod -Uri "$uiUrl/api/v1/health" -TimeoutSec 2
        $contentSecurityPolicy = [string]$page.Headers["Content-Security-Policy"]
        $inlineScriptHashes = @(
            [regex]::Matches($page.Content, '(?s)<script[^>]*>(.*?)</script>') |
                ForEach-Object {
                    $scriptContent = $_.Groups[1].Value
                    if (-not [string]::IsNullOrWhiteSpace($scriptContent)) {
                        $sha256 = [System.Security.Cryptography.SHA256]::Create()
                        try {
                            [Convert]::ToBase64String(
                                $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($scriptContent))
                            )
                        }
                        finally {
                            $sha256.Dispose()
                        }
                    }
                }
        )
        $unapprovedInlineScripts = @(
            $inlineScriptHashes |
                Where-Object {
                    -not $contentSecurityPolicy.Contains("'sha256-$($_)'")
                }
        )
        return (
            $page.StatusCode -eq 200 -and
            $contentSecurityPolicy.Contains("script-src 'self'") -and
            $contentSecurityPolicy.Contains("script-src-attr 'none'") -and
            $contentSecurityPolicy.Contains("object-src 'none'") -and
            $contentSecurityPolicy.Contains("frame-ancestors 'none'") -and
            $inlineScriptHashes.Count -gt 0 -and
            $unapprovedInlineScripts.Count -eq 0 -and
            $proxiedHealth.status -eq "ok" -and
            $proxiedHealth.service -eq "athena-master-api"
        )
    }

    Write-Host "MIGRATION_SMOKE_OK"
    Write-Host "BOOTSTRAP_LOGIN_SMOKE_OK"
    Write-Host "API_HEALTH_SMOKE_OK"
    Write-Host "UI_PROXY_SMOKE_OK"
}
catch {
    $operationFailed = $true
    foreach ($logPath in @($apiError, $uiError)) {
        if (Test-Path -LiteralPath $logPath -PathType Leaf) {
            $log = Get-Content -Raw -LiteralPath $logPath
            if (-not [string]::IsNullOrWhiteSpace($log)) {
                $safeLog = Protect-SensitiveOutput -Text $log
                Write-Error "$logPath`n$safeLog" -ErrorAction Continue
            }
        }
    }
    throw
}
finally {
    Stop-OwnedProcess -Process $uiProcess
    Stop-OwnedProcess -Process $apiProcess
    if ($smokeSchemaCreated) {
        try {
            Invoke-MasterSchemaOperation `
                -PythonPath $pythonPath `
                -Operation "drop" `
                -Schema $smokeSchema
        }
        catch {
            if ($operationFailed) {
                Write-Warning "Master startup smoke schema cleanup failed; output was withheld."
            }
            else {
                $schemaCleanupFailed = $true
            }
        }
    }
    if ($ownsTestPostgres -and $null -ne $dockerPath) {
        & $dockerPath compose `
            --project-name $testComposeProject `
            -f $testComposePath `
            down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) {
            if ($operationFailed) {
                Write-Warning "Disposable PostgreSQL cleanup failed for $testComposeProject."
            }
            else {
                $postgresCleanupFailed = $true
            }
        }
    }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
    }
    $temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $smokeLeaf = Split-Path -Leaf $smokeRoot
    if (
        $smokeRoot.StartsWith(
            $temporaryRoot,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -and
        $smokeLeaf.StartsWith("athena-master-startup-")
    ) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($schemaCleanupFailed) {
    throw "Master startup smoke schema cleanup failed; output was withheld."
}
if ($postgresCleanupFailed) {
    throw "Disposable PostgreSQL cleanup failed for $testComposeProject."
}

Write-Host "PASS: Master launcher and isolated startup smoke test cover migration, bootstrap, health, proxy, and single-worker boundaries."
