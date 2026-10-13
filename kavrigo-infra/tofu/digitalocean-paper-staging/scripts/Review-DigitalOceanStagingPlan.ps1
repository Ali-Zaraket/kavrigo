#requires -Version 5.1
# Reads the encrypted saved plan and prints a credential-free deployment summary.
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$workingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$tofu = Join-Path $root '.local\opentofu\bin\tofu.exe'
if (-not (Test-Path -LiteralPath $tofu)) {
    $tofu = (Get-Command tofu -ErrorAction Stop).Source
}
$planFile = Join-Path $root '.local\digitalocean-staging.tfplan'
if (-not (Test-Path -LiteralPath $planFile)) {
    throw 'The encrypted staging plan is missing. Run Plan-DigitalOceanStaging.ps1 first.'
}

$priorEncryption = [Environment]::GetEnvironmentVariable('TF_ENCRYPTION', 'Process')
$securePassphrase = $null
$passphrase = $null
$quotedPassphrase = $null
$locationPushed = $false
try {
    $securePassphrase = Read-Host 'State encryption passphrase from your password manager' -AsSecureString
    $passphrase = [System.Net.NetworkCredential]::new('', $securePassphrase).Password
    if ($passphrase.Length -lt 32) {
        throw 'The state encryption passphrase must contain at least 32 characters.'
    }
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
    $passphrase = $null
    $quotedPassphrase = $null

    Push-Location $workingDirectory
    $locationPushed = $true
    # Keep JSON in process memory: OpenTofu's JSON view can contain cleartext secrets.
    $planJson = (& $tofu show -json "-plan=$planFile" | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not read the encrypted plan. Check that the saved passphrase is the same one used to create it.'
    }
    $plan = $planJson | ConvertFrom-Json
    $planJson = $null

    $expected = @(
        'digitalocean_vpc.paper',
        'digitalocean_vpc_nat_gateway.paper',
        'digitalocean_container_registry.paper',
        'digitalocean_kubernetes_cluster.paper',
        'digitalocean_database_cluster.postgres',
        'digitalocean_database_firewall.postgres',
        'digitalocean_database_cluster.valkey',
        'digitalocean_database_firewall.valkey'
    )
    $changes = @($plan.resource_changes)
    $addresses = @($changes | ForEach-Object { $_.address })
    $unexpected = @($addresses | Where-Object { $_ -notin $expected })
    $missing = @($expected | Where-Object { $_ -notin $addresses })
    if ($unexpected.Count -gt 0 -or $missing.Count -gt 0 -or $changes.Count -ne $expected.Count) {
        throw "The plan differs from the expected eight-resource foundation. Unexpected: $($unexpected -join ', '); missing: $($missing -join ', '). Do not apply."
    }
    foreach ($change in $changes) {
        if ((@($change.change.actions) -join ',') -ne 'create') {
            throw "The plan contains an action other than create for $($change.address). Do not apply."
        }
    }

    $byAddress = @{}
    foreach ($change in $changes) { $byAddress[$change.address] = $change.change.after }
    $vpc = $byAddress['digitalocean_vpc.paper']
    $nat = $byAddress['digitalocean_vpc_nat_gateway.paper']
    $registry = $byAddress['digitalocean_container_registry.paper']
    $cluster = $byAddress['digitalocean_kubernetes_cluster.paper']
    $postgres = $byAddress['digitalocean_database_cluster.postgres']
    $valkey = $byAddress['digitalocean_database_cluster.valkey']
    $cidrs = @($cluster.control_plane_firewall[0].allowed_addresses)
    if ($vpc.region -ne 'ams3' -or $nat.region -ne 'ams3' -or
        $nat.type -ne 'PUBLIC' -or $nat.size -ne '1' -or
        $nat.vpcs[0].default_gateway -ne $true -or
        $registry.region -ne 'ams3' -or $registry.subscription_tier_slug -ne 'basic' -or
        $cluster.region -ne 'ams3' -or $cluster.version -notmatch '^1\.(3[6-9]|[4-9][0-9])\.' -or
        $cluster.isolated_workers -ne $true -or $cluster.ha -ne $true -or
        $cluster.node_pool[0].size -ne 's-2vcpu-4gb' -or $cluster.node_pool[0].node_count -ne 3 -or
        $cluster.control_plane_firewall[0].enabled -ne $true -or
        $cidrs.Count -ne 1 -or $cidrs[0] -notmatch '^(\d{1,3}\.){3}\d{1,3}/32$' -or
        $postgres.region -ne 'ams3' -or $postgres.engine -ne 'pg' -or
        $postgres.version -ne '18' -or $postgres.size -ne 'db-s-1vcpu-1gb' -or $postgres.node_count -ne 1 -or
        $valkey.region -ne 'ams3' -or $valkey.engine -ne 'valkey' -or
        $valkey.version -ne '8' -or $valkey.size -ne 'db-s-1vcpu-1gb' -or $valkey.node_count -ne 1 -or
        $byAddress['digitalocean_database_firewall.postgres'].rule[0].type -ne 'k8s' -or
        $byAddress['digitalocean_database_firewall.valkey'].rule[0].type -ne 'k8s') {
        throw 'A planned setting differs from the reviewed paper-staging defaults. Do not apply.'
    }

    Write-Host 'PASS: Encrypted plan matches the reviewed paper-staging foundation.'
    Write-Host 'Amsterdam: VPC; size-1 default NAT; Basic private registry.'
    Write-Host "DOKS: Kubernetes $($cluster.version); HA control plane; three isolated 2-vCPU/4-GiB workers."
    Write-Host 'Kubernetes API: firewall enabled for one operator IPv4 /32 (address withheld).'
    Write-Host 'Databases: single-node PostgreSQL 18 and Valkey 8; Kubernetes-only database firewalls.'
    Write-Host 'Plan: 8 to add, 0 to change, 0 to destroy.'
    Write-Host 'Estimated floor: about USD 187/month before transfer, storage and other services.'
    Write-Host 'No DigitalOcean resources were applied.'
}
finally {
    if ($locationPushed) { Pop-Location }
    if ($null -eq $priorEncryption) {
        Remove-Item Env:TF_ENCRYPTION -ErrorAction SilentlyContinue
    }
    else {
        $env:TF_ENCRYPTION = $priorEncryption
    }
    if ($securePassphrase) { $securePassphrase.Dispose() }
    $passphrase = $null
    $quotedPassphrase = $null
    $planJson = $null
    $plan = $null
}
