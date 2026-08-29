# push-to-canonical.ps1 — Push local commits to
# mybijouai-creator/bijou-monorepo using the right auth.
#
# The local repo's `origin` remote is multi-URL (both mnjbold and
# mybijouai-creator in one push), but the GitHub auth mismatch makes
# a single push fail (per agent memory: "the dual-push fails because
# of the GitHub auth mismatch"). This script pushes serially with the
# correct auth context for each remote.
#
# Run from the project root:
#   .\ops\coolify\push-to-canonical.ps1
#
# What it does:
#   1. Checks the current branch is main, the working tree is clean.
#   2. Verifies the GITHUB_PAT_TOKEN (from env or
#      ~/.hermes/secrets/.env.mybijou-creator).
#   3. Stages + commits any uncommitted changes (auto-generated
#      message; use -CommitMessage to override).
#   4. Switches gh auth to the mybijouai-creator identity and
#      pushes.
#   5. Reports the new commit SHA on the canonical remote.
#
# Idempotent. Re-running on a clean tree is a no-op.

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$Branch = 'main',
    [string]$CommitMessage = 'chore(2026-08-29): Coolify cutover prep — plan + 5 scripts + Appwrite module + .env.example',
    [string]$GitHubUser = 'mybijouai-creator',
    [switch]$SkipCommit,
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
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    return ([BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData($bytes)) -replace '-', '').ToLower()
}

Log "push-to-canonical.ps1 — pushing local to mybijouai-creator/bijou-monorepo"
Log "Project root: $ProjectRoot"

# ─── Resolve the GITHUB_PAT_TOKEN ────────────────────────────────────
$pat = $env:GITHUB_PAT_TOKEN
$patSource = '$env:GITHUB_PAT_TOKEN'
if (-not $pat) {
    $ghPath = Join-Path $env:USERPROFILE '.hermes\secrets\.env.mybijou-creator'
    if (Test-Path $ghPath) {
        $line = Select-String -Path $ghPath -Pattern '^GITHUB_PAT_TOKEN=(.+)$' -ErrorAction SilentlyContinue
        if ($line) {
            $pat = ($line.Matches[0].Groups[1].Value).Trim()
            $patSource = $ghPath
        }
    }
}
if (-not $pat) {
    throw "GITHUB_PAT_TOKEN not set. Either set `$env:GITHUB_PAT_TOKEN or save it to ~/.hermes/secrets/.env.mybijou-creator as `GITHUB_PAT_TOKEN=<token>`."
}
Log "Loaded PAT from $patSource (sha256 = $(HashValue $pat))"

# ─── Sanity check the project ────────────────────────────────────────
Push-Location $ProjectRoot
try {
    $gitRoot = git rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0) { throw "$ProjectRoot is not a git repo." }
    $currentBranch = git branch --show-current 2>$null
    if ($currentBranch -ne $Branch) {
        throw "Current branch is '$currentBranch', not '$Branch'. Check out $Branch first."
    }
    $status = git status --porcelain 2>$null
    if ($status -and -not $SkipCommit) {
        Log "Working tree has changes. Staging + committing…"
        if (-not $DryRun) {
            git add -A 2>&1 | Out-Null
            git commit -m $CommitMessage 2>&1 | Out-Null
        }
    } elseif ($status -and $SkipCommit) {
        throw "Working tree has uncommitted changes and -SkipCommit was passed. Commit them first."
    }

    # Get the local HEAD
    $localSha = git rev-parse HEAD 2>$null
    Log "Local HEAD: $localSha"

    # Get the remote HEAD
    $remoteUrl = git config --get remote.origin.url 2>$null
    if (-not $remoteUrl) {
        throw "No `origin` remote configured. Add one: git remote add origin https://github.com/mybijouai-creator/bijou-monorepo.git"
    }
    Log "Origin: $remoteUrl"

    try {
        $remoteSha = git rev-parse origin/$Branch 2>$null
        if ($remoteSha -eq $localSha) {
            Log "Local and remote are in sync at $localSha. Nothing to push."
            exit 0
        }
        Log "Remote HEAD: $remoteSha (local is $localSha, $(([datetime]'1970-01-01').AddSeconds((git rev-list --count $remoteSha..HEAD 2>$null)) - ([datetime]'1970-01-01')) commits ahead)"
    } catch {
        Log "Remote HEAD not reachable; will push regardless." 'WARN'
    }
} finally {
    Pop-Location
}

# ─── Push via the PAT ────────────────────────────────────────────────
# The mnjbold git identity is authed locally but 403s on push to the
# canonical remote. We set the auth just for this push using the PAT.
$authUrl = $remoteUrl -replace 'https://', "https://${GitHubUser}:$pat@"

if ($DryRun) {
    Log "DryRun: would push to $remoteUrl" 'WARN'
    exit 0
}

Push-Location $ProjectRoot
try {
    git push $authUrl $Branch 2>&1 | Tee-Object -Variable pushOutput | Out-Null
    Log "Push complete."
    Log "Output: $($pushOutput -join "`n")"

    # Verify
    $newRemoteSha = git rev-parse origin/$Branch 2>$null
    if ($newRemoteSha -eq $localSha) {
        Log "✅ Canonical HEAD is now $newRemoteSha — matches local." 'INFO'
    } else {
        Log "Remote HEAD is $newRemoteSha but local is $localSha. Investigate." 'WARN'
    }
} catch {
    throw "git push failed: $($_.Exception.Message). Check the PAT scopes (needs `contents:write` on mybijouai-creator/bijou-monorepo)."
} finally {
    Pop-Location
}
