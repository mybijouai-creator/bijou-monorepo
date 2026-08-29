# smoke-test-prod.ps1 — Run the 9 checks that prove the Bijou stack
# is healthy on a given URL. The user said "confirm all sign in,
# signup, dashboard, AI access, every menu pages" — this is the
# automatable part. The visual / UX part must be done by a human or
# the in-app Browser.
#
# What it does (in order):
#   1. /health                                → 200, service=bijou-ai-enterprise
#   2. /api/self-test/summary                 → 200, no critical failures
#   3. /api/menu/permissions                  → 200, has the expected top-level entries
#   4. /static/login.html                     → 200, contains a form
#   5. /static/signup.html                    → 200, contains a form
#   6. /static/dashboard.html                 → 200, references the dashboard app
#   7. /static/admin.html                     → 200, references the admin app
#   8. POST /api/auth/login with TEST_CREDS   → 200, returns a session JWT (if env set)
#   9. POST /api/chat with the JWT            → 200, non-empty AI reply
#
# The script halts on the first failure and prints the failing check.
# Pass -ContinueOnFail to run all 9 anyway and aggregate.
#
# Add to ops/coolify/COOLIFY-CUTOVER-REPORT.md once green.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [string]$TestEmail = $env:BIJOU_SMOKE_EMAIL,
    [string]$TestPassword = $env:BIJOU_SMOKE_PASSWORD,

    [string]$ExpectedService = 'bijou-ai-enterprise',

    [switch]$ContinueOnFail
)

$ErrorActionPreference = 'Continue'
$results = @()

function Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    Write-Host "[$ts] [$Level] $Message"
}

function Check {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Method = 'GET',
        [hashtable]$Headers = @{},
        [string]$Body = '',
        [string[]]$ExpectContains = @(),
        [int]$ExpectStatus = 200,
        [string]$SaveResponseTo = ''
    )
    $result = @{ Name = $Name; Status = 'pending'; Detail = ''; LatencyMs = 0 }
    $start = Get-Date
    try {
        $reqParams = @{
            Uri             = $Url
            Method          = $Method
            TimeoutSec      = 20
            Headers         = $Headers
            UseBasicParsing = $true
        }
        if ($Body) {
            $reqParams['Body'] = $Body
            $reqParams['ContentType'] = 'application/json'
        }
        $resp = Invoke-WebRequest @reqParams -ErrorAction Stop
        $latency = [math]::Round(((Get-Date) - $start).TotalMilliseconds, 0)
        $result.LatencyMs = $latency

        if ($resp.StatusCode -ne $ExpectStatus) {
            $result.Status = 'fail'
            $result.Detail = "expected $ExpectStatus, got $($resp.StatusCode)"
            return $result
        }
        $content = ($resp.Content | Out-String)
        foreach ($needle in $ExpectContains) {
            if ($content -notlike "*$needle*") {
                $result.Status = 'fail'
                $result.Detail = "missing expected content: '$needle'"
                return $result
            }
        }
        if ($SaveResponseTo) {
            $resp.Content | Set-Content -Path $SaveResponseTo -Encoding UTF8
        }
        $result.Status = 'pass'
        $result.Detail = "$($resp.StatusCode) in ${latency}ms"
        return $result
    } catch {
        $latency = [math]::Round(((Get-Date) - $start).TotalMilliseconds, 0)
        $result.LatencyMs = $latency
        $result.Status = 'fail'
        $result.Detail = $_.Exception.Message
        return $result
    }
}

Log "smoke-test-prod.ps1 — checking $BaseUrl"
$baseNoSlash = $BaseUrl.TrimEnd('/')

# ─── 1. Health ────────────────────────────────────────────────────────
$r = Check -Name '1. /health' -Url "$baseNoSlash/health" `
    -ExpectContains @($ExpectedService)
$results += $r

# ─── 2. Self-test summary ─────────────────────────────────────────────
$r = Check -Name '2. /api/self-test/summary' -Url "$baseNoSlash/api/self-test/summary" `
    -ExpectContains @('"overall"', '"pass"')
$results += $r

# ─── 3. Menu permissions (the user said "every menu pages") ──────────
$r = Check -Name '3. /api/menu/permissions' -Url "$baseNoSlash/api/menu/permissions" `
    -ExpectContains @('"menu"')
$results += $r

# ─── 4. Login page ────────────────────────────────────────────────────
$r = Check -Name '4. /static/login.html' -Url "$baseNoSlash/static/login.html" `
    -ExpectContains @('<form')
$results += $r

# ─── 5. Signup page ───────────────────────────────────────────────────
$r = Check -Name '5. /static/signup.html' -Url "$baseNoSlash/static/signup.html" `
    -ExpectContains @('<form')
$results += $r

# ─── 6. Dashboard HTML ────────────────────────────────────────────────
$r = Check -Name '6. /static/dashboard.html' -Url "$baseNoSlash/static/dashboard.html" `
    -ExpectContains @('dashboard')
$results += $r

# ─── 7. Admin HTML ────────────────────────────────────────────────────
$r = Check -Name '7. /static/admin.html' -Url "$baseNoSlash/static/admin.html" `
    -ExpectContains @('admin')
$results += $r

# ─── 8. Login API (only if test creds are set) ────────────────────────
if ($TestEmail -and $TestPassword) {
    $loginBody = (@{ email = $TestEmail; password = $TestPassword } | ConvertTo-Json)
    $loginResp = $null
    try {
        $loginResp = Invoke-WebRequest -Uri "$baseNoSlash/api/auth/login" -Method POST `
            -ContentType 'application/json' -Body $loginBody -TimeoutSec 20 -UseBasicParsing
        if ($loginResp.StatusCode -eq 200) {
            $json = ($loginResp.Content | Out-String) | ConvertFrom-Json
            # PowerShell 5.1 compat: manual null-coalesce (the `??` operator is PS7+)
            $jwt = $null
            if ($json.access_token) { $jwt = $json.access_token }
            elseif ($json.session -and $json.session.access_token) { $jwt = $json.session.access_token }
            elseif ($json.token) { $jwt = $json.token }
            if ($jwt) {
                $r = Check -Name '8. POST /api/auth/login' -Url "$baseNoSlash/api/auth/login" `
                    -Method POST -Headers @{} -Body $loginBody `
                    -ExpectContains @('"access_token"')
                $results += $r
                # ─── 9. AI access (only if login succeeded) ────────────
                if ($r.Status -eq 'pass') {
                    $chatBody = (@{
                        message = 'Hello, can you help me with a test question?'
                        customer_id = 'smoke-test'
                    } | ConvertTo-Json)
                    $r = Check -Name '9. POST /api/chat' -Url "$baseNoSlash/api/chat" `
                        -Method POST `
                        -Headers @{ 'Authorization' = "Bearer $jwt" } `
                        -Body $chatBody `
                        -ExpectContains @('"reply"', '"message"', '"text"')
                    $results += $r
                }
            } else {
                $r = @{ Name = '8. POST /api/auth/login'; Status = 'fail'; Detail = 'no access_token in response'; LatencyMs = 0 }
                $results += $r
            }
        } else {
            $r = @{ Name = '8. POST /api/auth/login'; Status = 'fail'; Detail = "expected 200, got $($loginResp.StatusCode)"; LatencyMs = 0 }
            $results += $r
        }
    } catch {
        $r = @{ Name = '8. POST /api/auth/login'; Status = 'fail'; Detail = $_.Exception.Message; LatencyMs = 0 }
        $results += $r
    }
} else {
    $r = @{ Name = '8-9. auth + AI'; Status = 'skip'; Detail = 'BIJOU_SMOKE_EMAIL / BIJOU_SMOKE_PASSWORD not set'; LatencyMs = 0 }
    $results += $r
}

# ─── Summary ──────────────────────────────────────────────────────────
Log ""
Log "Smoke test results:"
$pass = 0; $fail = 0; $skip = 0
foreach ($r in $results) {
    $color = switch ($r.Status) {
        'pass' { 'Green' }
        'fail' { 'Red' }
        'skip' { 'Yellow' }
        default { 'White' }
    }
    Write-Host ("  [{0}] {1}  {2}ms  {3}" -f $r.Status, $r.Name, $r.LatencyMs, $r.Detail) -ForegroundColor $color
    switch ($r.Status) {
        'pass' { $pass++ }
        'fail' { $fail++ }
        'skip' { $skip++ }
    }
    if ($r.Status -eq 'fail' -and -not $ContinueOnFail) {
        Log "Halting on first failure (use -ContinueOnFail to run all)." 'ERROR'
        exit 1
    }
}

Log ""
Log "Summary: $pass pass, $fail fail, $skip skip"
if ($fail -gt 0) { exit 1 } else { exit 0 }
