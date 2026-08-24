-- 2026-08-24: LLM Gateway v2 — usage observability
-- Records every llm.complete() call: which alias, which provider/model answered,
-- latency, token usage, cost, and any fallback reason. Powers the dashboard
-- "AI spend" view and per-tenant cost alerts.
--
-- This table is the single source of truth for cost observability. The gateway
-- (src/core/llm_gateway_v2.py) buffers rows in memory and flushes them here
-- via a cron / shutdown handler. Direct INSERTs are also fine.
create table if not exists public.llm_usage (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  ts timestamptz not null,            -- client-reported time (gateway clock)
  alias text not null,                -- 'ai://fast' | 'ai://reasoning' | 'ai://extract' | 'ai://private'
  provider text not null,             -- 'gemini' | 'openai_compatible' | 'openrouter' | '(none)' on full failure
  model text not null,
  cost_usd numeric(12, 6) not null default 0,
  latency_ms integer not null default 0,
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  fallback_reason text,               -- 'http_429' | 'http_503' | 'transport_error' | 'all_providers_failed' | null
  error_class text,                   -- exception classname on a failed call
  tenant_id uuid                      -- null for shared/system calls (self-test, lead-capture pre-auth)
);

-- Lookups the dashboard actually uses:
-- 1. per-day per-alias spend (for budget charts and alerts)
create index if not exists idx_llm_usage_alias_day
  on public.llm_usage (alias, date_trunc('day', created_at));

-- 2. per-tenant per-day cost (for billing / fairness)
create index if not exists idx_llm_usage_tenant_day
  on public.llm_usage (tenant_id, date_trunc('day', created_at))
  where tenant_id is not null;

-- 3. failure triage — which aliases are falling back most today?
create index if not exists idx_llm_usage_fallback
  on public.llm_usage (date_trunc('hour', created_at), fallback_reason)
  where fallback_reason is not null;

-- RLS: same posture as the rest of the schema (per CLAUDE.md "RLS was hardened
-- by ops/_fix_rls_v6.js"). Only service_role writes/reads. The dashboard reads
-- via a server-side endpoint, not directly from the browser.
alter table public.llm_usage enable row level security;
-- No permissive policies. service_role bypasses RLS.
comment on table public.llm_usage is
  'AI Gateway v2 per-request usage log. Service-role only.';
