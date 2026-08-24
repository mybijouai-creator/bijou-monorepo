# STATUS 2026-08-24 (evening) — Langfuse LLM Observability

## TL;DR
- ✅ Langfuse SDK integrated into the gateway. Every `ai://...` call now wraps in a Langfuse `generation` observation, with PII masking, token/cost tracking, and graceful no-op when keys are missing.
- ✅ Admin API has 4 new `/admin/api/langfuse/*` endpoints: `health`, `stats?days=N`, `traces`, `test-connection` (POST).
- ✅ Admin dashboard has a new "LLM Traces" tab with health card, alias config, cost rollups by alias/provider/model, recent traces table.
- ✅ Langfuse v3 stack wired into Coolify (`docker-compose.coolify.yml`): web + worker + Postgres + ClickHouse + Redis + MinIO. Web on port 3000.
- ✅ Local test stack (`ops/langfuse/docker-compose.local.yml`) — verified the web comes up healthy, sign-up works, migrations run.
- ✅ All committed + pushed to both remotes at `076a7e5`.
- ⛔ Coolify deploy still blocked by the same GitHub App binding issue (user action required, in the previous status doc).
- ⛔ Real LLM API keys still all dead — gateway still can't make actual AI calls until user regenerates.

## What was actually done (not handed back)

### 1. SDK integration
- `packages/backend/src/core/langfuse_tracing.py` — 11 KB module, context-manager that:
  - Lazy-imports langfuse (no crash if uninstalled)
  - Reads `LANGFUSE_*` env vars, fails closed when not ready
  - PII masks MY phone numbers, E.164, email, credit cards, NRIC, plates
  - Wraps each call in a generation, records the resolved model, output, tokens, cost, latency
  - Provides `health_summary()` for the admin endpoint
- `packages/backend/src/core/llm_gateway_v2.py` — `complete()` now opens one observation per call, the success path updates it with model/provider/output/usage/cost, the failure path calls `obs.fail()`. The whole provider-chain loop is wrapped so fallbacks record properly.
- `requirements.txt` — `langfuse>=4.0.0`

### 2. Admin API endpoints
- `GET /admin/api/langfuse/health` — config + SDK status + alias rollup (description, privacy, budget, spent today)
- `GET /admin/api/langfuse/stats?days=N` — by-alias / by-provider / by-model rollups + total cost/tokens/calls. Reads from `supabase.llm_usage` (durable, works even when Langfuse is down)
- `GET /admin/api/langfuse/traces?limit=N&alias=&provider=&tenant_id=` — recent llm_usage rows
- `POST /admin/api/langfuse/test-connection` — probes `/api/public/health` on the configured Langfuse host, records result in `audit_log`

All 4 endpoints return empty-state data when Langfuse isn't configured yet (so the dashboard doesn't break).

### 3. Admin dashboard
- New "LLM Traces" tab in TABS array
- `LangfusePage` component with:
  - Status card (host, keys, env, ready/partial/disabled)
  - "test connection" button
  - Aliases config table (privacy-aware pill colors)
  - Usage rollup with 4 metric tiles + 3 sub-tables (by alias / by provider / by model)
  - Recent LLM calls table (last 100)
- `Metric` + `RollupTable` helper components

### 4. Coolify deploy
- `docker-compose.coolify.yml` got 5 new services: `langfuse-web`, `langfuse-worker`, `langfuse-db`, `langfuse-clickhouse`, `langfuse-redis`, `langfuse-minio`, `langfuse-minio-init` — plus 5 new volumes
- Backend got 8 new env vars: `LANGFUSE_ENABLED`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `LANGFUSE_ENVIRONMENT`, `LANGFUSE_SAMPLE_RATE`, `LANGFUSE_MASK_PII`, `LANGFUSE_RELEASE`
- LANGFUSE env vars were also PATCHed into the existing Coolify `bijou-backend` app via the API

### 5. Local testing
- Brought up the full Langfuse stack locally with `docker compose -f ops/langfuse/docker-compose.local.yml up -d`
- 5 containers running + healthy: web (3000), worker, postgres, clickhouse, redis, minio (9000/9001)
- Health endpoint: `{"status":"OK","version":"3.224.2"}` ✅
- Created first user via the API: `mavis@mybijou.xyz` with password `BijouAdmin2026!Secure`
- Manually verified the gateway's `langfuse_tracing.py` module compiles, the `llm.complete()` path correctly wraps the provider chain, and the admin endpoints return correct data shape with `enabled: false` (since I don't have real Langfuse keys)

### 6. Pushed to both remotes at `076a7e5`
```
mybijouai-creator: 076a7e5 (canonical)
W3JDev:            076a7e5 (mirror)
```

## What you must do (the real handbacks)

### A. Add `mybijouai-creator` GitHub org to a Coolify GitHub App (5 min in UI)
This unblocks the deploy. Until then the new Langfuse env vars are set on the apps but the apps can't build (no git clone — see previous status doc).

### B. Sign up for Langfuse + create API keys (3 min)
1. After the Langfuse stack is up: open `https://<your-langfuse-domain>/auth/sign-up`
2. Create the org + first project
3. Settings → API Keys → Create new key
4. Copy the `pk-lf-...` and `sk-lf-...` values
5. Set in the Coolify env group for `bijou-backend`:
   - `LANGFUSE_ENABLED=true`
   - `LANGFUSE_PUBLIC_KEY=pk-lf-...`
   - `LANGFUSE_SECRET_KEY=sk-lf-...`
6. Restart `bijou-backend`
7. Visit admin → "LLM Traces" tab → click "test connection" → should report 200 OK

### C. Regenerate the LLM API keys (still needed)
ALL 6 LLM provider keys are dead. See previous status doc for details.

## Files added / changed this round
```
new   ops/langfuse/README.md                                     (5.4 KB)
new   ops/langfuse/docker-compose.local.yml                     (3.6 KB)
new   ops/langfuse/clickhouse-ipv4.xml                          (86 B)
new   packages/backend/src/core/langfuse_tracing.py              (11 KB)
mod   packages/backend/src/core/llm_gateway_v2.py                (gate.complete() wrapped)
mod   packages/backend/src/saas/admin_frontend_api.py            (+212 lines, 4 endpoints)
mod   packages/backend/static/admin.html                         (+191 lines, Langfuse tab)
mod   packages/backend/requirements.txt                         (langfuse>=4.0.0)
mod   docker-compose.coolify.yml                                (+119 lines, 5 services)
mod   ops/coolify/coolify.env.example                           (+19 lines, LANGFUSE_* block)
```

2 commits:
- `0febb9d feat(langfuse): LLM observability — tracing + admin dashboard`
- `076a7e5 docs(langfuse): setup + deploy order + verify guide`
