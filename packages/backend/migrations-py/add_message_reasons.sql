-- 2026-08-23: Reasoning Trace — the "why did Bijou say that" primitive
-- (issue #11, second of 4 agentic-GenUI primitives from the teardown).
--
-- When Bijou generates an AI response, we now record WHY: which KB docs were
-- retrieved, which tool calls were made, the model version, a confidence score,
-- and 2-3 alternative replies considered. The Inbox side panel (next step)
-- will show this on tap. This is also the EU AI Act 2024 traceability
-- primitive (Article 13 — transparency obligations for AI systems).
--
-- message_id is a string rather than a UUID FK because the source-of-truth
-- message lives in either public.messages or public.conversations (the
-- codebase uses both depending on the code path). We cross-check at
-- integration time and store the full reference for audit.
create table if not exists public.message_reasons (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,

  -- Reference to the source AI message. Soft FK; the actual message lives
  -- in messages or conversations depending on the chat's code path.
  message_id text not null,
  chat_jid text not null,
  channel text not null default 'whatsapp'
    check (channel in ('whatsapp','telegram','voice','sms','email')),

  -- The actual reasoning payload.
  retrieved_docs jsonb not null default '[]'::jsonb,  -- [{doc_id, title, relevance}]
  tool_calls jsonb not null default '[]'::jsonb,       -- [{name, args, result}]
  model text,                                          -- 'gemini-2.5-flash', etc.
  confidence numeric,                                  -- 0.0..1.0, nullable
  alternatives jsonb not null default '[]'::jsonb,     -- [{text, score}]
  metadata jsonb not null default '{}'::jsonb,          -- prompt_tokens, latency_ms, etc.

  created_at timestamptz not null default now()
);
create index if not exists idx_message_reasons_lookup
  on public.message_reasons (tenant_id, message_id);
create index if not exists idx_message_reasons_chat
  on public.message_reasons (tenant_id, chat_jid, created_at desc);
-- RLS: same posture as shared_context. service_role bypasses; tenant
-- isolation is enforced in the API layer.
alter table public.message_reasons enable row level security;
comment on table public.message_reasons is
  'Per-message AI reasoning trace. EU AI Act 2024 Article 13 traceability. Service-role only.';
