-- 2026-08-23: PDPA / GDPR data-request tracking (issue #26)
-- Records every data subject access or delete request Bijou receives.
-- The MVP endpoint at /api/data-request/{access,delete,download} logs
-- here for audit. A follow-up migration adds a deleted_at column to
-- conversations, messages, contacts, escalations, shared_context, and
-- message_reasons so the soft-delete actually hides data; a separate
-- cron hard-deletes after the 30-day grace period.
create table if not exists public.data_request_deletions (
  id uuid primary key default gen_random_uuid(),
  -- phone_normalized is the dedupe key: a customer can submit a delete
  -- request multiple times; the upsert keeps only the latest.
  phone_normalized text not null,
  email text not null,
  request_id text not null,
  row_count_at_request integer not null default 0,
  -- grace_until + status let the owner run a cron that hard-deletes
  -- rows after the 30-day grace expires.
  grace_until timestamptz not null,
  status text not null default 'pending' check (status in ('pending','processing','done','cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists idx_data_request_deletions_phone
  on public.data_request_deletions (phone_normalized);
create index if not exists idx_data_request_deletions_status_grace
  on public.data_request_deletions (status, grace_until);
-- RLS: same posture. service_role bypasses.
alter table public.data_request_deletions enable row level security;
comment on table public.data_request_deletions is
  'PDPA / GDPR right-to-erasure tracker. Owner runs a cron that hard-deletes after grace_until. Service-role only.';
