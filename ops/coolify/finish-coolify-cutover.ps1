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

.PARAMETER DryRun
    Print every SSH/scp/docker command but don't execute. Use to validate the
    script will run cleanly before committing.

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1 -SshKey C:\Users\W3jde\.ssh\coolify_host_ed25519

.EXAMPLE
    .\ops\coolify\finish-coolify-cutover.ps1 -DryRun

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
    [switch]$SkipImagePush,
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
        Write-Err "Tar not found at $TarFullPath"
        Write-Host "    The agent was supposed to build it locally. Run:"
        Write-Host "      docker build --no-cache -f Dockerfile.backend.optimized -t bijour-local/bijou-backend-optimized:v0.4.8 ."
        Write-Host "      docker save -o $TarFullPath bijour-local/bijou-backend-optimized:v0.4.8"
        exit 1
    }

    $remoteTar = "/tmp/bijou-backend-optimized-v0.4.8.tar"
    try {
        Run-Or-Print ("scp {0} {1}:{2}" -f $TarFullPath, $sshTarget, $remoteTar) {
            & scp @sshOpts $TarFullPath ("${sshTarget}:${remoteTar}")
            if ($LASTEXITCODE -ne 0) { throw "scp exit $LASTEXITCODE" }
        }
        if (-not $DryRun) { Write-OK "scp done" }
    } catch {
        Write-Err "scp failed: $($_.Exception.Message)"
        exit 1
    }

    Write-Step "Step 4: SSH: docker load + tag" 'Cyan'

    try {
        $loadCmd = 'set -e; cd /tmp; sudo docker load -i bijou-backend-optimized-v0.4.8.tar; sudo docker tag bijour-local/bijou-backend-optimized:v0.4.8 bijou-backend:v0.4.8; sudo docker images | grep -E "bijou-backend"'
        $out = Invoke-Ssh -Target $sshTarget -Opts $sshOpts -RemoteCommand $loadCmd
        if (-not $DryRun) { $out | ForEach-Object { Write-Host "    $_" } }
        Write-OK "image loaded + tagged as bijou-backend:v0.4.8"
    } catch {
        Write-Err "docker load failed: $($_.Exception.Message)"
        exit 1
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
while ((Get-Date) -lt $deadline) {
    $attempt++
    if ($DryRun) { Write-Host "    [DRY-RUN] would GET $HealthUrl"; $ok = $true; break }
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
        $lastStatus = $r.StatusCode
        if ($r.StatusCode -eq 200) {
            Write-OK "$HealthUrl -> 200 (healthy, attempt $attempt, $($r.Content.Length) bytes)"
            $r.Content | Out-String | Select-Object -First 1 | ForEach-Object { Write-Host "      body: $_" }
            $ok = $true
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

# --- summary ---------------------------------------------------------------

Write-Step "Summary" 'Magenta'
Write-Host "  chmod docker.sock + restart helper: $(if ($DryRun) {'DRY-RUN'} else {'APPLIED'})"
if (-not $SkipImagePush) {
    Write-Host "  SCP v0.4.8 tar:                    $(if ($DryRun) {'DRY-RUN'} else {'OK'})"
    Write-Host "  docker load + tag:                  $(if ($DryRun) {'DRY-RUN'} else {'OK'})"
}
Write-Host "  POST /services/start:               $(if ($DryRun) {'DRY-RUN'} elseif ($tok) {'ATTEMPTED'} else {'SKIPPED (no token)'})"
Write-Host "  /health probe:                      $(if ($ok) {'OK'} elseif ($DryRun) {'DRY-RUN'} else {'FAILED'})"

if (-not $ok -and -not $DryRun) {
    Write-Host ""
    Write-Step "Cutover completed with warnings -- check the FAIL above" 'Yellow'
    exit 2
}
Write-Host ""
Write-Step "Cutover complete" 'Green'
exit 0
