# preflight-check.ps1 — Validate the user's setup BEFORE the Bijou
# Coolify cutover. Catches the 4 most common "I'm stuck" failure
# modes before they cost 30 minutes of debugging.
#
# Run from the project root:
#   .\ops\coolify\preflight-check.ps1
#
# Checks (in order):
#   1. Project root exists and is a git repo.
#   2. Coolify access token is reachable (from env, mcp_config.json, or project .env).
#   3. The env files are parseable and the required keys are present
#      (project .env, ~/.hermes/.env, .env.porkbun, .env.mybijou-creator).
#   4. The GitHub PAT works (if a PAT is set, from any of 4 sources).
#   5. The Porkbun API key works (if a key is set, from .env.porkbun).
#   6. The DNS for app.mybijou.xyz currently resolves to a healthy
#      Bijou backend (pre-cutover state).
#   7. The docker-compose + Dockerfiles are present.
#   8. The SQL migrations are present.
#   9. All the new cutover scripts are present.
#
# Output: PASS/FAIL/SKIP per check, a summary, exit 0 only if all pass.
# The script NEVER logs the value of any secret.

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$EnvFilePath = '',
    [switch]$SkipGitHub,
    [switch]$SkipPorkbun,
    [switch]$SkipDns
)

$ErrorActionPreference = 'Continue'
$pass = 0
$fail = 0
$skip = 0

function HashValue {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '<empty>' }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hash = $sha.ComputeHash($bytes)
        return ([BitConverter]::ToString($hash) -replace '-', '').ToLower()
    } finally {
        $sha.Dispose()
    }
}

function Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    Write-Host "[$ts] [$Level] $Message"
}

function Pass-Check { param([string]$Detail) Write-Host "  [PASS] $Detail" -ForegroundColor Green; $script:pass++ }
function Fail-Check { param([string]$Detail) Write-Host "  [FAIL] $Detail" -ForegroundColor Red; $script:fail++ }
function Skip-Check { param([string]$Detail) Write-Host "  [SKIP] $Detail" -ForegroundColor Yellow; $script:skip++ }

Log "preflight-check.ps1 — Bijou Coolify cutover readiness"
Log "Project root: $ProjectRoot"

# ─── 1. Project root + git ───────────────────────────────────────────
Write-Host ""
Write-Host "── 1. Project root is a git repo ──" -ForegroundColor Cyan
try {
    Push-Location $ProjectRoot
    $gitRoot = git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail-Check "not a git repo"
    } else {
        $branch = git branch --show-current 2>$null
        $remoteUrl = git config --get remote.origin.url 2>$null
        Pass-Check "git root=$gitRoot branch=$branch remote=$remoteUrl"
    }
} catch {
    Fail-Check $_.Exception.Message
} finally { Pop-Location }

# ─── 2. Coolify token ────────────────────────────────────────────────
Write-Host ""
Write-Host "── 2. Coolify access token reachable ──" -ForegroundColor Cyan
$token = $env:COOLIFY_TOKEN
$source = '$env:COOLIFY_TOKEN'
if (-not $token) {
    $mcpPath = Join-Path $env:USERPROFILE '.hermes\mcp_config.json'
    if (Test-Path $mcpPath) {
        try {
            $mcp = Get-Content $mcpPath -Raw | ConvertFrom-Json
            $token = $mcp.mcpServers.coolify.env.COOLIFY_ACCESS_TOKEN
            $source = $mcpPath
        } catch {
            # ignore
        }
    }
}
if (-not $token) {
    $projEnv = Join-Path $ProjectRoot '.env'
    if (Test-Path $projEnv) {
        $line = Select-String -Path $projEnv -Pattern '^COOLIFY_API_TOKEN=(.+)$' -ErrorAction SilentlyContinue
        if ($line) {
            $token = ($line.Matches[0].Groups[1].Value).Trim()
            $source = "$projEnv (COOLIFY_API_TOKEN)"
        }
    }
}
if (-not $token) {
    Fail-Check 'no token in $env:COOLIFY_TOKEN, mcp_config.json, or project .env'
} else {
    try {
        $resp = Invoke-RestMethod -Uri 'https://coolify.getbijou.xyz/api/v1/version' -Headers @{ Authorization = "Bearer $token" } -Method GET -TimeoutSec 15
        Pass-Check "Coolify reachable from $source. Version: $($resp | ConvertTo-Json -Compress)"
    } catch {
        Fail-Check "token found but /api/v1/version failed: $($_.Exception.Message)"
    }
}

# ─── 3. Env file parseable + required keys present ────────────────────
Write-Host ""
Write-Host "── 3. Env files parseable + required keys present ──" -ForegroundColor Cyan
$requiredKeys = @(
    'SUPABASE_URL', 'SUPABASE_SERVICE_KEY',
    'GEMINI_API_KEY',
    'STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET',
    'APPWRITE_ENDPOINT', 'APPWRITE_PROJECT_ID', 'APPWRITE_API_KEY',
    'PUBLIC_URL'
)
$candidates = @()
if ($EnvFilePath) { $candidates += $EnvFilePath }
$candidates += @(
    (Join-Path $ProjectRoot '.env'),
    (Join-Path $env:USERPROFILE '.hermes\.env'),
    (Join-Path $ProjectRoot 'settings.json'),
    (Join-Path $env:USERPROFILE '.hermes\secrets\.env.porkbun'),
    (Join-Path $env:USERPROFILE '.hermes\secrets\.env.mybijou-creator')
)
$found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $found) {
    Fail-Check "no env file found. Tried: $($candidates -join ', ')"
} else {
    $content = Get-Content -LiteralPath $found -Raw -Encoding UTF8
    $envMap = @{}
    try {
        $json = $content | ConvertFrom-Json -ErrorAction Stop
        foreach ($p in $json.PSObject.Properties) { $envMap[$p.Name] = [string]$p.Value }
    } catch {
        $regex = [regex]'(?m)^\s*"?([A-Z][A-Z0-9_]+)\s*=\s*"?([^"\r\n]+)"?\s*$'
        foreach ($m in $regex.Matches($content)) { $envMap[$m.Groups[1].Value] = $m.Groups[2].Value.Trim() }
    }
    $missing = @($requiredKeys | Where-Object { -not $envMap.ContainsKey($_) -or [string]::IsNullOrEmpty($envMap[$_]) })
    if ($missing.Count -gt 0) {
        Fail-Check "file=$found, missing $($missing.Count) keys: $($missing -join ', ')"
    } else {
        Pass-Check "file=$found, $(($envMap.Keys).Count) keys, all required present"
    }
}

# ─── 4. GitHub PAT works ─────────────────────────────────────────────
Write-Host ""
Write-Host "── 4. GitHub PAT for mybijouai-creator ──" -ForegroundColor Cyan
if ($SkipGitHub) {
    Skip-Check 'skipped via -SkipGitHub'
} else {
    $pat = $env:GITHUB_PAT_TOKEN
    $source = '$env:GITHUB_PAT_TOKEN'
    if (-not $pat) {
        $ghPath = Join-Path $env:USERPROFILE '.hermes\secrets\.env.mybijou-creator'
        if (Test-Path $ghPath) {
            $line = Select-String -Path $ghPath -Pattern '^GITHUB_PAT_TOKEN=(.+)$' -ErrorAction SilentlyContinue
            if ($line) {
                $pat = ($line.Matches[0].Groups[1].Value).Trim()
                $source = $ghPath
            }
        }
    }
    if (-not $pat) {
        $hermesEnv = Join-Path $env:USERPROFILE '.hermes\.env'
        if (Test-Path $hermesEnv) {
            $line = Select-String -Path $hermesEnv -Pattern '^GITHUB_TOKEN="?([^"\r\n]+)"?\s*$' -ErrorAction SilentlyContinue
            if ($line) {
                $pat = ($line.Matches[0].Groups[1].Value).Trim()
                $source = "$hermesEnv (GITHUB_TOKEN)"
            }
        }
    }
    if (-not $pat) {
        $projEnv = Join-Path $ProjectRoot '.env'
        if (Test-Path $projEnv) {
            $line = Select-String -Path $projEnv -Pattern '^GITHUB_PAT_TOKEN=(.+)$' -ErrorAction SilentlyContinue
            if ($line) {
                $pat = ($line.Matches[0].Groups[1].Value).Trim()
                $source = "$projEnv (GITHUB_PAT_TOKEN)"
            }
        }
    }
    if (-not $pat) {
        Fail-Check "no PAT. Checked env, .env.mybijou-creator, .hermes/.env, project .env."
    } else {
        try {
            $resp = Invoke-RestMethod -Uri 'https://api.github.com/repos/mybijouai-creator/bijou-monorepo' -Headers @{ Authorization = "Bearer $pat"; 'User-Agent' = 'bijou-preflight'; Accept = 'application/vnd.github+json' } -Method GET -TimeoutSec 15
            Pass-Check "PAT from $source, repo=mybijouai-creator/bijou-monorepo, default_branch=$($resp.default_branch)"
        } catch {
            Fail-Check "PAT found but API call failed: $($_.Exception.Message)"
        }
    }
}

# ─── 5. Porkbun key works ────────────────────────────────────────────
Write-Host ""
Write-Host "── 5. Porkbun API key ──" -ForegroundColor Cyan
if ($SkipPorkbun) {
    Skip-Check 'skipped via -SkipPorkbun'
} else {
    $key = $env:PORKBUN_API_KEY
    $secret = $env:PORKBUN_SECRET_KEY
    $source = '$env:PORKBUN_API_KEY'
    if (-not $key -or -not $secret) {
        $porkFile = Join-Path $env:USERPROFILE '.hermes\secrets\.env.porkbun'
        if (Test-Path $porkFile) {
            $c = Get-Content -LiteralPath $porkFile -Raw -Encoding UTF8
            if ($c -match '(?m)API Key[:=]\s*(\S+)') { $key = $Matches[1].Trim() }
            if ($c -match '(?m)Secret Key[:=]\s*(\S+)') { $secret = $Matches[1].Trim() }
            if ($key -and $secret) { $source = $porkFile }
        }
    }
    if (-not $key -or -not $secret) {
        Skip-Check 'PORKBUN_API_KEY or PORKBUN_SECRET_KEY not set (env or .env.porkbun). DNS cutover step will be a no-op.'
    } else {
        $body = @{ apikey = $key; secretapikey = $secret } | ConvertTo-Json
        try {
            $resp = Invoke-RestMethod -Uri 'https://porkbun.com/api/json/v3/ping' -Method POST -ContentType 'application/json' -Body $body -TimeoutSec 15
            if ($resp.status -ne 'SUCCESS') {
                Fail-Check "ping returned $($resp | ConvertTo-Json -Compress)"
            } else {
                Pass-Check "Porkbun ping SUCCESS from $source. yourIp=$($resp.yourIp)"
            }
        } catch {
            Fail-Check "ping failed: $($_.Exception.Message)"
        }
    }
}

# ─── 6. DNS pre-cutover ──────────────────────────────────────────────
Write-Host ""
Write-Host "── 6. app.mybijou.xyz pre-cutover health ──" -ForegroundColor Cyan
if ($SkipDns) {
    Skip-Check 'skipped via -SkipDns'
} else {
    try {
        $resp = Invoke-RestMethod -Uri 'https://app.mybijou.xyz/health' -TimeoutSec 15
        if ($resp.status -eq 'healthy' -and $resp.service -like 'bijou-ai-enterprise*') {
            Pass-Check "service=$($resp.service) version=$($resp.version) db=$($resp.database)"
        } else {
            Fail-Check "service=$($resp.service) but not healthy"
        }
    } catch {
        Fail-Check "pre-cutover health check failed: $($_.Exception.Message). Do NOT cut DNS until this is green."
    }
}

# ─── 7. Docker compose + Dockerfiles ──────────────────────────────────
Write-Host ""
Write-Host "── 7. docker-compose.coolify.yml + Dockerfiles present ──" -ForegroundColor Cyan
$compose = Join-Path $ProjectRoot 'docker-compose.coolify.yml'
$back = Join-Path $ProjectRoot 'Dockerfile.backend'
$brdg = Join-Path $ProjectRoot 'Dockerfile.bridge'
$lndg = Join-Path $ProjectRoot 'Dockerfile.landing'
$missing = @()
if (-not (Test-Path $compose)) { $missing += 'docker-compose.coolify.yml' }
if (-not (Test-Path $back))   { $missing += 'Dockerfile.backend' }
if (-not (Test-Path $brdg))   { $missing += 'Dockerfile.bridge' }
if (-not (Test-Path $lndg))   { $missing += 'Dockerfile.landing' }
if ($missing.Count -gt 0) {
    Fail-Check "missing: $($missing -join ', ')"
} else {
    Pass-Check "all 4 deploy artifacts present"
}

# ─── 8. SQL migrations present ───────────────────────────────────────
Write-Host ""
Write-Host "── 8. SQL migrations present ──" -ForegroundColor Cyan
$dir = Join-Path $ProjectRoot 'packages\backend\migrations-py'
if (-not (Test-Path $dir)) {
    Fail-Check "$dir not found"
} else {
    $sqls = Get-ChildItem -LiteralPath $dir -Filter '*.sql' -ErrorAction SilentlyContinue
    if (-not $sqls -or $sqls.Count -lt 5) {
        Fail-Check "found $(if ($sqls) { $sqls.Count } else { 0 }) .sql files in migrations-py. Expected at least 5."
    } else {
        Pass-Check "found $($sqls.Count) SQL files in migrations-py"
    }
}

# ─── 9. The new cutover scripts are present ──────────────────────────
Write-Host ""
Write-Host "── 9. The new ops/coolify/*.ps1 scripts are present ──" -ForegroundColor Cyan
$expected = @(
    'wire-coolify.ps1', 'migrate-secrets-to-coolify.ps1',
    'porkbun-cutover.ps1', 'smoke-test-prod.ps1', 'preflight-check.ps1',
    'push-to-canonical.ps1', 'PRODUCTION-CUTOVER-PLAN.md',
    'coolify-env-group.template.json', 'bridge-cutover.md', 'menu-pages-verify.md'
)
$missing = @()
foreach ($f in $expected) {
    if (-not (Test-Path (Join-Path $PSScriptRoot $f))) { $missing += $f }
}
if ($missing.Count -gt 0) {
    Fail-Check "missing: $($missing -join ', ')"
} else {
    Pass-Check "all $($expected.Count) cutover scripts present"
}

# ─── Summary ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Preflight summary: $pass pass, $fail fail, $skip skip" -ForegroundColor $(if ($fail -eq 0) { 'Green' } else { 'Red' })
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan

if ($fail -gt 0) {
    Write-Host ""
    Write-Host "Do NOT start the cutover until all checks pass." -ForegroundColor Red
    Write-Host "Run again with -SkipGitHub / -SkipPorkbun / -SkipDns to isolate failures." -ForegroundColor Yellow
    exit 1
}
exit 0
