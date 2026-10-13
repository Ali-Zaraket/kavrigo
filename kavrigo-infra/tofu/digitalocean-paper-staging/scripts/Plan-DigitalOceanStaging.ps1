#requires -Version 5.1
# Creates an encrypted plan only. Never applies DigitalOcean resources.
param(
    [string]$KubernetesVersion = '1.36.5-do.0'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$workingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tofu = Join-Path $root '.local\opentofu\bin\tofu.exe'
if (-not (Test-Path -LiteralPath $tofu)) {
    $tofu = (Get-Command tofu -ErrorAction Stop).Source
}

$registryName = (Read-Host 'Globally unique registry name (lowercase letters, numbers, hyphens)').Trim()
if ($registryName -notmatch '^[a-z0-9][a-z0-9-]{2,62}$') {
    throw 'Enter a lowercase registry name of 3-63 letters, numbers or hyphens.'
}
$operatorCidr = (Read-Host 'Your current public IPv4 address with /32 for Kubernetes API access').Trim()
$cidrParts = $operatorCidr.Split('/')
$ipAddress = [System.Net.IPAddress]::None
if ($cidrParts.Count -ne 2 -or
    -not [System.Net.IPAddress]::TryParse($cidrParts[0], [ref]$ipAddress) -or
    $ipAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
    $cidrParts[1] -ne '32') {
    throw 'Enter your current public IPv4 address with /32, for example 203.0.113.10/32.'
}

$names = @(
    'DIGITALOCEAN_TOKEN', 'TF_HTTP_ADDRESS', 'TF_HTTP_LOCK_ADDRESS',
    'TF_HTTP_UNLOCK_ADDRESS', 'TF_HTTP_LOCK_METHOD', 'TF_HTTP_UNLOCK_METHOD',
    'TF_HTTP_USERNAME', 'TF_HTTP_PASSWORD', 'TF_ENCRYPTION'
)
$prior = @{}
foreach ($name in $names) {
    $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

$secureDoToken = $null
$secureGitLabToken = $null
$securePassphrase = $null
$doToken = $null
$gitLabToken = $null
$passphrase = $null
$locationPushed = $false
try {
    $secureDoToken = Read-Host 'DigitalOcean Read Only API token' -AsSecureString
    $secureGitLabToken = Read-Host 'GitLab personal access token (api scope)' -AsSecureString
    $securePassphrase = Read-Host 'State encryption passphrase from your password manager' -AsSecureString
    $doToken = [System.Net.NetworkCredential]::new('', $secureDoToken).Password
    $gitLabToken = [System.Net.NetworkCredential]::new('', $secureGitLabToken).Password
    $passphrase = [System.Net.NetworkCredential]::new('', $securePassphrase).Password
    if ([string]::IsNullOrWhiteSpace($doToken) -or [string]::IsNullOrWhiteSpace($gitLabToken)) {
        throw 'Both API tokens are required.'
    }
    if ($passphrase.Length -lt 32) {
        throw 'The state encryption passphrase must contain at least 32 characters.'
    }

    try {
        $kubernetesOptions = Invoke-RestMethod -Method Get `
            -Uri 'https://api.digitalocean.com/v2/kubernetes/options' `
            -Headers @{ Authorization = "Bearer $doToken" } `
            -TimeoutSec 30
        $databaseOptions = Invoke-RestMethod -Method Get `
            -Uri 'https://api.digitalocean.com/v2/databases/options' `
            -Headers @{ Authorization = "Bearer $doToken" } `
            -TimeoutSec 30
        $registryOptions = Invoke-RestMethod -Method Get `
            -Uri 'https://api.digitalocean.com/v2/registries/options' `
            -Headers @{ Authorization = "Bearer $doToken" } `
            -TimeoutSec 30
    }
    catch {
        throw 'Could not read DigitalOcean Kubernetes, database or registry options. Check token expiry, Read Only scope, and network access.'
    }
    if ('ams3' -notin @($kubernetesOptions.options.regions | ForEach-Object { $_.slug }) -or
        's-2vcpu-4gb' -notin @($kubernetesOptions.options.sizes | ForEach-Object { $_.slug }) -or
        $KubernetesVersion -notin @($kubernetesOptions.options.versions | ForEach-Object { $_.slug })) {
        throw 'Amsterdam, the planned worker size, or the chosen Kubernetes version is no longer listed by DigitalOcean.'
    }
    foreach ($database in @(@{ engine = 'pg'; version = '18' }, @{ engine = 'valkey'; version = '8' })) {
        $engineOptions = $databaseOptions.options.($database.engine)
        $singleNodeLayout = $engineOptions.layouts | Where-Object { $_.num_nodes -eq 1 } | Select-Object -First 1
        if ('ams3' -notin @($engineOptions.regions) -or
            $database.version -notin @($engineOptions.versions) -or
            -not $singleNodeLayout -or
            'db-s-1vcpu-1gb' -notin @($singleNodeLayout.sizes)) {
            throw "The planned $($database.engine) database version, size or Amsterdam region is unavailable."
        }
    }
    $basicTier = $registryOptions.options.subscription_tiers |
        Where-Object { $_.slug -eq 'basic' } | Select-Object -First 1
    if ('ams3' -notin @($registryOptions.options.available_regions) -or
        -not $basicTier -or $basicTier.eligible -eq $false) {
        throw 'The planned Basic container registry or Amsterdam storage region is unavailable.'
    }

    $address = 'https://gitlab.com/api/v4/projects/87561856/terraform/state/paper-staging-ams3-v1'
    $env:DIGITALOCEAN_TOKEN = $doToken
    $env:TF_HTTP_ADDRESS = $address
    $env:TF_HTTP_LOCK_ADDRESS = "$address/lock"
    $env:TF_HTTP_UNLOCK_ADDRESS = "$address/lock"
    $env:TF_HTTP_LOCK_METHOD = 'POST'
    $env:TF_HTTP_UNLOCK_METHOD = 'DELETE'
    $env:TF_HTTP_USERNAME = 'alizaraket600'
    $env:TF_HTTP_PASSWORD = $gitLabToken
    $quotedPassphrase = ConvertTo-Json -InputObject $passphrase -Compress
    $env:TF_ENCRYPTION = @"
key_provider "pbkdf2" "gitlab_staging" {
  passphrase = $quotedPassphrase
}
method "aes_gcm" "gitlab_staging" {
  keys = key_provider.pbkdf2.gitlab_staging
}
state {
  method = method.aes_gcm.gitlab_staging
}
plan {
  method = method.aes_gcm.gitlab_staging
}
"@
    $doToken = $null
    $gitLabToken = $null
    $passphrase = $null
    $quotedPassphrase = $null

    $localDirectory = Join-Path $root '.local'
    New-Item -ItemType Directory -Path $localDirectory -Force | Out-Null
    $variableFile = Join-Path $localDirectory 'digitalocean-staging-plan.tfvars'
    $planFile = Join-Path $localDirectory 'digitalocean-staging.tfplan'
    $variables = @"
registry_name      = $(ConvertTo-Json -InputObject $registryName -Compress)
kubernetes_version = $(ConvertTo-Json -InputObject $KubernetesVersion -Compress)
operator_cidrs     = $(ConvertTo-Json -InputObject @($operatorCidr) -Compress)
"@
    [System.IO.File]::WriteAllText($variableFile, $variables, [System.Text.UTF8Encoding]::new($false))

    Push-Location $workingDirectory
    $locationPushed = $true
    & $tofu init -reconfigure -lockfile=readonly -input=false -no-color
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu staging backend initialization failed.' }
    & $tofu plan -input=false -no-color -lock-timeout=0s "-var-file=$variableFile" "-out=$planFile"
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu staging plan failed; no DigitalOcean resources were applied.' }
    Write-Host "PASS: Encrypted staging plan saved to ignored path $planFile"
    Write-Host 'No DigitalOcean resources were applied.'
}
finally {
    if ($locationPushed) { Pop-Location }
    foreach ($name in $names) {
        $path = "Env:$name"
        if ($null -eq $prior[$name]) {
            Remove-Item -Path $path -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -Path $path -Value $prior[$name]
        }
    }
    if ($secureDoToken) { $secureDoToken.Dispose() }
    if ($secureGitLabToken) { $secureGitLabToken.Dispose() }
    if ($securePassphrase) { $securePassphrase.Dispose() }
    $doToken = $null
    $gitLabToken = $null
    $passphrase = $null
    $quotedPassphrase = $null
}
