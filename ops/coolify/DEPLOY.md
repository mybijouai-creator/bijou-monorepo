# Coolify Deploy Runbook — Bijou AI

**Status:** Authoritative. Last reviewed 2026-08-23.

**Why Coolify:** Fly.io and GitHub Actions are both billing-locked
(separate issues, per CLAUDE.md). Coolify is the **primary** deploy
target going forward. It runs on the same self-hosted infrastructure
as the rest of Bijou, so deploys don't depend on a third-party CI.

**Audience:** Owner (or any agent acting on the owner's behalf) with
Coolify admin access.

---

## 0. Pre-flight

Before deploying anything:

1. **Confirm Coolify is up** — open the Coolify dashboard and verify
   it's not in a "billing overdue" state. If it is, the same Fly
   problem happens to Coolify (separate bill).
2. **Confirm git is clean** on the branch you intend to deploy.
3. **Confirm secrets are set** in the env-group (see
   `ops/coolify/coolify.env.example` for the full list).

---

## 1. First-time setup (one-time per environment)

### 1.1 Add the git source

1. Coolify dashboard -> "+ New" -> "Resource" -> "Application" -> "Docker Compose"
2. Source: GitHub
3. Repository: `mybijouai-creator/bijou-monorepo` (canonical) or
   `W3JDev/bijou-monorepo` (mirror)
4. Branch: `main`
5. Base Directory: `/`
6. Compose File: `docker-compose.coolify.yml`

### 1.2 Create the env group

1. Coolify dashboard -> "Environment Variables" -> "+ New Group"
2. Name: `bijou-prod` (or `bijou-staging` for staging)
3. Fill in every `[required]` var from `coolify.env.example`
4. Fill in the `[optional]` vars you actually use (Stripe live vs test,
   Resend, Cal.com, Nango, Sentry)
5. Attach the group to the backend service in the Coolify UI

### 1.3 Apply the SQL migrations (one-time)

The backend container starts but cannot write to new tables until the
SQL migrations are applied to Supabase. Run them once in the Supabase
SQL editor (in order):

```sql
-- From migrations-py/, in this order:
\i add_shared_context.sql
\i add_message_reasons.sql
\i add_inbox_copilot_events.sql
\i add_data_request_deletions.sql
```

Or paste each file's contents in turn via the Supabase SQL editor UI.

### 1.4 Configure the domain

1. Coolify dashboard -> backend service -> "Domains"
2. Add `app.mybijou.xyz` (or your staging subdomain)
3. Coolify auto-provisions Let's Encrypt SSL
4. DNS: point `app.mybijou.xyz` CNAME to the Coolify-provided URL

---

## 2. Deploying a change

### 2.1 Via Coolify auto-deploy (recommended)

1. Push the commit to `main` on the canonical remote
2. Coolify's webhook fires (set this up in the Coolify UI under the
   git source)
3. Coolify pulls the latest main, builds the Docker images, runs
   `docker compose up -d`
4. Healthcheck passes within 60 seconds -> deploy is live
5. If healthcheck fails, Coolify auto-rolls-back to the previous
   container; you get a notification in the Coolify dashboard

### 2.2 Via manual deploy (when auto is off or you want a dry run)

1. Coolify dashboard -> project -> "Deploy" button
2. Watch the build log
3. Watch the runtime log for the first 60 seconds
4. Hit `https://app.mybijou.xyz/health` from your terminal

### 2.3 Per-tenant bridge (multi-instance pattern)

In production, each tenant gets their own bridge container. To add a
new tenant:

1. Coolify dashboard -> "+ New" -> "Application" -> "Docker Compose"
2. Same source repo + branch
3. Compose File: `docker-compose.bridge-only.yml` (TBD; per-tenant
   variant of the main compose, just the bridge service)
4. Unique env group per tenant (their own `BRIDGE_API_KEY`, their own
   `BIJOU_BACKEND_API_KEY`)
5. Unique persistent volume for `/data` (so the WhatsApp session
   survives container restarts)

---

## 3. Smoke-testing after deploy

After every deploy, before declaring "shipped":

```bash
# 1. Health
curl -fsS https://app.mybijou.xyz/health
# Expect: 200 OK, {"status": "ok", ...}

# 2. Static dashboard
curl -fsS -o /dev/null -w "%{http_code}\n" https://app.mybijou.xyz/dashboard
# Expect: 200

# 3. Sign in as a real user (manual)
# Open https://app.mybijou.xyz/login, log in, verify Home shows the
# Activity Feed widget, the Inbox loads, and a test message round-trips.

# 4. Verify the new routes from the latest commit are live
# e.g. for issue #26 (PDPA/GDPR):
curl -fsS -o /dev/null -w "%{http_code}\n" https://app.mybijou.xyz/data-request
# Expect: 200
```

If any check fails, rollback (Coolify dashboard -> "Rollback") and
investigate. Do not leave a broken deploy running.

---

## 4. Rollback

### 4.1 Coolify auto-rollback

If the healthcheck fails on a new deploy, Coolify auto-rolls-back to
the previous container. This is why the healthcheck matters: a broken
container with a 200-returning healthcheck will NOT be rolled back.

### 4.2 Manual rollback

1. Coolify dashboard -> service -> "Deployments" tab
2. Click the previous successful deploy
3. Click "Redeploy"

### 4.3 Nuclear option (DB migration went wrong)

If a DB migration broke prod:

1. Coolify rollback (above) — this only rolls back the container, not
   the DB
2. Manually reverse the SQL migration in Supabase
3. Verify with a smoke test
4. Open an incident report in `docs/handoffs-and-audits/`

---

## 5. Backup

### 5.1 Database (Supabase)

Supabase has its own daily backups (point-in-time recovery on paid
plans). For Bijou's scale, this is sufficient.

### 5.2 Bridge SQLite (per-tenant)

Each bridge has a persistent volume mounted at `/data`. Coolify does
NOT back up local volumes by default. To back up:

1. Coolify dashboard -> bridge service -> "Storages" -> the `/data`
   volume -> "Backup" -> enable
2. Configure backup schedule (daily recommended)
3. Configure backup destination (S3, B2, etc.)

### 5.3 User uploads

Backend uploads live in the `backend-uploads` volume. Same procedure
as the bridge SQLite.

---

## 6. Monitoring

### 6.1 Healthcheck

Coolify polls `/health` every 30s. If it returns non-2xx for 3
consecutive checks, Coolify restarts the container.

### 6.2 Error tracking

Set `SENTRY_DSN` in the env group. Sentry catches unhandled
exceptions and surfaces them with stack traces + user context.

### 6.3 Logs

Coolify dashboard -> service -> "Logs" shows the last 1000 lines.
For longer history, set up log shipping to a central log store
(planned, not implemented).

---

## 7. When the deploy path itself breaks

### "Coolify is down"

1. Check Coolify status page (if it has one) or your Coolify server's
   own health
2. SSH to the Coolify host and `docker ps` to see if the Coolify
   container is alive
3. If Coolify is truly down, fall back to **manual Docker on the same
   host**: `docker compose -f docker-compose.coolify.yml up -d` from
   the repo checkout
4. If the host is down, that's an infrastructure emergency — escalate

### "The build keeps failing"

1. Read the build log. The error is usually at the bottom.
2. Common causes:
   - A `pip install` is failing on a new dep — check
     `packages/backend/requirements.txt`
   - The `npm ci` is failing on a lockfile mismatch — run
     `npm install` locally, commit the updated `package-lock.json`
   - The Go build is failing on a `go mod` mismatch — run
     `go mod tidy` locally, commit the updated `go.sum`

### "The healthcheck is red but the app is up"

The healthcheck endpoint is `GET /health`. If it's returning 500,
read the app logs — there's an unhandled exception somewhere. The
most common cause is a missing env var; the app raises on startup
and the healthcheck never gets a chance to return.

---

## 8. Reference

- `docker-compose.coolify.yml` — the Coolify compose
- `Dockerfile.backend`, `Dockerfile.bridge`, `Dockerfile.landing` —
  the per-service images
- `ops/coolify/coolify.env.example` — the env-var template
- `CLAUDE.md` — deploy topology, blocker history, the 2026-08-10 /
  2026-08-23 canonical-domain bug class
- `docs/STATUS_<DATE>.md` — current deployment state
