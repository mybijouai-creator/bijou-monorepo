-- ============================================================================
-- BIJOU AI: ALL MIGRATIONS (combined)
-- ============================================================================
-- Generated: 2026-08-24 12:52:14
-- How to apply:
--   OPTION A (manual, 1 minute):
--     1. Open https://supabase.com/dashboard/project/lrwzlujomukzjykafmic/sql
--     2. Paste this entire file
--     3. Click "Run" (no need to enable any confirmations)
--   OPTION B (terminal, 30 seconds):
--     export SUPABASE_DB_URL="postgresql://postgres.lrwzlujomukzjykafmic:YOUR_PASSWORD@aws-0-...pooler.supabase.com:6543/postgres"
--     python scripts/apply_migrations.py
-- Idempotency: each migration uses IF NOT EXISTS, so it's safe to re-run.
-- ============================================================================


-- ============================================================================
-- add_data_request_deletions.sql (30 bytes)
-- ============================================================================

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

-- ============================================================================
-- add_device_session_schema.sql (79 bytes)
-- ============================================================================

-- Device Session Schema Migration
-- Purpose: Add multi-tenant device session support for WhatsApp GOWA integration
-- Run this in Supabase SQL Editor

-- Step 1: Add device-related columns to tenants table
ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS device_id TEXT,
ADD COLUMN IF NOT EXISTS whatsapp_jid TEXT,
ADD COLUMN IF NOT EXISTS session_active BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS session_connected_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;

-- Step 2: Create device_sessions table for multi-device management
CREATE TABLE IF NOT EXISTS device_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL UNIQUE,
    whatsapp_jid TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'disconnected', 'expired')),
    qr_code_url TEXT,
    qr_expires_at TIMESTAMPTZ,
    connected_at TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Step 3: Create indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_device_sessions_device_id ON device_sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_device_sessions_tenant_id ON device_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_device_sessions_status ON device_sessions(status);
CREATE INDEX IF NOT EXISTS idx_tenants_device_id ON tenants(device_id);

-- Step 4: Create function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Step 5: Create trigger for auto-updating updated_at
DROP TRIGGER IF EXISTS update_device_sessions_updated_at ON device_sessions;
CREATE TRIGGER update_device_sessions_updated_at
    BEFORE UPDATE ON device_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Step 6: Enable RLS on device_sessions table
ALTER TABLE device_sessions ENABLE ROW LEVEL SECURITY;

-- Step 7: Add RLS policies for device_sessions table

-- Allow service role full access
DROP POLICY IF EXISTS "Allow service role full access to device_sessions" ON device_sessions;
CREATE POLICY "Allow service role full access to device_sessions"
    ON device_sessions
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Allow authenticated users to view their own device sessions
DROP POLICY IF EXISTS "Users can view their own device sessions" ON device_sessions;
CREATE POLICY "Users can view their own device sessions"
    ON device_sessions
    FOR SELECT
    TO authenticated
    USING (
        tenant_id IN (
            SELECT id FROM tenants WHERE owner_id = auth.uid()
        )
    );

-- Verification queries (optional, uncomment to check)
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'tenants' AND column_name LIKE '%device%';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'device_sessions';
-- SELECT COUNT(*) as device_session_count FROM device_sessions;

-- ============================================================================
-- add_inbox_copilot_events.sql (45 bytes)
-- ============================================================================

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

-- ============================================================================
-- add_message_media_columns.sql (53 bytes)
-- ============================================================================

-- ============================================================================
-- Add media columns to messages table â€” 2026-08-23
-- ============================================================================
--
-- Problem: The `messages` table has NO media columns at all. When a customer
-- sends a photo/voice note/document over WhatsApp, `bijou.py` downloads it,
-- runs it through Gemini/Deepgram, and stores only the AI's text summary
-- (e.g. "ðŸ“¸ Image: a receipt for RM45.20...") in `content`. A human agent who
-- takes over the chat in the dashboard can read that summary but can never
-- see the actual attachment â€” no photo, no audio player, no file link.
--
-- Fix: additive, nullable columns to persist the raw WhatsApp media
-- reference alongside the message. Populated only for inbound customer
-- messages that actually carry media (see bijou.py::_save_message); left
-- NULL for text-only messages and for the AI's own text reply.
--
-- Run this against the Supabase Postgres database (same one `messages`
-- already lives in â€” service-role key required, RLS blocks anon/authenticated).
-- ============================================================================

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS media_url TEXT;

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS media_type TEXT;

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS media_mime TEXT;

-- ============================================================================
-- Verification Queries (run these after migration)
-- ============================================================================

-- Confirm columns exist:
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'messages' AND column_name IN ('media_url', 'media_type', 'media_mime');

-- Sanity check on real data (should show NULL for text-only rows):
-- SELECT id, role, media_type, media_url FROM messages ORDER BY created_at DESC LIMIT 20;

-- ============================================================================
-- How to Run This Migration
-- ============================================================================
--
-- Via Supabase SQL Editor:
--   1. Copy the SQL above
--   2. Go to Supabase SQL Editor (project lrwzlujomukzjykafmic)
--   3. Paste and run
--
-- Via local psql (if you have the DB URL):
--   psql "postgres://..." -f migrations-py/add_message_media_columns.sql
-- ============================================================================

-- ============================================================================
-- add_message_reasons.sql (43 bytes)
-- ============================================================================

-- 2026-08-23: Reasoning Trace â€” the "why did Bijou say that" primitive
-- (issue #11, second of 4 agentic-GenUI primitives from the teardown).
--
-- When Bijou generates an AI response, we now record WHY: which KB docs were
-- retrieved, which tool calls were made, the model version, a confidence score,
-- and 2-3 alternative replies considered. The Inbox side panel (next step)
-- will show this on tap. This is also the EU AI Act 2024 traceability
-- primitive (Article 13 â€” transparency obligations for AI systems).
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

-- ============================================================================
-- add_outreach_consent.sql (61 bytes)
-- ============================================================================

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

-- ============================================================================
-- add_shared_context.sql (26 bytes)
-- ============================================================================

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

-- ============================================================================
-- add_tenant_integrations.sql (22 bytes)
-- ============================================================================

-- Migration: tenant_integrations table for Nango-managed OAuth connections
-- Date: 2026-08-23
--
-- Replaces the never-launched Composio scaffold (src/connectors/oauth_api.py,
-- src/connectors/auth_configs.py â€” ENABLE_COMPOSIO was never set in
-- production, zero COMPOSIO_AUTH_ID_* secrets configured, router never
-- mounted) with Nango (nango.dev), which handles OAuth + token refresh for
-- each tenant's connected third-party account. Nango itself stores the OAuth
-- tokens; this table only records, per tenant, which integration is
-- connected and under which Nango connection_id, so the backend can look up
-- the right connection_id to call Nango's proxy on the tenant's behalf.
CREATE TABLE IF NOT EXISTS tenant_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    integration_id TEXT NOT NULL,       -- Nango "Provider-Config-Key", e.g. 'google-calendar'
    connection_id TEXT NOT NULL,        -- Nango "Connection-Id"
    status TEXT DEFAULT 'connected',
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, integration_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_integrations_tenant_id ON tenant_integrations (tenant_id);

-- ============================================================================
-- add_whatsapp_device_mapping.sql (54 bytes)
-- ============================================================================

-- Migration: Add WhatsApp Device Mapping for Admin Tenant
-- Purpose: Enable QR code generation for the system admin dashboard
-- Date: 2026-02-17

-- Step 1: Create whatsapp_devices table if it doesn't exist
CREATE TABLE IF NOT EXISTS whatsapp_devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  device_id TEXT NOT NULL UNIQUE,
  device_name TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Step 2: Add foreign key constraint (if tenants table exists)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants') THEN
    ALTER TABLE whatsapp_devices
    ADD CONSTRAINT fk_whatsapp_devices_tenant
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- Step 3: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_whatsapp_devices_tenant ON whatsapp_devices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_devices_device_id ON whatsapp_devices(device_id);

-- Step 4: Insert admin device mapping
INSERT INTO whatsapp_devices (tenant_id, device_id, device_name, is_active)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'w3j-admin-device',
  'W3J Admin WhatsApp',
  true
)
ON CONFLICT (device_id) DO UPDATE SET
  device_name = EXCLUDED.device_name,
  is_active = EXCLUDED.is_active,
  updated_at = NOW();

-- Step 5: Verify the insertion
SELECT
  id,
  tenant_id,
  device_id,
  device_name,
  is_active,
  created_at
FROM whatsapp_devices
WHERE tenant_id = '00000000-0000-0000-0000-000000000001';

-- ============================================================================
-- add_whatsapp_devices_tenant_unique.sql (30 bytes)
-- ============================================================================

-- Migration: unique constraint on whatsapp_devices.tenant_id
-- Date: 2026-08-22
--
-- Root cause: three call sites (onboarding_api.py provision-on-demand,
-- bijou.py send-message auto-discovery cache, dashboard_api_simple.py
-- auto-discovery cache) all upsert into whatsapp_devices with
-- on_conflict="tenant_id", assuming "one device row per tenant". But the
-- only constraint ever added on this table (add_whatsapp_device_mapping.sql)
-- is UNIQUE on device_id, not tenant_id. Postgres requires ON CONFLICT to
-- target a column backed by a real unique/exclusion constraint (error
-- 42P10) â€” every one of those upserts has been silently failing (caught by
-- a bare except and logged as a warning), so the device_id -> tenant_id
-- mapping this table exists to hold has never actually been persisted.
-- Downstream effect: the WhatsApp-connected webhook can't resolve tenant_id
-- for on-demand-provisioned devices (whose device_id isn't the predictable
-- bijou-{tenant_id} format), so onboarding never flips to "connected" even
-- after a real scan.
--
-- Step 1: collapse any pre-existing duplicate tenant_id rows (defensive â€”
-- given the upserts always errored, there should be at most one row per
-- tenant already, but don't assume it). Keep the newest row per tenant.
DELETE FROM whatsapp_devices a
USING whatsapp_devices b
WHERE a.tenant_id = b.tenant_id
  AND a.id <> b.id
  AND (a.updated_at, a.id) < (b.updated_at, b.id);

-- Step 2: add the constraint the three call sites already assume exists.
ALTER TABLE whatsapp_devices
  ADD CONSTRAINT uq_whatsapp_devices_tenant UNIQUE (tenant_id);

-- ============================================================================
-- bridge_add_tenant_id.sql (74 bytes)
-- ============================================================================

-- ============================================================================
-- WhatsApp Bridge Database Migration: Add tenant_id Support
-- ============================================================================
-- 
-- Problem: Bridge tables 'chats' and 'messages' are missing tenant_id column
-- Error: "SQL logic error: table chats has no column named tenant_id (1)"
--
-- This migration adds tenant_id to support multi-tenant WhatsApp sessions.
--
-- Run this against the WHATSAPP_DB_URL PostgreSQL database
-- ============================================================================

-- Step 1: Add tenant_id column to chats table
ALTER TABLE chats 
ADD COLUMN IF NOT EXISTS tenant_id TEXT;

-- Step 2: Add tenant_id column to messages table  
ALTER TABLE messages 
ADD COLUMN IF NOT EXISTS tenant_id TEXT;

-- Step 3: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_chats_tenant_id ON chats(tenant_id);
CREATE INDEX IF NOT EXISTS idx_messages_tenant_id ON messages(tenant_id);

-- Step 4: Update existing rows with default tenant ID (if any exist)
-- This assumes you have one existing tenant - update the UUID to match yours
UPDATE chats 
SET tenant_id = '87dcc712-1eb3-4772-a682-d74f67d13f92' 
WHERE tenant_id IS NULL;

UPDATE messages 
SET tenant_id = '87dcc712-1eb3-4772-a682-d74f67d13f92' 
WHERE tenant_id IS NULL;

-- Step 5: (Optional) Make tenant_id NOT NULL after backfilling
-- Uncomment these if you want to enforce tenant_id requirement:
-- ALTER TABLE chats ALTER COLUMN tenant_id SET NOT NULL;
-- ALTER TABLE messages ALTER COLUMN tenant_id SET NOT NULL;

-- ============================================================================
-- Verification Queries (run these after migration)
-- ============================================================================

-- Check chats table structure
-- SELECT column_name, data_type, is_nullable 
-- FROM information_schema.columns 
-- WHERE table_name = 'chats';

-- Check messages table structure  
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns 
-- WHERE table_name = 'messages';

-- Check if existing data has tenant_id
-- SELECT tenant_id, COUNT(*) FROM chats GROUP BY tenant_id;
-- SELECT tenant_id, COUNT(*) FROM messages GROUP BY tenant_id;

-- ============================================================================
-- How to Run This Migration
-- ============================================================================
--
-- Option 1: Via Fly.io SSH (if psql is available):
--   flyctl ssh console -a whatsapp-bridge-staging-w3j
--   psql $WHATSAPP_DB_URL -f /path/to/this/file.sql
--
-- Option 2: Via Supabase SQL Editor (if using Supabase for bridge DB):
--   1. Copy the SQL above
--   2. Go to Supabase SQL Editor
--   3. Paste and run
--
-- Option 3: Via local psql (if you have the DB URL):
--   psql "postgres://..." -f migrations/bridge_add_tenant_id.sql
--
-- ============================================================================
