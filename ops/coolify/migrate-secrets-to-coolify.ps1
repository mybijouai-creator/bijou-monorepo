# migrate-secrets-to-coolify.ps1 — Populate a Coolify env group from a
# local .env file. Optionally mirror the same values to Infisical.
#
# This is step 2 in the cutover sequence. See
# ops/coolify/PRODUCTION-CUTOVER-PLAN.md §3 step 2.
#
# What it does:
#   1. Reads the local .env file (gitignored, line format: KEY=value).
#   2. POSTs each var to the Coolify env group via
#      POST /api/v1/envs (key + value + is_required).
#   3. If INFISICAL_TOKEN is set, mirrors the same vars to Infisical
#      via the v3 API (or self-hosted if INFISICAL_HOST is set).
#   4. Never logs the value of any secret — only the var name and a
#      sha256 of the value (so the run log proves what was set).
#
# The script is idempotent. Re-running with new values updates the
# existing entries in Coolify. Infisical supports create-or-update by
# secret name.
#
# Also handles the legacy Bijou 'settings.json' format (the
# invalid-JSON unquoted k=v strings) via a regex fallback, so the
# user's hand-edited settings.json at the project root can be used as
# a source if needed.

[CmdletBinding()]
param(
    [string]$EnvFilePath = "$PSScriptRoot\..\..\.env",
    [string]$CoolifyBaseUrl = 'https://coolify.getbijou.xyz',
    [string]$CoolifyToken = $env:COOLIFY_TOKEN,
    [string]$EnvGroupName = 'bijou-prod',
    [string]$InfisicalHost = 'https://app.infisical.com',
    [string]$InfisicalToken = $env:INFISICAL_TOKEN,
    [string]$InfisicalProjectId = $env:INFISICAL_PROJECT_ID,
    [string]$InfisicalEnvironment = 'production',
    [string[]]$IncludeOnly = @(),  # if non-empty, only these keys are migrated
    [string[]]$Exclude = @('COOLIFY_TOKEN', 'GITHUB_PAT_TOKEN'),  # never push these
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    Write-Host "[$ts] [$Level] $Message"
}

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

function Parse-DotenvFile {
    # Returns a hashtable of KEY -> value. Tries 3 formats in order:
    # 1. Standard .env (KEY=value, # comments, optional quotes)
    # 2. Loose k=v (also handles the .env.porkbun format: "API Key:=value" or "Key\tvalue")
    # 3. Tab-separated (.env.xyz format: KEY<tab>VALUE)
    param([string]$Path, [string]$Hint = '')
    if (-not (Test-Path $Path)) { return @{} }
    $content = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $map = @{}
    # JSON first (works for .env.json, settings.json, mcp_config.json)
    if ($content -match '^\s*\{') {
        try {
            $j = $content | ConvertFrom-Json -ErrorAction Stop
            foreach ($p in $j.PSObject.Properties) {
                $map[$p.Name] = [string]$p.Value
            }
            return $map
        } catch {}
    }
    # Tab-separated (used by .env.xyz)
    if ($Hint -eq 'xyz' -or ($content -match "`t" -and $content -notmatch "`r?`n.*=.*`r?`n.*=")) {
        foreach ($raw in ($content -split "`r?`n")) {
            $line = $raw.TrimEnd()
            if (-not $line) { continue }
            if ($line.StartsWith('#') -or $line.StartsWith('//')) { continue }
            $parts = $line -split "`t"
            $key = ($parts[0]).Trim()
            if (-not $key -or $key.Contains(' ')) { continue }
            $value = ($parts[1..($parts.Length - 1)] -join "`t").Trim()
            if (-not $value) { continue }
            $map[$key] = $value
        }
        if ($map.Count -gt 0) { return $map }
    }
    # Standard dotenv
    $lineRegex = [regex]'(?m)^\s*"?([A-Za-z][A-Za-z0-9_./-]*)"?\s*[:=]\s*"?([^"\r\n]*)"?\s*$'
    foreach ($m in $lineRegex.Matches($content)) {
        $k = $m.Groups[1].Value
        $v = $m.Groups[2].Value
        if ($k.StartsWith('#')) { continue }
        if ($map.ContainsKey($k)) { continue }
        $map[$k] = $v
    }
    return $map
}

# ─── Pre-flight ───────────────────────────────────────────────────────
Log "migrate-secrets-to-coolify.ps1 — Coolify env group: $EnvGroupName"

if (-not $CoolifyToken) {
    $mcpPath = Join-Path $env:USERPROFILE '.hermes\mcp_config.json'
    if (Test-Path $mcpPath) {
        $mcp = Get-Content $mcpPath -Raw | ConvertFrom-Json
        $CoolifyToken = $mcp.mcpServers.coolify.env.COOLIFY_ACCESS_TOKEN
        Log "Loaded Coolify token from $mcpPath (sha256 = $(HashValue $CoolifyToken))"
    } else {
        throw "No Coolify token. Set $env:COOLIFY_TOKEN or pass -CoolifyToken."
    }
}

# ─── Resolve env-file candidates ─────────────────────────────────────
# Order matters: later files override earlier ones. Hermes canonical
# .env wins over Bijou .env wins over .env.porkbun wins over .env.xyz
# (Hermes .env is the cleaned, deduplicated master).
$candidates = @()
if ($EnvFilePath) { $candidates += @{ p = $EnvFilePath; hint = '' } }

# 1. The Bijou production .env at the project root.
$projectEnv = Join-Path $PSScriptRoot '..\..\.env'
if (Test-Path $projectEnv) { $candidates += @{ p = $projectEnv; hint = '' } }

# 2. The user's older "settings.json" at the project root (invalid JSON, has the Appwrite creds).
$settingsJson = Join-Path $PSScriptRoot '..\..\settings.json'
if (Test-Path $settingsJson) { $candidates += @{ p = $settingsJson; hint = '' } }

# 3. The canonical Hermes credential vault (the cleaned, deduplicated
#    master generated by wire_env_xyz.py).
$hermesEnv = Join-Path $env:USERPROFILE '.hermes\.env'
if (Test-Path $hermesEnv) { $candidates += @{ p = $hermesEnv; hint = '' } }

# 4. The raw .env.xyz (Porkbun + everything else, in tab-separated format).
$hermesXyz = Join-Path $env:USERPROFILE '.hermes\secrets\.env.xyz'
if (Test-Path $hermesXyz) { $candidates += @{ p = $hermesXyz; hint = 'xyz' } }

# 5. The Porkbun-specific file (we KNOW this contains the Porkbun key).
$hermesPorkbun = Join-Path $env:USERPROFILE '.hermes\secrets\.env.porkbun'
if (Test-Path $hermesPorkbun) { $candidates += @{ p = $hermesPorkbun; hint = '' } }

# 6. The GitHub PAT specifically (GITHUB_PAT_TOKEN).
$hermesGHPat = Join-Path $env:USERPROFILE '.hermes\secrets\.env.mybijou-creator'
if (Test-Path $hermesGHPat) { $candidates += @{ p = $hermesGHPat; hint = '' } }

# 7. The opaque tokens.
$hermesBijouToken = Join-Path $env:USERPROFILE '.hermes\secrets\bijou-internal-api-token'
if (Test-Path $hermesBijouToken) {
    $candidates += @{ p = $hermesBijouToken; hint = 'opaque' }
}

if ($candidates.Count -eq 0) {
    throw "No env file found. Tried: Bijou project .env, .hermes\.env, .hermes\secrets\.env.*, settings.json."
}
Log "Will merge $($candidates.Count) source files (later overrides earlier):"
foreach ($c in $candidates) { Log "  - $($c.p)" }

# ─── Merge all candidates into a single env map ─────────────────────
$envMap = @{}
foreach ($c in $candidates) {
    $hint = $c.hint
    if ($hint -eq 'opaque') {
        # Special: the file is just a single token. Map it to the well-known
        # var name the code reads.
        $tok = (Get-Content -LiteralPath $c.p -Raw -Encoding UTF8).Trim()
        if ($tok) {
            $envMap['BIJOU_INTERNAL_API_TOKEN'] = $tok
            Log "  + opaque token $c.p → BIJOU_INTERNAL_API_TOKEN (sha256 = $(HashValue $tok))"
        }
        continue
    }
    $partial = Parse-DotenvFile -Path $c.p -Hint $hint
    Log "  + $c.p → $($partial.Count) keys"
    foreach ($k in $partial.Keys) {
        $envMap[$k] = $partial[$k]
    }
}

if (Test-Path $hermesPorkbun) {
    # The .env.porkbun file uses non-standard labels: "API Key:=" and "Secret Key=".
    # Normalize them to the canonical names the cutover scripts read.
    $pork = Parse-DotenvFile -Path $hermesPorkbun
    if ($pork.ContainsKey('API Key')) {
        $envMap['PORKBUN_API_KEY'] = $pork['API Key']
    }
    if ($pork.ContainsKey('Secret Key')) {
        $envMap['PORKBUN_SECRET_KEY'] = $pork['Secret Key']
    }
    Log "  + Porkbun keys normalized to PORKBUN_API_KEY / PORKBUN_SECRET_KEY"
}

if (Test-Path $hermesGHPat) {
    # .env.mybijou-creator contains GITHUB_PAT_TOKEN=value (single line, already standard).
    $gh = Parse-DotenvFile -Path $hermesGHPat
    if ($gh.ContainsKey('GITHUB_PAT_TOKEN')) {
        $envMap['GITHUB_PAT_TOKEN'] = $gh['GITHUB_PAT_TOKEN']
        Log "  + GITHUB_PAT_TOKEN loaded from .env.mybijou-creator"
    }
}

if ($envMap.Count -eq 0) {
    throw "Parsed 0 keys across all candidate files. File format is unexpected."
}
Log "Merged env map: $($envMap.Count) unique keys."

# ─── Parse the env file ──────────────────────────────────────────────
$envMap = @{}
$content = Get-Content -LiteralPath $found -Raw -Encoding UTF8

# Try JSON first (for settings.json-like files, even if malformed)
try {
    $json = $content | ConvertFrom-Json -ErrorAction Stop
    foreach ($prop in $json.PSObject.Properties) {
        $envMap[$prop.Name] = [string]$prop.Value
    }
    Log "Parsed as JSON ($(($envMap.Keys).Count) keys)"
} catch {
    # Fall back to regex for the legacy unquoted k=v format
    $regex = [regex]'(?m)^\s*"?([A-Z][A-Z0-9_]+)\s*=\s*"?([^"\r\n]+)"?\s*$'
    foreach ($m in $regex.Matches($content)) {
        $envMap[$m.Groups[1].Value] = $m.Groups[2].Value.Trim()
    }
    Log "Parsed as loose k=v ($(($envMap.Keys).Count) keys)"
}

# Also handle standard dotenv format if it didn't match
if (($envMap.Keys).Count -eq 0) {
    $lineRegex = [regex]'(?m)^\s*([A-Z][A-Z0-9_]+)\s*=\s*(.*?)\s*$'
    foreach ($line in ($content -split "`r?`n")) {
        if ($line -match '^\s*#' -or [string]::IsNullOrWhiteSpace($line)) { continue }
        $m = $lineRegex.Match($line)
        if ($m.Success) { $envMap[$m.Groups[1].Value] = $m.Groups[2].Value.Trim('"').Trim("'") }
    }
    Log "Parsed as dotenv ($(($envMap.Keys).Count) keys)"
}

if (($envMap.Keys).Count -eq 0) {
    throw "Parsed 0 keys from $found. The file appears empty or unparseable."
}

# Apply filters
if ($IncludeOnly.Count -gt 0) {
    $envMap = @{} + ($envMap.GetEnumerator() | Where-Object { $IncludeOnly -contains $_.Key })
    Log "Filtered to $($IncludeOnly.Count) include keys. Final count: $(($envMap.Keys).Count)"
}
foreach ($ex in $Exclude) {
    if ($envMap.ContainsKey($ex)) {
        $envMap.Remove($ex)
        Log "Excluded '$ex' from migration" 'WARN'
    }
}

Log "Will migrate $(($envMap.Keys).Count) keys."

# ─── Resolve the Coolify env-group UUID ──────────────────────────────
$coolifyHeaders = @{
    'Authorization' = "Bearer $CoolifyToken"
    'Content-Type'  = 'application/json'
}

$envGroups = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/envs" `
    -Headers $coolifyHeaders -Method GET -TimeoutSec 30
$group = $envGroups | Where-Object { $_.name -eq $EnvGroupName } | Select-Object -First 1
if (-not $group) {
    if ($DryRun) {
        Log "DryRun: would create env group '$EnvGroupName'" 'WARN'
        $groupUuid = 'dry-run-uuid'
    } else {
        $created = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/envs" `
            -Headers $coolifyHeaders -Method POST `
            -Body (@{ name = $EnvGroupName } | ConvertTo-Json) -TimeoutSec 30
        $groupUuid = $created.uuid
        Log "Created env group uuid=$groupUuid"
    }
} else {
    $groupUuid = $group.uuid
    Log "Reusing env group uuid=$groupUuid"
}

# ─── Push to Coolify ──────────────────────────────────────────────────
$coolifyCount = 0
foreach ($kvp in $envMap.GetEnumerator()) {
    $body = @{
        key         = $kvp.Key
        value       = $kvp.Value
        is_required = $true
        is_runtime  = $true
    } | ConvertTo-Json -Depth 3
    if ($DryRun) {
        Log "DryRun: would POST $CoolifyBaseUrl/api/v1/envs/$groupUuid key=$($kvp.Key) sha256=$(HashValue $kvp.Value)"
    } else {
        try {
            Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/envs/$groupUuid" `
                -Headers $coolifyHeaders -Method POST -Body $body -TimeoutSec 15 | Out-Null
            $coolifyCount++
        } catch {
            # If the key already exists, PATCH instead
            $existingList = Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/envs/$groupUuid" `
                -Headers $coolifyHeaders -Method GET -TimeoutSec 15
            $existingKey = $existingList | Where-Object { $_.key -eq $kvp.Key } | Select-Object -First 1
            if ($existingKey) {
                Invoke-RestMethod -Uri "$CoolifyBaseUrl/api/v1/envs/$groupUuid/$($existingKey.uuid)" `
                    -Headers $coolifyHeaders -Method PATCH -Body $body -TimeoutSec 15 | Out-Null
                $coolifyCount++
            } else {
                Log "Failed to push $($kvp.Key): $($_.Exception.Message)" 'ERROR'
            }
        }
    }
    # Brief log without the value
    Log "  $kvp.Key → Coolify (sha256=$(HashValue $kvp.Value))"
}
Log "Pushed $coolifyCount / $(($envMap.Keys).Count) keys to Coolify."

# ─── Mirror to Infisical (optional) ──────────────────────────────────
$infisicalCount = 0
if ($InfisicalToken -and $InfisicalProjectId -and -not $DryRun) {
    Log "Mirroring to Infisical at $InfisicalHost (project $InfisicalProjectId, env $InfisicalEnvironment)…"
    $infHeaders = @{
        'Authorization' = "Bearer $InfisicalToken"
        'Content-Type'  = 'application/json'
    }
    foreach ($kvp in $envMap.GetEnumerator()) {
        $body = @{
            secretName   = $kvp.Key
            secretValue  = $kvp.Value
            projectId    = $InfisicalProjectId
            environment  = $InfisicalEnvironment
            secretPath   = '/'
            type         = 'shared'
        } | ConvertTo-Json
        try {
            Invoke-RestMethod -Uri "$InfisicalHost/api/v3/secrets/$InfisicalProjectId/$InfisicalEnvironment/create" `
                -Headers $infHeaders -Method POST -Body $body -TimeoutSec 15 | Out-Null
            $infisicalCount++
        } catch {
            # Try update path
            try {
                $list = Invoke-RestMethod -Uri "$InfisicalHost/api/v3/secrets/$InfisicalProjectId/$InfisicalEnvironment?secretPath=/" `
                    -Headers $infHeaders -Method GET -TimeoutSec 15
                $match = $list.secrets | Where-Object { $_.secretKey -eq $kvp.Key } | Select-Object -First 1
                if ($match) {
                    $upd = @{ secretValue = $kvp.Value } | ConvertTo-Json
                    Invoke-RestMethod -Uri "$InfisicalHost/api/v3/secrets/$($match.id)" `
                        -Headers $infHeaders -Method PATCH -Body $upd -TimeoutSec 15 | Out-Null
                    $infisicalCount++
                } else {
                    Log "Infisical update failed for $($kvp.Key): $($_.Exception.Message)" 'ERROR'
                }
            } catch {
                Log "Infisical both create+update failed for $($kvp.Key): $($_.Exception.Message)" 'ERROR'
            }
        }
    }
    Log "Mirrored $infisicalCount / $(($envMap.Keys).Count) keys to Infisical."
} elseif ($DryRun) {
    Log "DryRun: would mirror to Infisical (not actually called)" 'WARN'
} else {
    Log "Infisical token not set; skipping mirror. (Set $env:INFISICAL_TOKEN to enable.)" 'WARN'
}

Log "Done. Coolify: $coolifyCount. Infisical: $infisicalCount. Total keys: $(($envMap.Keys).Count)."
