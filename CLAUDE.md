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

Before 2026-08-10 the Vercel project was linked to a *different repository*
(`W3JDev/Bijou-AI---Digital-Employee`), so `packages/landing/` changes never
reached users despite `README.md` claiming otherwise. It now builds from this
monorepo. If a landing change doesn't appear live, re-check the project link
before debugging code.

**Never claim "deployed" or "fixed in prod" from a green build.** Hit the live
URL. A pushed commit is not a deployed commit.

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
  `w3j-bijou-enterprise/` layout and forbids creating `.md` files; contradicts
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
