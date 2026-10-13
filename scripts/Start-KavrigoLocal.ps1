param(
    [switch]$RebuildWeb
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root 'kavrigo-platform\apps\web'
$api = Join-Path $root 'kavrigo-platform\services\api'
$local = Join-Path $root '.local'
$envFile = Join-Path $root '.env'
$webEnvFile = Join-Path $web '.env.local'
$python = Join-Path $root '.venv\Scripts\python.exe'
$next = Join-Path $web 'node_modules\next\dist\bin\next'
$compose = @(
    'compose', '--env-file', $envFile,
    '-f', (Join-Path $root 'kavrigo-infra\local\docker-compose.yml'),
    '-f', (Join-Path $root 'kavrigo-infra\local\docker-compose.clerk.yml')
)

foreach ($path in @($envFile, $webEnvFile, $python, $next)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Local setup is incomplete: $path is missing. See kavrigo-infra/local/README.md."
    }
}

$portLine = Get-Content -LiteralPath $envFile | Where-Object {
    $_ -match '^KAVRIGO_API_HOST_PORT=([0-9]+)$'
} | Select-Object -First 1
$apiPort = if ($portLine -match '^KAVRIGO_API_HOST_PORT=([0-9]+)$') { $Matches[1] } else { '58000' }
$apiHealth = "http://127.0.0.1:$apiPort/readyz"
$webHealth = 'http://localhost:3000/healthz'
$webApp = 'http://localhost:3000/app'

function Test-HttpOk([string]$url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

Write-Host 'Starting local Kavrigo services...'
& docker @compose up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Docker services did not become healthy.' }
if (-not (Test-HttpOk $apiHealth)) { throw "API did not become ready at $apiHealth." }

$previousDsn = $env:POSTGRES_MIGRATION_DSN
try {
    $env:POSTGRES_MIGRATION_DSN = 'postgresql+asyncpg://kavrigo:kavrigo_local_dev@127.0.0.1:55432/kavrigo'
    Push-Location $api
    try {
        & $python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Local database migration failed.' }
    } finally {
        Pop-Location
    }
} finally {
    if ($null -eq $previousDsn) {
        Remove-Item Env:POSTGRES_MIGRATION_DSN -ErrorAction SilentlyContinue
    } else {
        $env:POSTGRES_MIGRATION_DSN = $previousDsn
    }
}

if ($RebuildWeb -and (Test-HttpOk $webHealth)) {
    $pidFile = Join-Path $local 'web-server.pid'
    if (-not (Test-Path -LiteralPath $pidFile)) {
        throw 'Port 3000 is active, but Kavrigo did not record its process ID; no process was stopped.'
    }
    $webPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    $webProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$webPid"
    if (-not $webProcess -or $webProcess.CommandLine -notmatch 'next.*start') {
        throw 'The recorded web process is not a verified Kavrigo server; no process was stopped.'
    }
    Stop-Process -Id $webPid
    Start-Sleep -Seconds 1
}

if (Test-HttpOk $webHealth) {
    if (-not (Test-HttpOk $webApp)) {
        throw 'Port 3000 is occupied by a web service that does not serve Kavrigo /app.'
    }
    Write-Host "Kavrigo is already running: $webApp"
    exit 0
}

if ($RebuildWeb -or -not (Test-Path -LiteralPath (Join-Path $web '.next\BUILD_ID'))) {
    Write-Host 'Building the local web app...'
    Push-Location $web
    try {
        & node $next build
        if ($LASTEXITCODE -ne 0) { throw 'Web build failed.' }
    } finally {
        Pop-Location
    }
}

New-Item -ItemType Directory -Path $local -Force | Out-Null
$process = Start-Process -FilePath (Get-Command node).Source `
    -ArgumentList @($next, 'start', '--hostname', 'localhost', '--port', '3000') `
    -WorkingDirectory $web -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $local 'web-stdout.log') `
    -RedirectStandardError (Join-Path $local 'web-stderr.log') -PassThru
Set-Content -LiteralPath (Join-Path $local 'web-server.pid') -Value $process.Id

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if (Test-HttpOk $webHealth -and (Test-HttpOk $webApp)) {
        Write-Host "Kavrigo is ready: $webApp"
        exit 0
    }
    if ($process.HasExited) { break }
    Start-Sleep -Seconds 1
}
throw "Web startup failed. Inspect .local/web-stdout.log and .local/web-stderr.log."
