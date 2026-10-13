# Requires -Version 5.1
# Creates only a terraform_data marker in a separate, disposable Spaces state key.
param([switch]$TestLock)

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
    if ($TestLock) {
        # Force a replacement. The local-exec marker is written only after the
        # holder has acquired the backend lock, then it holds the lock briefly.
        $marker = Join-Path $scratch ("lock-held-$([guid]::NewGuid().ToString('N')).marker")
        $markerForPowerShell = $marker.Replace('\', '/')
        $holdCommand = "Set-Content -LiteralPath '$markerForPowerShell' -Value ready; Start-Sleep -Seconds 25"
        $holdCommandHcl = ConvertTo-Json -InputObject $holdCommand -Compress
        $lockConfiguration = @"
terraform {
  required_version = ">= 1.12.0, < 2.0.0"
  backend "s3" {}
  encryption {
    state { enforced = true }
    plan { enforced = true }
  }
}
resource "terraform_data" "preflight" {
  input            = "kavrigo-spaces-state-preflight-v1"
  triggers_replace = timestamp()
  provisioner "local-exec" {
    interpreter = ["powershell.exe", "-NoProfile", "-Command"]
    command     = $holdCommandHcl
  }
}
"@
        [System.IO.File]::WriteAllText((Join-Path $scratch 'main.tf'), $lockConfiguration, [System.Text.UTF8Encoding]::new($false))
        $stdout = Join-Path $scratch 'lock-holder.stdout.log'
        $stderr = Join-Path $scratch 'lock-holder.stderr.log'
        $holder = Start-Process -FilePath $tofu -ArgumentList @('apply', '-auto-approve', '-input=false', '-no-color') -WorkingDirectory $scratch -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        try {
            $deadline = (Get-Date).AddSeconds(45)
            while (-not (Test-Path -LiteralPath $marker) -and -not $holder.HasExited -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 250
                $holder.Refresh()
            }
            if (-not (Test-Path -LiteralPath $marker)) {
                throw 'The lock holder did not reach its holding phase; inspect the ignored lock-holder logs.'
            }
            $contenderOutput = (& $tofu plan -lock-timeout=0s -input=false -no-color 2>&1 | Out-String)
            $contenderExit = $LASTEXITCODE
            if ($contenderExit -eq 0 -or $contenderOutput -notmatch 'Error acquiring the state lock|Error locking state') {
                throw 'Lock contention was not proven: the second process did not report a state-lock conflict.'
            }
        }
        finally {
            $holder.Refresh()
            if (-not $holder.HasExited) {
                Wait-Process -Id $holder.Id -Timeout 60 -ErrorAction Stop
            }
        }
        $holder.Refresh()
        if ($holder.ExitCode -ne 0) {
            throw 'The lock holder failed; inspect the ignored lock-holder logs.'
        }
        Write-Host 'PASS: A concurrent OpenTofu plan was rejected while the first process held the Spaces state lock.'
        Remove-Item -LiteralPath $marker -ErrorAction SilentlyContinue
    }
    Write-Host 'No DigitalOcean infrastructure was created. Version recovery remains a separate test.'
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
