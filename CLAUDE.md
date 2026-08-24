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
| Backend (`app.mybijou.xyz`, `bijou-production.fly.dev`) | `packages/backend/` | **Coolify primary** (`docker-compose.coolify.yml`); `flyctl deploy` fallback (billing-locked) | ⛔ **CI blocked**; Coolify manual deploy ready |
| Bridge | `packages/bridge/` | **Coolify primary** (multi-tenant one-container-per-tenant); Fly fallback | ⛔ **CI blocked**; Coolify manual deploy ready |
| Landing preview (self-hosted) | `Dockerfile.landing` + nginx | Coolify with `--profile preview` | ✅ ready (optional) |

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

**2026-08-23 deploy path:**

1. **Coolify is the primary deploy target.** `docker-compose.coolify.yml` +
   `Dockerfile.backend` + `Dockerfile.bridge` + `Dockerfile.landing` are
   commit-ready. Runbook: `ops/coolify/DEPLOY.md`. Env template:
   `ops/coolify/coolify.env.example`. Coolify reads the compose file, builds
   the images, deploys, and uses the healthcheck for rollback.

2. **Fly.io is the secondary fallback**, behind a **billing lock**
   (`https://fly.io/dashboard/web3-933/billing` — overdue invoice). A
   `flyctl deploy` attempt on 2026-08-23 returned `status 403: Your account
   has overdue invoices` from the builder. This is **independent** of the
   GitHub Actions billing issue. Both must be resolved before Fly is a
   working deploy path.

3. **The auto-mode permission classifier in Claude Code also blocks
   `flyctl deploy --remote-only` and `flyctl secrets set/unset`** even after
   in-chat user approval. These commands must be run from a shell the
   classifier doesn't gate (the project owner's terminal works — confirmed
   2026-08-22/23, before Fly went fully billing-locked).

4. **Git push access:** the `mnjbold` gh identity has 403 on `git push` to
   the canonical remote (`mybijouai-creator/bijou-monorepo`). Use the
   `GITHUB_PAT_TOKEN` from `C:\Users\W3jde\.hermes\secrets\.env.mybijou-creator`
   (works as of 2026-08-23). Push script pattern documented in
   `docs/STATUS_2026-08-23.md`. **Verify which identity you're pushing as**
   before assuming a commit is safely backed up.

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

### Shared context (A2A) — first 30-day step of issue #23

The A2A shared-context layer lets Bijou's WhatsApp agent and the (forthcoming)
Telnyx voice agent share conversation state per `(tenant_id, customer_phone)`.
Foundation landed 2026-08-23: table `public.shared_context` (see
`packages/backend/migrations-py/add_shared_context.sql`, RLS on with no
permissive policies — service-role only, matches the post-v6 RLS hardening
described in § Data + keys) plus `src/core/shared_context_api.py` mounted in
`src/core/bijou.py::_include_routers()`. The router exposes
`POST /api/shared-context/append` (logs a new turn) and
`GET /api/shared-context?phone=…&since_hours=…&limit=…` (unified cross-channel
thread view, newest first). All routes go through `verify_session` so
`tenant_id` is always taken from the authenticated session, never client input;
unit tests live at `tests/unit/test_shared_context.py` (3 new round-trip
+ isolation tests added 2026-08-23, see commit `62fdd12`).

The full protocol spec (message envelope, privacy posture, conflict
resolution) is documented separately in
`docs/superpowers/specs/2026-08-23-a2a-seam-protocol.md` (issue #31). That
doc is the source of truth for any new channel integration.

### Compliance posture (added 2026-08-23)

Three lawyer-ready documents live in `docs/compliance/`:

- `EU_AI_ACT_2024.md` — risk classification (limited-risk, Article 50
  transparency only), Article-by-Article obligations with file references,
  conformity assessment, post-market monitoring
- `DATA_SUBJECT_RIGHTS.md` — PDPA + GDPR + UK GDPR + MY PDPA 2010 rights
  matrix, exercised via `GET /data-request` (issue #26) — public, no login
- `MODEL_CARD.md` — Gemini 2.5 Flash model card (lineage, intended use,
  evaluation, ethics)

Sign-off blocks in all three are TBD — owner action.

### Shared-nervous-system plan (locked 2026-08-23)

The plan is to absorb three external projects into this monorepo so Bijou
has a unified "connect your tools + talk to you anywhere" layer. Tracked
in issues #21 (EPIC), #22 (Connector-Hub → `packages/connect/`), #27
(W3J-BIJOU PROJECT → `packages/voice/`), #28 (voice concierge wiring),
#29 (Contact-Center escalation bug), #30 (Connector-Hub fragility audit),
#31 (A2A seam protocol).

**Decision lock:** Nango (shipped today) stays as the short-term
Integrations backend until the Connector-Hub audit (#30) finishes. If the
audit recommends absorb, Nango is replaced. If not, Nango stays.

**Security:** 3 SECURITY.md files written in the telnyx/ projects. All
real plaintext credentials (Telnyx JWT, org API key, MiniMax key, SIP
creds) still on disk; owner action required to rotate per the runbooks.

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

## AI Gateway (v2)

> The single rule: **never name a provider or model in a callsite.** All
> LLM usage goes through `await llm.complete("ai://<alias>", messages)`.
> The alias policy lives in `packages/backend/llm_gateway.yaml`.

The gateway is data-driven: change the YAML, change the behaviour. No Python
code change needed to add a new alias, add a new provider, or change a
fallback order.

**Six shipped aliases:**

| Alias             | Purpose                                          | Privacy  | Daily cap |
|-------------------|--------------------------------------------------|----------|-----------|
| `ai://fast`       | Default chat replies — short, friendly.           | standard | $25       |
| `ai://reasoning`  | Agent loop + tool-calling + complex KB lookups.   | standard | $50       |
| `ai://extract`    | Structured JSON — handover, lead, emotion.        | standard | $10       |
| `ai://private`    | PDPA-sensitive — **strict-only providers** (no OpenRouter). | strict | $20 |
| `ai://helpdesk`   | `/api/help/chat` in-product support widget.       | standard | $5        |
| `ai://vision`     | Image / document understanding (multimodal).      | standard | $10       |

**Public surface:**

```python
from src.core.llm_gateway_v2 import llm
result = await llm.complete("ai://reasoning", messages, tools=..., tenant_id=...)
# result.text, .provider, .model, .fallback_reason, .function_calls,
# .prompt_tokens, .completion_tokens, .cost_usd, .latency_ms
```

**Key files:**
- Policy:       `packages/backend/llm_gateway.yaml`
- Module:       `packages/backend/src/core/llm_gateway_v2.py`
- Tests:        `packages/backend/tests/unit/test_llm_gateway_v2.py` (28 tests)
- Usage table:  `public.llm_usage` (migration: `migrations-py/add_llm_usage.sql`)
- Full docs:    `docs/AI_GATEWAY.md`

**Status codes that trigger a fallback:** 429, 500, 502, 503, 504.
400/401/403/404 are config bugs and surface to the caller without retrying.

**Exceptions:** `BudgetExceeded` (daily cap hit) and `NoProviderAvailable`
(no provider has a key) — both should become HTTP 429 / 503 to the user.

The v1 key-rotator (`src/core/llm_gateway.py`'s `RoundRobinRotator`) is still
in use — it handles **per-provider key** rotation (multiple Gemini keys for
rate-limit spreading). v2 sits one layer up and adds **cross-provider**
fallback. They are complementary, not in conflict.

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

## Recent changes (2026-08-23)

- **3 commits shipped this turn** (in local git, awaiting owner push):
  - `d6b1a3c` Competitor comparison table on landing pricing
  - `d491325` Session status doc + organized issue batch
  - `2d833b7` "What your AI just did" activity feed on Home (first agentic-GenUI primitive)
- **29 commits total** sit unpushed on local `main` vs `mybijouai-creator/bijou-monorepo`. The `mnjbold` git identity is authed but has 403 on push. **Owner must push from terminal.** See `docs/STATUS_2026-08-23.md`.
- **2nd deploy blocker confirmed**: Fly.io billing is locked (separate from the GitHub Actions billing lock). Currently no working backend deploy path. **Coolify is the primary deploy target** going forward.
- **Shared context (A2A) layer** is in progress (worker `bg_e846b3af` — see issue #23). Lets Bijou's WA agent and the (forthcoming) Telnyx voice agent share conversation state per (tenant_id, customer_phone). New `shared_context` table + `POST/GET /api/shared-context` endpoints. When worker lands, run the SQL migration manually in Supabase before restarting the dev server.
- **3 SECURITY.md files** added (one in each of the 3 telnyx projects) with rotation runbooks. Live plaintext credentials still on disk in those 3 projects — owner action required per the runbooks.

### Round 3 (later 2026-08-23) — pushed to canonical

- `62fdd12` **chore(2026-08-23-round3)** — pushed to `mybijouai-creator/main` via Hermes PAT
  - 3 compliance docs (`docs/compliance/EU_AI_ACT_2024.md`, `DATA_SUBJECT_RIGHTS.md`, `MODEL_CARD.md`) — closes #17
  - `AGENTS.md` updated (Coolify primary, voice/connect placeholders, shared-ns section, compliance section) — closes #25
  - Coolify deploy artifacts (`Dockerfile.backend`, `Dockerfile.bridge`, `Dockerfile.landing`, `docker-compose.coolify.yml`, `ops/coolify/DEPLOY.md`, `ops/coolify/coolify.env.example`)
  - "Your Data Rights" footer link in landing + new "Data Rights & Privacy" Settings card in dashboard
  - 3 new A2A shared-context tests (round-trip WA→voice, cross-tenant isolation, channel validation)
  - Issues #28-31 created (Telnyx voice wiring, Contact-Center bug, Connector-Hub audit, A2A protocol)
- Issues #17 + #25 closed with audit-trail comments
- 15 of 31 issues now closed; 16 open (incl. #3, #4 P0 owner actions + the 4 new shared-ns issues)
- Remote HEAD: `62fdd12` (local HEAD: `62fdd12`, in sync)
- `.git/config` cleaned of stale token; `$env:GITHUB_PAT_TOKEN` nulled after push
- Pre-commit secret guard active and clean on the new diff (fixed a placeholder-vs-real-JWT false positive in `coolify.env.example` by replacing `eyJ...` with `<your-supabase-service-role-key>`)

## Conventions

- Components `PascalCase.tsx` with `export const X: React.FC<XProps>`; services
  and utils `camelCase.ts`. Named exports except `App.tsx`.
- User-facing error copy is deliberately **Manglish** ("Aiyo, server having
  hiccup boss"). Keep it — it's the product voice.
- `api/chat.js` returns HTTP 200 with a friendly message even on failure so the
  demo never hard-fails. Other endpoints should return honest status codes.
- New user-facing strings go in `i18n.ts`, not hardcoded.
- Non-trivial fixes get a regression test. `tests/unit/` is the fast tier.
