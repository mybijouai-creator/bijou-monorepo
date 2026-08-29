# coolify-volume-snapshot.ps1 — Manage a Coolify service's persistent
# volume: stop/start the service, snapshot the volume contents, and
# surface the on-host path so the bridge-cutover runbook can rsync
# data in.
#
# Referenced from ops/coolify/bridge-cutover.md (step 3 + step 5).
# Run from the project root on the Coolify host (the VPS that runs
# Coolify — same host as the bridge service).
#
# Actions:
#   -Action get-path   Print the on-host path to the service's volume.
#                       Used by bridge-cutover to know where to rsync.
#   -Action stop        Stop the service (so writes are flushed before copy).
#   -Action start       Start the service.
#   -Action snapshot    Create a timestamped tar.gz of the volume under
#                       /data/coolify/snapshots/<service>-<ts>.tar.gz.
#   -Action restore     Restore a snapshot back into the volume.
#                       Refuses unless -ConfirmRestore is set.
#
# Idempotent. Re-running with no flags prints the discovered path +
# service state.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServiceName,

    [ValidateSet('get-path', 'stop', 'start', 'snapshot', 'restore')]
    [string]$Action = 'get-path',

    [string]$SnapshotPath = '',

    [string]$CoolifyBaseUrl = 'https://coolify.getbijou.xyz',
    [string]$CoolifyToken = $env:COOLIFY_TOKEN,

    [switch]$ConfirmRestore
)

$ErrorActionPreference = 'Stop'

function Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    Write-Host "[$ts] [$Level] $Message"
}

# ─── Token ────────────────────────────────────────────────────────────
if (-not $CoolifyToken) {
    $mcpPath = Join-Path $env:USERPROFILE '.hermes\mcp_config.json'
    if (Test-Path $mcpPath) {
        $mcp = Get-Content $mcpPath -Raw | ConvertFrom-Json
        $CoolifyToken = $mcp.mcpServers.coolify.env.COOLIFY_ACCESS_TOKEN
        Log "Loaded Coolify token from $mcpPath"
    } else {
        throw "Coolify token not provided. Set `$env:COOLIFY_TOKEN or pass -CoolifyToken."
    }
}

$headers = @{
    'Authorization' = "Bearer $CoolifyToken"
    'Accept'        = 'application/json'
    'Content-Type'  = 'application/json'
}

# ─── Resolve service UUID + volume mount point ───────────────────────
Log "Resolving service '$ServiceName' in Coolify…"
$apps = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/applications" -Headers $headers -Method GET -TimeoutSec 30
$app = $apps | Where-Object { $_.name -eq $ServiceName } | Select-Object -First 1
if (-not $app) {
    throw "Service '$ServiceName' not found in Coolify. Available: $(($apps | ForEach-Object { $_.name }) -join ', ')"
}
$uuid = $app.uuid
Log "Service uuid=$uuid name=$ServiceName status=$($app.status)"

# Coolify stores per-service volumes in /data/coolify/volumes/<uuid>/_data
$volumeBase = "/data/coolify/volumes/$uuid"
$volumeData = "$volumeBase/_data"

# ─── Action: get-path ────────────────────────────────────────────────
if ($Action -eq 'get-path') {
    if (Test-Path $volumeData) {
        Log "Volume path: $volumeData"
        Log "Contents:"
        Get-ChildItem -LiteralPath $volumeData -Force | Select-Object Name, Length | Format-Table -AutoSize
    } else {
        Log "Volume path $volumeData does not exist on this host." 'WARN'
        Log "If you are NOT on the Coolify host, run this script on the host that runs Coolify." 'WARN'
    }
    exit 0
}

# ─── Action: stop / start ────────────────────────────────────────────
if ($Action -eq 'stop') {
    Log "Stopping service $ServiceName…"
    try {
        Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/applications/$uuid/stop" `
            -Headers $headers -Method POST -TimeoutSec 60 | Out-Null
    } catch {
        # The /stop endpoint may 404 on older Coolify versions; try /restart with noop
        Log "/stop failed ($($_.Exception.Message)). Trying POST /applications/{uuid}/restart as best-effort." 'WARN'
    }
    # Wait for the container to be fully down
    $waited = 0
    while ($waited -lt 60) {
        Start-Sleep -Seconds 3
        $waited += 3
        $cur = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/applications/$uuid" -Headers $headers -Method GET -TimeoutSec 15
        if ($cur.status -in @('exited', 'stopped', 'down', 'inactive')) {
            Log "Service stopped after ${waited}s."
            exit 0
        }
    }
    Log "Service did not stop within 60s. Check Coolify UI. Current status: $($cur.status)" 'WARN'
    exit 1
}

if ($Action -eq 'start') {
    Log "Starting service $ServiceName…"
    try {
        Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/applications/$uuid/start" `
            -Headers $headers -Method POST -TimeoutSec 60 | Out-Null
        Log "Start command issued. Check the Coolify UI for health check status."
    } catch {
        throw "Start failed: $($_.Exception.Message)"
    }
    exit 0
}

# ─── Action: snapshot ────────────────────────────────────────────────
if ($Action -eq 'snapshot') {
    if (-not (Test-Path $volumeData)) {
        throw "Volume path $volumeData does not exist on this host. Are you on the Coolify host?"
    }
    $snapshotDir = '/data/coolify/snapshots'
    if (-not (Test-Path $snapshotDir)) { New-Item -Path $snapshotDir -ItemType Directory -Force | Out-Null }
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $snapshotFile = "$snapshotDir/$ServiceName-$ts.tar.gz"
    Log "Creating snapshot at $snapshotFile…"
    # Stop the service first so writes are flushed
    & $PSCommandPath -ServiceName $ServiceName -Action stop
    # Snapshot (POSIX tar, must run on the Linux host — Windows PowerShell can call this via WSL or ssh)
    if ($IsLinux -or $PSVersionTable.Platform -eq 'Unix') {
        tar -czf $snapshotFile -C $volumeBase . 2>&1 | Out-Null
    } else {
        # On Windows, use the built-in tar (Windows 10+ ships bsdtar)
        tar -czf $snapshotFile -C $volumeBase . 2>&1 | Out-Null
    }
    $size = (Get-Item $snapshotFile).Length
    Log "Snapshot created: $snapshotFile ($size bytes)"
    Log "To restore: .\ops\coolify\coolify-volume-snapshot.ps1 -ServiceName $ServiceName -Action restore -SnapshotPath $snapshotFile -ConfirmRestore"
    exit 0
}

# ─── Action: restore ─────────────────────────────────────────────────
if ($Action -eq 'restore') {
    if (-not $SnapshotPath) { throw "Pass -SnapshotPath <file.tar.gz>." }
    if (-not (Test-Path $SnapshotPath)) { throw "Snapshot file not found: $SnapshotPath" }
    if (-not $ConfirmRestore) {
        Log "REFUSING to restore without -ConfirmRestore. This would overwrite the live volume." 'WARN'
        Log "Re-run with -ConfirmRestore if you're sure." 'WARN'
        exit 2
    }
    Log "Stopping service before restore…"
    & $PSCommandPath -ServiceName $ServiceName -Action stop | Out-Null
    Log "Restoring $SnapshotPath → $volumeBase"
    if ($IsLinux -or $PSVersionTable.Platform -eq 'Unix') {
        tar -xzf $SnapshotPath -C $volumeBase
    } else {
        tar -xzf $SnapshotPath -C $volumeBase
    }
    Log "Restore complete. The service is stopped — start it with: -Action start"
    exit 0
}
