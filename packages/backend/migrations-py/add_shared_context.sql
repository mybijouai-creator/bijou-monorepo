-- 2026-08-23: A2A shared context layer
-- Lets Bijou's WA agent and the (forthcoming) Telnyx voice agent share
-- conversation state per (tenant_id, customer_phone). This is the first
-- 30-day step of issue #23.
create table if not exists public.shared_context (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  customer_phone text not null,
  channel text not null check (channel in ('whatsapp','telegram','voice','sms','email')),
  thread_id text not null,  -- chat_jid for WA, call_id for voice
  role text not null check (role in ('user','assistant','system')),
  content text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_shared_context_lookup
  on public.shared_context (tenant_id, customer_phone, created_at desc);
create index if not exists idx_shared_context_thread
  on public.shared_context (tenant_id, thread_id, created_at desc);
-- RLS: only service_role reads/writes (matches the RLS policy in the rest
-- of the schema per CLAUDE.md "RLS was hardened by ops/_fix_rls_v6.js")
alter table public.shared_context enable row level security;
-- No policies; service_role bypasses RLS. Tenant isolation is enforced in
-- the API layer (every query filters by tenant_id from verify_session).
comment on table public.shared_context is
  'Cross-channel conversation state for A2A handoffs. Service-role only.';
