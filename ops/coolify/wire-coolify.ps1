# wire-coolify.ps1 — Wire the Bijou project into a Coolify instance
# and add the manual GitHub webhook that triggers auto-deploys.
#
# This is the first script in the cutover sequence. See
# ops/coolify/PRODUCTION-CUTOVER-PLAN.md section 3 step 1.
#
# What it does (in order):
#   1. Verifies the Coolify token by hitting /api/v1/version.
#   2. Creates a private Docker Compose application in Coolify pointed
#      at mybijouai-creator/bijou-monorepo, branch main, compose file
#      docker-compose.coolify.yml.
#   3. Adds the manual GitHub webhook on the repo (HMAC-SHA256 signed)
#      so pushes to main trigger a Coolify auto-build + deploy.
#   4. Writes ops/coolify/COOLIFY-CUTOVER-REPORT.md with the resulting
#      app UUID, deploy URL, webhook URL, and webhook secret hash.
#
# Idempotent. NEVER echoes the Coolify access token or webhook secret.

[CmdletBinding()]
param(
    [string]$CoolifyBaseUrl = 'https://coolify.getbijou.xyz',
    [string]$CoolifyToken = $env:COOLIFY_TOKEN,
    [string]$GitHubOrg = 'mybijouai-creator',
    [string]$GitHubRepo = 'bijou-monorepo',
    [string]$GitHubToken = $env:GITHUB_PAT_TOKEN,
    [string]$WebhookSecret = $env:COOLIFY_WEBHOOK_SECRET,
    [string]$AppName = 'bijou-prod',
    [string]$ComposeFile = 'docker-compose.coolify.yml',
    [string]$Branch = 'main',
    [string]$BaseDirectory = '/',
    [switch]$WhatIf = $false,
    [switch]$SkipGitHub
)

$ErrorActionPreference = 'Stop'
$reportLines = @()
$reportPath = Join-Path $PSScriptRoot 'COOLIFY-CUTOVER-REPORT.md'

function Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = '[' + (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz') + '] [' + $Level + '] ' + $Message
    Write-Host $line
    $script:reportLines += $line
}

function HashValue {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '<unset>' }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        $hash = $sha.ComputeHash($bytes)
        return ([BitConverter]::ToString($hash) -replace '-', '').ToLower()
    } finally {
        $sha.Dispose()
    }
}

Log 'wire-coolify.ps1 - Bijou Coolify wire-up'
Log ('Coolify base: ' + $CoolifyBaseUrl)
Log ('GitHub target: ' + $GitHubOrg + '/' + $GitHubRepo + '@' + $Branch)
Log ('Compose file: ' + $ComposeFile + ' (base dir: ' + $BaseDirectory + ')')

if (-not $CoolifyToken) {
    $mcpPath = Join-Path $env:USERPROFILE '.hermes\mcp_config.json'
    if (Test-Path $mcpPath) {
        try {
            $mcp = Get-Content $mcpPath -Raw | ConvertFrom-Json
            $CoolifyToken = $mcp.mcpServers.coolify.env.COOLIFY_ACCESS_TOKEN
            Log ('Loaded Coolify token from ' + $mcpPath + ' (sha256 = ' + (HashValue $CoolifyToken) + ')')
        } catch {
            throw ('Failed to read Coolify token from ' + $mcpPath + ' : ' + $_.Exception.Message)
        }
    } else {
        throw 'Coolify token not provided. Set the COOLIFY_TOKEN env var, or pass -CoolifyToken, or ensure mcp_config.json exists.'
    }
}

if (-not $WebhookSecret) {
    $WebhookSecret = -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
    Log ('Generated new webhook secret (sha256 = ' + (HashValue $WebhookSecret) + ')')
    Log 'Save this to your .env: COOLIFY_WEBHOOK_SECRET=<the value>'
}

if (-not $GitHubToken -and -not $SkipGitHub) {
    $ghPath = Join-Path $env:USERPROFILE '.hermes\secrets\.env.mybijou-creator'
    if (Test-Path $ghPath) {
        $line = Select-String -Path $ghPath -Pattern '^GITHUB_PAT_TOKEN=(.+)$' -ErrorAction SilentlyContinue
        if ($line) {
            $GitHubToken = ($line.Matches[0].Groups[1].Value).Trim()
            Log ('Loaded GitHub PAT from ' + $ghPath + ' (sha256 = ' + (HashValue $GitHubToken) + ')')
        }
    }
    if (-not $GitHubToken) {
        $hermesEnv = Join-Path $env:USERPROFILE '.hermes\.env'
        if (Test-Path $hermesEnv) {
            $line = Select-String -Path $hermesEnv -Pattern '^GITHUB_TOKEN="?([^"\r\n]+)"?\s*$' -ErrorAction SilentlyContinue
            if ($line) {
                $GitHubToken = ($line.Matches[0].Groups[1].Value).Trim()
                Log ('Loaded GitHub PAT from ' + $hermesEnv + ' (sha256 = ' + (HashValue $GitHubToken) + ')')
            }
        }
    }
    if (-not $GitHubToken) {
        Log 'No GITHUB_PAT_TOKEN found. The webhook step will be skipped - add it manually in GitHub repo settings.' 'WARN'
    }
}

$coolifyHeaders = @{
    'Authorization' = 'Bearer ' + $CoolifyToken
    'Content-Type'  = 'application/json'
    'Accept'        = 'application/json'
}

# Step 1: Verify Coolify auth
Log 'Step 1/4 - Verifying Coolify auth...'
try {
    $version = Invoke-RestMethod -Uri ($CoolifyBaseUrl + '/api/v1/version') -Headers $coolifyHeaders -Method GET -TimeoutSec 15
    Log ('Coolify reachable. Version: ' + ($version | ConvertTo-Json -Compress))
} catch {
    throw ('Coolify auth failed: ' + $_.Exception.Message + '. Check -CoolifyToken.')
}

# Step 2: Create or reuse the Coolify app
Log ('Step 2/4 - Reconciling Coolify application ' + $AppName + '...')
$apps = Invoke-RestMethod -Uri ($CoolifyBaseUrl + '/api/v1/applications') -Headers $coolifyHeaders -Method GET -TimeoutSec 30
$existing = $apps | Where-Object {
    $_.name -eq $AppName -and ($_.git_repository -like ('*' + $GitHubOrg + '/' + $GitHubRepo + '*'))
} | Select-Object -First 1

if ($existing) {
    $appUuid = $existing.uuid
    Log ('Reusing existing app uuid=' + $appUuid + ' name=' + $existing.name)
} else {
    if ($WhatIf) {
        Log ('Would create new Coolify app ' + $AppName + '.') 'WARN'
        return
    }
    $createBody = @{
        name                  = $AppName
        description           = 'Bijou AI production stack (backend + bridge + langfuse).'
        environment_name      = 'production'
        git_repository        = ('https://github.com/' + $GitHubOrg + '/' + $GitHubRepo)
        git_branch            = $Branch
        git_commit_sha        = 'HEAD'
        base_directory        = $BaseDirectory
        docker_compose_location = $ComposeFile
        build_pack            = 'docker-compose'
        ports_exposes         = '8080'
    } | ConvertTo-Json -Depth 5
    $created = Invoke-RestMethod -Uri ($CoolifyBaseUrl + '/api/v1/applications') -Headers $coolifyHeaders -Method POST -Body $createBody -TimeoutSec 60
    $appUuid = $created.uuid
    Log ('Created Coolify app uuid=' + $appUuid)
}

# Step 3: Wire the manual GitHub webhook
if (-not $SkipGitHub) {
    Log 'Step 3/4 - Reconciling GitHub webhook...'
    $webhookUrl = $CoolifyBaseUrl + '/webhooks/source/github/events/manual'
    $webhookBodyJson = @{
        name   = 'web'
        active = $true
        events = @('push')
        config = @{
            url          = $webhookUrl
            content_type = 'json'
            secret       = $WebhookSecret
            insecure_ssl = '0'
        }
    } | ConvertTo-Json -Depth 6

    if ($GitHubToken) {
        $ghHeaders = @{
            'Authorization'        = 'Bearer ' + $GitHubToken
            'Accept'               = 'application/vnd.github+json'
            'X-GitHub-Api-Version' = '2022-11-28'
            'Content-Type'         = 'application/json'
            'User-Agent'           = 'bijou-wire-coolify'
        }
        $existingHooks = Invoke-RestMethod -Uri ('https://api.github.com/repos/' + $GitHubOrg + '/' + $GitHubRepo + '/hooks') -Headers $ghHeaders -Method GET -TimeoutSec 30
        $matched = $existingHooks | Where-Object { $_.config.url -eq $webhookUrl } | Select-Object -First 1
        if ($matched) {
            Invoke-RestMethod -Uri ('https://api.github.com/repos/' + $GitHubOrg + '/' + $GitHubRepo + '/hooks/' + $matched.id) -Headers $ghHeaders -Method PATCH -Body $webhookBodyJson -TimeoutSec 30 | Out-Null
            Log ('Updated existing webhook id=' + $matched.id)
        } else {
            Invoke-RestMethod -Uri ('https://api.github.com/repos/' + $GitHubOrg + '/' + $GitHubRepo + '/hooks') -Headers $ghHeaders -Method POST -Body $webhookBodyJson -TimeoutSec 30 | Out-Null
            Log 'Created new webhook.'
        }
    } else {
        Log ('Skipped webhook mutation (no GitHub token). Manual setup URL: ' + $webhookUrl + ' - secret sha256: ' + (HashValue $WebhookSecret)) 'WARN'
    }
} else {
    Log 'Step 3/4 - Skipped (--SkipGitHub).'
}

# Step 4: Write the report
Log ('Step 4/4 - Writing ' + $reportPath)
$deployUrl = $CoolifyBaseUrl + '/project/' + $appUuid
$coolifyFingerprint = HashValue $CoolifyToken
$githubFingerprint = if ($GitHubToken) { HashValue $GitHubToken } else { '<not provided>' }
$runLog = ($reportLines -join "`n")

$reportContent = @"
# Bijou Coolify cutover - wire-up report

_Generated $(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz') by wire-coolify.ps1._

## Coolify application
- **UUID**: `$appUuid`
- **Name**: `$AppName`
- **Repository**: `https://github.com/$GitHubOrg/$GitHubRepo`
- **Branch**: `$Branch`
- **Compose file**: `$ComposeFile` (base dir: `$BaseDirectory`)
- **Deploy URL**: $deployUrl

## GitHub webhook
- **URL**: `$webhookUrl`
- **Events**: `push`
- **Secret sha256**: `$(HashValue $WebhookSecret)`  save the real secret in your password manager; the wire script does not echo it

## Token fingerprints (sha256, for audit only)
- Coolify access token: `$coolifyFingerprint`
- GitHub PAT: `$githubFingerprint`

## Run log
$runLog

---

## Next steps
1. Run `ops/coolify/migrate-secrets-to-coolify.ps1` to populate the env group.
2. Trigger a deploy (push to main, or POST /api/v1/applications/{uuid}/deploy).
3. Run `ops/coolify/smoke-test-prod.ps1` to verify the 9 checks.
4. When green, run `ops/coolify/porkbun-cutover.ps1 -ConfirmCutover` to flip DNS.

See `ops/coolify/PRODUCTION-CUTOVER-PLAN.md` for the full sequence.
"@
Set-Content -Path $reportPath -Value $reportContent -Encoding UTF8
Log ('Done. App UUID: ' + $appUuid)
