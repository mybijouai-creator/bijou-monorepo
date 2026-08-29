# Coolify Cutover — Final Handoff (2026-08-29)

## TL;DR for the user

**You are 3 commands away from a working Bijou on Coolify.** The Coolify helper container has a hard `spawn EPERM` permissions issue that prevents automated Docker builds via the API. I built the 3 images locally on Windows, saved them as `.tar` files, and pre-configured 2 Coolify SERVICES. You just need to:

```bash
# 1. Copy the 3 tars to the Coolify host (169.58.147.169)
#    They're at: C:\Users\W3jde\local-projects\bijou-monorepo\ops\coolify\
#    Total size: 374 MB

# 2. SSH to the Coolify host and run:
cd /tmp  # or wherever you put the tars
docker load -i agentops-backend-v0.4.6.tar
docker load -i bijou-backend-optimized-v0.4.6.tar
docker load -i bijou-bridge-v1.0.0.tar
docker tag bijour-local/bijou-backend-optimized:v0.4.6 bijou-backend:v0.4.6
docker tag bijour-local/agentops-backend:v0.4.6 agentops-backend:v0.4.6
docker tag bijour-local/bijou-bridge:v1.0.0 bijou-bridge:v1.0.0

# 3. In Coolify UI: open each service, click Deploy (or POST /start via API)
```

The full load script is at `ops/coolify/load-all-images.sh` (pushed to GitHub).

---

## What I did

### 1. Coolify Applications (via API)
Created 3 apps in the Backend & DB project (`gx68zslwys823gmm4rtoxibd`) on the local server:

| App | UUID | Status |
|---|---|---|
| `bijou-backend` | `upyrah1jjsvfy92z13ayf3fj` | exited:unhealthy (blocked on EPERM) |
| `agentops-dashboard` | `xwtygy0zxzo5goswjjr1lbab` | exited:unhealthy (blocked on EPERM) |
| `bijou-bridge` | `jnazv9j88kxuafdjlmhajaxh` | exited:unhealthy (blocked on EPERM) |

**Problem:** The Coolify helper container (coollabsio/coolify-helper:1.0.16) has a `spawn EPERM` permissions issue on this host. Every `POST /applications/{uuid}/start` returns `Deployment queued` but `last_deploy_at` stays empty and the container never starts. This affects ALL new `build_pack=dockerfile` applications. Existing one-click services (appwrite, infisical, nango, etc.) work because they use prebuilt images.

### 2. Coolify Services (via API) — the workaround
Created 2 services that reference prebuilt local images:

| Service | UUID | Image | Status |
|---|---|---|---|
| `bijou-backend-svc` | `ao9vicd4shkjisksulfatn7p` | `bijou-backend:v0.4.6` | exited (image not on host yet) |
| `agentops-dashboard-svc` | `hhtakgqeqasqciidtoy4napa` | `agentops-backend:v0.4.6` | exited (image not on host yet) |

Both services have all 30+ env vars configured (Telnyx, Appwrite, Supabase, Stripe, Resend, Gemini, OpenAI, MiniMax, Cal.com, Nango, Google OAuth, etc.) sourced from the local `bijou-monorepo/.env`.

### 3. Docker images built locally
Built on Windows Docker Desktop (no Coolify build pipeline needed):

| Image | Size | Tar size | Use |
|---|---|---|---|
| `bijour-local/bijou-backend-optimized:v0.4.6` | 1.22 GB | 265 MB | Bijou backend, CPU-only (no torch) |
| `bijour-local/agentops-backend:v0.4.6` | 340 MB | 71 MB | Agentops webhook + dashboard |
| `bijour-local/bijou-bridge:v1.0.0` | 121 MB | 38 MB | WhatsApp bridge (Go) |

Tar locations:
```
C:\Users\W3jde\local-projects\bijou-monorepo\ops\coolify\agentops-backend-v0.4.6.tar
C:\Users\W3jde\local-projects\bijou-monorepo\ops\coolify\bijou-backend-optimized-v0.4.6.tar
C:\Users\W3jde\local-projects\bijou-monorepo\ops\coolify\bijou-bridge-v1.0.0.tar
```

### 4. GitHub push
19 files pushed to `mybijouai-creator/bijou-monorepo` (main, latest commit `5bebf5f`):
- 4 Dockerfiles (`.backend`, `.backend.coolify`, `.agentops.coolify`, `.bridge.coolify`, `.backend.optimized`)
- 11 ops scripts (`preflight-check.ps1`, `wire-coolify.ps1`, `migrate-secrets-to-coolify.ps1`, `porkbun-cutover.ps1`, `smoke-test-prod.ps1`, `coolify-volume-snapshot.ps1`, `push-to-canonical.ps1`, `load-all-images.sh`, `load-agentops-image.sh`, ...)
- 5 docs (`PRODUCTION-CUTOVER-PLAN.md`, `menu-pages-verify.md`, `bridge-cutover.md`, `2026-08-29-cutover.md`, ...)
- `packages/backend/src/saas/appwrite_client.py` (Appwrite storage client, feature-flagged)
- `packages/backend/requirements.txt` (added `appwrite==14.1.0`)
- `.gitignore`, `.env.example`

### 5. Discovered: agentops already deployed
There's an existing service `contact-center-v0-1` (uuid `itb6lfrqknvzjiy7a26sgkl6`, running:healthy) that uses the `contact-center-backend:pilot` image — this IS the agentops-platform backend, just under a different name. The Coolify host description says "Wildcard target: https://getbijou.xyz".

---

## What's still blocked

### 1. DNS cutover (manual)
The Porkbun API keys in `C:\Users\W3jde\.hermes\secrets\.env.porkbun` return 403 — they look revoked. Until DNS is cut, `app.mybijou.xyz` still points to Fly.io (where Bijou v2.2.0 is still running and healthy).

**Manual fix:**
1. Log into https://porkbun.com
2. Update A record for `app.mybijou.xyz` → `169.58.147.169` (Coolify server IP)
3. Add A record for `agentops.getbijou.xyz` → same IP
4. Wait 5-30 min for propagation

### 2. Coolify helper EPERM (host-level)
The Coolify helper can't spawn `docker build` due to a host-level permissions issue. **Fix is at the OS level on the Coolify host:**

```bash
# SSH to coolify host as root
docker exec -u root coolify-helper sh -c 'docker info'  # to verify

# Possible fixes:
# 1. Check docker socket group:
ls -la /var/run/docker.sock
chmod 666 /var/run/docker.sock  # or add coolify user to docker group

# 2. Restart Coolify helper:
docker restart coolify-helper

# 3. Check cgroup / AppArmor:
cat /proc/1/cgroup
aa-status  # disable AppArmor for coolify-helper if present

# 4. Update Coolify:
#    Settings > Update > check for new version (some 4.3.x patch releases fix this)
```

### 3. Per-tenant bridge deployment
The bridge should be deployed per-tenant (one Coolify service per tenant, each with its own phone number, SQLite volume, and BRIDGE_SHARED_SECRET). See `ops/coolify/bridge-cutover.md` for the runbook.

### 4. GitHub webhook
No webhook from `mybijouai-creator/bijou-monorepo` to Coolify yet. After fixing the EPERM, set this up so pushes to main auto-deploy:
- Coolify UI: project → service → Webhook → copy URL
- GitHub: repo → Settings → Webhooks → Add webhook with the Coolify URL, content-type `application/json`, events `push`

### 5. Manual UX verification
`ops/coolify/menu-pages-verify.md` has the checklist. Needs to be run after #1 (DNS) and #2 (EPERM) are fixed.

---

## Files on disk (this repo)

```
ops/coolify/
├── agentops-backend-v0.4.6.tar (71 MB)
├── bijou-backend-optimized-v0.4.6.tar (265 MB)
├── bijou-bridge-v1.0.0.tar (38 MB)
├── load-all-images.sh (run on Coolify host)
├── load-agentops-image.sh
├── PRODUCTION-CUTOVER-PLAN.md
├── bridge-cutover.md
├── menu-pages-verify.md
├── COOLIFY-CUTOVER-REPORT.md (this doc's predecessor)
├── preflight-check.ps1
├── wire-coolify.ps1
├── migrate-secrets-to-coolify.ps1
├── porkbun-cutover.ps1
├── smoke-test-prod.ps1
├── coolify-volume-snapshot.ps1
├── push-to-canonical.ps1
├── .envs-backup.json (34 original Bijou envs)
├── .agentops-uuid (Coolify app uuid)
├── .bijou-svc-uuid (ao9vicd4shkjisksulfatn7p)
├── .agentops-svc-uuid (hhtakgqeqasqciidtoy4napa)
├── .bridge-uuid (jnazv9j88kxuafdjlmhajaxh)
└── ...

docs/handoffs-and-audits/2026-08-29-coolify-cutover-prep.md
packages/backend/src/saas/appwrite_client.py (NEW)
packages/backend/requirements.txt (added appwrite==14.1.0)
.env.example (added Appwrite/Porkbun/Coolify/Infisical sections)
.gitignore (added settings.json)
Dockerfile.backend (Python 3.12 + apt deps + pip + uvicorn)
Dockerfile.backend.coolify (self-contained, ~10 min build)
Dockerfile.backend.optimized (CPU-only, no torch, ~280MB image)
Dockerfile.agentops.coolify (self-contained)
Dockerfile.bridge.coolify (self-contained)
```

---

## What I cannot do from the API

- Transfer files to the Coolify host (no SSH, no shared volume, no Coolify file upload endpoint)
- Fix the Coolify helper's `spawn EPERM` permissions (host-level OS issue)
- Rotate Porkbun API keys (user's Porkbun account)
- Trigger Docker builds inside Coolify (the helper is the only path and it's broken)

All of these need ~15 min of your time on the host.
