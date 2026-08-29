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

.PARAMETER HostName
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

.PARAMETER AgentopsSvcUuid
    Agentops service UUID (for the post-fix smoke test). If not provided,
    reads AGENTOPS_SVC_UUID from .env.

.PARAMETER ProbeHealthUrl
    Public health URL to verify after the restart. Defaults to https://app.mybijou.xyz/health.

.PARAMETER ProbeAgentopsUrl
    Agentops public health URL to verify after the restart. Defaults to https://agentops.getbijou.xyz/health.

.PARAMETER HelperWaitSeconds
    Seconds to wait for coolify-helper to reconnect. Defaults to 30.

.PARAMETER HealthTimeoutSeconds
    Seconds to poll /health before giving up. Defaults to 60.

.PARAMETER DryRun
    Print the SSH commands that would be run, but do not execute them.
    Useful for first-time validation.

.PARAMETER SkipApiCheck
    Skip step 4 (Coolify API version probe).

.PARAMETER SkipServiceStart
    Skip step 5 (POST /services/{uuid}/start).

.PARAMETER SkipHealthCheck
    Skip step 6 (poll /health endpoints).

.EXAMPLE
    .\ops\coolify\fix-coolify-helper-eperm.ps1

.EXAMPLE
    .\ops\coolify\fix-coolify-helper-eperm.ps1 -DryRun -Verbose

.EXAMPLE
    .\ops\coolify\fix-coolify-helper-eperm.ps1 -HelperWaitSeconds 60 -HealthTimeoutSeconds 180

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
    [ValidateRange(1, 65535)][int]$Port = 22,
    [string]$User = 'root',
    [string]$CoolifyBaseUrl = 'https://coolify.getbijou.xyz',
    [string]$ApiToken,
    [string]$BackendSvcUuid,
    [string]$AgentopsSvcUuid,
    [string]$ProbeHealthUrl = 'https://app.mybijou.xyz/health',
    [string]$ProbeAgentopsUrl = 'https://agentops.getbijou.xyz/health',
    [ValidateRange(1, 300)][int]$HelperWaitSeconds = 30,
    [ValidateRange(1, 600)][int]$HealthTimeoutSeconds = 60,
    [switch]$DryRun,
    [switch]$SkipApiCheck,
    [switch]$SkipServiceStart,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = 'Stop'

# --- helpers ----------------------------------------------------------------

function Read-EnvValue {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Key)
    if (-not (Test-Path .env)) { return $null }
    $line = Select-String -Path .env -Pattern ("^$Key=(.+)$") | Select-Object -First 1
    if ($line) { return $line.Matches.Groups[1].Value.Trim() }
    return $null
}

function Write-Step {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Message, [string]$Color = 'Cyan')
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor $Color
}

function Write-OK { param([Parameter(Mandatory)][string]$Message) Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Warn { param([Parameter(Mandatory)][string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Err { param([Parameter(Mandatory)][string]$Message) Write-Host "  [ERR]  $Message" -ForegroundColor Red }

function Invoke-Ssh {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string[]]$Opts,
        [Parameter(Mandatory)][string]$RemoteCommand
    )
    if ($DryRun) {
        Write-Host "    [DRY-RUN] ssh $($Opts -join ' ') $Target -- $RemoteCommand"
        return
    }
    & ssh @Opts $Target -- $RemoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "ssh command failed with exit code $LASTEXITCODE"
    }
}

function Get-SshAgentSummary {
    [CmdletBinding()]
    # Returns one of: 'no-agent', 'agent-no-keys', 'agent-with-keys', plus a
    # human-readable description. Distinguishing 'no-agent' from 'agent-no-keys'
    # matters because the latter can still succeed if the SSH key is loaded
    # by some other means (e.g. Windows SSH agent forwarding).
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & ssh-add -l 2>&1
    } catch {
        $out = $_.Exception.Message
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    if ($LASTEXITCODE -eq 2) { return @{ State = 'no-agent'; Detail = 'ssh-agent not running' } }
    if ($LASTEXITCODE -ne 0) { return @{ State = 'unknown'; Detail = "ssh-add exit=${LASTEXITCODE}: $($out -join ' | ')" } }
    if (-not $out -or ($out -join "`n") -match 'The agent has no identities') {
        return @{ State = 'agent-no-keys'; Detail = 'ssh-agent running but has no keys' }
    }
    $count = ($out | Measure-Object).Count
    $first = ($out | Select-Object -First 1) -replace '\s+', ' '
    return @{ State = 'agent-with-keys'; Detail = "$count key(s); first: $first" }
}

# --- preflight --------------------------------------------------------------

Write-Step "Bijou Coolify helper EPERM fix" 'Magenta'
Write-Host "  Host:             $User@$HostName`:$Port"
Write-Host "  Coolify API:      $CoolifyBaseUrl"
Write-Host "  Backend health:   $ProbeHealthUrl"
Write-Host "  Agentops health:  $ProbeAgentopsUrl"
Write-Host "  Mode:             $(if ($DryRun) {'DRY-RUN'} else {'LIVE'})"

if (-not $ApiToken) { $ApiToken = Read-EnvValue 'COOLIFY_API_TOKEN' }
if (-not $BackendSvcUuid) { $BackendSvcUuid = Read-EnvValue 'BIJOU_BACKEND_SVC_UUID' }
if (-not $AgentopsSvcUuid) { $AgentopsSvcUuid = Read-EnvValue 'AGENTOPS_SVC_UUID' }

if (-not $ApiToken) {
    Write-Err "No API token. Set COOLIFY_API_TOKEN in .env or pass -ApiToken."
    exit 1
}

$agentSummary = Get-SshAgentSummary
Write-Host "  ssh-agent:        $($agentSummary.State) - $($agentSummary.Detail)"
if ($agentSummary.State -eq 'no-agent') {
    Write-Warn "ssh-agent not running. If SSH fails, run:  ssh-add C:\path\to\key"
}

$sshOpts = @(
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ConnectTimeout=10',
    '-p', $Port
)
$sshTarget = "$User@$HostName"

# --- step 1: SSH + chmod docker.sock ---------------------------------------

Write-Step "Step 1: chmod /var/run/docker.sock on host" 'Cyan'

try {
    $permCmd = 'ls -l /var/run/docker.sock; sudo chmod 666 /var/run/docker.sock; ls -l /var/run/docker.sock'
    if ($DryRun) {
        Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $permCmd
    } else {
        $permOut = Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $permCmd 2>&1
        $permOut | ForEach-Object { Write-Host "    $_" }
        Write-OK "docker.sock permission updated"
    }
} catch {
    Write-Err "SSH chmod failed: $($_.Exception.Message)"
    Write-Host "    Common causes:"
    Write-Host "      - SSH key not in agent (run: ssh-add C:\path\to\key)"
    Write-Host "      - host unreachable or firewall blocking port $Port"
    Write-Host "      - user $User lacks sudo on the host"
    exit 1
}

# --- step 2: restart coolify-helper -----------------------------------------

Write-Step "Step 2: docker restart coolify-helper" 'Cyan'

try {
    $restartCmd = 'docker ps --filter name=coolify-helper --format "{{.Names}} {{.Status}}"; echo ---; docker restart coolify-helper; echo ---; sleep 2; docker ps --filter name=coolify-helper --format "{{.Names}} {{.Status}}"'
    if ($DryRun) {
        Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $restartCmd
    } else {
        $restartOut = Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $restartCmd 2>&1
        $restartOut | ForEach-Object { Write-Host "    $_" }
        Write-OK "coolify-helper restart initiated"
    }
} catch {
    Write-Err "docker restart failed: $($_.Exception.Message)"
    exit 1
}

# --- step 3: wait for helper to come back up --------------------------------

Write-Step "Step 3: wait ${HelperWaitSeconds}s for the helper to reconnect" 'Cyan'

if ($DryRun) {
    Write-Host "    [DRY-RUN] would wait $HelperWaitSeconds seconds"
} else {
    for ($i = 1; $i -le $HelperWaitSeconds; $i++) {
        Write-Host -NoNewline ("`r  {0,2}s elapsed" -f $i)
        Start-Sleep -Seconds 1
    }
    Write-Host ""
}

# --- step 4: probe Coolify API ----------------------------------------------

$apiOk = $false
if (-not $SkipApiCheck) {
    Write-Step "Step 4: probe Coolify API" 'Cyan'
    if ($DryRun) {
        Write-Host "    [DRY-RUN] would GET $CoolifyBaseUrl/api/v1/version"
        $apiOk = $true
    } else {
        try {
            $ver = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/version" -Headers @{Authorization = "Bearer $ApiToken"} -TimeoutSec 10
            Write-OK "Coolify API responsive, version $ver"
            $apiOk = $true
        } catch {
            Write-Err "Coolify API still not responding: $($_.Exception.Message)"
            Write-Host "    The helper may need more time. Wait 30s and re-run."
        }
    }
}

# --- step 5: try starting the backend + agentops services (optional) -------

if (-not $SkipServiceStart) {
    Write-Step "Step 5: POST /services/{uuid}/start for each service" 'Cyan'
    foreach ($svc in @(
        @{ Uuid = $BackendSvcUuid; Name = 'bijou-backend-svc' },
        @{ Uuid = $AgentopsSvcUuid; Name = 'agentops-dashboard-svc' }
    )) {
        if (-not $svc.Uuid) {
            Write-Warn "$($svc.Name): no UUID configured (set BIJOU_BACKEND_SVC_UUID / AGENTOPS_SVC_UUID in .env)"
            continue
        }
        if ($DryRun) {
            Write-Host "    [DRY-RUN] POST $CoolifyBaseUrl/api/v1/services/$($svc.Uuid)/start"
            continue
        }
        try {
            $startResp = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/services/$($svc.Uuid)/start" -Headers @{Authorization = "Bearer $ApiToken"} -Method POST -TimeoutSec 30
            Write-Host "    $($svc.Name): $($startResp.message)"
        } catch {
            Write-Warn "$($svc.Name) start returned $($_.Exception.Response.StatusCode.value__): $($_.Exception.Message)"
        }
    }
} else {
    Write-Step "Step 5: skipped (SkipServiceStart)" 'DarkGray'
}

# --- step 6: probe /health (optional) ---------------------------------------

$healthOk = $true
if (-not $SkipHealthCheck) {
    Write-Step "Step 6: probe /health endpoints (timeout ${HealthTimeoutSeconds}s)" 'Cyan'

    $probes = @(
        @{ Name = 'backend'; Url = $ProbeHealthUrl },
        @{ Name = 'agentops'; Url = $ProbeAgentopsUrl }
    )

    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    foreach ($probe in $probes) {
        Write-Host "  Polling $($probe.Name) at $($probe.Url)..."
        $ok = $false
        $lastStatus = '-'
        while ((Get-Date) -lt $deadline) {
            if ($DryRun) { Write-Host "    [DRY-RUN] would GET $($probe.Url)"; $ok = $true; break }
            try {
                $r = Invoke-WebRequest -Uri $probe.Url -UseBasicParsing -TimeoutSec 5
                $lastStatus = $r.StatusCode
                if ($r.StatusCode -eq 200) {
                    Write-OK "$($probe.Name) -> 200 (healthy, $($r.Content.Length) bytes)"
                    $ok = $true
                    break
                }
            } catch {
                $lastStatus = $_.Exception.Response.StatusCode.value__
                if (-not $lastStatus) { $lastStatus = $_.Exception.Message.Substring(0, [Math]::Min(60, $_.Exception.Message.Length)) }
            }
            Start-Sleep -Seconds 3
        }
        if (-not $ok) {
            Write-Warn "$($probe.Name) did not return 200 within ${HealthTimeoutSeconds}s (last status: $lastStatus). May still be starting."
            $healthOk = $false
        }
    }
}

# --- summary ----------------------------------------------------------------

Write-Step "Summary" 'Magenta'
Write-Host "  chmod /var/run/docker.sock: $(if ($DryRun) {'DRY-RUN'} else {'APPLIED'})"
Write-Host "  docker restart coolify-helper: $(if ($DryRun) {'DRY-RUN'} else {'APPLIED'})"
Write-Host "  Coolify API version:         $(if ($SkipApiCheck) {'SKIPPED'} elseif ($apiOk) {'OK'} elseif ($DryRun) {'DRY-RUN'} else {'FAILED'})"
Write-Host "  Service start API:           $(if ($SkipServiceStart) {'SKIPPED'} elseif ($DryRun) {'DRY-RUN'} else {'ATTEMPTED'})"
Write-Host "  /health probes:              $(if ($SkipHealthCheck) {'SKIPPED'} elseif ($healthOk) {'OK'} elseif ($DryRun) {'DRY-RUN'} else {'FAILED'})"

if ($DryRun) {
    Write-Host ""
    Write-Step "Dry-run complete. Re-run without -DryRun to apply." 'Green'
    exit 0
}
if (-not $apiOk -or -not $healthOk) {
    Write-Host ""
    Write-Step "EPERM fix completed with warnings" 'Yellow'
    exit 2
}
Write-Host ""
Write-Step "EPERM fix complete" 'Green'
exit 0
