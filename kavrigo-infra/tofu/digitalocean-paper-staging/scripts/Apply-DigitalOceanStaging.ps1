#requires -Version 5.1
# Applies only the previously reviewed encrypted staging plan, after explicit cost confirmation.
param(
    [switch]$ApproveMonthlyCharges
)

$ErrorActionPreference = 'Stop'
if (-not $ApproveMonthlyCharges) {
    throw 'This creates paid DigitalOcean resources. Review the plan and run with -ApproveMonthlyCharges only after accepting the recurring cost.'
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$workingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tofu = Join-Path $root '.local\opentofu\bin\tofu.exe'
if (-not (Test-Path -LiteralPath $tofu)) {
    $tofu = (Get-Command tofu -ErrorAction Stop).Source
}
$planFile = Join-Path $root '.local\digitalocean-staging.tfplan'
if (-not (Test-Path -LiteralPath $planFile)) {
    throw 'The encrypted staging plan is missing. Re-run planning and review it before applying.'
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
$quotedPassphrase = $null
$locationPushed = $false
try {
    $secureDoToken = Read-Host 'DigitalOcean write-capable API token' -AsSecureString
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

    Push-Location $workingDirectory
    $locationPushed = $true
    & (Join-Path $PSScriptRoot 'Review-DigitalOceanStagingPlan.ps1') -UseExistingEncryption
    Write-Host 'This will create eight resources in DigitalOcean Amsterdam, including billable services.'
    Write-Host 'Estimated floor: about USD 187/month before transfer, storage and other services.'
    $confirmation = (Read-Host 'Type APPLY 8 RESOURCES to accept recurring charges').Trim()
    if ($confirmation -cne 'APPLY 8 RESOURCES') {
        throw 'Apply cancelled; no resources were created by this script.'
    }
    # A saved plan is already approved by OpenTofu; the explicit prompt above is the apply gate.
    & $tofu apply -input=false -no-color -lock-timeout=30s $planFile
    if ($LASTEXITCODE -ne 0) {
        throw 'OpenTofu apply failed or partially completed. Inspect the GitLab state and DigitalOcean resources before retrying; do not create a fresh plan blindly.'
    }
    Write-Host 'PASS: The reviewed paper-staging foundation was applied.'
    Write-Host 'Next: verify resource health and security settings before deploying workloads.'
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
