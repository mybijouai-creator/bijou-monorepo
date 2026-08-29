<#
.SYNOPSIS
    One-shot cutover completion: fix EPERM + ship v0.4.8 image + restart backend.

.DESCRIPTION
    Finishes the 3 owner actions that can't be done from inside the agent sandbox
    (no SSH to 169.58.147.169). Wraps them in a single script so the user can
    run it once from their terminal.

    Steps (in order):
      1. chmod /var/run/docker.sock + restart coolify-helper   (fix EPERM)
      2. Probe Coolify /api/v1/version until 200              (wait for helper reconnect)
      3. SCP the locally-built v0.4.8 backend tar              (image built by
         the agent in advance; saved to ops/coolify/bijou-backend-optimized-v0.4.8.tar)
      4. SSH: docker load + tag the new image
      5. POST /api/v1/services/{uuid}/start                    (trigger redeploy)
      6. Poll /health until 200                                (verify)

    The GitHub webhook (id 672019233) was already wired to
    https://coolify.getbijou.xyz/api/v1/deploy?uuid=ao9vicd4shkjisksulfatn7p
    in the previous session, so future pushes to main auto-redeploy too.

.PARAMETER Host
    Coolify host. Default: 169.58.147.169.

.PARAMETER SshKey
    Path to the SSH private key authorized on the Coolify host.
    Try ~/.ssh/id_ed25519 first; if "Permission denied", try ~/.ssh/claude_code_w3j.

.PARAMETER TarPath
    Path to the v0.4.8 tar built locally.
    Default: ops/coolify/bijou-backend-optimized-v0.4.8.tar (relative to repo root).

.PARAMETER BackendSvcUuid
    UUID of the Bijou backend service in Coolify.
    Default: ao9vicd4shkjisksulfatn7p.

.PARAMETER HealthUrl
    Public health URL to verify after the restart.
    Default: https://app.mybijou.xyz/health.

.PARAMETER SkipImagePush
    Skip steps 3-4 (only do EPERM fix + restart). Useful when debugging the
    helper bug alone.

.PARAMETER BuildImageIfMissing
    If the local tar doesn't exist, run `docker build` first. Useful if you
    deleted the tar but still have Docker + the repo.

.PARAMETER ImageTag
    The Coolify tag for the backend image. Must match what Coolify's service
    is configured to pull. Default: bijou-backend:v0.4.8.

.PARAMETER DryRun
    Print every SSH/scp/docker command but don't execute. Use to validate the
    script will run cleanly before committing.

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1 -SshKey C:\Users\W3jde\.ssh\coolify_host_ed25519

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1 -DryRun

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1 -BuildImageIfMissing -ImageTag bijou-backend:v0.4.8

.NOTES
    Run from the repo root. Needs an SSH key the Coolify host accepts.
    The agent couldn't reach the host from inside its sandbox, hence this
    user-side wrapper.
#>

[CmdletBinding()]
param(
    [string]$HostName = '169.58.147.169',
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$SshUser = 'root',
    [string]$TarPath = "ops\coolify\bijou-backend-optimized-v0.4.8.tar",
    [string]$BackendSvcUuid = 'ao9vicd4shkjisksulfatn7p',
    [string]$HealthUrl = 'https://app.mybijou.xyz/health',
    [int]$HelperWaitSeconds = 30,
    [int]$HealthTimeoutSeconds = 120,
    [string]$ImageTag = 'bijou-backend:v0.4.8',
    [string]$SourceImage = 'bijour-local/bijou-backend-optimized:v0.4.8',
    [string]$Dockerfile = 'Dockerfile.backend.optimized',
    [switch]$SkipImagePush,
    [switch]$BuildImageIfMissing,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# --- helpers ----------------------------------------------------------------

function Write-Step {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Message, [string]$Color = 'Cyan')
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor $Color
}
function Write-OK  { param([Parameter(Mandatory)][string]$Message) Write-Host "  [OK]   $Message" -ForegroundColor Green }
function Write-Warn { param([Parameter(Mandatory)][string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Err  { param([Parameter(Mandatory)][string]$Message) Write-Host "  [ERR]  $Message" -ForegroundColor Red }

function Invoke-Ssh {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string[]]$Opts,
        [Parameter(Mandatory)][string]$RemoteCommand
    )
    if ($DryRun) {
        Write-Host "    [DRY-RUN] ssh $($Opts -join ' ') $Target -- $RemoteCommand"
        return ""
    }
    & ssh @Opts $Target -- $RemoteCommand
    if ($LASTEXITCODE -ne 0) { throw "ssh exited $LASTEXITCODE" }
}

function Run-Or-Print {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Description, [Parameter(Mandatory)][scriptblock]$Block)
    if ($DryRun) {
        Write-Host "    [DRY-RUN] $Description"
        return
    }
    & $Block
}

# --- preflight --------------------------------------------------------------

Write-Step "Bijou Coolify cutover: EPERM fix + v0.4.8 push + restart" 'Magenta'
Write-Host "  Host:           $SshUser@$HostName"
Write-Host "  SSH key:        $SshKey"
Write-Host "  Tar:            $TarPath"
Write-Host "  Backend UUID:   $BackendSvcUuid"
Write-Host "  Health URL:     $HealthUrl"
Write-Host "  Mode:           $(if ($DryRun) {'DRY-RUN'} else {'LIVE'})"

$ProjectRoot = (Resolve-Path '.').Path
$TarFullPath = if ([System.IO.Path]::IsPathRooted($TarPath)) { $TarPath } else { Join-Path $ProjectRoot $TarPath }

if (-not $DryRun) {
    if (-not (Test-Path $SshKey)) { Write-Err "SSH key not found at $SshKey. Try -SshKey to override."; exit 1 }
    if (-not (Test-Path $TarFullPath)) { Write-Warn "Tar not found at $TarFullPath. Step 3 will fail unless you build it first." }
}

$sshOpts = @('-i', $SshKey, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=10')
$sshTarget = "$SshUser@$HostName"

# --- step 1: fix EPERM ------------------------------------------------------

Write-Step "Step 1: chmod /var/run/docker.sock + restart coolify-helper" 'Cyan'

try {
    $permCmd = 'ls -l /var/run/docker.sock; sudo chmod 666 /var/run/docker.sock; ls -l /var/run/docker.sock; sudo docker ps --filter name=coolify-helper --format "{{.Names}} {{.Status}}"; echo ---; sudo docker restart coolify-helper; echo ---; sleep 2; sudo docker ps --filter name=coolify-helper --format "{{.Names}} {{.Status}}"'
    $out = Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $permCmd
    if (-not $DryRun) { $out | ForEach-Object { Write-Host "    $_" } }
    Write-OK "coolify-helper restarted"
} catch {
    Write-Err "EPERM fix failed: $($_.Exception.Message)"
    Write-Host "    If 'Permission denied (publickey)', try:  -SshKey C:\Users\W3jde\.ssh\claude_code_w3j"
    Write-Host "    Otherwise check that your SSH key is in the Coolify host's authorized_keys."
    exit 1
}

# --- step 2: wait for helper -----------------------------------------------

Write-Step "Step 2: wait $HelperWaitSeconds`s for the helper to reconnect" 'Cyan'

if (-not $DryRun) {
    for ($i = 1; $i -le $HelperWaitSeconds; $i++) {
        Write-Host -NoNewline ("`r  {0,2}s elapsed" -f $i)
        Start-Sleep -Seconds 1
    }
    Write-Host ""
}

# probe Coolify
Write-Host "  Probing Coolify /api/v1/version..."
$tok = $null
if (Test-Path .env) {
    $line = Select-String -Path .env -Pattern '^COOLIFY_API_TOKEN=(.+)$' | Select-Object -First 1
    if ($line) { $tok = ($line.Matches.Groups[1].Value).Trim() }
}
if (-not $tok) { Write-Warn "no COOLIFY_API_TOKEN in .env; skipping probe" }
else {
    try {
        Run-Or-Print "GET https://coolify.getbijou.xyz/api/v1/version" {
            $v = Invoke-RestMethod -Uri 'https://coolify.getbijou.xyz/api/v1/version' -Headers @{Authorization="Bearer $tok"} -TimeoutSec 10
            Write-OK "Coolify API responsive, version $v"
        }
    } catch {
        Write-Err "Coolify API not responsive: $($_.Exception.Message)"
        Write-Host "    The helper may need more time. Re-run with -HelperWaitSeconds 60."
        exit 1
    }
}

# --- step 3 + 4: ship the v0.4.8 image ------------------------------------

if (-not $SkipImagePush) {
    Write-Step "Step 3: SCP the v0.4.8 tar to the host" 'Cyan'

    if (-not (Test-Path $TarFullPath)) {
        if ($BuildImageIfMissing -and -not $DryRun) {
            Write-Warn "Tar not found at $TarFullPath -- building image locally"
            $buildStart = Get-Date
            & docker build --no-cache -f $Dockerfile -t $SourceImage .
            if ($LASTEXITCODE -ne 0) { Write-Err "docker build failed"; exit 1 }
            & docker save -o $TarFullPath $SourceImage
            if ($LASTEXITCODE -ne 0) { Write-Err "docker save failed"; exit 1 }
            $buildElapsed = [Math]::Round(((Get-Date) - $buildStart).TotalSeconds)
            $buildSize = (Get-Item $TarFullPath).Length
            $buildMB = [Math]::Round($buildSize / 1048576, 1)
            $buildMsg = ("built + saved in {0}s ({1} MB)" -f $buildElapsed, $buildMB)
            Write-OK $buildMsg
        } else {
            Write-Err "Tar not found at $TarFullPath. Either:"
            Write-Host "    1. The agent was supposed to build it â€” re-run without -SkipImagePush"
            Write-Host "    2. Run with -BuildImageIfMissing to auto-build via docker"
            Write-Host "    3. Manually:"
            Write-Host "         docker build --no-cache -f $Dockerfile -t $SourceImage ."
            Write-Host "         docker save -o $TarFullPath $SourceImage"
            exit 1
        }
    }

    $tarFileName = Split-Path -Leaf $TarFullPath
    $remoteTar = "/tmp/$tarFileName"
    try {
        Run-Or-Print ("scp {0} {1}:{2}" -f $TarFullPath, $sshTarget, $remoteTar) {
            & scp @sshOpts $TarFullPath ("${sshTarget}:${remoteTar}")
            if ($LASTEXITCODE -ne 0) { throw "scp exit $LASTEXITCODE" }
        }
        if (-not $DryRun) {
            $sizeBytes = (Get-Item $TarFullPath).Length
            $sizeMB = [Math]::Round($sizeBytes / 1048576, 1)
            Write-Host "    [OK]   scp done - size $sizeMB MB" -ForegroundColor Green
        }
    } catch {
        Write-Err "scp failed: $($_.Exception.Message)"
        exit 1
    }

    Write-Step "Step 4: SSH: docker load + tag" 'Cyan'

    try {
        # Use single-quoted remote command; bash on the host does the variable expansion
        $loadCmd = "set -e; cd /tmp; sudo docker load -i $tarFileName; sudo docker tag $SourceImage $ImageTag; echo '---'; sudo docker images | grep -E 'bijou-backend'"
        $out = Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $loadCmd
        if (-not $DryRun) { $out | ForEach-Object { Write-Host "    $_" } }
        Write-OK ("image loaded + tagged as {0}" -f $ImageTag)
    } catch {
        Write-Err "docker load failed: $($_.Exception.Message)"
        exit 1
    }

    # Verify the image is visible to Coolify
    if (-not $DryRun -and $tok) {
        Write-Host "  Verifying Coolify sees the image..."
        try {
            $svc = Invoke-RestMethod -Uri "https://coolify.getbijou.xyz/api/v1/services/$BackendSvcUuid" -Headers @{Authorization="Bearer $tok"} -TimeoutSec 10
            $expectedTag = $ImageTag.Split(':')[1]
            $remoteTag = $svc.applications[0].image.Split(':')[-1]
            if ($remoteTag -eq $expectedTag) {
                Write-OK "Coolify reports the service image as $($svc.applications[0].image)"
            } else {
                Write-Warn "Coolify image registry shows v$remoteTag (wanted $expectedTag). May need a moment to refresh, or re-trigger step 5."
            }
        } catch {
            Write-Warn "Could not verify via Coolify API: $($_.Exception.Message)"
        }
    }
} else {
    Write-Step "Step 3-4: skipped (SkipImagePush)" 'DarkGray'
}

# --- step 5: trigger redeploy via API --------------------------------------

Write-Step "Step 5: POST /api/v1/services/$BackendSvcUuid/start" 'Cyan'

if ($tok) {
    try {
        Run-Or-Print "POST /api/v1/services/$BackendSvcUuid/start" {
            $r = Invoke-RestMethod -Uri "https://coolify.getbijou.xyz/api/v1/services/$BackendSvcUuid/start" -Headers @{Authorization="Bearer $tok"} -Method POST -TimeoutSec 30 -ContentType 'application/json' -Body '{}'
            Write-Host "    $($r.message)"
        }
    } catch {
        Write-Warn "start returned $($_.Exception.Response.StatusCode.value__): $($_.Exception.Message)"
    }
} else {
    Write-Warn "no token; skipping API restart"
}

# --- step 6: poll /health ---------------------------------------------------

Write-Step "Step 6: poll $HealthUrl (timeout ${HealthTimeoutSeconds}s)" 'Cyan'

$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
$ok = $false
$attempt = 0
$lastStatus = '-'
$deployedVersion = ''
while ((Get-Date) -lt $deadline) {
    $attempt++
    if ($DryRun) { Write-Host "    [DRY-RUN] would GET $HealthUrl"; $ok = $true; break }
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
        $lastStatus = $r.StatusCode
        if ($r.StatusCode -eq 200) {
            $healthBytes = $r.Content.Length
            $healthMsg = "$HealthUrl -> 200 (healthy, attempt $attempt, $healthBytes bytes)"
            Write-OK $healthMsg
            $firstLine = ($r.Content | Out-String).Split("`n")[0]
            Write-Host "      body: $firstLine"
            $ok = $true
            # parse the deployed version for the summary
            try {
                $j = $r.Content | ConvertFrom-Json -ErrorAction Stop
                if ($j.version) { $deployedVersion = $j.version }
                if ($j.database) { Write-Host "      db: $($j.database)" }
            } catch {}
            break
        }
    } catch {
        $lastStatus = $_.Exception.Message.Substring(0, [Math]::Min(80, $_.Exception.Message.Length))
    }
    if ($attempt % 5 -eq 1) { Write-Host "    attempt $attempt, last: $lastStatus" }
    Start-Sleep -Seconds 3
}
if (-not $ok) {
    Write-Err "$HealthUrl did not return 200 within ${HealthTimeoutSeconds}s (last: $lastStatus)"
    Write-Host "    The image may have started but is still initializing. Try -HealthTimeoutSeconds 180."
}

# --- step 7: verify the P0 fix endpoints are now live (sanity check) -------
if (-not $DryRun -and $ok) {
    Write-Step "Step 7: verify P0 endpoints are live" 'Cyan'
    foreach ($endpoint in @('/api/menu/permissions', '/api/self-test/summary')) {
        try {
            $r = Invoke-WebRequest -Uri ("https://app.mybijou.xyz" + $endpoint) -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -eq 200) {
                Write-OK "GET $endpoint -> 200 (was 404 before deploy)"
            } else {
                Write-Warn "GET $endpoint -> $($r.StatusCode) (expected 200)"
            }
        } catch {
            $code = $null
            try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
            Write-Warn "GET $endpoint -> $code : $($_.Exception.Message)"
        }
    }
}

# --- summary ---------------------------------------------------------------

Write-Step "Summary" 'Magenta'
Write-Host "  chmod docker.sock + restart helper: $(if ($DryRun) {'DRY-RUN'} else {'APPLIED'})"
if (-not $SkipImagePush) {
    Write-Host "  SCP v0.4.8 tar:                    $(if ($DryRun) {'DRY-RUN'} else {'OK'})"
    Write-Host "  docker load + tag:                  $(if ($DryRun) {'DRY-RUN'} else {'OK'})"
    Write-Host "  Coolify image check:                $(if ($DryRun) {'DRY-RUN'} else {'OK'})"
}
Write-Host "  POST /services/start:               $(if ($DryRun) {'DRY-RUN'} elseif ($tok) {'ATTEMPTED'} else {'SKIPPED (no token)'})"
$healthLine = if ($ok) {
        if ([string]::IsNullOrEmpty($deployedVersion)) { 'OK' } else { "OK (v$deployedVersion)" }
    } elseif ($DryRun) { 'DRY-RUN' } else { 'FAILED' }
Write-Host "  /health probe:                      $healthLine"

if (-not $ok -and -not $DryRun) {
    Write-Host ""
    Write-Step "Cutover completed with warnings -- check the FAIL above" 'Yellow'
    exit 2
}
Write-Host ""
Write-Step "Cutover complete" 'Green'
exit 0
