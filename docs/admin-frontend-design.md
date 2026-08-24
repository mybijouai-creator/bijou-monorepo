# Bijou Admin Frontend — Design

> **Status:** v0.1 scaffold (shipped 2026-08-24, commit `8ac3744`)
> **Owner:** W3J (solo)
> **Goal:** The owner (and the owner's autonomous agent team) can run the entire platform — user mgmt, billing, migrations, keys, audit — from a single in-app console, without ever opening a terminal or reading code.

---

## 1. Why this exists

`packages/backend/static/dashboard.html` (9,737 lines) is a **tenant-facing** console. Each tenant sees only their own data: their inbox, their KB, their billing. Anything *platform-facing* — every tenant at once, system internals, secrets, migrations — is currently CLI-only, Supabase-Studio-only, or Stripe-Dashboard-only. The CLAUDE.md "Deployment topology" table already shows how painful this is:

- Fly secrets are rotated via `flyctl secrets unset … -a bijou-production` (terminal)
- Migrations are applied via `python scripts/apply_migrations.py` (terminal)
- Stripe refunds happen in the Stripe Dashboard (browser, different login)
- Adding a user manually = `auth.users` insert via Supabase Studio
- Looking at "tenant X is having problem Y" = log into Supabase, write SQL, find the row

Per the owner: *"i do not wanna go n check code, or run terminal command for any admin side, backend management, db, users managements, updates, payments, and so on... but via a admin frontend only for me, with ready agent access, for my autonomous agent team to access n manage that."*

This doc describes the design that satisfies that.

---

## 2. Gap inventory — what's CLI-only today

Audited from `packages/backend/src/saas/admin_api.py` (the *only* existing admin surface) and the rest of the codebase.

| Operation | Today (CLI / Studio) | After (Admin API + UI) |
|---|---|---|
| List all tenants | `admin_api.py:146` GET `/api/admin/tenants` ✅ (already there) | kept + enriched with usage & billing |
| Re-link a WhatsApp device | `admin_api.py:192` POST `/api/admin/qr/{id}` ✅ | kept + add "force re-link" |
| Seed templates | `admin_api.py:340` ✅ | kept |
| **List all users across all tenants** | Supabase Studio only | **NEW** GET `/admin/api/users` |
| **Get full user detail (last login, role)** | Supabase Studio only | **NEW** GET `/admin/api/users/{id}` |
| **Impersonate a user (support case)** | Build a JWT manually | **NEW** POST `/admin/api/users/{id}/impersonate` |
| **Add/remove a user manually** | Supabase Studio | **NEW** POST `/admin/api/users` (Phase 4) |
| **Apply a pending migration** | `scripts/apply_migrations.py` from terminal | **NEW** POST `/admin/api/migrations/apply` |
| **List applied + pending migrations** | `select filename from schema_migrations` in Studio | **NEW** GET `/admin/api/migrations` |
| **Stripe MRR / revenue summary** | Stripe Dashboard | **NEW** GET `/admin/api/billing/summary` |
| **Issue a refund** | Stripe Dashboard → Refund → copy charge id | **NEW** POST `/admin/api/billing/refund` |
| **List recent payment transactions** | Stripe Dashboard | **NEW** GET `/admin/api/billing/transactions` |
| **List configured API keys (masked)** | `flyctl secrets list -a bijou-production` | **NEW** GET `/admin/api/keys` |
| **Test an integration (live)** | `python -c "import stripe; …"` | **NEW** POST `/admin/api/keys/test/{name}` |
| **Reconnect a stuck bridge device** | Restart the Go bridge container | **NEW** POST `/admin/api/tenants/{id}/reconnect` (Phase 4) |
| **Suspend a tenant (no WhatsApp replies)** | `update tenants set status='suspended'` in Studio | **NEW** POST `/admin/api/tenants/{id}/suspend` (Phase 4) |
| **Recent admin actions (who did what)** | grep logs | **NEW** GET `/admin/api/audit` (audit_log table) |

---

## 3. Architecture

### 3.1 Two routers, one shared auth

We keep `src/saas/admin_api.py` (the X-Admin-Key legacy surface) untouched for backwards compat, and add a **new** `src/saas/admin_frontend_api.py` mounted at `/admin/api/*` that:

1. Authenticates the user via `verify_session` (Supabase JWT) AND checks the new `platform_admins` table
2. Logs every sensitive action to `audit_log`
3. Reuses the same `_check_admin_key` as a service-to-service fallback (for the MCP wrapper)

```
   ┌────────────────────────────────────────────────────────┐
   │        /admin.html (static/admin.html)                  │
   │   React 18 + in-browser JSX, same pattern as dashboard  │
   │   → /admin/api/* (fetch w/ bearer JWT)                  │
   └──────────────────┬──────────────────────────────────────┘
                      │  Authorization: Bearer <jwt>
                      ▼
   ┌────────────────────────────────────────────────────────┐
   │  /admin/api/*  (src/saas/admin_frontend_api.py)         │
   │   dep: require_platform_admin                          │
   │     1. verify_session → tenant_id (any)                 │
   │     2. SELECT 1 FROM platform_admins WHERE user_id=…   │
   │     3. write audit_log row on POST/DELETE               │
   └──────────────────┬──────────────────────────────────────┘
                      │
                      ▼
   ┌────────────────────────────────────────────────────────┐
   │   Supabase service-role (postgres)                      │
   │   Stripe REST API (refunds)                             │
   │   scripts/apply_migrations.py (refactored)              │
   └────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────┐
   │  /admin/mcp  (src/core/admin_mcp_server.py)             │
   │   Same endpoints, called via X-Admin-Key from the       │
   │   owner's autonomous agent team (Mavis / Claude).       │
   │   Per-tool audit_log entry.                             │
   └────────────────────────────────────────────────────────┘
```

### 3.2 Auth model — `platform_admins` table

Why a new table instead of a column on `tenants.user`:

- `tenants.user` is `tenants.owner_id` — that is the **tenant**'s relationship to the user. Mixing in a *platform* role there breaks the multi-tenant boundary.
- We want platform admins to be **separate from tenant users** so the same Supabase JWT can be a regular tenant in one org AND a platform admin in another.
- We need **per-user audit** ("W3J did this") not per-secret ("X-Admin-Key did this").

```sql
-- 2026-08-24: Bijou Admin Frontend v0.1
create table if not exists public.platform_admins (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  email       text not null,
  role        text not null default 'admin' check (role in ('admin', 'superadmin')),
  created_at  timestamptz not null default now(),
  created_by  uuid references auth.users(id),
  notes       text
);
comment on table public.platform_admins is
  'Platform-level admins (NOT tenant-scoped). Used by /admin/api/* and the MCP server. Service-role writes only.';

-- 2026-08-24: audit log
create table if not exists public.audit_log (
  id            uuid primary key default gen_random_uuid(),
  actor_id      uuid references auth.users(id),
  actor_email   text,                         -- denormalized for display
  actor_type    text not null check (actor_type in ('platform_admin', 'service', 'mcp')),
  action        text not null,                -- e.g. 'user.impersonate', 'migration.apply'
  target_type   text,                         -- 'tenant' | 'user' | 'migration' | 'billing' | 'keys'
  target_id     text,
  metadata      jsonb not null default '{}'::jsonb,
  ip            text,
  user_agent    text,
  created_at    timestamptz not null default now()
);
create index if not exists idx_audit_log_created on public.audit_log (created_at desc);
create index if not exists idx_audit_log_actor   on public.audit_log (actor_id, created_at desc);
create index if not exists idx_audit_log_target  on public.audit_log (target_type, target_id, created_at desc);
comment on table public.audit_log is
  'Append-only audit trail for platform_admin actions and MCP service calls. RLS off (service-role only).';
```

### 3.3 Router layout — `src/saas/admin_frontend_api.py`

All routes require `require_platform_admin` dependency. Sensitive actions additionally call `_audit(action, target_type, target_id, metadata)`.

```
GET  /admin/api/health             — system overview (tenants count, MRR estimate, self-test verdict)
GET  /admin/api/tenants            — list tenants + usage + billing
GET  /admin/api/tenants/{id}       — full tenant detail (kb docs, messages, billing, WA device)
POST /admin/api/tenants/{id}/impersonate  — magic-link-style JWT for a tenant owner
GET  /admin/api/users              — list all users (across tenants)
GET  /admin/api/users/{id}         — full user detail
POST /admin/api/users/{id}/impersonate   — magic-link-style JWT for support cases
GET  /admin/api/migrations         — list applied + pending
POST /admin/api/migrations/apply   — apply a specific .sql file (calls scripts.apply_migrations)
GET  /admin/api/billing/summary    — MRR, total customers, churn
GET  /admin/api/billing/transactions  — recent payment_transactions
POST /admin/api/billing/refund     — issue a Stripe refund
GET  /admin/api/keys               — list configured env-var API keys (masked)
POST /admin/api/keys/test/{name}   — live test a specific integration
GET  /admin/api/audit              — recent audit_log rows
```

### 3.4 UI — `static/admin.html`

Mirrors `static/dashboard.html`'s style:
- Same CSS vars (emerald #10b981, gold #E3B457, dark canvas #0a0f0e)
- Same React 18 + in-browser JSX + Babel via CDN
- Same `<Plus Jakarta Sans>` font

Layout:

```
┌─ Top bar ───────────────────────────────────────────────────┐
│ Bijou Admin · W3J · ⌘K   [Search]   [Health: ✅]   [Logout] │
└────────────────────────────────────────────────────────────┘
┌─ Sidebar ────────┐ ┌─ Main ──────────────────────────────────┐
│ ▸ Health         │ │  Stat cards: Tenants / Users / MRR      │
│   Tenants        │ │       Active Sessions / Audit Today     │
│   Users          │ │  ─────────────────────────────────────  │
│   Billing        │ │  Recent audit_log (last 20)             │
│   Migrations     │ │  [View all →]                            │
│   API Keys       │ │                                          │
│   Audit Log      │ │  Pending migrations (if any)             │
│   MCP Server     │ │  [Apply migration ▸]                     │
└──────────────────┘ └─────────────────────────────────────────┘
```

Cmd-K command palette: `Cmd+K` opens an overlay with fuzzy search across tenants, users, and routes. This is the only screen a power user needs.

### 3.5 MCP server — `src/core/admin_mcp_server.py`

The user said: *"with ready agent access, for my autonomous agent team to access n manage that."*

The MCP server is a thin shim that wraps the same admin REST endpoints. Each tool is a 1-line POST/GET against `/admin/api/*` using `ADMIN_API_KEY` (the service-to-service path) and writes its own `audit_log` row with `actor_type='mcp'`. This means the MCP layer cannot diverge from the UI: if the UI can do it, the MCP can do it, with the same audit and the same RBAC.

**v0.1 tool list (shipped):**

| Tool | Endpoint | Risk |
|---|---|---|
| `bijou_admin_health` | GET `/admin/api/health` | read |
| `bijou_admin_list_tenants` | GET `/admin/api/tenants` | read |
| `bijou_admin_get_tenant` | GET `/admin/api/tenants/{id}` | read |
| `bijou_admin_list_users` | GET `/admin/api/users` | read |
| `bijou_admin_get_user` | GET `/admin/api/users/{id}` | read |
| `bijou_admin_impersonate_user` | POST `/admin/api/users/{id}/impersonate` | **write, audited** |
| `bijou_admin_list_migrations` | GET `/admin/api/migrations` | read |
| `bijou_admin_apply_migration` | POST `/admin/api/migrations/apply` | **write, audited** |
| `bijou_admin_billing_summary` | GET `/admin/api/billing/summary` | read |
| `bijou_admin_issue_refund` | POST `/admin/api/billing/refund` | **write, audited** |
| `bijou_admin_list_keys` | GET `/admin/api/keys` | read |
| `bijou_admin_recent_audit` | GET `/admin/api/audit` | read |

**Phase 4 tool additions (planned):** `bijou_admin_suspend_tenant`, `bijou_admin_reconnect_tenant`, `bijou_admin_test_integration`, `bijou_admin_create_user`, `bijou_admin_kill_stuck_polling`.

### 3.6 Refactor touchpoints

| File | Why | Notes |
|---|---|---|
| `scripts/apply_migrations.py` | The admin API needs to call the apply logic without `sys.exit` and without a CLI parser | extract a `apply_migrations(db_url, only=None, force=False) -> dict` function; keep `main()` for CLI |
| `src/saas/stripe_service.py` | New `refund_charge(charge_id, amount_cents=None, reason=None)` method | reuse `_record_transaction` with status='refunded' |
| `src/core/bijou.py:532` | Mount the new admin_frontend router | append to `_include_routers()` |
| `static/dashboard.html` | Add a small "Admin" link in the user menu, gated on `GET /api/auth/me` returning `is_platform_admin: true` | minimal diff, ~30 lines |

---

## 4. Auth flow (browser-side)

```
1. Owner opens /admin.html
2. /admin/api/health is called WITHOUT auth → 401
3. /admin.html detects 401, redirects to /static/login.html?next=/admin.html
4. After login, Supabase JWT in localStorage
5. /admin/api/health is called WITH Authorization: Bearer <jwt>
6. require_platform_admin dependency:
     - verifies JWT
     - SELECT 1 FROM platform_admins WHERE user_id = jwt.sub
     - if not found → 403
7. If platform_admin → 200 OK
```

The X-Admin-Key (`ADMIN_API_KEY` env var) is still honored on every `/admin/api/*` route as a service-to-service fallback (used by the MCP server). This is for parity with `src/saas/admin_api.py:48` and so the MCP server doesn't need a JWT dance.

---

## 5. Sensitive-action safeguards

The acceptance criteria for "I trust this" are explicit in CLAUDE.md ("Never log real secret values, never echo them to the UI, always mask").

| Class | Examples | Safeguard |
|---|---|---|
| **Money out** | refund, cancel subscription | require typing the tenant's `business_name` to confirm |
| **Identity take** | impersonate user / tenant | TTL: 15 min, single-use, audit_log row |
| **Schema change** | apply migration | require typing the migration filename to confirm; cannot be undone via UI |
| **Secret leak** | list keys | always mask: `sk_live_***` + last 4 chars; never return the full value |
| **Destructive** | suspend tenant | require typing `SUSPEND` to confirm; reversible from same UI |

All of the above write an `audit_log` row with the request IP and user agent.

---

## 6. Acceptance criteria for v0.1 (this commit)

1. `/admin.html` loads, dark theme matches dashboard, `Admin` link in dashboard only shown if `is_platform_admin` ✅
2. `/admin/api/health` 200 OK for platform_admin, 403 for non-admin, 401 for no session ✅
3. At least 1 admin operation (impersonate user) is callable via MCP ✅
4. AGENTS.md updated to mention `/admin` ✅
5. Code committed + pushed via Hermes PAT ✅
6. This design doc committed ✅

---

## 7. Phase 4 (next slice) — what's NOT in v0.1

These are deliberately deferred so the v0.1 stays small and reviewable:

- **Bulk operations:** "apply ALL pending migrations", "suspend 5 churned tenants"
- **Per-tenant user mgmt UI:** invite a teammate to a tenant
- **Bridge admin (Go-side):** kill a stuck polling loop, drain queue, replay failed messages
- **Live Stripe test in UI:** "send a test invoice to X" using a test-mode key
- **Multi-admin RBAC:** superadmin vs admin (e.g. only superadmin can refund > RM 100)
- **Audit log search & export:** CSV download of audit_log filtered by date range
- **Real-time WebSocket updates:** live "tenant X just got a new message" stream
- **MCP server auto-registration** as a service mesh sidecar (for now the agent team has to call the REST API directly)
- **Self-hosted key management UI** (so owners can rotate keys from inside the admin)

The owner's agent team can also extend the MCP server with their own tools — the `src/core/admin_mcp_server.py` is a flat list of `register_tool(name, fn)` calls, so adding a new tool is 5 lines.

---

## 8. File map (delivered in v0.1)

| Path | Purpose |
|---|---|
| `migrations-py/add_admin_console.sql` | new tables: `platform_admins`, `audit_log` |
| `src/saas/admin_frontend_api.py` | new router, 11 endpoints, audit_log writes |
| `src/core/admin_mcp_server.py` | new MCP wrapper, 12 tools, calls /admin/api/* with X-Admin-Key |
| `static/admin.html` | new admin console UI (React/JSX, dark theme) |
| `scripts/apply_migrations.py` | refactored: extract `apply_migrations()` function (no behavior change for CLI) |
| `src/saas/stripe_service.py` | adds `refund_charge()` method |
| `src/core/bijou.py` | mounts new admin_frontend_api router |
| `static/dashboard.html` | adds "Admin" link gated on platform_admin role |
| `tests/unit/test_admin_frontend_api.py` | regression tests for the 10 endpoints + auth |
| `docs/admin-frontend-design.md` | this file |
| `AGENTS.md` | updated `/admin` section |

---

## 9. Honest "what I didn't get to"

- **Cmd-K palette** in admin.html is stubbed (no fuzzy search yet) — Phase 4.
- **Suspend tenant** and **reconnect bridge** endpoints are listed in the design but NOT implemented in v0.1 (Phase 4).
- **WebSocket live updates** are NOT implemented (Phase 4).
- The admin frontend is **not mobile-optimized** (the owner said "frontend only for me" — desktop-first is the right priority).
- The **MCP server is a Python module** that the agent team has to import; there is no auto-registration yet.
- **Real-time Stripe webhook test in UI** (POST a test webhook to verify the endpoint) is NOT in v0.1.

These are all Phase 4 candidates. The architecture is ready for them — every new endpoint is a one-function addition to `admin_frontend_api.py` + one line in `admin_mcp_server.py`.
