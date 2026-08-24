# First Coolify Deploy — 30 Minute Playbook

**Target:** Get `https://app.mybijou.xyz` served by Coolify (replacing the
Fly.io backend) so telephony work can start.

**Prereqs (already done):**
- [x] Coolify v4.3.10 reachable at `https://coolify.getbijou.xyz`
- [x] All Bijou API keys in `.env` (Supabase, Stripe, Resend, Nango, Cal.com, Telnyx, MiniMax, Gemini)
- [x] `docker-compose.coolify.yml` validates locally
- [x] All 3 Dockerfiles committed (`Dockerfile.backend`, `Dockerfile.bridge`, `Dockerfile.landing`)
- [x] `ops/coolify/coolify.env.example` lists every env var

**Pre-deploy (5 min):**

1. **Open Coolify** at https://coolify.getbijou.xyz (the one with your `COOLIFY_API_TOKEN`).
2. **Create new project** (or use "My first project" = id 1).
3. **"+ New Resource" → "Application" → "Docker Image"** (NOT "Docker Compose"; the
   compose file is for reference only — each service needs its own resource so
   you can set per-service env vars and volumes).
4. **Repeat 4 times** — one resource per service:
   - `bijou-backend` (Dockerfile: `Dockerfile.backend`, port 8080, domain: `app.mybijou.xyz`)
   - `bijou-bridge` (Dockerfile: `Dockerfile.bridge`, port 8081, no public domain — internal only)
   - `bijou-landing-preview` (Dockerfile: `Dockerfile.landing`, port 3000, optional)
   - `bijou-admin-api` (shares backend image, no separate deploy needed)
5. **Git source:** point all 4 at `mybijouai-creator/bijou-monorepo`, branch `main`,
   base directory `/`. Use the GitHub App integration (Coolify auto-detects) or a
   deploy key — your `BIJOU_GITHUB_TOKEN=ghp_...` works for HTTPS-based deploys.

**Set env vars (15 min):**

For each resource, copy the env vars from `ops/coolify/coolify.env.example`.
Use a Coolify "Environment Variables" group shared across all 4 resources so
you only fill them in once.

**Critical vars (must be set, no defaults):**
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (the service-role key, not anon)
- `GEMINI_API_KEY` (note: your current one in `.env` is **SUSPENDED** by Google — generate a fresh one at https://aistudio.google.com/apikey first)
- `STRIPE_SECRET_KEY` (live key) + `STRIPE_WEBHOOK_SECRET`
- `RESEND_API_KEY` (for magic-link emails)
- `PUBLIC_URL=https://app.mybijou.xyz` (do NOT use a fly.dev value — this is the
  2026-08-10 bug class)

**Bridge-specific vars:**
- `BRIDGE_URL=http://bijou-bridge:8080` (internal DNS, not the public URL)
- `BIJOU_BACKEND_URL=http://bijou-backend:8080`
- `BIJOU_BACKEND_API_KEY` — must match the backend's `BIJOU_API_KEY`

**Deploy (5 min):**

1. Click "Deploy" on `bijou-backend` first.
2. Watch the build log. Build takes ~5 min (pip install is the slow part).
3. When the container starts, hit `https://app.mybijou.xyz/api/self-test/summary`.
4. Expected: `{"overall": "pass", ...}` (after you paste the SQL migrations
   into Supabase; otherwise `new_tables_exist` will fail).
5. Deploy `bijou-bridge` next. Verify `https://<bridge-url>/health` returns "OK".
6. If `bijou-landing-preview` is set up, deploy it last.

**DNS cutover (5 min, manual):**

The current DNS for `app.mybijou.xyz` points at Fly.io. Cut it over to Coolify
by changing the A record in your DNS provider (Porkbun) to the Coolify
container's public IP, OR use a Cloudflare Tunnel for zero-downtime cutover.

**Verification (after deploy):**

```powershell
Invoke-WebRequest -Uri 'https://app.mybijou.xyz/api/self-test/summary' -UseBasicParsing
# Expect: overall=pass, all 10 checks green

Invoke-WebRequest -Uri 'https://app.mybijou.xyz/login' -UseBasicParsing
# Expect: 200 OK, HTML login page

# Bridge health
Invoke-WebRequest -Uri 'https://<your-bridge-url>/health' -UseBasicParsing
# Expect: 200 OK, "OK" body
```

**If something goes wrong:**

- **Build fails on `pip install`**: check `packages/backend/requirements.txt` for
  any local-only paths or pinned versions that don't exist in the registry.
- **Container starts but `/api/self-test/summary` is 503**: the 2 critical
  failures are `new_tables_exist` (paste the migrations) and `gemini_reachable`
  (regenerate the Gemini key). Both are non-deploy blockers.
- **Webhook signature fails**: `STRIPE_WEBHOOK_SECRET` doesn't match the
  Stripe dashboard's endpoint signing secret. Re-copy from the dashboard.
- **Bridge can't reach backend**: check the internal network — Coolify creates
  a default network, but cross-resource DNS only works if they're in the same
  project. Both `bijou-backend` and `bijou-bridge` must be in the same project.

**Once the backend + bridge are healthy on Coolify, telephony work can start**
(see issue #28). The 4th service (`bijou-voice`) will be added then as a
new Coolify resource.
