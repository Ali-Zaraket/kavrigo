# Requires -Version 5.1
# Creates only a terraform_data marker in a separate, disposable Spaces state key.
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$stage = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tofu = Join-Path $root '.local\opentofu\bin\tofu.exe'
if (-not (Test-Path -LiteralPath $tofu)) {
    $tofu = (Get-Command tofu -ErrorAction Stop).Source
}

$sourceBackend = Join-Path $stage 'backend.hcl'
if (-not (Test-Path -LiteralPath $sourceBackend)) {
    throw 'Create the ignored staging backend.hcl before testing Spaces state.'
}
$backend = Get-Content -LiteralPath $sourceBackend -Raw
if ($backend -notmatch '(?m)^\s*bucket\s*=\s*"kavrigo-tofu-state-ams3-az2026"\s*$' -or
    $backend -notmatch 'https://ams3\.digitaloceanspaces\.com') {
    throw 'backend.hcl must point to the reviewed Kavrigo AMS3 state bucket.'
}
if ($backend -notmatch '(?m)^\s*use_lockfile\s*=\s*true\s*$') {
    throw 'backend.hcl must enable use_lockfile before this test.'
}
$backend = $backend -replace '(?m)^\s*key\s*=\s*"[^"]+"\s*$', 'key = "preflight/ams3-state-v1.tfstate"'
if ($backend -notmatch '(?m)^key = "preflight/ams3-state-v1.tfstate"$') {
    throw 'Could not set the disposable preflight state key.'
}

$scratch = Join-Path $root '.local\spaces-state-preflight'
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
[System.IO.File]::WriteAllText((Join-Path $scratch 'backend.hcl'), $backend, [System.Text.UTF8Encoding]::new($false))
$configuration = @'
terraform {
  required_version = ">= 1.12.0, < 2.0.0"
  backend "s3" {}

  encryption {
    state { enforced = true }
    plan { enforced = true }
  }
}

resource "terraform_data" "preflight" {
  input = "kavrigo-spaces-state-preflight-v1"
}
'@
[System.IO.File]::WriteAllText((Join-Path $scratch 'main.tf'), $configuration, [System.Text.UTF8Encoding]::new($false))

$names = @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'TF_ENCRYPTION')
$prior = @{}
foreach ($name in $names) {
    $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

$secureId = $null
$secureSecret = $null
$securePassphrase = $null
$locationPushed = $false
try {
    $secureId = Read-Host 'Spaces Access Key ID' -AsSecureString
    $secureSecret = Read-Host 'Spaces Secret Key' -AsSecureString
    $securePassphrase = Read-Host 'State encryption passphrase from your password manager' -AsSecureString

    $env:AWS_ACCESS_KEY_ID = [System.Net.NetworkCredential]::new('', $secureId).Password
    $env:AWS_SECRET_ACCESS_KEY = [System.Net.NetworkCredential]::new('', $secureSecret).Password
    $passphrase = [System.Net.NetworkCredential]::new('', $securePassphrase).Password
    if ($passphrase.Length -lt 32) {
        throw 'The state passphrase must contain at least 32 characters.'
    }
    $quotedPassphrase = ConvertTo-Json -InputObject $passphrase -Compress
    $env:TF_ENCRYPTION = @"
key_provider "pbkdf2" "spaces_state" {
  passphrase = $quotedPassphrase
}
method "aes_gcm" "spaces_state" {
  keys = key_provider.pbkdf2.spaces_state
}
state {
  method = method.aes_gcm.spaces_state
}
plan {
  method = method.aes_gcm.spaces_state
}
"@
    $passphrase = $null
    $quotedPassphrase = $null

    Push-Location $scratch
    $locationPushed = $true
    & $tofu init -reconfigure '-backend-config=backend.hcl' -input=false -no-color
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu backend initialization failed.' }
    & $tofu apply -auto-approve -input=false -no-color
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu disposable state write failed.' }
    $state = (& $tofu state pull | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0 -or -not ($state.resources | Where-Object { $_.type -eq 'terraform_data' -and $_.name -eq 'preflight' })) {
        throw 'OpenTofu could not read the disposable encrypted state.'
    }
    Write-Host 'PASS: Encrypted disposable state was written to and read from the AMS3 Spaces bucket.'
    Write-Host 'No DigitalOcean infrastructure was created. Lock contention and recovery are separate tests.'
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
    if ($secureId) { $secureId.Dispose() }
    if ($secureSecret) { $secureSecret.Dispose() }
    if ($securePassphrase) { $securePassphrase.Dispose() }
    $passphrase = $null
    $quotedPassphrase = $null
}
