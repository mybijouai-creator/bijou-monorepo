<#
.SYNOPSIS
    Fixes the Coolify helper "spawn EPERM" bug on /var/run/docker.sock
    and verifies Coolify is healthy again.

.DESCRIPTION
    The Coolify helper container runs in a sandbox where /var/run/docker.sock
    gets mounted with restrictive perms after a host reboot or helper restart.
    Symptoms:
      - Coolify API returns 200 but POST /services/{uuid}/start queues forever
      - Coolify UI shows service as "exited" even though the container is healthy
      - Logs show: "spawn EPERM" on docker.sock

    The fix:
      1. SSH to the Coolify host (169.58.147.169)
      2. chmod 666 /var/run/docker.sock
      3. docker restart coolify-helper
      4. Wait ~30s for the helper to reconnect
      5. Probe Coolify's /api/v1/version and a known service to confirm health

.PARAMETER Host
    The Coolify host. Defaults to 169.58.147.169.

.PARAMETER Port
    SSH port. Defaults to 22.

.PARAMETER User
    SSH user. Defaults to root.

.PARAMETER CoolifyBaseUrl
    Coolify public URL. Defaults to https://coolify.getbijou.xyz.

.PARAMETER ApiToken
    Coolify API token. If not provided, reads COOLIFY_API_TOKEN from .env at repo root.

.PARAMETER BackendSvcUuid
    Backend service UUID (for the post-fix smoke test). If not provided,
    reads BIJOU_BACKEND_SVC_UUID from .env.

.PARAMETER ProbeHealthUrl
    Public health URL to verify after the restart. Defaults to https://app.mybijou.xyz/health.

.EXAMPLE
    .\ops\coolify\fix-coolify-helper-eperm.ps1

.NOTES
    Requires:
      - An SSH key that the Coolify host accepts (in ssh-agent)
      - Network access to 169.58.147.169:22
      - Network access to https://coolify.getbijou.xyz
      - Network access to https://app.mybijou.xyz (for the health probe)
#>

[CmdletBinding()]
param(
    [string]$HostName = '169.58.147.169',
    [int]$Port = 22,
    [string]$User = 'root',
    [string]$CoolifyBaseUrl = 'https://coolify.getbijou.xyz',
    [string]$ApiToken,
    [string]$BackendSvcUuid,
    [string]$ProbeHealthUrl = 'https://app.mybijou.xyz/health',
    [int]$HelperWaitSeconds = 30,
    [switch]$SkipApiCheck,
    [switch]$SkipServiceStart,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = 'Stop'

# --- helpers ----------------------------------------------------------------

function Read-EnvValue {
    param([string]$Key)
    if (-not (Test-Path .env)) { return $null }
    $line = Select-String -Path .env -Pattern ("^$Key=(.+)$") | Select-Object -First 1
    if ($line) { return $line.Matches.Groups[1].Value.Trim() }
    return $null
}

function Write-Step {
    param([string]$Message, [string]$Color = 'Cyan')
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor $Color
}

function Write-OK { param([string]$Message) Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "  [ERR]  $Message" -ForegroundColor Red }

# --- preflight --------------------------------------------------------------

Write-Step "Bijou Coolify helper EPERM fix" 'Magenta'
Write-Host "  Host:           $User@$HostName`:$Port"
Write-Host "  Coolify API:    $CoolifyBaseUrl"
Write-Host "  Health probe:   $ProbeHealthUrl"

if (-not $ApiToken) { $ApiToken = Read-EnvValue 'COOLIFY_API_TOKEN' }
if (-not $BackendSvcUuid) { $BackendSvcUuid = Read-EnvValue 'BIJOU_BACKEND_SVC_UUID' }

if (-not $ApiToken) {
    Write-Err "No API token. Set COOLIFY_API_TOKEN in .env or pass -ApiToken."
    exit 1
}

# Check ssh-agent for any keys
$sshAgentKeys = & ssh-add -l 2>$null
if ($LASTEXITCODE -ne 0 -or -not $sshAgentKeys) {
    Write-Warn "ssh-agent has no keys loaded. If SSH fails, run:  ssh-add C:\path\to\key"
} else {
    $keyCount = ($sshAgentKeys | Measure-Object).Count
    Write-Host "  ssh-agent has $keyCount key(s) loaded"
}

# --- step 1: SSH + chmod docker.sock ---------------------------------------

Write-Step "Step 1: chmod /var/run/docker.sock on host" 'Cyan'

$sshTarget = "$User@$HostName"
$sshOpts = @(
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ConnectTimeout=10',
    '-p', $Port
)

Write-Host "  $ ssh $sshTarget -- sudo chmod 666 /var/run/docker.sock"
try {
    $permOut = & ssh @sshOpts $sshTarget -- 'ls -l /var/run/docker.sock; sudo chmod 666 /var/run/docker.sock; ls -l /var/run/docker.sock' 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "SSH failed (exit $LASTEXITCODE):"
        $permOut | ForEach-Object { Write-Host "    $_" }
        exit $LASTEXITCODE
    }
    $permOut | ForEach-Object { Write-Host "    $_" }
    Write-OK "docker.sock permission updated"
} catch {
    Write-Err "SSH command threw: $($_.Exception.Message)"
    exit 1
}

# --- step 2: restart coolify-helper -----------------------------------------

Write-Step "Step 2: docker restart coolify-helper" 'Cyan'

try {
    $restartOut = & ssh @sshOpts $sshTarget -- 'docker ps --filter name=coolify-helper --format "{{.Names}} {{.Status}}"; echo ---; docker restart coolify-helper; echo ---; sleep 2; docker ps --filter name=coolify-helper --format "{{.Names}} {{.Status}}"' 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker restart failed (exit $LASTEXITCODE):"
        $restartOut | ForEach-Object { Write-Host "    $_" }
        exit $LASTEXITCODE
    }
    $restartOut | ForEach-Object { Write-Host "    $_" }
    Write-OK "coolify-helper restart initiated"
} catch {
    Write-Err "SSH command threw: $($_.Exception.Message)"
    exit 1
}

# --- step 3: wait for helper to come back up --------------------------------

Write-Step "Step 3: wait $HelperWaitSeconds`s for the helper to reconnect" 'Cyan'

for ($i = 1; $i -le $HelperWaitSeconds; $i++) {
    Write-Host -NoNewline ("`r  {0,2}s elapsed" -f $i)
    Start-Sleep -Seconds 1
}
Write-Host ""

# --- step 4: probe Coolify API ----------------------------------------------

if (-not $SkipApiCheck) {
    Write-Step "Step 4: probe Coolify API" 'Cyan'
    try {
        $ver = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/version" -Headers @{Authorization = "Bearer $ApiToken"} -TimeoutSec 10
        Write-OK "Coolify API responsive, version $ver"
    } catch {
        Write-Err "Coolify API still not responding: $($_.Exception.Message)"
        Write-Host "    The helper may need more time. Wait 30s and re-run."
        exit 1
    }
}

# --- step 5: try starting the backend service (optional) --------------------

if (-not $SkipServiceStart -and $BackendSvcUuid) {
    Write-Step "Step 5: try POST /services/$BackendSvcUuid/start" 'Cyan'
    try {
        $startResp = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/services/$BackendSvcUuid/start" -Headers @{Authorization = "Bearer $ApiToken"} -Method POST -TimeoutSec 30
        Write-Host "    $($startResp | ConvertTo-Json -Depth 3)"
        Write-OK "start queued"
    } catch {
        Write-Warn "Start returned $($_.Exception.Response.StatusCode.value__): $($_.Exception.Message)"
    }
}

# --- step 6: probe /health (optional) ---------------------------------------

if (-not $SkipHealthCheck) {
    Write-Step "Step 6: probe $ProbeHealthUrl" 'Cyan'
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $ProbeHealthUrl -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) {
                Write-OK "$ProbeHealthUrl -> $($r.StatusCode) (healthy)"
                Write-Host ""
                Write-Step "EPERM fix complete" 'Green'
                exit 0
            }
        } catch {
            # not yet — keep polling
        }
        Start-Sleep -Seconds 3
    }
    Write-Warn "$ProbeHealthUrl did not return 200 within 60s. May still be starting."
}

Write-Step "Done" 'Green'
