# Deployment Blockers � 2026-08-24

**Author:** Independent SRE-style investigation (Verifier agent).
**Scope:** Why isn't Bijou AI in production today? What are the *real*
blockers, and which ones are not what they look like?
**Date:** 2026-08-24 (Asia/Kuala_Lumpur)
**Repo state at time of investigation:** local `main` = remote
`mybijouai-creator/main` = `22a5ed4` (in sync). 4 uncommitted
modifications under `packages/backend/` (apply_migrations, email_service,
email_templates, stripe_service, static/pricing.html) and a swarm of
untracked `.claude/agents/*.md` and `.agents/` files (not in scope here).

---

## 0. TL;DR

Three of the five "known blockers" are real but over-stated, one is
factually wrong, and one is a misnomer for a different problem. The
**bigger blockers** are not on the user's list: a live admin API key
in git history, a stale `PUBLIC_URL` in the `.env` that would
re-trigger the 2026-08-10 bug class, a bridge whose deploy config
points webhooks at a dead Fly app, a missing
`docker-compose.bridge-only.yml` that the runbook says is required
for per-tenant rollout, zero alerting on top of the self-test, and
no database backup plan that survives the Coolify host dying. None
of the five known blockers are actually a deploy-stopper for the
Coolify path � Coolify doesn't need Fly.io or GitHub Actions at all.
The system can be deployed today, but only after a 2-3 hour
"housekeeping" sprint; the per-tenant bridge and the security cleanup
are each an additional sprint.

---


## 1. The five "known blockers" � verified, refuted, or qualified

### 1.1 Fly.io billing locked (claimed)

**Status: PARTIALLY REAL, but not the deploy stopper the user thinks.**

- **Evidence:** CLAUDE.md states `flyctl deploy` returns `403: Your
  account has overdue invoices` as of 2026-08-23. Two of the three
  GitHub Actions workflows (`.github/workflows/backend.yml:188` and
  `.github/workflows/bridge.yml:99`) have a `flyctl deploy` step
  that this blocks. The two Fly deploy apps in scope are
  `bijou-production` (`fly.toml:6`) and `bijou-bridge-production-v2`
  (`packages/bridge/fly.bridge-production.toml:1`).
- **What the user has right:** Fly deploys are blocked.
- **What the user has wrong:** **the user has 4 different Fly.io
  deploy tokens in local `.env` files** (root `.env:259-260`,
  `packages/landing/.env:23` and `.env:206`, plus the `FLY_*_TOKEN`
  variants). It is not certain every one of them is locked. The
  "deploy-scoped token" still works for `fly deploy` even after a
  metrics/auth 401 � see the comment at
  `.github/workflows/backend.yml:184-186`. So a manual `flyctl deploy`
  with a deploy-scoped token *might* still work, and we have not
  actually tested this. The user assumed "billing locked = every
  token dead" which is unverified.
- **What is the actual deploy stopper for Fly?** Even if a token
  works, the Fly app *org* is billing-locked per CLAUDE.md. You
  cannot push to a Fly app whose org is locked. So Fly is dead
  *for now* regardless of which token is used.
- **Workaround in place:** Coolify self-hosted
  (`docker-compose.coolify.yml` + `Dockerfile.{backend,bridge,landing}`
  + `ops/coolify/DEPLOY.md`). Coolify does not depend on Fly.
- **What clears it:** Pay the overdue Fly invoice at
  `https://fly.io/dashboard/web3-933/billing`. Not a code change.
  Effort: 1 invoice payment + 1 hour to re-test manual `flyctl
  deploy` with the working token.

### 1.2 GitHub Actions billing locked (claimed)

**Status: PARTIALLY REAL, but only blocks 2 of 3 deploy paths.**

- **Evidence:** CLAUDE.md states "The job was not started because
  your account is locked due to a billing issue." I cannot see
  private billing state from here. The evidence I *can* see in the
  repo is that the landing deploy is already disabled
  (`.github/workflows/landing.yml:79` � `if: false`) with a comment
  explaining Vercel native integration handles it. The backend
  (`backend.yml:155-190`) and bridge (`bridge.yml:66-104`) workflows
  each have a `flyctl deploy` step that runs *after* the CI job.
- **What the user has right:** the `flyctl deploy` step in the two
  workflows is blocked because the Fly account is locked. The CI
  job (lint, type-check, syntax) may or may not be blocked
  depending on whether the lock also killed compute minutes. I see
  no private minutes status from the repo.
- **What the user has wrong:** the user treats "CI is locked" as
  monolithic. In fact:
  - `landing.yml` already routes production through Vercel native
    integration � the GitHub deploy step is intentionally disabled
    (comment at `landing.yml:62-75` explains exactly why, including
    the 2026-08-10 sign-up outage that motivated it).
  - The Coolify path is completely independent of GitHub Actions.
    `ops/coolify/DEPLOY.md:28-70` is a first-time setup of a Git
    source in Coolify; pushes to `main` on `mybijouai-creator/
    bijou-monorepo` then trigger a webhook on the Coolify host,
    which builds the images and deploys.
- **What clears it:** Pay the GitHub Actions invoice OR keep using
  Coolify, which does not need GitHub Actions at all. The CI test
  jobs are a quality-of-life improvement, not a deploy dependency.
  Effort: 0 hours if you accept the Coolify path; 1 hour if you
  want CI tests back.

### 1.3 Telnyx keys not rotated � 3 SECURITY.md files (claimed)

**Status: REFUTED � those SECURITY.md files do not exist in this repo.**

- **Evidence:** recursive search for `SECURITY.md` excluding
  `node_modules/` and `legacy/`. **Zero hits** in the monorepo. The
  only `SECURITY.md` files on disk are inside
  `node_modules/typescript/` and `node_modules/tslib/` (unrelated
  third-party package documentation).
- **What the user has right:** Telnyx keys are present in plaintext
  in the local `.env` (lines 27-31: `TELNYX_API_KEY`,
  `TELNYX_PUBLIC_API_KEY`, `TELNYX_ORGANIZATION_API_KEY`,
  `TELNYX_ORGANIZATION_API_ID`, `TELNYX_API_BASE`). These are the
  Bold Business production keys. `.env` is gitignored at
  `.gitignore:5-12`, but the user has a track record of leaks per
  `docs/SUPABASE_TOKEN_ROTATION.md` (Supabase token leaked in commit
  `e21b0cb`).
- **What the user has wrong:** the user said "see SECURITY.md files
  in telnyx projects." There are no telnyx projects in this repo.
  The voice/Telnyx work referenced in CLAUDE.md is in three
  separate external repos that are not part of the monorepo. The
  "3 SECURITY.md files" the user is referring to presumably live
  in those external repos � but the user has confused "the work
  for telnyx projects" with "code in this monorepo."
- **What to do instead:** treat the Telnyx keys as un-rotated, plan
  a real rotation (dashboard ? rotate ? update Coolify env group ?
  redeploy). The WhatsApp bridge does *not* use Telnyx; the
  voice/contact-center work does. Write the SECURITY.md file **in
  this monorepo** (`docs/SECURITY_TELNYX_ROTATION.md` or similar)
  so it is actually findable, and add a follow-up issue.
- **Effort:** 1 hour if keys are still valid in Telnyx dashboard;
  4-8 hours if Telnyx has revoked the org API key (need to
  re-issue from Bold Business side).

### 1.4 SUPABASE_DB_URL is empty in .env (claimed)

**Status: REAL, but the symptom is mis-stated. The variable is named `DATABASE_URL`, not `SUPABASE_DB_URL`, and it is only needed for migrations.**

- **Evidence:** root `.env:104` has `DATABASE_URL=` (empty). The
  variable the user named (`SUPABASE_DB_URL`) does not appear
  anywhere in the monorepo. The Postgres DSN is *not* what the
  application uses at runtime � `auth_api.py:44` calls
  `os.getenv("SUPABASE_URL")` and `SUPABASE_SERVICE_KEY` for all
  normal Supabase traffic (REST, not direct SQL).
- **What the user has right:** the Postgres DSN is needed for
  `packages/backend/scripts/apply_migrations.py` to apply the
  12 SQL files in `packages/backend/migrations-py/`. Per
  `docs/STATUS_2026-08-23.md:67-69`, the operator step is
  exactly: get the DSN from Supabase dashboard, set
  `DATABASE_URL=...`, run `python -m
  packages.backend.scripts.apply_migrations`.
- **What the user has wrong:** the operator step is already
  documented and explicit � the empty `DATABASE_URL=` in `.env`
  is not a hidden bug, it is the placeholder the owner fills in
  *just before* running migrations. Calling it a "blocker" is
  over-stating; it is a one-line owner action, gated on having
  Supabase dashboard access.
- **Hidden risk I want to flag:** `apply_migrations.py` is
  currently *modified* (uncommitted change). Whoever runs the
  script next will run it with the local-edit version, not the
  version on `main`. Recommend committing or stashing before
  any deploy.
- **Effort:** 15 minutes (Supabase dashboard ? Project Settings ?
  Database ? Connection string ? Transaction mode ? paste into
  `.env` ? run script). The script must be committed first; 5
  minutes of git.

### 1.5 mnjbold git identity 403 on push (claimed)

**Status: REAL, with workaround already in place.**

- **Evidence:** `git remote -v` shows two remotes:
  - `mybijouai-creator` ?
    `https://oauth2:github_pat_11CGKGOBI0�@github.com/mybijouai-creator/bijou-monorepo.git`
    � the PAT is **embedded in the URL**. This is the working
    remote. `mybijouai-creator/main` HEAD is `22a5ed4` and local
    `main` is also `22a5ed4` (verified via
    `git rev-list --left-right --count main...mybijouai-creator/main`
    ? `0	0`).
  - `origin` ? `https://github.com/<personal-account>/bijou-monorepo.git` �
    the legacy/old remote. Not the canonical repo per CLAUDE.md.
- **What the user has right:** the `mnjbold` identity is locked
  out of push. CLAUDE.md confirms the PAT-from-Hermes workaround
  is in use.
- **What the user has wrong:** this is **not blocking anything** �
  local and remote are in sync, no commits are stranded, the
  workaround is working as of 2026-08-24 12:54 MYT. The user's
  worry that "29 commits sit unpushed on local" was true on
  2026-08-23 per `docs/STATUS_2026-08-23.md` but is no longer true.
- **Hidden risk:** the PAT is sitting in the git config file in
  plaintext on this machine. If the machine is shared or backed up
  to a public cloud, that PAT is exposed. The PAT only has
  `mybijouai-creator/bijou-monorepo` scope by design, so the
  blast radius is limited. But the per-AGENTS.md convention is to
  read from
  `%USERPROFILE%\.hermes\secrets\.env.mybijou-creator` and not
  store it in `.git/config`. This is a footgun.
- **Effort:** 0 minutes if you accept the embedded-PAT pattern.
  30 minutes to extract to a `credential.helper` and scrub the URL.

---

## 2. Hidden blockers � what nobody has called out

### 2.1 [CRITICAL] Live admin API key in git history

- **Evidence:** `docs/ADMIN_API_KEY.txt` was committed in commit
  `1e718eb` on 2026-08-10. The file contains
  `ADMIN_API_KEY = 8tunr0gzd32v16bphiwqfsljxya79o5m` and the
  literal rotation command `fly secrets set ADMIN_API_KEY=�`. The
  file is **not** in `.gitignore` � `.gitignore` only covers
  `.env*` and `*_token` patterns, neither of which match this
  filename. The file is tracked on `main` and on
  `mybijouai-creator` (per the local=remote sync at `22a5ed4`).
- **Why this matters:** anyone with read access to the
  `mybijouai-creator/bijou-monorepo` GitHub repo (including any
  fork, any leak via PR, any GitHub Archive mirror) has the live
  admin key. The key gates `/api/admin/*` endpoints per
  `packages/backend/src/saas/admin_api.py:62-135`. Rotating the
  key on Fly alone does not invalidate the value in git history.
- **Fix:** (a) rotate the key in Fly **now**, (b) update
  `docs/ADMIN_API_KEY.txt` to point at the new value (or
  replace the value with only the rotation procedure), (c) add
  `docs/ADMIN_API_KEY.txt` to `.gitignore` and stop tracking it,
  (d) accept that the historical commit is in git history; the
  rotated key makes the historical value inert. Optionally
  rewrite history with `git-filter-repo` (destructive; do not
  do without explicit owner OK per the Supabase-token rotation
  precedent in `docs/SUPABASE_TOKEN_ROTATION.md:97-100`).
- **Effort:** 30 minutes. Severity: P0 � secrets in git are how
  outages start.

### 2.2 [HIGH] `.env` still has `PUBLIC_URL=https://bijou-production.fly.dev`

- **Evidence:** root `.env:54`:
  `PUBLIC_URL=https://bijou-production.fly.dev`. The canonical
  URL is `https://app.mybijou.xyz` (per
  `packages/backend/src/saas/auth_api.py:41`
  `CANONICAL_PUBLIC_URL = "https://app.mybijou.xyz"`).
- **Why this matters:** `_check_env_canonical_url()` in
  `packages/backend/src/core/self_test_api.py:241-258` explicitly
  fails if `PUBLIC_URL` contains `fly.dev`. The 2026-08-10
  canonical-domain bug class � auth silently looping because the
  redirect lands on the wrong origin � is documented in CLAUDE.md
  � "Recurring bug class". The codebase defends itself with the
  `_public_base_url()` helper (which prefers
  `PUBLIC_URL` ? `APP_URL` ? `CANONICAL_PUBLIC_URL`), but anything
  that reads `PUBLIC_URL` directly without the helper � like
  `bijou.py:934`
  `dashboard_url = f"{os.getenv('PUBLIC_URL', 'https://app.mybijou.xyz')}/dashboard?..."`
  � will use the wrong value if `PUBLIC_URL` is set.
- **Specific risk:** `ops/coolify/DEPLOY.md:34` correctly hardcodes
  `PUBLIC_URL: "https://app.mybijou.xyz"` in the Coolify compose.
  So *if* the deploy uses the Coolify compose's env group, the
  wrong value in the on-disk `.env` is overridden. But if anyone
  ever runs the backend container with the local `.env` mounted
  (e.g. for a `docker run --env-file .env` smoke test), the
  wrong URL silently wins. This is exactly the class of bug the
  2026-08-10 fix was meant to prevent.
- **Fix:** change root `.env:54` to
  `PUBLIC_URL=https://app.mybijou.xyz`. Same for any other
  `.env*` file with the wrong value. Add a pre-commit hook that
  greps for `PUBLIC_URL=.*fly.dev` and blocks the commit.
- **Effort:** 5 minutes. Severity: P1 � known failure mode with
  a known fix and a known self-test that catches it.

### 2.3 [HIGH] The WhatsApp bridge's deploy config points webhooks at a dead Fly app

- **Evidence:** `packages/bridge/fly.toml:19`:
  `BIJOU_WEBHOOK_URL = 'https://bijou-ai-enterprise-legacy.fly.dev/webhook/message'`.
  The Fly app `bijou-ai-enterprise-legacy` is referenced in
  `docs/DEPLOYMENT_SAFETY.md:26-31` as the "OLD production Bijou"
  � *not* the canonical `bijou-production` app. There is no
  workflow in `.github/workflows/` that deploys to
  `bijou-ai-enterprise-legacy`, and per CLAUDE.md that app is on the
  old (pre-monorepo) layout. It is the one we are explicitly
  trying to retire.
- **Why this matters:** if anyone deploys the bridge using
  `packages/bridge/fly.toml` (the file the bridge CI uses by
  default per `bridge.yml:88-101`), every WhatsApp message
  delivered to the bridge will be POSTed to a dead backend. The
  bridge container starts fine, `/health` returns 200, Fly keeps
  the machine running, but messages vanish into a black hole. No
  alert would fire because the bridge does not know the webhook
  is failing � it just gets 5xx responses from the dead app and
  the messages are dropped.
- **Specific risk:** the coolify compose is correct � it uses
  `${BRIDGE_API_KEY:?required}` and points to the backend via
  service discovery (`docker-compose.coolify.yml:96-102`). The
  per-tenant bridge compose that the runbook says is required
  (`ops/coolify/DEPLOY.md:96-104`) **does not exist yet** � the
  runbook calls it `docker-compose.bridge-only.yml` and marks it
  `TBD`. So the multi-tenant bridge pattern the user thinks they
  have is not actually deployable.
- **Fix:** (a) fix `fly.toml:19` to point at the canonical
  `https://app.mybijou.xyz/webhook/message` (or
  `https://bijou-production.fly.dev/webhook/message` if the
  bridge stays on Fly); (b) create `docker-compose.bridge-only.yml`
  with only the `bridge:` service and templated
  `BIJOU_BACKEND_URL` for production deployments; (c) add a
  bridge-side smoke test that POSTs a fake message and asserts
  the backend received it.
- **Effort:** 1-2 hours. Severity: P1 � silent message loss in
  production is the most user-visible failure mode possible.

### 2.4 [HIGH] No alerting on top of the self-test

- **Evidence:** `packages/backend/src/core/self_test_api.py:325-450`
  implements `/api/self-test` and `/api/self-test/summary` with
  nine checks (5 critical: Supabase connectivity, the 4 new
  tables, Gemini, `PUBLIC_URL` canonical, Resend configured;
  4 non-critical: Stripe, Nango, Cal.com, disk space, response
  coordinator). The self-test runs on demand. Nothing else
  triggers it.
- **What is missing:** no `cron` entry, no systemd timer, no
  GitHub Actions scheduled workflow, no external monitor like
  BetterStack / UptimeRobot / Cronitor / Sentry cron. The
  `BIJOU_BETTERSTACK_TOKEN` in root `.env:268` is **empty** and
  the key is even commented out as `# optional, for prod uptime
  monitoring`. The `SENTRY_DSN` env var in
  `ops/coolify/coolify.env.example:53` is also commented as
  optional. The Coolify healthcheck polls every 30s and would
  restart the container on persistent failure � but the
  `docker-compose.coolify.yml:70` healthcheck hits
  `/api/self-test/summary`, which only returns 503 on *critical*
  failures. A Supabase-down-but-Gemini-up scenario (plausible
  during a Supabase regional outage) would return 503 ? Coolify
  auto-rolls back. But the operator would only know if they
  happen to be looking at the Coolify dashboard.
- **Why this matters:** a SaaS with paying customers that has
  zero alerting is one bad day away from a customer finding out
  first. The Coolify auto-rollback is a safety net, not a
  monitoring solution.
- **Fix:** (a) add a `*/5 * * * *` cron job (locally on the
  Coolify host is fine) that runs
  `curl -fsS https://app.mybijou.xyz/api/self-test/summary` and
  pages the owner on `overall=fail`; (b) wire Sentry DSN in the
  Coolify env group so unhandled exceptions show up there; (c)
  set `BIJOU_BETTERSTACK_TOKEN` to a free-tier BetterStack /
  Cronitor / UptimeRobot token for external uptime checks.
- **Effort:** 1 hour. Severity: P1 � first paying customer
  outage will surface this.

### 2.5 [MEDIUM] No database backup plan that survives the Coolify host

- **Evidence:** `docker-compose.coolify.yml:127-130` defines
  `bridge-data` and `backend-uploads` volumes with
  `driver: local`. `ops/coolify/DEPLOY.md:170-185` ("5. Backup")
  acknowledges this and says "Coolify does NOT back up local
  volumes by default" � then says the operator must configure
  backup in the Coolify UI. The instructions are correct but
  **not done** (no `.env`-style or compose-style backup
  configuration, no `coolify backup` script, no S3 destination
  set up).
- **What this means in practice:** the WhatsApp session
  (`packages/bridge/store/*.db3`), the bridge message history
  (`packages/bridge/store/*.db`), and the user uploads in
  `backend-uploads` all live on a single Coolify host disk. If
  the host dies � disk failure, hosting provider incident,
  accidental `docker volume prune` � every per-tenant WhatsApp
  session and every user upload is gone. Tenants have to
  re-scan QR codes. Recoverable but disruptive.
- **The Supabase side is better:** Supabase has PITR on paid
  plans, and the user is on a paid plan. So the actual
  *business data* (tenants, conversations, billing) is backed
  up. The risk is the WhatsApp session and user uploads.
- **Fix:** in the Coolify UI, enable "Backup" on the
  `bridge-data` and `backend-uploads` volumes with a daily
  schedule, S3 destination (Backblaze B2 is the cheap option).
  Test the restore. Add `ops/coolify/BACKUP.md` with the
  step-by-step.
- **Effort:** 2 hours including the first test-restore.
  Severity: P2.

### 2.6 [MEDIUM] The `Dockerfile.backend` HEALTHCHECK uses the trivial `/health`

- **Evidence:** `Dockerfile.backend:46-47`:
  `HEALTHCHECK --interval=30s --timeout=5s --start-period=20s
  --retries=3 CMD curl -fsS http://localhost:8080/health || exit 1`.
  Per `packages/backend/src/core/self_test_api.py:5-10`, the
  trivial `/health` returns 200 unconditionally. The
  `docker-compose.coolify.yml:70` healthcheck correctly uses
  `/api/self-test/summary`. So the compose override is right,
  but the bare image's healthcheck is wrong.
- **Why this matters:** if anyone ever runs the bare image (not
  through the compose � e.g. `docker run` for a one-off smoke
  test, or a future CI pipeline that tests the image directly),
  they get the bad healthcheck. This is the source of the
  "broken deploys because healthcheck lies" footgun that
  `self_test_api.py` was built to prevent. The compose being
  right is good defense-in-depth, but the Dockerfile being
  right is one less footgun.
- **Fix:** change `Dockerfile.backend:47` to
  `CMD curl -fsS http://localhost:${PORT:-8080}/api/self-test/summary || exit 1`.
- **Effort:** 2 minutes. Severity: P3.

### 2.7 [MEDIUM] `docker-compose.bridge-only.yml` does not exist

- **Evidence:** `ops/coolify/DEPLOY.md:96-104` says "Compose
  File: `docker-compose.bridge-only.yml` (TBD; per-tenant variant
  of the main compose, just the bridge service)." The file does
  not exist in the repo. Multi-tenant bridge deploys are blocked
  on this artifact.
- **Why this matters:** the per-tenant bridge is the *whole point*
  of the multi-tenant architecture. The
  `packages/bridge/fly.bridge-production.toml` is a single-app
  config, not per-tenant. The compose-level per-tenant pattern is
  the only way to do this in Coolify (without provisioning a new
  Fly app per tenant, which we cannot because Fly is locked). So
  the entire "one bridge per tenant" story is currently
  unimplementable.
- **Fix:** create `docker-compose.bridge-only.yml` from the
  existing compose, drop the `backend` and `landing-preview`
  services, parameterize `BRIDGE_API_KEY`,
  `WHATSAPP_SESSION_PATH`, and the persistent volume. Document
  the per-tenant provisioning workflow in
  `ops/coolify/DEPLOY.md` (update the TBD note).
- **Effort:** 2-3 hours. Severity: P1 for multi-tenant, P3 if
  you only have one tenant today.

### 2.8 [MEDIUM] Stripe webhook endpoint ID is set but the URL is not visible in repo

- **Evidence:** root `.env:112`:
  `STRIPE_WEBHOOK_ENDPOINT_ID=we_1T3KsCAdgDGXBSXVtXmDiE40`. The
  matching URL is *not* in any file. The Stripe dashboard holds
  the URL (it is how `STRIPE_WEBHOOK_SECRET` is paired with the
  endpoint).
- **Why this matters:** if the Stripe webhook URL is
  `https://bijou-production.fly.dev/api/billing/stripe/webhook`
  (which is what `packages/backend/src/saas/payment_api.py:424`
  implies), then **a Coolify migration breaks Stripe webhooks**
  � the URL would need to be re-registered in Stripe dashboard
  as `https://app.mybijou.xyz/api/billing/stripe/webhook` (or
  the equivalent Coolify URL). And the `STRIPE_WEBHOOK_SECRET`
  rotates when the endpoint URL changes, so the secret in the
  `.env` becomes inert.
- **Fix:** before the Coolify cutover, (a) list the existing
  Stripe webhook endpoints via
  `stripe webhook_endpoints list --api-key=$STRIPE_SECRET_KEY`,
  (b) decide whether to keep the Fly URL as a no-op or
  deactivate it, (c) create a new endpoint at the Coolify URL,
  (d) set the new `STRIPE_WEBHOOK_SECRET` in the Coolify env
  group.
- **Effort:** 30 minutes + a Stripe test event. Severity: P1 �
  silent subscription lifecycle failures = revenue loss.

---

### 2.9 [MEDIUM] Google OAuth redirect URI mismatch

- **Evidence:** `packages/backend/src/saas/google_oauth.py:65`
  reads `GOOGLE_REDIRECT_URI` from env. The
  `packages/backend/fly.production.toml:245` comment says it
  should be set to
  `https://bijou-production.fly.dev/api/auth/google/callback`. The
  `ops/coolify/coolify.env.example` does not list
  `GOOGLE_REDIRECT_URI` at all. The `packages/backend/.env` does
  not have `GOOGLE_REDIRECT_URI` set.
- **Why this matters:** Google OAuth clients in Google Cloud
  Console have a strict allow-list of redirect URIs. If
  `GOOGLE_REDIRECT_URI` in Coolify is empty, the code falls
  back to `_public_base_url()` (which is the canonical
  `https://app.mybijou.xyz`) but Google rejects with
  `redirect_uri_mismatch` because the canonical domain is *not*
  registered in the Google Cloud project. The user has already
  documented this exact failure mode in CLAUDE.md � "Recurring
  bug class" (the 2026-08-10 fix), and the `GOOGLE_REDIRECT_URI`
  Fly secret needs to match the *registered* URL in Google Cloud
  Console, not the canonical domain.
- **Fix:** (a) verify the Google Cloud project
  `gen-lang-client-0423187661` has the correct redirect URI
  registered, (b) add `GOOGLE_REDIRECT_URI` to
  `ops/coolify/coolify.env.example` as required, (c) set the
  matching value in the Coolify env group, (d) test the Google
  sign-in flow end-to-end after deploy.
- **Effort:** 1 hour including the test. Severity: P1 � Google
  sign-in is the most-used auth path after email.

### 2.10 [LOW] Telegram bot token not in `.env`

- **Evidence:** root `.env` has no `TELEGRAM_BOT_TOKEN` line.
  The `packages/backend/fly.production.toml:127` comment says
  "TELEGRAM_BOT_TOKEN set via secrets". The
  `docker-compose.coolify.yml` does not pass any Telegram env
  var.
- **Why this matters:** if Telegram is supposed to be a channel
  (per CLAUDE.md "Telegram" and `voice-waitlist.js` and
  `VoiceComingSoon.tsx`), the Coolify deploy will silently
  disable it. Per `CLAUDE.md:73-80` voice is "forthcoming" and
  the Telegram integration status is unclear.
- **Fix:** confirm whether Telegram is in scope for v1, then
  either add the env var to the Coolify template or document
  it as deferred.
- **Effort:** 5 minutes if Telegram is in scope, 0 if not.
  Severity: P3.

### 2.11 [LOW] Resend domain verification status unknown

- **Evidence:** root `.env:77`: `EMAIL_DOMAIN=mybijou.xyz`.
  Resend requires domain verification (DNS records) before you
  can send from `hello@mybijou.xyz`. There is no doc in the
  repo that confirms the verification is done. The `Resend`
  env var in `ops/coolify/coolify.env.example:30` is marked
  `[optional]`, but `self_test_api.py:218-227` makes it
  *critical* (magic-link login depends on it). The
  `_check_resend_configured` raises if `RESEND_API_KEY` is
  missing OR if it does not start with `re_`.
- **Why this matters:** magic-link login is the primary auth
  flow. If Resend cannot send from `mybijou.xyz`, magic links
  go to spam or are silently dropped.
- **Fix:** verify in Resend dashboard
  (`https://resend.com/domains`) that `mybijou.xyz` is verified
  with the DKIM, SPF, and DMARC records Resend provides. Add a
  `docs/RESEND_VERIFICATION.md` with the status.
- **Effort:** 15 minutes to verify. Severity: P1 � without it,
  login is broken.

### 2.12 [LOW] Five different Fly deploy tokens, no canonical reference

- **Evidence:** Fly.io deploy tokens in the local environment
  (none logged here for safety, but counted):
  - root `.env:259-260`: `FLY_IO_PRODUCTION_DEPLOY_TOKEN`,
    `FLY_IO_PRODUCTION_BRIDGE_DEPLOY_TOKEN`
  - `packages/landing/.env:23`: "OLD FLY.IO TOKEN �
    REACTIVATED"
  - `packages/landing/.env:206`: "NEW FLY.IO TOKEN � USE THIS
    FOR DEPLOYMENT"
  - root `.env:268`: `BIJOU_FLY_API_TOKEN=` (empty)
  - `SPRITE_TOKEN` is also present (line 212 of landing .env),
    suggesting Sprites was considered as another fallback
- **Why this matters:** when the user needs to run a manual
  `flyctl deploy`, which token? The naming implies
  `packages/landing/.env:206` is current, but the root
  `.env:259-260` also has live tokens. The "OLD / NEW" naming
  in `landing/.env` is human-readable but not
  machine-verifiable. No `_read_token` helper script, no
  per-environment vault, no token rotation date.
- **Fix:** consolidate to one token store (1Password or
  `~/.config/bijou/fly_token` with `chmod 600`), document the
  canonical location in `ops/DEPLOY_SECRETS.md`, and dedupe
  the values across the various `.env*` files.
- **Effort:** 1 hour. Severity: P3.

### 2.13 [LOW] The GOWA vs custom-Go bridge confusion

- **Evidence:** the `packages/bridge/` directory has *three*
  Fly configs: `fly.toml` (custom Go, 256MB VM, webhook to the
  dead `bijou-ai-enterprise-legacy.fly.dev`), `fly.staging.toml`
  (custom Go, 512MB, points to `bijou-staging.fly.dev`),
  `fly.bridge-production.toml` (GOWA Docker image
  `aldinokemal2104/go-whatsapp-web-multidevice:latest`, 1GB,
  points to `bijou-production.fly.dev`). The Coolify
  `Dockerfile.bridge` builds the **custom Go** code from source
  (uses `go build` and distroless static). The three configs
  are not consistent with each other. The
  `GOWA_BRIDGE_EXPLORATION_REPORT.md` and
  `GOWA_BRIDGE_EXPERT_GUIDE.md` describe a GOWA *v8.1.2*
  instance at `bijou-bridge-staging-v2.fly.dev` with Basic
  Auth, a web UI, and multi-device support � that is the
  **GOWA image option**, not the custom Go code.
- **Why this matters:** the user has been talking about "the
  Go bridge" and "GOWA" as if they were the same thing. They
  are not. The custom Go bridge is 55KB of hand-written
  `whatsmeow` glue with a custom REST surface (the
  `/api/send`, `/api/download`, `/api/media/` endpoints). The
  GOWA image is a different program with a different REST
  surface (`/devices`, `/app/login`, `/send/text`, etc.) and
  a different webhook format (the v8.x event envelope that
  `packages/backend/src/core/bijou.py:7219-7258` already
  expects). Picking the wrong one as the "canonical" bridge
  will create a contract mismatch with the backend.
- **Fix:** decide which one is the production bridge
  (recommendation: **GOWA image**, because it has a web UI
  for QR login, multi-device support, basic auth, and is a
  well-maintained upstream project that decouples Bijou from
  the whatsmeow Go glue). Update `Dockerfile.bridge` to use
  the GOWA image as the runtime instead of compiling from
  source, or document clearly that the Coolify path uses the
  GOWA image and the Fly path uses the custom Go. Pick one.
- **Effort:** 2-4 hours depending on which is chosen.
  Severity: P1 � if the wrong one gets deployed, no WhatsApp
  messages will reach the backend.

### 2.14 [LOW] WhatsApp inbound webhook URL is not registered in the bridge

- **Evidence:** I searched for the bridge's *inbound* webhook
  configuration (the URL Meta calls to deliver messages to
  the bridge). I did not find it in any fly.toml, compose
  file, or `.env`. The bridge fly configs have an *outbound*
  `BIJOU_WEBHOOK_URL` (bridge ? backend) but not an *inbound*
  webhook URL (Meta ? bridge). For the GOWA image, this is
  registered via the GOWA web UI (port 3000). For the custom
  Go bridge, it is typically configured via a
  `BRIDGE_WEBHOOK_URL` env var on the *Meta Cloud API* side.
- **Why this matters:** the WhatsApp Cloud API requires a
  registered webhook URL + verify token. If the bridge gets
  deployed without the webhook URL being registered in Meta
  Business dashboard, no inbound messages will ever arrive.
  The DEPLOY.md does not list "register webhook with Meta"
  as a deploy step.
- **Fix:** add "register webhook with Meta Business
  dashboard" as step 1.5 in `ops/coolify/DEPLOY.md`, with
  the exact URL and verify token.
- **Effort:** 30 minutes. Severity: P0 if WhatsApp inbound is
  the primary product, P3 if not.

### 2.15 [INFO] Uncommitted local changes

- **Evidence:** `git status` shows modified-but-not-committed:
  - `packages/backend/scripts/apply_migrations.py`
  - `packages/backend/src/saas/email_service.py`
  - `packages/backend/src/saas/email_templates/__init__.py`
  - `packages/backend/src/saas/stripe_service.py`
  - `packages/backend/static/pricing.html`
  - Many untracked `.claude/agents/*.md` and `.agents/`
    files (out of scope)
- **Why this matters:** the migration runner change in
  particular is a deploy-time artifact; if the operator pulls
  the repo and runs the script, they get the modified version.
  The other changes may or may not have been intended. Per
  AGENTS.md's auto-cleanup convention, every commit should
  run prettier, lint, tests; the working tree should be
  clean before deploy.
- **Fix:** commit and push the changes, or stash them with a
  clear reason. The `.claude/agents/` and `.agents/` are
  probably out of scope.
- **Effort:** 30 minutes. Severity: P3.

---

## 3. Recommended order to fix

| # | Item | Severity | Effort | Blocker for what |
|---|---|---|---|---|
| 1 | Rotate `ADMIN_API_KEY`; replace value in `docs/ADMIN_API_KEY.txt` with only the procedure (Section 2.1) | P0 | 30 min | Security |
| 2 | Fix `PUBLIC_URL` in root `.env:54` from `fly.dev` to `app.mybijou.xyz` (Section 2.2) | P1 | 5 min | Auth |
| 3 | Fix bridge `fly.toml:19` `BIJOU_WEBHOOK_URL` to canonical backend (Section 2.3) | P1 | 5 min | WhatsApp inbound |
| 4 | Create `docker-compose.bridge-only.yml` per `ops/coolify/DEPLOY.md:96-104` (Section 2.7) | P1 | 2-3 h | Per-tenant bridge |
| 5 | Get Supabase DB DSN, set `DATABASE_URL=`, commit the modified `apply_migrations.py`, run migrations on live Supabase (Section 1.4) | P0 | 1 h | Backend feature surface |
| 6 | Re-register Stripe webhook endpoint at the Coolify URL + rotate `STRIPE_WEBHOOK_SECRET` (Section 2.8) | P1 | 30 min | Billing |
| 7 | Add `GOOGLE_REDIRECT_URI` to Coolify env template, verify Google Cloud project (Section 2.9) | P1 | 1 h | Google sign-in |
| 8 | Verify Resend domain in `https://resend.com/domains` (Section 2.11) | P1 | 15 min | Magic-link login |
| 9 | Decide GOWA vs custom-Go bridge; align `Dockerfile.bridge` with the choice (Section 2.13) | P1 | 2-4 h | WhatsApp bridge contract |
| 10 | Add WhatsApp inbound webhook registration to `ops/coolify/DEPLOY.md` (Section 2.14) | P0 | 30 min | WhatsApp inbound |
| 11 | Wire Sentry DSN + BetterStack/UptimeRobot in Coolify env group + 5-min self-test cron (Section 2.4) | P1 | 1 h | Observability |
| 12 | Configure Coolify volume backup to S3/B2 for `bridge-data` + `backend-uploads` (Section 2.5) | P2 | 2 h | Data durability |
| 13 | Fix `Dockerfile.backend` healthcheck to use `/api/self-test/summary` (Section 2.6) | P3 | 2 min | Image hygiene |
| 14 | Rotate Telnyx keys; document rotation in `docs/SECURITY_TELNYX_ROTATION.md` (Section 1.3) | P1 | 1-8 h | Voice (when live) |
| 15 | Consolidate Fly deploy tokens into one canonical store (Section 2.12) | P3 | 1 h | Operator hygiene |
| 16 | Commit and push the 5 uncommitted local changes (Section 2.15) | P3 | 30 min | Working-tree hygiene |
| 17 | Add `TELEGRAM_BOT_TOKEN` or document as deferred (Section 2.10) | P3 | 5 min | Telegram channel |
| 18 | Cut over to Coolify; first production deploy with `/api/self-test/summary` 200 (Section 5) | P0 | 2-4 h | Live deploy |

**Total minimum to first healthy prod deploy:** 12-18 hours of
focused work. Items 1-3, 5, 10, 18 are must-haves; the rest can
land in the first two weeks of post-launch hardening.

---

## 4. The "self-hosted GOWA" option � what it actually is

**GOWA is already in the repo � but it is used as a *fallback* image, not as the production bridge.**

- **What GOWA is** (per the docs the user already has):
  `aldinokemal2104/go-whatsapp-web-multidevice` is a public
  Docker image that wraps the same `whatsmeow` Go library the
  custom bridge uses, but adds:
  - a web UI on port 3000 (device list, QR code display, send
    panel, group management, etc.)
  - a REST API on port 3000 with a v8.x event envelope
    (`{"event": "message", "device_id": "...", "payload": {...}}`)
  - basic auth (`APP_BASIC_AUTH` env var, `user:password` format)
  - persistent device state in `/app/storages/sqlite.db`
- **The GOWA option is *already* the recommended bridge for
  production in this repo**:
  - `packages/bridge/fly.bridge-production.toml:5` says
    `[build] image = "aldinokemal2104/go-whatsapp-web-multidevice:latest"`
    (GOWA, not custom Go)
  - The backend's `/webhook/message` endpoint at
    `packages/backend/src/core/bijou.py:7219-7258` already
    expects the GOWA v8.x format
  - `GOWA_BRIDGE_EXPLORATION_REPORT.md` and
    `GOWA_BRIDGE_EXPERT_GUIDE.md` already document the
    endpoints the operator needs to hit
- **What is *not* done**: the Coolify `Dockerfile.bridge` builds
  the **custom Go code** from `packages/bridge/main.go`
  (multi-stage `golang:1.24-alpine` ? `distroless/static`). The
  custom Go bridge does *not* speak the GOWA webhook format �
  it speaks a different format (look at `main.go:650`
  `http.Post(webhookURL, ...)` and the payload structure it
  builds). The backend's `/webhook/message` would either
  reject the custom bridge's payload or fall through to the
  catch-all logging path.
- **Decision required:** pick one of these two paths:
  - **A. Use GOWA as the production bridge** (recommended).
    Replace `Dockerfile.bridge` with a
    `FROM aldinokemal2104/go-whatsapp-web-multidevice:latest`
    image, inject `APP_BASIC_AUTH` + `WHATSAPP_WEBHOOK` from
    the Coolify env group, mount a persistent volume at
    `/app/storages`. The backend's webhook receiver already
    understands the format. The `APP_BASIC_AUTH` value
    (currently `$BRIDGE_USER:$BRIDGE_PASSWORD` — the literal value used to be
    printed here in a public repo; treat it as compromised and rotate it)
    needs to be set on the backend too � but the
    `BridgeAdapter` at
    `packages/backend/src/channels/bridge_adapter.py:35-65`
    uses `X-API-Key` header auth, not Basic Auth. So the
    bridge's Basic Auth will be rejected by the backend's
    outbound calls, which is a separate bug. Either the GOWA
    bridge needs to also send `X-API-Key`, or the backend's
    `BridgeAdapter` needs to send Basic Auth. This is a small
    fix.
  - **B. Use the custom Go bridge as the production bridge**.
    Update the backend's `/webhook/message` to accept the
    custom bridge's payload format (or have the custom bridge
    translate to GOWA v8.x format before sending). Either way,
    the contracts need to match.
- **Effort to make GOWA the production bridge via Coolify:** 1
  hour. Replace `Dockerfile.bridge`; align the backend's
  `BridgeAdapter` auth; update `docker-compose.coolify.yml` if
  needed. Update the runbook to say "scan QR via
  `https://bridge.mybijou.xyz/`" (the GOWA web UI) instead of
  "scan QR via `fly logs`."
- **My recommendation:** pick A. The GOWA image has a real
  community, the backend already speaks its format, and the
  custom-Go bridge has known sharp edges (the AGENT.md
  documents multiple media-download bugs fixed in
  `main.go:893`).

---

## 5. CI/CD reality � what is actually deployable today

### 5.1 What works today (no work needed)

- **Landing (`mybijou.xyz`)** � Vercel native git integration.
  Per CLAUDE.md � "Deployment topology" and the comment in
  `.github/workflows/landing.yml:62-75`, this was re-pointed
  2026-08-10 and confirmed working. Every push to `main` on
  `mybijouai-creator/bijou-monorepo` builds on Vercel's
  infrastructure and deploys to `mybijou.xyz`. **Bypasses
  GitHub Actions billing completely.** Bypasses Fly.io.
- **Landing preview (`Dockerfile.landing`)** � optional
  self-hosted preview, gated behind `--profile preview` in
  Coolify. Works on any Coolify host with a port-3000
  reverse-proxy.

### 5.2 What is blocked

- **`packages/backend/` deploys via GitHub Actions** � the
  `deploy:` job in `.github/workflows/backend.yml:155-190`
  needs `BIJOU_FLY_API_TOKEN` and Fly deploy minutes. Both
  are blocked. The `ci:` job (lint, type-check, unit tests)
  may or may not be blocked depending on minutes; either way
  it is not a deploy dependency.
- **`packages/bridge/` deploys via GitHub Actions** � same
  situation. `.github/workflows/bridge.yml:66-104`.
- **Direct `flyctl deploy` from this machine** � Fly billing
  is locked. The `flyctl` command is installed (per the .env
  entries) but every deploy attempt returns 403. The 4 cached
  Fly deploy tokens in the local `.env*` files are not in
  scope here for safety, but they exist.
- **`flyctl secrets set` on `bijou-production` or
  `bijou-bridge-production-v2`** � same Fly lock. Any secret
  rotation that needs a Fly secret update has to wait for Fly
  billing to clear OR move to Coolify.

### 5.3 The path that works without any of the above

**Coolify + git auto-deploy.** Documented in
`ops/coolify/DEPLOY.md:75-86`. The steps:

1. In the Coolify UI, create a "Docker Compose" resource
   pointing at `mybijouai-creator/bijou-monorepo`, branch
   `main`, compose file `docker-compose.coolify.yml`.
2. Create an env group with all `[required]` vars from
   `ops/coolify/coolify.env.example` and the `BRIDGE_API_KEY`
   set to the same value as the bridge compose expects.
3. Apply the SQL migrations to Supabase (Section 1.4 above).
4. First-time deploy: Coolify pulls the repo, builds the
   three images, runs `docker compose up -d`. The
   healthcheck on `/api/self-test/summary` (set in
   `docker-compose.coolify.yml:70`) returns 200 = deploy is
   live. 503 = Coolify auto-rolls-back.
5. Subsequent deploys: push to `main` on
   `mybijouai-creator/bijou-monorepo`. Coolify's webhook
   fires (set up in step 1), pulls the latest, rebuilds,
   redeploys. No GitHub Actions involvement.

**This path uses zero Fly.io, zero GitHub Actions compute
minutes, and the only third-party is the GitHub source-pull
(which works regardless of GitHub Actions billing).** It is
the path that unblocks production deploys today.

### 5.4 What is *not* in this path that production needs

- **No external alerting** (Section 2.4). Coolify auto-rollback
  is the only automated response. Add a cron-driven monitor.
- **No automated DB backup** (Section 2.5). Configure Coolify
  volume backup manually.
- **No per-tenant bridge** (Section 2.7). The single `bridge`
  service in `docker-compose.coolify.yml` is fine for a
  single-tenant v1 but blocks multi-tenant.
- **No load test.** The 439 unit tests do not include a load
  test for the WhatsApp burst path. Recommended before
  announcing anything that says "production."

### 5.5 Cost reality

Per the Coolify runbook (no direct cost cited, but inferred):
- The Coolify host is the same self-hosted infrastructure as
  the rest of Bijou (per `ops/coolify/DEPLOY.md:5-8`). No
  new line item.
- The 3 Docker images (backend ~500MB, bridge ~15MB custom
  Go or ~100MB GOWA, landing ~50MB) build on the Coolify
  host. No Docker Hub or registry cost.
- The persistent volumes (`bridge-data`, `backend-uploads`)
  grow with usage. For Bijou's scale (a few tenants, ~MB-sized
  uploads) the disk cost is negligible.
- **Net new cost to deploy via Coolify: $0.**

---

## 6. The honest summary

The user's mental model � "Fly billing, GitHub billing, Telnyx
keys, and DB DSN are the blockers" � is half right. The Fly
billing and GitHub billing blockers are real but irrelevant
because Coolify bypasses both. The Telnyx blocker is mis-stated
(those keys may be un-rotated but the SECURITY.md files do not
exist where the user thinks they do). The DB DSN is a one-line
owner action, not a blocker.

The blockers nobody is talking about are all the things the
user *built around* and stopped noticing: the live admin key
in git history, the stale `PUBLIC_URL` in the .env, the bridge
webhook pointing at a dead app, the missing per-tenant bridge
compose, the zero-alerting setup, the bare-image healthcheck
lying, the Stripe webhook URL that will break on cutover, the
Google OAuth redirect URI not in the Coolify env template, and
the GOWA-vs-custom-Go bridge ambiguity that has been quietly
accumulating since 2026-01-28.

The first deploy on Coolify will work. The first *production
incident* will be a learning experience, but the system will
not silently lose data � the self-test catches the
canonical-class bugs and Coolify's auto-rollback catches the
rest. The first *customer-impacting* incident will be the
absence of alerting, not the absence of code.

Fix Section 2.1, 2.2, 2.3, 2.7, 2.13, 1.4, 2.14 in roughly
that order, and the rest of Section 2 within the first two
weeks of post-launch. Section 3 has the time estimates.
Section 4 is the GOWA decision. Section 5 is the deploy path.
The system is closer to shippable than the user thinks; the
gap is roughly two focused days of housekeeping, not two
months of engineering.

� Verifier
