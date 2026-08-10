# Supabase Token Rotation — Bijou Monorepo

**Why:** `sbp_<REDACTED-see-password-manager>` leaked in commit `e21b0cb` (`ops/_linter_fix_*.js`). Rotating kills the live secret; the historical commit stays in git but the token becomes inert.

---

## Role split

| Step | You | Me |
|---|---|---|
| 1. Generate new token (dashboard) | ✅ | |
| 2. Save new token to local file | ✅ | |
| 3. Hand off ("token saved, go") | ✅ | |
| 4. Update `.env` + scrub remaining hardcoded refs in `ops/` | | ✅ |
| 5. Run verification command | ✅ | |
| 6. Revoke old token (dashboard) | ✅ | |

---

## Step 1 — Generate new token

Open: https://supabase.com/dashboard/account/tokens

- Click **Generate new token**
- Name: `Bijou monorepo ops 2026-08-10`
- Copy the value (starts with `sbp_`, 40+ chars)

**Never paste the token in chat.**

## Step 2 — Save to local file

PowerShell:
```powershell
$dir = "$HOME\.config\bijou"
New-Item -ItemType Directory -Path $dir -Force | Out-Null
notepad "$dir\supabase_token"   # paste token, save, close
icacls "$dir\supabase_token" /inheritance:r /grant:r "${env:USERNAME}:(R,W)"
```

WSL bash:
```bash
mkdir -p ~/.config/bijou
nano ~/.config/bijou/supabase_token   # paste, Ctrl+O, Enter, Ctrl+X
chmod 600 ~/.config/bijou/supabase_token
```

## Step 3 — Hand off

Tell me: **"token saved, go"**. I will read the file, never chat.

## Step 4 — I update project files

I will:

1. Read `~/.config/bijou/supabase_token` to get the new value.
2. Replace the token in `C:\Users\W3jde\local-projects\bijou-monorepo\packages\landing\.env` (line `SUPABASE_ACCESS_TOKEN=...`).
3. `grep -r "sbp_42d6dbcf" ops/` to catch any remaining hardcoded refs in scripts that were committed before the earlier `ops/_scrub.js` run.
4. Rewrite each hit to use `process.env.SUPABASE_ACCESS_TOKEN` instead.
5. Report back with: files touched, remaining matches (should be 0), and a one-line summary.

## Step 5 — Verify

```powershell
cd C:\Users\W3jde\local-projects\bijou-monorepo
node ops/_supabase_linter_postcheck.js
```

Expected: `no further changes needed` (the linter fixes are already applied; this run only confirms the new token has the right access).

## Step 6 — Revoke old token

Open: https://supabase.com/dashboard/account/tokens

Find the row for `sbp_42d6dbcf...` and click **Revoke**. The old token is now dead.

---

## Troubleshooting

### New token has wrong scopes
**Symptom:** postcheck returns 401/403, or fails to list projects.
**Fix:**
1. Revoke the bad new token in the dashboard.
2. Regenerate, ensuring the Bijou project (or "All projects") is selected with the scopes the postcheck needs.
3. Repeat from Step 2.

### Ops scripts still hardcode the old token
**Symptom:** postcheck passes but a grep still finds `sbp_42d6dbcf` in `ops/`.
**Quick check:**
```powershell
cd C:\Users\W3jde\local-projects\bijou-monorepo
Select-String -Path ops\*.js -Pattern "sbp_42d6dbcf" -List
```
Send me the output — I will re-scrub and re-verify.

### GitHub still flags `e21b0cb`
Informational only once the token is revoked (the value is dead). GitHub re-evaluates secret scanning within ~90 days; the alert should clear on its own.
**To force-clear faster:**
- In your repo's **Security → Secret scanning** page, find the alert and click **"Mark as revoked"** or **"Request review"** (whichever GitHub shows).
- Rewrite history with `git-filter-repo` — destructive, ask me first; affects all clones and any open PRs.

---

## Quick reference

- **Old token (revoke after verify):** `sbp_<REDACTED-see-password-manager>`
- **New token storage:** `~/.config/bijou/supabase_token` (chmod 600 / icacls user-only)
- **New token home in repo:** `packages/landing/.env` → `SUPABASE_ACCESS_TOKEN=...`
- **Leaked commit:** `e21b0cb` (`ops/_linter_fix_*.js`)
- **Dashboard:** https://supabase.com/dashboard/account/tokens
