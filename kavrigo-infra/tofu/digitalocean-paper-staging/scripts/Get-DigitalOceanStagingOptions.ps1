#requires -Version 5.1
# Read-only lookup of current DOKS options; never stores the API token.
$ErrorActionPreference = 'Stop'

$secureToken = $null
$token = $null
try {
    $secureToken = Read-Host 'DigitalOcean Read Only API token' -AsSecureString
    $token = [System.Net.NetworkCredential]::new('', $secureToken).Password
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'The DigitalOcean token cannot be empty.'
    }

    try {
        $response = Invoke-RestMethod -Method Get `
            -Uri 'https://api.digitalocean.com/v2/kubernetes/options' `
            -Headers @{ Authorization = "Bearer $token" } `
            -TimeoutSec 30
    }
    catch {
        throw 'Could not read DigitalOcean Kubernetes options. Check token expiry, Read Only scope, team, and network access.'
    }

    $regions = @($response.options.regions | ForEach-Object { $_.slug })
    $sizes = @($response.options.sizes | ForEach-Object { $_.slug })
    $versions = @($response.options.versions | ForEach-Object { $_.slug } |
        Where-Object { $_ -match '^1\.(3[6-9]|[4-9][0-9])\.' })

    Write-Host "Amsterdam (ams3) listed for DOKS: $('ams3' -in $regions)"
    Write-Host "Planned worker size (s-2vcpu-4gb) listed: $('s-2vcpu-4gb' -in $sizes)"
    if ($versions.Count -eq 0) {
        throw 'No Kubernetes 1.36+ version was returned; isolated-worker staging cannot be planned yet.'
    }
    Write-Host 'Available Kubernetes 1.36+ version slugs:'
    $versions | ForEach-Object { Write-Host "  $_" }
    Write-Host 'This lookup did not create or change DigitalOcean resources.'
}
finally {
    $token = $null
    if ($secureToken) { $secureToken.Dispose() }
}
