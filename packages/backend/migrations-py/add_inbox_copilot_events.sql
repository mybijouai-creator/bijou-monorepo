-- 2026-08-23: Inbox Co-pilot audit log (issue #13)
-- Records every suggestion batch the Co-pilot surfaces and every
-- user action (accept / edit / dismiss) on a suggestion. Gives the
-- founder real data on which suggestions are useful and which to retire.
-- The frontend is intentionally read-only on this data; the founder
-- views it via Supabase Studio or a follow-up analytics tab.
create table if not exists public.inbox_copilot_events (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,

  -- 'suggest' = a batch of suggestions was surfaced;
  -- 'accept' / 'edit' / 'dismiss' = a user action on one suggestion.
  kind text not null check (kind in ('suggest','accept','edit','dismiss')),

  -- For 'suggest': a unique id for the batch; client passes it back in
  -- the 'action' POST. For accept/edit/dismiss: the same id (groups
  -- the suggestion with the user response).
  event_id text not null,

  -- The chat this happened in. chat_jid is denormalized here for
  -- fast "what happened in this conversation" queries.
  chat_jid text not null,

  -- For 'suggest' kinds: the full list of suggestion ids surfaced.
  -- For 'accept'/'edit'/'dismiss' kinds: the single id that was acted on.
  suggestion_id text,
  suggestion_ids jsonb,

  -- Optional context: the draft the agent was typing, the last
  -- customer message, the conversation age. Best-effort, may be null.
  draft_reply text,
  last_customer_message text,
  conversation_age_minutes integer,

  created_at timestamptz not null default now()
);
create index if not exists idx_inbox_copilot_events_tenant
  on public.inbox_copilot_events (tenant_id, created_at desc);
create index if not exists idx_inbox_copilot_events_event
  on public.inbox_copilot_events (event_id);
-- RLS: same posture as the rest of the schema. service_role bypasses;
-- tenant isolation enforced in the API layer via verify_session.
alter table public.inbox_copilot_events enable row level security;
comment on table public.inbox_copilot_events is
  'Inbox Co-pilot audit log. Track which suggestions surface and which the user accepts/edits/dismisses. Service-role only.';
