# validate-local.ps1 - Coolify deploy dry-run for Bijou AI
#
# Purpose: prove that `docker-compose.coolify.yml` parses, the build
# contexts work, the env-file is complete, and the resulting images
# would start cleanly. Run this BEFORE pushing to a real Coolify
# instance, to catch config drift and missing env vars early.
#
# Usage:
#   cd C:\Users\W3jde\local-projects\bijou-monorepo
#   powershell -ExecutionPolicy Bypass -File ops/coolify/validate-local.ps1
#
# What it does:
#   1. Checks Docker / docker compose are available
#   2. Validates the compose file (docker compose config --quiet)
#   3. Builds the images locally (no push) so we catch Dockerfile bugs
#   4. Boots the backend container with a test env, hits /health,
#      then tears down
#   5. Prints a summary + the next manual step
#
# What it does NOT do:
#   - It does not push to Coolify or anywhere else
#   - It does not require real Supabase / Stripe creds (it uses dummy
#     placeholders; the boot check only verifies the container can
#     START, not that it can SERVE real traffic)
#   - It does not touch the host's /data volume
#
# Exit codes:
#   0 = all checks passed
#   1 = Docker not available
#   2 = compose file is invalid
#   3 = image build failed
#   4 = container failed to come up healthy

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $repoRoot

function Write-Header($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Write-Ok($text) { Write-Host "  [OK]   $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [WARN] $text" -ForegroundColor Yellow }
function Write-Fail($text) { Write-Host "  [FAIL] $text" -ForegroundColor Red }

# 1. Pre-flight
Write-Header "Pre-flight"

$docker = $null
$compose = $null
try {
    $docker = (Get-Command docker -ErrorAction Stop).Source
    Write-Ok "docker found at $docker"
} catch {
    Write-Fail "docker not on PATH. Install Docker Desktop and re-run."
    exit 1
}
# Detect docker compose (v2 plugin) or docker-compose (v1). PowerShell
# needs the command-name quoted when it has a space, otherwise it
# treats "compose" as a separate argument.
try {
    $null = & docker 'compose' version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $compose = @('docker', 'compose')
        Write-Ok "docker compose plugin found"
    } else {
        throw "no plugin"
    }
} catch {
    try {
        $null = (Get-Command docker-compose -ErrorAction Stop).Source
        $compose = @('docker-compose')
        Write-Ok "docker-compose v1 found (legacy)"
    } catch {
        Write-Fail "neither 'docker compose' nor 'docker-compose' on PATH"
        exit 1
    }
}

# Helper to invoke compose with multiple args. We discard stderr
# because docker compose prints info-level warnings to stderr
# (e.g. about deprecated keys) that are not actually errors. We
# trust the exit code.
function Invoke-Compose {
    $output = & $compose[0] $compose[1..($compose.Count-1)] @args 2>$null
    return $LASTEXITCODE
}

# 2. Compose file syntax check
Write-Header "Compose file syntax"
$composeFile = "docker-compose.coolify.yml"
if (-not (Test-Path $composeFile)) {
    Write-Fail "$composeFile not found at repo root"
    exit 2
}

Invoke-Compose -f $composeFile config --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "$composeFile parses cleanly"
} else {
    Write-Fail "$composeFile has a syntax error. Run: $($compose -join ' ') -f $composeFile config"
    Invoke-Compose -f $composeFile config 2>&1 | Out-String | Select-Object -First 30
    exit 2
}

# 3. Env-file check
Write-Header "Env file"
$envFile = "ops\coolify\coolify.env.example"
if (Test-Path $envFile) {
    $content = Get-Content $envFile -Raw
    $required = @("SUPABASE_URL","SUPABASE_SERVICE_KEY","GEMINI_API_KEY","STRIPE_SECRET_KEY","STRIPE_WEBHOOK_SECRET","BRIDGE_API_KEY")
    $missing = @()
    foreach ($r in $required) {
        if ($content -notmatch "(?m)^$r\s*=") { $missing += $r }
    }
    if ($missing.Count -eq 0) {
        Write-Ok "all required env vars documented in $envFile"
    } else {
        Write-Warn "missing required env vars in $envFile : $($missing -join ', ')"
    }
} else {
    Write-Fail "$envFile not found"
}

# 4. Image build
Write-Header "Image build (Dockerfile.backend)"
Write-Host "  building bijou-backend:test ... (this can take a few minutes the first time)"
Invoke-Compose -f $composeFile build backend 2>&1 | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -eq 0) {
    Write-Ok "backend image built"
} else {
    Write-Fail "backend build failed"
    exit 3
}

Write-Header "Image build (Dockerfile.bridge)"
Invoke-Compose -f $composeFile build bridge 2>&1 | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -eq 0) {
    Write-Ok "bridge image built"
} else {
    Write-Fail "bridge build failed"
    exit 3
}

# 5. Backend boot test
Write-Header "Backend boot test"
Write-Host "  starting backend with dummy env, hitting /health ..."

# Write a temp env file with dummy-but-non-empty values so the
# backend's import-time env validation passes. The dummy values are
# NOT valid for real traffic, so we tear down immediately.
#
# Note: values are kept short (< 12 chars) and obviously-not-credentials
# so the pre-commit secret-guard regex doesn't false-positive on them.
$tmpEnv = New-TemporaryFile
@"
SUPABASE_URL=https://example.invalid
SUPABASE_SERVICE_KEY=PLACEHOLDER
GEMINI_API_KEY=PLACEHOLDER
STRIPE_SECRET_KEY=PLACEHOLDER
STRIPE_WEBHOOK_SECRET=PLACEHOLDER
BRIDGE_API_KEY=PLACEHOLDER
PUBLIC_URL=http://localhost:8080
LOG_LEVEL=INFO
PORT=8080
"@ | Out-File -FilePath $tmpEnv.FullName -Encoding ASCII

# Start in detached mode with the temp env
Invoke-Compose -f $composeFile --env-file $tmpEnv.FullName up -d backend 2>&1 | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" }

# Give it 20s to come up
$healthy = $false
for ($i = 1; $i -le 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) {
            Write-Ok "backend /health returned 200 after ${i}s"
            $healthy = $true
            break
        }
    } catch {
        # not ready yet
    }
}

# Always tear down
Invoke-Compose -f $composeFile --env-file $tmpEnv.FullName down -v 2>&1 | Out-Null
Remove-Item $tmpEnv -Force -ErrorAction SilentlyContinue

if ($healthy) {
    Write-Ok "backend boot test passed"
} else {
    Write-Fail "backend did not become healthy within 20s. Check the logs above."
    exit 4
}

# 6. Summary + next step
Write-Header "Summary"
Write-Ok "All local checks passed."
Write-Host ""
Write-Host "Next step for a real deploy:" -ForegroundColor White
Write-Host "  1. Fill in ops/coolify/coolify.env.example with real values"
Write-Host "  2. Commit and push to main"
Write-Host "  3. In Coolify UI: New Resource -> Docker Compose"
Write-Host "       Source: $repoRoot"
Write-Host "       Compose file: docker-compose.coolify.yml"
Write-Host "       Env group: $envFile (filled in)"
Write-Host "  4. Watch the build log, then hit https://app.mybijou.xyz/health"
Write-Host ""
Write-Host "See ops/coolify/DEPLOY.md for the full runbook." -ForegroundColor Cyan

exit 0
