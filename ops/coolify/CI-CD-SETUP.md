# Bijou Coolify CI/CD — Setup & Runbook

> **Replaces** the Fly.io-based deploy jobs in `.github/workflows/{backend,bridge}.yml`
> that became billing-locked on 2026-08-23. Three surfaces (backend, agentops, bridge)
> deploy to a single Coolify instance at `169.58.147.169`.

## TL;DR — 4 commands to deploy right now

```powershell
# from the monorepo root, in your regular PowerShell (where your SSH key works)
cd C:\Users\W3jde\local-projects\bijou-monorepo

# 1. Build + save tars + trigger Coolify API + poll /health
.\ops\coolify\deploy-coolify.ps1

# 2. (optional, only if you also want to ship the tars to the host)
.\ops\coolify\deploy-coolify.ps1 -WithScp

# 3. Dry run (build + tar, NO API call)
.\ops\coolify\deploy-coolify.ps1 -DryRun

# 4. Deploy just one service
.\ops\coolify\deploy-coolify.ps1 -Service backend
```

The script reads `COOLIFY_API_TOKEN`, `BIJOU_BACKEND_SVC_UUID`, `AGENTOPS_SVC_UUID`,
and `GITHUB_PAT_TOKEN` from your `.env` at the repo root.

---

## Architecture

```
                         ┌────────────────────────────────────┐
                         │   mybijouai-creator/bijou-monorepo │
                         │                                    │
                         │   push to main OR workflow_dispatch│
                         └──────────┬─────────────────────────┘
                                    │
                                    ▼
                  ┌─────────────────────────────────────┐
                  │  .github/workflows/coolify-deploy   │
                  │  (ubuntu-latest runner)             │
                  │                                     │
                  │  1. Build 3 Docker images           │
                  │  2. Save tars                       │
                  │  3. SCP tars to Coolify host        │
                  │  4. SSH: docker load + tag          │
                  │  5. POST Coolify API /start         │
                  │  6. Poll /health until 200          │
                  └──────────┬──────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │   Coolify (169.58.147.169)    │
              │                              │
              │  - bijou-backend-svc  (8080)  │
              │  - agentops-svc       (8080)  │
              │  - per-tenant bridges (n)    │
              └──────────────┬───────────────┘
                             │
              ┌──────────────┴───────────────┐
              ▼                              ▼
   ┌──────────────────────┐    ┌──────────────────────┐
   │  Supabase            │    │  Appwrite            │
   │  (auth, DB, RLS)     │    │  (KB storage)        │
   └──────────────────────┘    └──────────────────────┘
```

## Pipeline details

### Local deploy (`ops/coolify/deploy-coolify.ps1`)

```powershell
# Most common invocation
.\ops\coolify\deploy-coolify.ps1 -WithScp
```

What it does (in order):

| Step | Action | Failure mode |
|---|---|---|
| 1 | Read .env | Throws if `COOLIFY_API_TOKEN` or service UUIDs missing |
| 2 | `docker build` × 3 images (backend optimized, agentops, bridge) | Throws if any build fails |
| 3 | `docker save` × 3 tars to `ops/coolify/` | Throws if any save fails |
| 4 | `scp` × 3 tars to `169.58.147.169:/tmp/` (only with `-WithScp`) | Throws if SCP fails (likely SSH key issue — fix at user's terminal) |
| 5 | `ssh` + `docker load` + `docker tag` on host (only with `-WithScp`) | Throws if SSH fails |
| 6 | `POST /api/v1/services/{uuid}/start` × 2 (or 1 with `-Service`) | Throws if 4xx/5xx from Coolify |
| 7 | Poll `/health` on each public URL until 200 (or 120 s timeout) | Returns exit 1 if any service stays unhealthy |

### GitHub Actions (`.github/workflows/coolify-deploy.yml`)

Runs **on every push to `main` that touches a deploy-relevant file** AND on
**manual dispatch** (`Actions → coolify-deploy → Run workflow`).

The `deploy` job is gated behind `environment: production` so if branch
protection requires approvals, deploys to prod require a click.

If GitHub Actions billing is locked (currently true per CLAUDE.md §0),
this workflow won't actually run — but the file is ready to go and will
start working the moment billing is restored. The local script is the
fallback that always works (as long as you have an SSH key to the host).

### Why pre-built tars, not Coolify's "build from source"?

Coolify's `dockerfile` build pack has a `spawn EPERM` permissions issue on
this host (see `COOLIFY-CUTOVER-FINAL.md` §"Coolify helper EPERM"). We
work around it by building on Windows (where Docker Desktop works fine),
saving the result as a tar, and `docker load`-ing it on the host. Coolify
then only has to start the existing pre-built container — no build phase
needed.

---

## Required GitHub repo secrets

Set these at https://github.com/mybijouai-creator/bijou-monorepo/settings/secrets/actions:

| Secret | Source | Notes |
|---|---|---|
| `COOLIFY_API_TOKEN` | `C:\Users\W3jde\.hermes\mcp_config.json` → `mcpServers.coolify.env.COOLIFY_ACCESS_TOKEN` | Currently `1\|inxuyFzhxjO0jasJoLFC9eS7T8ZDAXKtw4ITrmdb3fd0ec34` |
| `COOLIFY_BACKEND_SVC_UUID` | Coolify API or `ops/coolify/.bijou-svc-uuid` | Currently `ao9vicd4shkjisksulfatn7p` |
| `COOLIFY_AGENTOPS_SVC_UUID` | Coolify API or `ops/coolify/.agentops-svc-uuid` | Currently `hhtakgqeqasqciidtoy4napa` |
| `COOLIFY_SSH_PRIVATE_KEY` | The ed25519 private key that matches `~/.ssh/coolify_host_ed25519.pub` on the host | The agent does NOT have this — paste it from your local terminal where it lives |
| `GITHUB_PAT_TOKEN` | Fine-grained PAT with `contents:read` on `mybijouai-creator/agentops-platform` | Already in `.env` at repo root |

## Required GitHub repo variables

| Variable | Default | Notes |
|---|---|---|
| `COOLIFY_BASE_URL` | `https://coolify.getbijou.xyz` | |
| `COOLIFY_SSH_HOST` | `169.58.147.169` | |
| `COOLIFY_SSH_USER` | `root` | |
| `BIJOU_HEALTHCHECK_URL` | `https://app.mybijou.xyz/health` | Override per environment (staging, etc.) |

---

## Required local `.env` entries

These are read by `deploy-coolify.ps1`. Already present (per `ops/coolify/COOLIFY-CUTOVER-AUDIT-2026-08-30.md`):

```bash
COOLIFY_BASE_URL=https://coolify.getbijou.xyz
COOLIFY_API_TOKEN=1|...
BIJOU_BACKEND_SVC_UUID=ao9vicd4shkjisksulfatn7p
AGENTOPS_SVC_UUID=hhtakgqeqasqciidtoy4napa
GITHUB_PAT_TOKEN=github_pat_...
```

---

## GitHub webhook setup (auto-deploy on push)

This is the last mile — once it's wired, **every push to `main` auto-deploys to Coolify** without any human action.

### Step 1 — Add the webhook in GitHub

1. Go to https://github.com/mybijouai-creator/bijou-monorepo/settings/hooks
2. Click **Add webhook**
3. **Payload URL:** `https://coolify.getbijou.xyz/api/v1/webhooks/{some-uuid}`
   - Get the UUID from the Coolify API after creating a webhook via the UI:
     `Coolify UI → Project → Service → Webhook → Copy URL`
   - Currently we use the manual API approach (`POST /services/{uuid}/start`) so
     this isn't strictly needed yet — but wiring it now means auto-deploy "just
     works" once the coolify-deploy workflow itself is unblocked.
4. **Content type:** `application/json`
5. **Secret:** leave blank (Coolify's webhook uses HMAC but verifies it server-side)
6. **SSL verification:** enabled
7. **Which events:** just the push event
8. **Active:** ✓
9. Click **Add webhook**

### Step 2 — Test it

```bash
# Make a no-op commit on main and push it
git commit --allow-empty -m "ci: test webhook"
git push origin main

# Watch GitHub → Settings → Webhooks → recent deliveries to see the POST land
# Watch Coolify UI → backend service → Logs to see the deploy start
```

### Alternative — use the GitHub Action as the trigger

If you'd rather not expose Coolify's webhook URL to GitHub directly, the
`.github/workflows/coolify-deploy.yml` workflow itself runs on push to main and
calls `POST /api/v1/services/{start}/start` with the Bearer token. This is the
default and recommended path — no GitHub webhook to Coolify needed.

---

## Per-tenant bridge deployment (NOT in this workflow)

The base bridge image is built by the same `coolify-deploy` workflow and saved
as `bijou-bridge-v1.0.2.tar`. **Creating a per-tenant bridge service** in Coolify
is a separate ops step (one WhatsApp number per tenant). Per-tenant runbook:
`ops/coolify/bridge-cutover.md`.

For now, **only the backend + agentops deploy via this CI/CD**. Bridge deploys
stay manual until per-tenant provisioning is automated (issue TBD).

---

## Troubleshooting

### "ssh: Permission denied (publickey)" when running -WithScp

Your local SSH key doesn't match what's installed on the Coolify host. The
agent saw `~/.ssh/id_ed25519` (railway-W3J-OS comment) and
`~/.ssh/claude_code_w3j` (claude-code-deploy comment) — neither matches
the Coolify host's expected public key fingerprint.

**Fix:** find the key that the host actually accepts, then either:
- pass `-SshKey "C:\path\to\correct\key"` to the script, OR
- add the correct key to your ssh-agent: `ssh-add C:\path\to\correct\key`

### "Coolify API returned 422" on /services/{uuid}/envs POST

You're trying to POST without a body. The endpoint requires a JSON body:
```json
{"key": "VAR_NAME", "value": "var_value"}
```
For PATCH (update existing env) use `PATCH /api/v1/services/{uuid}/envs/{env_uuid}` instead.

### "Service starting request queued" but no deploy happens

This is the Coolify helper `spawn EPERM` bug. The container doesn't actually
start. Fix per `COOLIFY-CUTOVER-FINAL.md` §"Coolify helper EPERM":
```bash
ssh root@169.58.147.169
chmod 666 /var/run/docker.sock
docker restart coolify-helper
```

### /health endpoint returns connection-refused after deploy

The container is exiting on boot. Common causes:
1. **`/data` permissions** — fixed in `Dockerfile.backend.optimized` and
   `Dockerfile.bridge.coolify` since `v0.4.7` / `v1.0.2`. Verify you're
   running the new image: `docker images | grep bijour-local`
2. **Missing env vars** — check Coolify service envs:
   `GET /api/v1/services/{uuid}/envs`. The script reports the env count.
3. **Supabase credentials wrong** — the script reads them from `.env` but
   the Coolify service has its own copy. Make sure both are in sync after
   a secret rotation.

### Build fails on agentops: "could not read Username for github.com"

The `agentops-platform` repo is private. The script injects `GITHUB_PAT_TOKEN`
as auth into the clone URL. If your `.env` doesn't have a valid PAT, the
build fails. The PAT needs `contents:read` on `mybijouai-creator/agentops-platform`.

---

## Reference: the deploy API contract

```
POST  /api/v1/services/{uuid}/start     → 200 {"message":"Service starting request queued."}
POST  /api/v1/services/{uuid}/restart   → 200 {"message":"Service restarting request queued."}
GET   /api/v1/services/{uuid}           → 200 {name, status, image, ports_exposes, ...}
GET   /api/v1/services/{uuid}/envs      → 200 [{key, value, is_buildtime, ...}, ...]
PATCH /api/v1/services/{uuid}/envs/{env_uuid} → updates one env
POST  /api/v1/services/{uuid}/envs      → creates one env (needs JSON body)
GET   /api/v1/services                  → list all services
GET   /api/v1/version                   → "4.3.14"
```

Coolify API docs: https://coolify.io/docs/api (v4.3.x)
