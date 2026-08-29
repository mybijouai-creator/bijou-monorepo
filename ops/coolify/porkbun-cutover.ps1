# porkbun-cutover.ps1 — Flip a DNS record (or a whole set) from the
# Fly.io value to the Coolify value via the Porkbun API.
#
# This is the destructive step in the cutover. See
# ops/coolify/PRODUCTION-CUTOVER-PLAN.md §3 step 6.
#
# Safety:
#   - The actual DNS mutation is gated behind -ConfirmCutover.
#     Without it, the script prints the plan and exits.
#   - The pre-cutover DNS state is snapshotted to
#     ops/coolify/dns-snapshot-<timestamp>.json so the operator can
#     roll back with -RollbackFromSnapshot.
#   - The API secret is read from the environment ($env:PORKBUN_SECRET_KEY)
#     and is never echoed. The secret sha256 is logged for audit.
#
# Porkbun API reference:
#   https://porkbun.com/api/json/v3/documentation

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Domain = 'mybijou.xyz',

    [Parameter(Mandatory = $false)]
    [string]$Subdomain = 'app',

    [Parameter(Mandatory = $false)]
    [string]$RecordType = 'CNAME',

    [Parameter(Mandatory = $false)]
    [string]$NewTarget = 'coolify-bijou.getbijou.xyz',

    [string]$PorkbunApiKey = $env:PORKBUN_API_KEY,
    [string]$PorkbunSecret = $env:PORKBUN_SECRET_KEY,

    # Multi-domain batch mode: pass an array of {domain, subdomain, type, target}
    # to update many records in one run. Each is gated by the same -ConfirmCutover.
    [Parameter(Mandatory = $false)]
    [hashtable[]]$Batch = @(),

    # Rollback: pass the path to a snapshot file to revert the change.
    [string]$RollbackFromSnapshot = '',

    # Safety gate
    [switch]$ConfirmCutover,

    # For testing — generate the snapshot + plan but don't talk to Porkbun
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$apiBase = 'https://porkbun.com/api/json/v3'

function Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    Write-Host "[$ts] [$Level] $Message"
}

function HashValue {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '<empty>' }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    return ([BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData($bytes)) -replace '-', '').ToLower()
}

function Get-PorkbunRecords {
    param([string]$Dom, [string]$Sub)
    $body = @{
        apikey    = $PorkbunApiKey
        secretapikey = $PorkbunSecret
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$apiBase/dns/retrieve/$Dom" `
        -Method POST -ContentType 'application/json' -Body $body -TimeoutSec 30
    if ($resp.status -ne 'SUCCESS') { throw "Porkbun retrieve failed: $($resp | ConvertTo-Json -Compress)" }
    $all = $resp.records
    if ($Sub) { $all = $all | Where-Object { $_.name -eq $Sub } }
    return $all
}

function Set-PorkbunRecord {
    param(
        [string]$Dom,
        [string]$Sub,
        [string]$Type,
        [string]$Content,
        [int]$Ttl = 300
    )
    $endpoint = if ($Sub) { "$apiBase/dns/edit/$Dom/$Type/$Sub" }
                else { "$apiBase/dns/edit/$Dom/$Type" }
    $body = @{
        apikey    = $PorkbunApiKey
        secretapikey = $PorkbunSecret
        content   = $Content
        ttl       = $Ttl
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri $endpoint -Method POST -ContentType 'application/json' -Body $body -TimeoutSec 30
    if ($resp.status -ne 'SUCCESS') { throw "Porkbun edit failed: $($resp | ConvertTo-Json -Compress)" }
    return $resp
}

function New-PorkbunRecord {
    param(
        [string]$Dom,
        [string]$Sub,
        [string]$Type,
        [string]$Content,
        [int]$Ttl = 300
    )
    $endpoint = if ($Sub) { "$apiBase/dns/create/$Dom/$Type/$Sub" }
                else { "$apiBase/dns/create/$Dom/$Type" }
    $body = @{
        apikey    = $PorkbunApiKey
        secretapikey = $PorkbunSecret
        content   = $Content
        ttl       = $Ttl
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri $endpoint -Method POST -ContentType 'application/json' -Body $body -TimeoutSec 30
    if ($resp.status -ne 'SUCCESS') { throw "Porkbun create failed: $($resp | ConvertTo-Json -Compress)" }
    return $resp
}

# ─── Build the plan ───────────────────────────────────────────────────
$plan = @()
if ($Batch.Count -gt 0) {
    foreach ($item in $Batch) {
        $plan += @{
            Domain    = $item.Domain
            Subdomain = $item.Subdomain
            Type      = if ($item.Type) { $item.Type } else { 'CNAME' }
            Target    = $item.Target
        }
    }
} else {
    $plan += @{
        Domain    = $Domain
        Subdomain = $Subdomain
        Type      = $RecordType
        Target    = $NewTarget
    }
}

Log "porkbun-cutover.ps1 — DNS plan:"
foreach ($p in $plan) {
    Log "  $($p.Domain)  $($p.Subdomain)  $($p.Type)  →  $($p.Target)"
}

# ─── Rollback path ────────────────────────────────────────────────────
if ($RollbackFromSnapshot) {
    if (-not (Test-Path $RollbackFromSnapshot)) {
        throw "Snapshot not found: $RollbackFromSnapshot"
    }
    $snap = Get-Content $RollbackFromSnapshot -Raw | ConvertFrom-Json
    if (-not $ConfirmCutover) {
        Log "Rollback planned (NOT executed — pass -ConfirmCutover):" 'WARN'
        $snap | ForEach-Object {
            Log "  $($_.domain) $($_.sub) $($_.type) → $($_.content) (ttl=$($_.ttl))"
        }
        return
    }
    if (-not $PorkbunApiKey -or -not $PorkbunSecret) {
        throw "Rollback requires PORKBUN_API_KEY and PORKBUN_SECRET_KEY in env."
    }
    Log "Rolling back from $RollbackFromSnapshot…"
    foreach ($r in $snap) {
        if ($r.record_id) {
            Set-PorkbunRecord -Dom $r.domain -Sub $r.sub -Type $r.type -Content $r.content -Ttl $r.ttl
            Log "  Restored $($r.domain) $($r.sub) $($r.type) → $($r.content)"
        } else {
            New-PorkbunRecord -Dom $r.domain -Sub $r.sub -Type $r.type -Content $r.content -Ttl $r.ttl
            Log "  Recreated $($r.domain) $($r.sub) $($r.type) → $($r.content)"
        }
    }
    Log "Rollback complete."
    return
}

# ─── Forward path: snapshot + plan ────────────────────────────────────
if (-not $PorkbunApiKey -or -not $PorkbunSecret) {
    if (-not $DryRun) {
        throw "PORKBUN_API_KEY and PORKBUN_SECRET_KEY must be set in env (or pass -DryRun to plan only)."
    } else {
        Log "DryRun: would have queried Porkbun, skipping auth check." 'WARN'
    }
} else {
    Log "Porkbun secret sha256: $(HashValue $PorkbunSecret)"
}

$snapshotPath = Join-Path $PSScriptRoot ("dns-snapshot-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$snapshot = @()

foreach ($p in $plan) {
    if ($DryRun) {
        Log "DryRun: would query $($p.Domain) $($p.Subdomain)"
        continue
    }
    $existing = Get-PorkbunRecords -Dom $p.Domain -Sub $p.Subdomain
    foreach ($r in $existing) {
        $snapshot += @{
            domain    = $p.Domain
            sub       = $r.name
            type      = $r.type
            content   = $r.content
            ttl       = $r.ttl
            record_id = $r.id
        }
    }
}

if ($snapshot.Count -gt 0 -and -not $DryRun) {
    $snapshot | ConvertTo-Json -Depth 5 | Set-Content -Path $snapshotPath -Encoding UTF8
    Log "Pre-cutover snapshot: $snapshotPath"
    Log "Snapshot has $($snapshot.Count) records."
} else {
    Log "No pre-cutover records found for these subdomains (nothing to back up)."
}

if (-not $ConfirmCutover) {
    Log ""
    Log "This was a DRY PLAN. Re-run with -ConfirmCutover to apply." 'WARN'
    Log "Or to test the path end-to-end, use -DryRun (no mutation, no Porkbun call)." 'WARN'
    return
}

# ─── Apply the cutover ────────────────────────────────────────────────
if ($DryRun) {
    Log "DryRun: would apply $($plan.Count) record updates." 'WARN'
    return
}

foreach ($p in $plan) {
    $existing = Get-PorkbunRecords -Dom $p.Domain -Sub $p.Subdomain
    $target = ($existing | Where-Object { $_.type -eq $p.Type }) | Select-Object -First 1
    if ($target) {
        Set-PorkbunRecord -Dom $p.Domain -Sub $p.Subdomain -Type $p.Type -Content $p.Target -Ttl 300
        Log "  Updated $($p.Domain)/$($p.Subdomain) $($p.Type) → $($p.Target)"
    } else {
        New-PorkbunRecord -Dom $p.Domain -Sub $p.Subdomain -Type $p.Type -Content $p.Target -Ttl 300
        Log "  Created $($p.Domain)/$($p.Subdomain) $($p.Type) → $($p.Target)"
    }
}

Log ""
Log "Cutover applied. To roll back:"
Log "  .\ops\coolify\porkbun-cutover.ps1 -RollbackFromSnapshot '$snapshotPath' -ConfirmCutover"
Log ""
Log "Polling for DNS propagation (up to 10 min, expects ~5 min with TTL=300)…"

$start = Get-Date
$healthUrl = "https://$($plan[0].Subdomain).$($plan[0].Domain)/health"
$expectedService = $null
$ok = $false
while (((Get-Date) - $start).TotalMinutes -lt 10) {
    Start-Sleep -Seconds 30
    try {
        $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 15
        $svc = $resp.service
        if ($resp.status -eq 'healthy' -and $svc -like 'bijou-ai-enterprise*') {
            $expectedService = $svc
            $ok = $true
            break
        }
    } catch {
        # DNS not propagated yet, or service not up — keep polling
    }
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 0)
    Log "  ...${elapsed}s elapsed, $healthUrl not yet returning 200 from the Coolify stack"
}

if ($ok) {
    Log "DNS propagated. $healthUrl → $expectedService" 'INFO'
} else {
    Log "DNS did not propagate within 10 min. Check Porkbun UI manually." 'ERROR'
}
