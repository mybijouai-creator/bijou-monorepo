-- 2026-08-23: Outreach consent log (issue #14, the other half of PDPA)
--
-- We already have the data-request page (right to be forgotten, issue #26)
-- and the DATA_SUBJECT_RIGHTS.md matrix. This table is the OTHER half of
-- PDPA: a verifiable record of affirmative consent BEFORE sending any
-- outreach message. Without this, a "the customer asked to be removed
-- from your list" complaint can only be answered with a shrug.
--
-- The contract:
--   1. A contact must have at least one row in this table with
--      consent_type IN ('opt_in', 'transactional') and
--      revoked_at IS NULL BEFORE any campaign can include them.
--   2. Every row records WHO gave consent, WHEN, WHERE (channel),
--      and the EXACT consent text they saw (so we can prove it was
--      unambiguous, not buried in fine print).
--   3. Revocation is soft (revoked_at timestamp) so the audit trail
--      is preserved; we never lose the proof that consent was given
--      and later withdrawn.
--   4. The outreach_api start_campaign endpoint REFUSES to queue a
--      message to any contact without an active consent row. This is
--      enforced at the API layer, not just at the DB layer.
create table if not exists public.outreach_consent_log (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id) on delete cascade,
  contact_id      uuid not null references public.contacts(id) on delete cascade,

  -- What kind of consent was given
  consent_type    text not null
    check (consent_type in ('opt_in','opt_out','transactional','imported_legacy')),

  -- The exact text the contact agreed to (or NULL for opt_out /
  -- imported_legacy where there's no agreement text)
  consent_text    text,

  -- How the consent was collected
  channel         text not null
    check (channel in ('web_form','whatsapp','sms','email','in_person','api','imported')),

  -- Provenance: who/what recorded this consent
  source          text not null default 'manual',  -- 'form','csv_import','api','whatsapp_keyword'
  ip_address      inet,                            -- nullable for non-web sources
  user_agent      text,                            -- nullable for non-web sources

  -- Lifecycle
  granted_at      timestamptz not null default now(),
  expires_at      timestamptz,                     -- nullable; null = no expiry
  revoked_at      timestamptz,                     -- nullable; null = still active
  revoked_reason  text,

  created_at      timestamptz not null default now()
);
create index if not exists idx_outreach_consent_contact
  on public.outreach_consent_log (tenant_id, contact_id, revoked_at);
create index if not exists idx_outreach_consent_active
  on public.outreach_consent_log (tenant_id, contact_id)
  where revoked_at is null;
-- RLS: only service_role reads/writes (same posture as the other
-- consent/audit tables in this schema).
alter table public.outreach_consent_log enable row level security;
comment on table public.outreach_consent_log is
  'Per-contact outreach consent audit log. PDPA / GDPR / MY PDPA 2010: an outreach message cannot be sent without an active row in this table. Service-role only.';
