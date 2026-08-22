# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Bijou AI — a WhatsApp/Telegram AI agent for Malaysian SMEs. Three deployable
surfaces in one repo, plus a multi-tenant Supabase SaaS engine.

> `AGENTS.md` (root) is the older master playbook, written for a **MiniMax
> agent team**, not Claude Code. Where the two disagree, **this file wins** —
> several of its references are stale (see § Known-stale docs).

---

## Deployment topology — read before claiming anything shipped

This is the most expensive thing to get wrong here, and it has burned this
project before.

| Surface | Source of truth | Trigger | Status |
|---|---|---|---|
| Landing (`mybijou.xyz`) | `packages/landing/` | Vercel native git integration on `main`, `rootDirectory=packages/landing` | ✅ working (re-pointed 2026-08-10) |
| Backend (`app.mybijou.xyz`, `bijou-production.fly.dev`) | `packages/backend/` | `.github/workflows/backend.yml` → `flyctl deploy` | ⛔ **blocked** |
| Bridge | `packages/bridge/` | `.github/workflows/bridge.yml` | ⛔ **blocked** |

**GitHub Actions is currently locked**: runs fail in ~3s with *"The job was not
started because your account is locked due to a billing issue."* Until that is
resolved, **no backend or bridge change can reach production through CI**.

Before 2026-08-10 the Vercel project was linked to a *different, pre-monorepo
repository* (the old standalone "Bijou AI Digital Employee" landing repo), so `packages/landing/` changes never
reached users despite `README.md` claiming otherwise. It now builds from this
monorepo. If a landing change doesn't appear live, re-check the project link
before debugging code.

**Never claim "deployed" or "fixed in prod" from a green build.** Hit the live
URL. A pushed commit is not a deployed commit.

**Confirmed still locked as of 2026-08-22** (`gh run view <id>` on the latest
`backend`/`landing` runs still shows the billing annotation). A manual escape
hatch exists — `flyctl`, authenticated as the project owner's personal Fly.io
account, can deploy `packages/backend` directly: `flyctl deploy --config
fly.production.toml --remote-only` from `packages/backend/` — but a Claude
Code sandbox's own auto-mode permission classifier blocks that command
outright even after in-chat user approval; it has to be run from a shell the
classifier doesn't gate. **Confirmed working 2026-08-22/23**: the project
owner ran this manual deploy themselves from a normal terminal and it
succeeded (`registry.fly.io/bijou-production:deployment-...`, machine update
succeeded) — this is the real, current path to ship backend fixes while CI
is locked. The same classifier also blocks `flyctl secrets set/unset` — those
need the owner's terminal too. Separately, **some Claude Code sessions run
under a git credential with no push access to the upstream repo** (`git push`
403s, confirmed again 2026-08-23 with 18 unpushed commits sitting local-only)
— commits can be made locally but may not reach `origin/main` from every
environment. Verify which identity you're pushing as before assuming a
commit is safely backed up upstream.

### Recurring bug class: stale Fly secrets overriding the canonical-domain fix

`auth_api.py`/`google_oauth.py` both build user-facing URLs from
`_public_base_url()`, which correctly prefers `PUBLIC_URL` (`=
https://app.mybijou.xyz`, confirmed correctly set live) over a hardcoded
Fly-domain fallback. But **several call sites read a *different*,
narrower env var first, with no fallback guard**, so a stale leftover value
from before the domain was finalized silently wins:
`auth_api.py:848`'s magic-link builder reads `LOGIN_URL` directly;
`google_oauth.py`'s OAuth config reads `GOOGLE_REDIRECT_URI` directly;
`pricing_engine.py`/`reporting_engine.py`/`escalation_notifier.py`/
`stripe_service.py`/`trial_manager.py` all read `APP_URL`/`DASHBOARD_URL`.
Found 2026-08-23 because all four were still set as live Fly secrets from
before the `_public_base_url()` fix existed, causing "login redirects to the
Fly domain, session lost, loops back to login." Fixed by `flyctl secrets
unset LOGIN_URL APP_URL DASHBOARD_URL GOOGLE_REDIRECT_URI -a
bijou-production` (safe for the first three — code's own fallback is already
the correct canonical domain; `GOOGLE_REDIRECT_URI` additionally needs
`https://app.mybijou.xyz/api/auth/google/callback` registered in Google
Cloud Console's OAuth client, or Google rejects with `redirect_uri_mismatch`
instead of looping). **If a similar "wrong domain" symptom recurs, check
`flyctl secrets list` for other narrow env-var overrides before re-deriving
the fix from scratch** — this is the second time this exact bug class has
bitten this project (see `auth_api.py`'s own 2026-08-10 comment about the
first occurrence).

### Integration platform: Nango, not Composio (decided 2026-08-22)

The `src/connectors/oauth_api.py`/`auth_configs.py`/`static/integrations.html`
Composio scaffold was never launched (confirmed: `ENABLE_COMPOSIO` never set,
router never mounted, zero `COMPOSIO_AUTH_ID_*` configured) and Composio's
real self-hosting story turned out to be weaker than advertised (the
credential-storage/execution backend is closed-source, self-host images are
Enterprise-gated). Decision: replaced with **Nango** (open-source, genuinely
self-hostable, purpose-built for multi-tenant customer-facing OAuth) —
`src/connectors/nango_client.py` + `src/connectors/nango_api.py` +
`migrations-py/add_tenant_integrations.sql`, gated behind `NANGO_SECRET_KEY`
(or `NANGO_API_KEY`) being set. **Not yet verified against the real Nango
API** — built and unit-tested with mocks only; nobody has hit
`POST /api/nango/session` through a running app instance yet. The
dashboard's Integrations tab still needs the frontend Connect UI wired up to
call it (not done as of 2026-08-23).

---

## Commands

Only commands verified to exist are listed. Several advertised targets are
broken — see § Broken tooling.

```bash
# Landing (React 19 + Vite) — from repo root
npm install
npm run dev:landing          # Vite dev server, port 3000
npm run typecheck:landing    # npx tsc --noEmit — the ONLY landing gate
npm run build:landing
npm run preview:landing

# i18n maintenance (Python scripts, all present)
npm run i18n:audit
npm run i18n:usage
npm run i18n:orphans

# Lead pipeline (needs packages/backend/.env)
npm run lead:overpass        # scout prospects from OpenStreetMap
npm run lead:scorer
npm run lead:outreach
npm run lead:research
```

```bash
# Backend (FastAPI, Python 3.12) — from packages/backend/
make test                    # pytest tests/ -v --tb=short  (54 files, 439 tests)
make test-fast
python -m pytest tests/unit/test_auth_signup_error_mapping.py -q   # single file
python -m pytest tests/unit/ -q -k "signup"                        # single pattern
python -m py_compile src/saas/auth_api.py                          # quick syntax gate
```

```bash
# Bridge (Go 1.24) — from packages/bridge/
go vet ./...
go build -o bridge_test .
```

**`tsc` does not check `api/**`.** `tsconfig.json` deliberately excludes it —
those files run on Node (Vercel), not in the browser. Validate serverless
handlers with `node --check api/<file>.js` plus a real request.

---

## Architecture

### Three runtimes, one repo

- **`packages/landing/`** — React 19 + Vite + Tailwind **via CDN** (config is an
  inline `tailwind.config = {…}` block in `index.html`; there is no
  `tailwind.config.js`). No router: `App.tsx` is one scroll page of section
  components, plus a single hash route `#/admin/outreach-queue`. State is
  `useState` + prop drilling — no Redux/Zustand; keep it that way.
  `api/*.js` are Vercel serverless handlers (`export default async function
  handler(req, res)`) and hold all secrets. `lib/` is server-only; `services/`
  is client-only.
- **`packages/backend/`** — FastAPI. The real tree is **`src/`**
  (`src/core/bijou.py` mounts the routers; `src/saas/` holds auth, onboarding,
  tenants). `app/*.cjs` is the Node lead pipeline. Serves the authenticated
  product as **hand-written static HTML** from `static/` (`dashboard.html` is
  ~7.1k lines with in-browser JSX) — this, not `packages/landing`, is the
  actual app UI.
- **`packages/bridge/`** — Go + whatsmeow + SQLite, one instance per tenant.

### Where the user-facing surfaces actually live

`packages/landing` is a **marketing site + lead capture**. Its
`OnboardingModal` does **not** create accounts — all three modes POST to
`/api/leads`, then link out to `app.mybijou.xyz/signup`.
`packages/landing/api/onboarding/signup.js` exists but **nothing calls it**.

Real auth lives in `packages/backend/static/{signup,login,onboarding,
reset-password}.html` against `src/saas/auth_api.py`.

### Auth invariants (learned the hard way, 2026-08-10)

- **Email confirmation is ON** (GoTrue `mailer_autoconfirm: false`). A
  *successful* new signup therefore returns `session=None`. Never treat a
  missing session as "email already exists" — that rejected 100% of
  registrations. The correct discriminator is `user.identities == []`.
- **Never build a user-facing URL from `request.base_url`.** Behind Fly's proxy
  it resolves to `bijou-production.fly.dev`, a different browser origin from
  `app.mybijou.xyz`. The dashboard keeps its JWT in origin-scoped
  `localStorage`, so a cross-origin redirect silently destroys the session.
  Use `PUBLIC_URL` defaulted to `https://app.mybijou.xyz`.
- Signup writes `tenants` **and** `tenant_users`. If either is skipped the user
  is stranded: login resolves no tenant and 404s forever.

### Data + keys

Supabase (project `lrwzlujomukzjykafmic`) is multi-tenant. Server-side writers
use the **service-role** key; the anon key appears only in `static/login.html`
and `static/auth-callback.html` for GoTrue OAuth. Env names have undocumented
aliases — readers accept `SUPABASE_SERVICE_KEY | SUPABASE_SERVICE_ROLE_KEY |
SUPABASE_KEY` and `SUPABASE_URL | VITE_SUPABASE_URL | NEXT_PUBLIC_SUPABASE_URL`.

RLS was hardened by `ops/_fix_rls_v6.js`, which dropped **every** permissive
`{public}`-role policy in the public schema (no table filter). Net effect: only
`service_role` reads/writes. Anything using the anon or authenticated role
against Postgres will fail until policies are rewritten.

---

## Broken tooling — don't trust these

| Command | Why it fails |
|---|---|
| `make setup`, `make lint` | `.pre-commit-config.yaml` does not exist |
| `make audit`, `audit-strict`, `audit-json`, `check-root`, `ci-check` | `scripts/static_audit.py` does not exist |
| `npm test` (backend) | placeholder — `exit 1` |
| `npx playwright test` | `baseURL` hardcoded to `bijou-staging.fly.dev`; cannot test a local build |

CI quality gates are largely cosmetic: in `backend.yml`, `ruff` and `mypy` both
end in `|| echo` (mypy also has `continue-on-error: true`), and **`pytest` never
runs** — all 439 tests are unexecuted in CI. Only `py_compile` and `node --check`
can actually fail a build.

## Known-stale docs

- `packages/backend/AI_RULES.md` — targets the pre-monorepo
  legacy "enterprise" layout (see `legacy/`) and forbids creating `.md` files; contradicts
  `AGENTS.md`. Its `START_HERE.md`, `scripts/check_file_sizes.sh`, and
  `scripts/static_audit.py` do not exist.
- Root `AGENTS.md` — references `memory/MEMORY.md` and `topics/*.md`; **neither
  directory exists**. Says backend tests are "when tests added" (there are 439).
- **i18n is 4 locales** (`en`, `ms`, `zh`, `ta`), not 5 as `README.md` and
  `AGENTS.md` claim.
- Nested `src/core/tools/AGENT.md` and `src/saas/AGENT.md` declare a
  `packages/bijou-core/` path that does not exist.

## Conventions

- Components `PascalCase.tsx` with `export const X: React.FC<XProps>`; services
  and utils `camelCase.ts`. Named exports except `App.tsx`.
- User-facing error copy is deliberately **Manglish** ("Aiyo, server having
  hiccup boss"). Keep it — it's the product voice.
- `api/chat.js` returns HTTP 200 with a friendly message even on failure so the
  demo never hard-fails. Other endpoints should return honest status codes.
- New user-facing strings go in `i18n.ts`, not hardcoded.
- Non-trivial fixes get a regression test. `tests/unit/` is the fast tier.
