# Langfuse — LLM Observability for Bijou AI

> Traces every `ai://...` call from the Bijou backend into Langfuse, with
> per-alias cost, latency, token usage, and PII-masked input/output.

## What's wired

| Piece | Where | Purpose |
|---|---|---|
| `langfuse_tracing.py` | `packages/backend/src/core/` | Context-manager that opens a Langfuse `generation` observation per `ai://` call, records provider/model/output/tokens/cost, PII-masks MY phone numbers / emails / NRIC / credit cards, gracefully no-ops when keys are missing. |
| `llm_gateway_v2.py` integration | same dir | `LLMGateway.complete()` wraps the whole provider-chain loop in one observation. Each fallback updates the same span, the success path records the resolved model + token counts + cost. |
| Admin API | `packages/backend/src/saas/admin_frontend_api.py` | 4 new endpoints under `/admin/api/langfuse/`: `health`, `stats?days=N`, `traces`, `test-connection` (POST). |
| Admin dashboard | `packages/backend/static/admin.html` | New "LLM Traces" tab — health card, alias config, cost rollups by alias/provider/model, recent traces table. |
| Coolify service | `docker-compose.coolify.yml` | Full Langfuse v3 stack: web + worker + Postgres + ClickHouse + Redis + MinIO. Web on port 3000. |
| Local test stack | `ops/langfuse/docker-compose.local.yml` | Same stack for local dev. ClickHouse forced to IPv4 only (Docker Desktop on Windows breaks IPv6 in containers). |

## Deploy order (Coolify)

1. **Bring up Langfuse first**, before the backend. The Coolify compose
   file already lists them as siblings; if you re-import via the bot
   they'll be deployed in dependency order.

2. **Open the Langfuse UI** at `https://<your-langfuse-domain>/auth/sign-up`.
   Create the org + first project. The first user is automatically
   made an org owner.

3. **Create API keys** in the Langfuse UI: Settings → API Keys → Create
   new key. You'll get a `pk-lf-...` (public) and `sk-lf-...` (secret)
   pair.

4. **Set the env vars** in the Coolify env group for the `bijou-backend`
   service:
   ```
   LANGFUSE_ENABLED=true
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_HOST=http://langfuse-web:3000
   LANGFUSE_ENVIRONMENT=production
   LANGFUSE_SAMPLE_RATE=1.0
   LANGFUSE_MASK_PII=true
   ```

5. **Restart `bijou-backend`**. The gateway now sends every `ai://`
   call to Langfuse automatically. The admin dashboard's "LLM Traces"
   tab surfaces the same data via the `public.llm_usage` table so
   the dashboard works even when Langfuse itself is down.

## Verify the connection

Once deployed:

1. Open `https://<your-admin>/admin.html` → "LLM Traces" tab.
2. The status card should show `Langfuse: ready` and the probe button
   should report `200 OK /api/public/health`.
3. Send a chat message through the bot (or any code path that calls
   `await llm.complete("ai://fast", ...)`). Within ~10s a new trace
   shows up in the Langfuse UI under the project + in the "Recent
   LLM calls" table at the bottom of the admin tab.

## Self-hosted vs Langfuse Cloud

| | Self-hosted (this compose file) | Langfuse Cloud |
|---|---|---|
| Cost | $0 (just your server) | Free tier 50k obs/mo, then per-100k |
| Setup | 1 deploy + 1 sign-up | 1 sign-up |
| Data | Your Postgres | Langfuse Postgres (EU or US) |
| Customize prompts | Yes | Yes |
| Eval features | Yes | Yes |

For production, self-hosting is recommended because the traces may
contain customer PII (even after masking, defensive privacy posture is
to keep data on your own infrastructure). The compose file is
production-ready — change the `LANGFUSE_NEXTAUTH_SECRET` and
`LANGFUSE_SALT` env vars before exposing publicly.

## PII masking (PDPA / GDPR)

`LANGFUSE_MASK_PII=true` (default on) strips:

- Malaysian phone numbers (`+60...`)
- International E.164 numbers
- Email addresses
- Credit card numbers (basic Luhn-shaped)
- Malaysian NRIC (`YYMMDD-PB-###G`)
- MY plate (rough)

Masking happens inside `trace_completion()` BEFORE the input is sent
to Langfuse. The gateway's own logs and the `llm_usage` table get the
**raw** content (those stay inside Bijou's Supabase, which is your
own RLS-protected DB).

## Sampling

`LANGFUSE_SAMPLE_RATE=0.1` traces 10% of calls. Useful for production
where the full trace volume is too much for the Langfuse cluster.
Set to `1.0` (default) for development. The admin dashboard's
`llm_usage` table still records every call regardless of sample rate.

## Local testing (no Coolify)

```bash
docker compose -f ops/langfuse/docker-compose.local.yml up -d
# wait ~30s for the web to come up
open http://localhost:3000
# sign up, create project, copy the public+secret keys
# paste into .env as LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=...
# set LANGFUSE_ENABLED=true and LANGFUSE_HOST=http://localhost:3000
# restart the Bijou backend
```

Then visit `http://localhost:8080/admin.html` → "LLM Traces" tab.

## Health

```bash
curl -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8080/admin/api/langfuse/health
```

```json
{
  "enabled": true,
  "sdk_available": true,
  "configured": true,
  "ready": true,
  "host": "http://langfuse-web:3000",
  "environment": "production",
  "sample_rate": 1.0,
  "mask_pii": true,
  "aliases": [
    {"alias": "ai://fast", "description": "Default chat replies ...", "privacy": "standard", "daily_budget_usd": 25.0, "spent_today_usd": 0.0}
  ]
}
```
