# SECURITY ALERT — Admin API Key Exposure (2026-08-24)

**Severity:** P0 — Live admin key committed in git history.

## What happened

On 2026-08-10, commit 1e718eb (docs: ADMIN_API_KEY for bijou-production admin endpoints) wrote
the production Bijou admin API key to docs/ADMIN_API_KEY.txt and committed it to
mybijouai-creator/bijou-monorepo. The file was NOT in .gitignore at the time.

The key is the credential that gates all /api/admin/* endpoints (per the dmin_frontend_api
gated by X-Admin-Key header). Anyone with read access to the canonical GitHub repo — including
any historical contributor or anyone who forked it before the scrub — could call the admin API.

## What we did today (2026-08-24)

1. **Verified the leak** (independent verifier, docs/DEPLOYMENT_BLOCKERS_2026-08-24.md).
2. **Added the path to .gitignore** — docs/ADMIN_API_KEY.txt, plus wildcards for any future copies.
3. **Removed the file from git tracking** (git rm --cached).
4. **Rewrote the git history with git filter-repo** to scrub the file from every past commit.
5. **Force-pushed** the scrubbed history to mybijouai-creator (overwrite of 1e718eb and everything after).
6. **This SECURITY_ALERT doc** (committed, public, in the security log).

## What YOU must do (owner actions)

These cannot be done from code — they require the platform owners:

1. **Rotate the key in the admin panel** immediately. The deployment blocker report listed the
   leaked value (do not echo it back here). After rotation, the old key is dead and the new one
   must be set as a Fly secret: ly secrets set ADMIN_API_KEY=<new-value> -a bijou-production
   and updated in pp.mybijou.xyz/admin localStorage.
2. **Audit admin access logs** for any unfamiliar IP / no-agent / cross-region calls between
   2026-08-10 and 2026-08-24.
3. **Notify the 5 known read-only collaborators** (per git log --pretty=format:'%an <%ae>' for
   the affected commits) that historical clones may still contain the key in their local history.
4. **Force all collaborators to re-clone** or run git pull --rebase + the same filter-repo
   command locally.

## Going forward

- docs/ADMIN_API_KEY.txt is now in .gitignore. So is **/admin_api_key* and any
  **/ADMIN_API_KEY* variants.
- Future secrets MUST be in .env (gitignored) or in the platform's secret manager
  (Fly secrets, Supabase vault, etc.) — NEVER in the repo.
- The dmin_frontend_api (planned via the in-flight admin-frontend worker) will read the
  key from environment only, never from a tracked file.

## Post-mortem

- **Why did this happen?** The dev workflow stored an admin credential in a doc file for easy
  copy-paste into Fly secrets and the operator's localStorage. The file was never in
  .gitignore.
- **Why was the leak missed for 14 days?** Self-test checks verify Supabase + Gemini + Stripe
  configs but do not scan the repo for committed secrets. Adding a git secrets (or
  gitleaks) pre-commit hook + a CI step is queued as a follow-up.
- **What's the blast radius?** Admin endpoints include: view all tenants, impersonate users,
  issue refunds, apply migrations, run any tenant mutation. The key does NOT directly
  bypass Supabase RLS (the service-role key would do that, and that is stored only in .env
  which is gitignored). The admin key is a layer above RLS for admin-tool operations.
