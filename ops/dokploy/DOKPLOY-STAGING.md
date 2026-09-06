# Dokploy staging rollout — backend + bridge

Status: **parallel staging**, not yet production. Coolify (`169.58.147.169`,
`coolify.getbijou.xyz`) keeps serving `app.mybijou.xyz` and the bridge
domains until this stack is verified healthy and someone explicitly
flips DNS.

## Why parallel, not a straight cutover

The Coolify host hit a `docker build` EPERM bug that forced a fragile
workaround (build on Windows → save tar → SCP → `docker load` on host —
see `ops/coolify/COOLIFY-CUTOVER-FINAL.md`). Dokploy is a different host,
so it's worth confirming its native git-build path actually works cleanly
before trusting it with live tenants and Stripe-live traffic.

## What's in scope

- `backend` (FastAPI, multi-tenant) — built from `Dockerfile.backend`
- `bridge` (Go, per-tenant WhatsApp) — built from `Dockerfile.bridge`

Out of scope for this stack: `voice` (Telnyx), `langfuse` (LLM
observability), `landing` (stays on Vercel's native git integration),
and the database (stays Supabase — nothing here runs Postgres for app
data).

## Rollout steps

1. **Dokploy ⇄ GitHub**: connect via Dokploy's native GitHub App
   integration (Settings → Git Providers), not a manual PAT. This gives
   auto-deploy-on-push with no GitHub Actions secrets to manage.
2. **Create the Compose service**: point it at
   `mybijouai-creator/bijou-monorepo`, the branch this file ships on,
   compose path `docker-compose.dokploy.yml`.
3. **Environment tab**: paste real values for every var in
   `ops/dokploy/dokploy.env.example`. Use **Stripe test keys** and a
   **fresh `BRIDGE_API_KEY`** for this stack — don't reuse the Coolify
   production bridge secret.
4. **Domains tab**: use a Dokploy-generated preview domain for both
   `backend` (container port 8080) and `bridge` (container port 8080).
   Do not attach `app.mybijou.xyz` or any `bridge.*.mybijou.xyz` yet.
5. **Enable Auto Deploy** on the branch.
6. **Verify health** before anything else changes:
   - `GET <backend-domain>/api/self-test/summary` → 200
   - bridge container healthcheck (`/app/bridge --health-check`) → passing
7. **Cutover** (only when you say go): point Porkbun DNS for
   `app.mybijou.xyz` (and the relevant `bridge.*` records) at this
   Dokploy stack's domain/IP, watch traffic and error rates, keep
   Coolify warm as instant rollback for at least one full day before
   decommissioning it.

## Rollback

Until DNS is flipped in step 7, rollback is free — Coolify never
stopped serving production. After DNS is flipped, rollback is just
reverting the DNS record back to the Coolify host.
