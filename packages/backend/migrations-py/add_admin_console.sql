-- 2026-08-24: Bijou Admin Frontend v0.1
-- Adds two tables for the new /admin console and the MCP server.
--
--   platform_admins  — who is allowed to call /admin/api/* and the MCP
--   audit_log        — append-only trail of every sensitive admin action
--
-- Both are written via the Supabase service-role key only. RLS is enabled
-- but no permissive policies are added (the post-v6 RLS hardening posture:
-- anything not service-role is denied, and the API layer enforces its own
-- tenancy via verify_session + the platform_admins lookup).

-- =========================================================================
-- platform_admins
-- =========================================================================
create table if not exists public.platform_admins (
  -- References auth.users so we can join to the Supabase JWT's `sub` claim
  -- without a second table. ON DELETE CASCADE: if the auth user is deleted,
  -- the platform-admin row goes with it (no orphans).
  user_id    uuid primary key references auth.users(id) on delete cascade,

  -- Denormalized for display. Supabase auth.users.email is also available
  -- via admin API but we cache it here so audit_log doesn't need a join
  -- for the "who did this" column.
  email      text not null,

  -- Two roles:
  --   admin      — can do everything except manage other platform_admins
  --   superadmin — can also add/remove other platform_admins
  -- The Phase 4 UI will respect this distinction; v0.1 treats both as
  -- "platform admin" with full access to the 10 endpoints.
  role       text not null default 'admin' check (role in ('admin', 'superadmin')),

  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id),
  notes      text
);

comment on table public.platform_admins is
  'Platform-level admins (NOT tenant-scoped). Used by /admin/api/* and the MCP server. Service-role writes only.';
comment on column public.platform_admins.role is
  'admin = full access to the 10 admin endpoints. superadmin = also allowed to manage other platform_admins (Phase 4).';

-- =========================================================================
-- audit_log
-- =========================================================================
create table if not exists public.audit_log (
  id          uuid primary key default gen_random_uuid(),

  -- Who did this. NULL when the action came from a service that doesn't
  -- have a user identity (e.g. a cron that hits /admin/api/migrations/apply
  -- via a service-to-service key). When the actor is a platform_admin,
  -- this is their Supabase auth.uid.
  actor_id    uuid references auth.users(id),

  -- Denormalized for display — never break the audit trail if the user
  -- changes their email later.
  actor_email text,

  -- Where the action came from. The UI sends 'platform_admin'; the MCP
  -- server sends 'mcp'; cron / webhooks send 'service'.
  actor_type  text not null check (actor_type in ('platform_admin', 'service', 'mcp')),

  -- What was done. A dotted path: 'user.impersonate', 'migration.apply',
  -- 'billing.refund', etc. Kept short so the audit table is grep-friendly.
  action      text not null,

  -- What it was done to. Optional — some actions are global (e.g.
  -- 'migration.apply' targets a migration filename, not a row id).
  target_type text,
  target_id   text,

  -- Free-form per-action context. We keep this structured (jsonb) so the
  -- Phase 4 search UI can filter ("show me all refunds over RM 100 this
  -- month"). Never put secrets here.
  metadata    jsonb not null default '{}'::jsonb,

  -- Network layer — for the "someone from an unexpected IP did something"
  -- alert. Best-effort; we read X-Forwarded-For in the API.
  ip          text,
  user_agent  text,

  created_at  timestamptz not null default now()
);

-- Indexes for the Phase 4 audit-log search UI.
create index if not exists idx_audit_log_created
  on public.audit_log (created_at desc);
create index if not exists idx_audit_log_actor
  on public.audit_log (actor_id, created_at desc);
create index if not exists idx_audit_log_target
  on public.audit_log (target_type, target_id, created_at desc);
create index if not exists idx_audit_log_action
  on public.audit_log (action, created_at desc);

comment on table public.audit_log is
  'Append-only audit trail for platform_admin actions and MCP service calls. Service-role writes only; reads via /admin/api/audit.';
comment on column public.audit_log.actor_type is
  'platform_admin = came from /admin.html via JWT; mcp = came from the owner''s agent team via /admin/mcp; service = cron / webhook.';
comment on column public.audit_log.action is
  'Dotted action name. user.impersonate / migration.apply / billing.refund / tenant.suspend / keys.test.';

-- =========================================================================
-- RLS — same posture as the rest of the schema post-v6 hardening.
-- Enabled, with no permissive policies. service_role bypasses.
-- Anything using the anon or authenticated role against these tables will
-- fail with a clear "permission denied for table platform_admins" until
-- a policy is added. We intentionally do not add one.
-- =========================================================================
alter table public.platform_admins enable row level security;
alter table public.audit_log     enable row level security;
