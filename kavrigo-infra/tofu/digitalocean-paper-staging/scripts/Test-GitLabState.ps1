#requires -Version 5.1
# Writes only a disposable terraform_data marker to the dedicated GitLab state project.
param(
    [ValidatePattern('^[0-9]+$')]
    [string]$ProjectId = '87561856',
    [switch]$TestLock
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$tofu = Join-Path $root '.local\opentofu\bin\tofu.exe'
if (-not (Test-Path -LiteralPath $tofu)) {
    $tofu = (Get-Command tofu -ErrorAction Stop).Source
}

$scratch = Join-Path $root '.local\gitlab-state-preflight'
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$configuration = @'
terraform {
  required_version = ">= 1.12.0, < 2.0.0"
  backend "http" {}

  encryption {
    state { enforced = true }
    plan { enforced = true }
  }
}

resource "terraform_data" "preflight" {
  input = "kavrigo-gitlab-state-preflight-v1"
}
'@
[System.IO.File]::WriteAllText((Join-Path $scratch 'main.tf'), $configuration, [System.Text.UTF8Encoding]::new($false))

if ($TestLock) {
    # Keep a second, independently initialized checkout of the same disposable state.
    $contender = Join-Path $root '.local\gitlab-state-preflight-contender'
    New-Item -ItemType Directory -Force -Path $contender | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $contender 'main.tf'), $configuration, [System.Text.UTF8Encoding]::new($false))
}

$address = "https://gitlab.com/api/v4/projects/$ProjectId/terraform/state/preflight-kavrigo-v1"
$names = @(
    'TF_HTTP_ADDRESS', 'TF_HTTP_LOCK_ADDRESS', 'TF_HTTP_UNLOCK_ADDRESS',
    'TF_HTTP_LOCK_METHOD', 'TF_HTTP_UNLOCK_METHOD', 'TF_HTTP_USERNAME',
    'TF_HTTP_PASSWORD', 'TF_ENCRYPTION'
)
$prior = @{}
foreach ($name in $names) {
    $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

$secureToken = $null
$securePassphrase = $null
$locationPushed = $false
try {
    $secureToken = Read-Host 'GitLab personal access token (api scope)' -AsSecureString
    $securePassphrase = Read-Host 'State encryption passphrase from your password manager' -AsSecureString
    $token = [System.Net.NetworkCredential]::new('', $secureToken).Password
    $passphrase = [System.Net.NetworkCredential]::new('', $securePassphrase).Password
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'The GitLab token cannot be empty.'
    }
    if ($passphrase.Length -lt 32) {
        throw 'The state passphrase must contain at least 32 characters.'
    }

    $env:TF_HTTP_ADDRESS = $address
    $env:TF_HTTP_LOCK_ADDRESS = "$address/lock"
    $env:TF_HTTP_UNLOCK_ADDRESS = "$address/lock"
    $env:TF_HTTP_LOCK_METHOD = 'POST'
    $env:TF_HTTP_UNLOCK_METHOD = 'DELETE'
    $env:TF_HTTP_USERNAME = 'alizaraket600'
    $env:TF_HTTP_PASSWORD = $token
    $quotedPassphrase = ConvertTo-Json -InputObject $passphrase -Compress
    $env:TF_ENCRYPTION = @"
key_provider "pbkdf2" "gitlab_preflight" {
  passphrase = $quotedPassphrase
}
method "aes_gcm" "gitlab_preflight" {
  keys = key_provider.pbkdf2.gitlab_preflight
}
state {
  method = method.aes_gcm.gitlab_preflight
}
plan {
  method = method.aes_gcm.gitlab_preflight
}
"@
    $token = $null
    $passphrase = $null
    $quotedPassphrase = $null

    Push-Location $scratch
    $locationPushed = $true
    & $tofu init -reconfigure -input=false -no-color
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu backend initialization failed.' }
    & $tofu apply -auto-approve -input=false -no-color
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu disposable state write failed.' }
    $stateText = & $tofu state pull
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu disposable state read failed.' }
    $state = $stateText | ConvertFrom-Json
    if (-not ($state.resources | Where-Object { $_.type -eq 'terraform_data' -and $_.name -eq 'preflight' })) {
        throw 'The disposable state marker was not found after reading GitLab state.'
    }
    Write-Host 'PASS: Encrypted disposable state was written to and read from GitLab.'
    if ($TestLock) {
        Push-Location $contender
        try {
            & $tofu init -reconfigure -input=false -no-color
            if ($LASTEXITCODE -ne 0) { throw 'OpenTofu contender initialization failed.' }
        }
        finally { Pop-Location }

        # The marker is written only after the holder acquires the GitLab backend lock.
        $marker = Join-Path $scratch ("lock-held-$([guid]::NewGuid().ToString('N')).marker")
        $markerForPowerShell = $marker.Replace('\', '/')
        $holdCommand = "Set-Content -LiteralPath '$markerForPowerShell' -Value ready; Start-Sleep -Seconds 25"
        $holdCommandHcl = ConvertTo-Json -InputObject $holdCommand -Compress
        $lockConfiguration = @"
terraform {
  required_version = ">= 1.12.0, < 2.0.0"
  backend "http" {}

  encryption {
    state { enforced = true }
    plan { enforced = true }
  }
}

resource "terraform_data" "preflight" {
  input            = "kavrigo-gitlab-state-preflight-v1"
  triggers_replace = timestamp()

  provisioner "local-exec" {
    interpreter = ["powershell.exe", "-NoProfile", "-Command"]
    command     = $holdCommandHcl
  }
}
"@
        [System.IO.File]::WriteAllText((Join-Path $scratch 'main.tf'), $lockConfiguration, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText((Join-Path $contender 'main.tf'), $lockConfiguration, [System.Text.UTF8Encoding]::new($false))
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
            $contenderStdout = Join-Path $contender 'lock-contender.stdout.log'
            $contenderStderr = Join-Path $contender 'lock-contender.stderr.log'
            $blockedPlan = Start-Process -FilePath $tofu -ArgumentList @('plan', '-lock-timeout=0s', '-input=false', '-no-color') -WorkingDirectory $contender -WindowStyle Hidden -RedirectStandardOutput $contenderStdout -RedirectStandardError $contenderStderr -Wait -PassThru
            $contenderOutput = (Get-Content -LiteralPath $contenderStdout, $contenderStderr -Raw | Out-String)
            if ($blockedPlan.ExitCode -eq 0 -or $contenderOutput -notmatch 'Error acquiring the state lock|Error locking state') {
                throw 'Lock contention was not proven: the second process did not report a state-lock conflict.'
            }
        }
        finally {
            $holder.Refresh()
            if (-not $holder.WaitForExit(60000)) {
                throw 'The lock holder did not finish within 60 seconds; inspect the ignored lock-holder logs.'
            }
            $holder.WaitForExit()
        }
        $holder.Refresh()
        if ($holder.ExitCode -ne 0) {
            throw "The lock holder exited with code $($holder.ExitCode); inspect the ignored lock-holder logs."
        }
        $releasedStdout = Join-Path $contender 'post-release.stdout.log'
        $releasedStderr = Join-Path $contender 'post-release.stderr.log'
        $releasedPlan = Start-Process -FilePath $tofu -ArgumentList @('plan', '-input=false', '-no-color') -WorkingDirectory $contender -WindowStyle Hidden -RedirectStandardOutput $releasedStdout -RedirectStandardError $releasedStderr -Wait -PassThru
        if ($releasedPlan.ExitCode -ne 0) {
            throw 'The contender could not plan after the holder released the lock; inspect the ignored post-release logs.'
        }
        Write-Host 'PASS: A concurrent plan was rejected while the first process held the GitLab state lock.'
        Write-Host 'PASS: The first process released the lock and a later plan succeeded.'
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
    if ($secureToken) { $secureToken.Dispose() }
    if ($securePassphrase) { $securePassphrase.Dispose() }
    $token = $null
    $passphrase = $null
    $quotedPassphrase = $null
    $stateText = $null
    $state = $null
}
