#requires -Version 5.1
# Writes only a disposable terraform_data marker to the dedicated GitLab state project.
param(
    [ValidatePattern('^[0-9]+$')]
    [string]$ProjectId = '87561856',
    [switch]$TestLock,
    [switch]$TestRecovery
)

$ErrorActionPreference = 'Stop'
if ($TestLock -and $TestRecovery) {
    throw 'Run lock and recovery tests separately.'
}

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
$oldStatePath = $null
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
    if (-not $TestRecovery) {
        & $tofu apply -auto-approve -input=false -no-color
        if ($LASTEXITCODE -ne 0) { throw 'OpenTofu disposable state write failed.' }
    }
    $stateText = & $tofu state pull
    if ($LASTEXITCODE -ne 0) { throw 'OpenTofu disposable state read failed.' }
    $state = $stateText | ConvertFrom-Json
    if (-not ($state.resources | Where-Object { $_.type -eq 'terraform_data' -and $_.name -eq 'preflight' })) {
        throw 'The disposable state marker was not found after reading GitLab state.'
    }
    if ($TestRecovery) {
        Write-Host 'PASS: Existing encrypted disposable state was read from GitLab.'
    }
    else {
        Write-Host 'PASS: Encrypted disposable state was written to and read from GitLab.'
    }
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
        # Windows PowerShell 5.1 returns a null ExitCode for a background
        # Start-Process -PassThru even after WaitForExit(). Confirm OpenTofu's
        # completion record here, then require a successful fresh plan below.
        $holderOutput = Get-Content -LiteralPath $stdout -Raw
        if ($holderOutput -notmatch '(?m)^Apply complete! Resources:') {
            throw 'The lock holder did not report a completed apply; inspect the ignored lock-holder logs.'
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
    if ($TestRecovery) {
        $currentSerial = [int]$state.serial
        if ($currentSerial -lt 2) {
            throw 'At least two disposable state versions are needed for recovery testing.'
        }
        $oldSerial = $currentSerial - 1
        $recoverySource = Join-Path $root '.local\gitlab-state-recovery-source'
        $recoveryTarget = Join-Path $root '.local\gitlab-state-recovery-target'
        New-Item -ItemType Directory -Force -Path $recoverySource, $recoveryTarget | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $recoverySource 'main.tf'), $configuration, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText((Join-Path $recoveryTarget 'main.tf'), $configuration, [System.Text.UTF8Encoding]::new($false))

        # Read GitLab's older version through OpenTofu so client-side encryption
        # is decrypted by the normal configuration, never by the GitLab API.
        $env:TF_HTTP_ADDRESS = "$address/versions/$oldSerial"
        Push-Location $recoverySource
        try {
            & $tofu init -reconfigure -input=false -no-color
            if ($LASTEXITCODE -ne 0) { throw 'Could not initialize the historical GitLab state version.' }
            $oldStateText = & $tofu state pull
            if ($LASTEXITCODE -ne 0) { throw 'Could not read the historical GitLab state version.' }
        }
        finally { Pop-Location }
        $oldState = $oldStateText | ConvertFrom-Json
        $oldMarker = $oldState.resources | Where-Object { $_.type -eq 'terraform_data' -and $_.name -eq 'preflight' } | Select-Object -First 1
        if ([int]$oldState.serial -ne $oldSerial -or -not $oldMarker) {
            throw 'The historical state version did not contain the expected disposable marker.'
        }
        $oldStatePath = Join-Path $root '.local\gitlab-state-recovery-older.tfstate'
        [System.IO.File]::WriteAllText($oldStatePath, ($oldStateText -join "`n"), [System.Text.UTF8Encoding]::new($false))

        # Restore into a new disposable name. Never overwrite the original.
        $recoveryName = "preflight-kavrigo-recovery-$([guid]::NewGuid().ToString('N'))"
        $recoveryAddress = "https://gitlab.com/api/v4/projects/$ProjectId/terraform/state/$recoveryName"
        Write-Host "Restoring historical version $oldSerial into disposable state $recoveryName."
        $env:TF_HTTP_ADDRESS = $recoveryAddress
        $env:TF_HTTP_LOCK_ADDRESS = "$recoveryAddress/lock"
        $env:TF_HTTP_UNLOCK_ADDRESS = "$recoveryAddress/lock"
        Push-Location $recoveryTarget
        try {
            & $tofu init -reconfigure -input=false -no-color
            if ($LASTEXITCODE -ne 0) { throw 'Could not initialize the disposable recovery state.' }
            & $tofu state push -lock-timeout=0s $oldStatePath
            if ($LASTEXITCODE -ne 0) { throw 'Could not restore the older version into a new disposable state.' }
            $restoredText = & $tofu state pull
            if ($LASTEXITCODE -ne 0) { throw 'Could not read the restored disposable state.' }
        }
        finally { Pop-Location }
        $restored = $restoredText | ConvertFrom-Json
        $restoredMarker = $restored.resources | Where-Object { $_.type -eq 'terraform_data' -and $_.name -eq 'preflight' } | Select-Object -First 1
        # A fresh state name may assign its own lineage and serial. Compare
        # the marker's identity and values, since state serialization metadata
        # can differ after a push and pull through another backend state name.
        $singleResource = @($oldState.resources).Count -eq 1 -and
            @($restored.resources).Count -eq 1
        $singleInstance = [bool]$restoredMarker -and
            @($oldMarker.instances).Count -eq 1 -and
            @($restoredMarker.instances).Count -eq 1
        $idMatches = $singleInstance -and
            $restoredMarker.instances[0].attributes.id -ceq $oldMarker.instances[0].attributes.id
        $inputMatches = $singleInstance -and
            (($restoredMarker.instances[0].attributes.input | ConvertTo-Json -Depth 32 -Compress) -ceq
                ($oldMarker.instances[0].attributes.input | ConvertTo-Json -Depth 32 -Compress))
        $outputMatches = $singleInstance -and
            (($restoredMarker.instances[0].attributes.output | ConvertTo-Json -Depth 32 -Compress) -ceq
                ($oldMarker.instances[0].attributes.output | ConvertTo-Json -Depth 32 -Compress))
        if (-not ($singleResource -and $singleInstance -and $idMatches -and $inputMatches -and $outputMatches)) {
            throw "The restored disposable marker does not match historical version $oldSerial (one resource: $singleResource; one marker instance: $singleInstance; id: $idMatches; input: $inputMatches; output: $outputMatches)."
        }
        Write-Host "PASS: Historical version $oldSerial was retrieved and restored to separate disposable state $recoveryName."
        Write-Host 'The separate state has its own lineage and serial history.'
        Write-Host 'The original preflight state was not overwritten.'
    }
    if ($TestRecovery) {
        Write-Host 'No DigitalOcean infrastructure was created.'
    }
    else {
        Write-Host 'No DigitalOcean infrastructure was created. Version recovery remains a separate test.'
    }
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
    if ($oldStatePath -and (Test-Path -LiteralPath $oldStatePath)) {
        Remove-Item -LiteralPath $oldStatePath -ErrorAction SilentlyContinue
    }
    $oldStateText = $null
    $oldState = $null
    $restoredText = $null
    $restored = $null
}
