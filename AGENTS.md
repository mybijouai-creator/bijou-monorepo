# AGENTS.md — Bijou AI Monorepo (Master Playbook)

> **Read this first.** This is the master playbook for the **MiniMax Code agent team**
> working on the Bijou AI monorepo. Per-package coding guidelines live in
> `packages/<name>/AGENTS.md` — this file is the strategic + cross-cutting layer.

---

## 0. What this is

Bijou AI is a **WhatsApp/Telegram AI agent** for Malaysian SMEs. The product
has 3 deployable surfaces today (landing / backend / bridge) and a
**shared-nervous-system** in progress (voice / connect). Multi-tenant
SaaS engine behind it all. This monorepo is the **single source of truth**.

| Surface | Stack | Lives in | Deploys to |
|---|---|---|---|
| **Landing** (mybijou.xyz) | React 19 + Vite + i18n (4 locales: en/ms/zh/ta) + Vercel serverless API | `packages/landing/` | Vercel |
| **Backend** (app.mybijou.xyz) | Python 3.12 (FastAPI) + Node lead pipeline + Supabase | `packages/backend/` | **Coolify (primary)**, Fly.io (secondary) |
| **Bridge** (per-tenant) | Go 1.24 + whatsmeow + SQLite | `packages/bridge/` | **Coolify (primary)**, Fly.io (secondary) |
| **Voice** (forthcoming, issue #27) | Telnyx MCP server + voice AI agents + Convex RAG | `packages/voice/` (to be absorbed from `W3J-BIJOU PROJECT/`) | Coolify |
| **Connect** (forthcoming, issue #22) | Connector-Hub (15 connectors) + Nango | `packages/connect/` (to be absorbed) | Coolify |
| **Ops** | PowerShell / bash deploy scripts | `ops/` | local |
| **Docs** | Strategy + compliance + handoffs | `docs/` | this repo |
| **Compliance** | EU AI Act 2024 + PDPA/GDPR + model card | `docs/compliance/` | this repo |

Live URLs (last verified 2026-08-23):
- <https://mybijou.xyz> — landing (200/307, Vercel)
- <https://app.mybijou.xyz/health> — dashboard API (200)
- <https://bijou-production.fly.dev/health> — Fly backend (200, **billing-locked** as of 2026-08-23)
- Coolify primary: TBD (Coolify billing issue must be resolved first)

**Canonical remote:** `https://github.com/mybijouai-creator/bijou-monorepo.git`
(per CLAUDE.md; the `W3J-Dev` mirror exists for backup but is not the
source of truth). Push via `GITHUB_PAT_TOKEN` from
`C:\Users\W3jde\.hermes\secrets\.env.mybijou-creator` (the `mnjbold`
gh auth has 403 on push).

---

## 1. The 3 rules for any agent (or human) touching this repo

### Rule 1 — Don't break prod. Verify, then claim.

- Run `npx tsc --noEmit` in the package you touched. If you change `api/*.js`, exercise the endpoint with `curl` (see "verify after change" below).
- **Never claim "fixed" unless you hit the live URL for the exact port + process the user is running.** A parallel uvicorn on port 8081 is NOT proof the live port-8000 service is fixed. (Lesson: this rule exists because of an actual 4-time repeat failure.)
- Read `memory/MEMORY.md` "PR body claim vs reality" before writing any PR or commit message that claims live behavior.
- **Deploy gate (added 2026-08-23):** CI is currently **locked** (GitHub Actions billing issue + Fly.io billing issue). Deploys go through Coolify manually OR `flyctl deploy --remote-only` from the project owner's terminal. Do **not** claim a backend or bridge change is "deployed" without hitting the live URL.

### Rule 2 — The right agent for the right file.

| If you touch... | You are | Read |
|---|---|---|
| `packages/landing/**` | `bijou-frontend` | `packages/landing/AGENTS.md` |
| `packages/backend/src/**/*.py` | `bijou-backend` | `packages/backend/AGENTS.md` (FastAPI) |
| `packages/backend/app/*.cjs` (lead pipeline) | `bijou-pipeline` | `packages/backend/AGENTS.md` § Lead Pipeline |
| `packages/backend/migrations-py/*.sql` | `bijou-data` | `packages/backend/AGENTS.md` § Schema |
| `packages/bridge/**` | `bijou-bridge` | `packages/bridge/AGENT.md` |
| `packages/voice/**` (forthcoming) | `bijou-voice` | this file § Shared-nervous-system |
| `packages/connect/**` (forthcoming) | `bijou-connect` | this file § Shared-nervous-system |
| `ops/**`, `fly.*.toml`, `vercel.json`, `docker-compose.yml`, `coolify.yaml`, `.github/workflows/**` | `bijou-devops` | this file § 6 |
| `docs/compliance/**` | `bijou-compliance` | this file § Compliance |
| Tests, type-check, lint | `bijou-qa` | this file § 7 |
| Any PR diff | `bijou-reviewer` | `adversarial-reviewer` skill |

If your change spans 2 packages, you need a coordinating branch session, not
a single agent. The root Mavis dispatches.

### Rule 3 — Document what you did, in the place future-you will look.

- If you changed a deploy config, update `docs/DEPLOYMENT_SAFETY.md`.
- If you fixed a bug with non-obvious cause, drop a 1-line note in `docs/handoffs-and-audits/` (filename: `<TOPIC>-<DATE>.md`).
- If you changed an env var, update `.env.example` at root.
- If you learned something durable, write it to agent memory (via the `memory` tool, target=main or topic). High-signal only — not every observation.

---

## 2. The autonomous build loop (the "no human in the loop" part)

This is the **5-bottleneck framework**. Solve these 5, you have a hackathon-winner setup.

```
TODO filed (by you OR auto-detected from logs/code)
    ↓
[1] Orchestrator (root Mavis) reads TODO + AGENTS.md + relevant code
    ↓
[2] Dispatches branch session with right specialist (bijou-frontend, etc.)
    ↓
[3] Specialist: implement → test → review-self → commit → push
    ↓
[4] CI runs: lint → typecheck → unit → integration → build → deploy
    ↓  (each step writes STATUS.json)
[5] If green → reviewer agent (adversarial-reviewer)
    ↓
[6] If approved → merge to main → auto-deploy
    ↓
[7] Smoke test in prod (curl /health) → mark done
    ↓
[8] If anything fails twice → self-heal → if still fails, escalate to root
```

**Self-heal rule** (memory-enforced): max **2 retries on the same error**.
After 2 fails, escalate. Don't burn tokens retrying the same broken approach.

**Human escalation triggers** (everything else is autonomous):
- Initial scope ("what's done?")
- Major architecture pivots
- Production deploy button (one human click)
- Anything costing money (DIDs, infra spend, paid APIs)
- A decision needs your authority ("should we kill this old endpoint?")

---

## 3. The agent team

| Agent | Scope | When triggered |
|---|---|---|
| `bijou-architect` | cross-package, specs, ADRs | New feature, refactor request |
| `bijou-frontend` | `packages/landing/` | UI/UX issues, i18n, Vercel api/ |
| `bijou-backend` | `packages/backend/app/*.py` | FastAPI, pricing engine, Supabase schema |
| `bijou-pipeline` | `packages/backend/app/*.cjs` | Lead-gen pipeline (overpass, scorer, outreach) |
| `bijou-bridge` | `packages/bridge/` | WhatsApp Web bridge, history sync |
| `bijou-devops` | CI/CD, `ops/`, deploy configs | Infra issues, secrets, deploys |
| `bijou-qa` | Tests, type-check, lint, e2e | Every PR |
| `bijou-reviewer` | Adversarial review | Every PR pre-merge |
| `bijou-incident` | PagerDuty-style self-heal | Prod health-check fail |

Each agent runs in a **branch session** via the `task` tool. They don't pollute
the root context. They get one job, ship the PR, return.

**Root Mavis (this session) is the orchestrator** — it reads TODOs, dispatches
agents, watches CI, decides when to escalate. Root never writes code directly
unless it's a one-line hotfix that doesn't justify a branch session.

---

## 4. Local + remote sync (the "always-on brain" pattern)

You have 2 places this monorepo lives:
- **Local** (Windows + WSL on your ZBook)
- **Remote** (Contabo VPS, when provisioned)

**The pattern:**
- **Code sync** = git (free, trivial)
- **CI sync** = GitHub Actions is the single source of truth (both local + remote watch it)
- **State sync** = Supabase (the multi-tenant DB) — no per-machine state
- **Cron sync** = same `cron list` on both, **remote (Contabo) is primary** because it never sleeps
- **Agent sync** = same Mavis config on both, same agent roster

**Failure modes:**
- Local down → Contabo keeps the swarm running, picks up next TODO from the queue
- Contabo down → local takes over, same queue, same crons
- Both down → TODO queue persists in Supabase, picks up when one is back

This is the **only way** to get a truly autonomous 24/7 dev loop without paying for always-on CI minutes.

---

## 5. The 1-2 day plan (the one that wins the hackathon)

**Day 1 — foundation (this session + 1 follow-up)**
1. ✅ Survey (done)
2. ✅ Create monorepo + move files (done in this session)
3. ✅ Write master AGENTS.md + .env.example + package.json + .gitignore + README.md (done)
4. ⏳ git init + first commit
5. ⏳ Verify: `npx tsc --noEmit` + `go build` + `python -c "import app"`
6. ⏳ Per-package AGENTS.md updates (pointers to this master)

**Day 2 — agent team + first end-to-end build**
1. ⏳ `mavis agent create` × 6 specialists
2. ⏳ Add 3 GitHub Actions workflows (landing.yml, backend.yml, bridge.yml)
3. ⏳ Add i18n-drift.yml (daily cron for pricing-drift)
4. ⏳ Wire `cron self` for daily cost watchdog + drift + lead pipeline
5. ⏳ First end-to-end build: fix the **9-day i18n.ts pricing drift** (per `topics/bijou-pricing-drift-state.md` — 1 line per string, 4 locales)
6. ⏳ `ship-gate` audit + `adversarial-reviewer` pass
7. ⏳ Production deploy button
8. ⏳ Set up Contabo as remote brain

After Day 2, the swarm runs itself. You get pinged only for the 4 things in §2.

---

## 6. CI/CD — the 4 gates every change goes through

Per package, before merge to `main`:

| Step | Landing | Backend | Bridge |
|---|---|---|---|
| Lint | `npx tsc --noEmit` | `ruff check app/` | `go vet ./...` |
| Type-check | `npx tsc --noEmit` | `mypy app/` (when py.typed added) | `go build ./...` |
| Unit test | (none yet — add in Day 2) | `pytest tests/` (when tests added) | `go test ./...` (when added) |
| Build | `npm run build` | `pip install -r requirements.txt && python -c "import app"` | `go build -o bridge .` |
| Deploy | Vercel auto on main | Fly.io auto on main | Fly.io auto on main |

**Deployment status badges** (add to README once workflows are in):
- ![Landing CI](https://github.com/W3J-Dev/bijou-monorepo/actions/workflows/landing.yml/badge.svg)
- ![Backend CI](.../backend.yml/badge.svg)
- ![Bridge CI](.../bridge.yml/badge.svg)

**Status file**: each CI step writes to a `STATUS.json` artifact that the
orchestrator reads. If a step is red, the orchestrator routes the failure
to the right specialist for self-heal.

---

## 7. Verify after change (the 2-check rule)

For ANY change, before claiming "fixed":

1. **Local check**: run the package's type-check / build / test command locally. Get green.
2. **Live check** (for changes that hit prod): curl the live URL with the exact same path + method + auth as a real user would.

**The 2-check rule exists because of a real failure pattern:**
- Smoke against a parallel uvicorn (port 8081) ≠ smoke against the live port-8000 service
- A unit test that asserts the wrong expected value will pass and still be wrong
- The git "fix" branch can be 3 commits behind `main` and the diff you tested is gone

See `memory/MEMORY.md` "PR body claim vs reality" for the full case study.

**The local commands:**

```bash
# Landing
cd packages/landing && npx tsc --noEmit
cd packages/landing && npm run build

# Backend (Python) — needs venv
cd packages/backend && python -c "import sys; sys.path.insert(0, 'app'); import ai_router"  # adjust per file

# Bridge (Go)
cd packages/bridge && go build -o bridge_test .
cd packages/bridge && go vet ./...
```

---

## 8. Emergency procedures

### "Prod is down"
1. Check `topics/bijou-prod-health-state.md` (last tick state)
2. `curl -fsS https://app.mybijou.xyz/health` — if red, backend is down
3. `curl -fsS https://mybijou.xyz/` — if red, landing is down
4. Spin up `bijou-incident` agent (don't try to fix manually)
5. If the user is the only one with deploy access, escalate with: which service, what the logs say, what you tried

### "I made a change and CI is red"
1. Read the actual error, not the summary
2. Check if `main` is ahead of your branch (rebase first)
3. Self-heal ONCE with the obvious fix
4. If still red, escalate to root with: branch name, error, what you tried

### "I don't know which package a file belongs to"
1. The path tells you: `packages/<name>/` = that package
2. Files at monorepo root = cross-cutting (AGENTS.md, README.md, .env.example, .gitignore, package.json)
3. Files in `docs/` = strategy + history, never edit without good reason
4. Files in `legacy/` = **DO NOT TOUCH** — it's a safety net

### "I want to make a change that doesn't fit the package model"
- Open an ADR: `docs/architecture/ADR-<NNN>-<topic>.md`
- Use the `senior-architect` skill to draft
- Get human sign-off before coding

---

## 9. The don't list (lessons paid for in blood)

These are real mistakes from the project's history (in `topics/` + memory). Don't repeat them.

- ❌ Don't change env var names in prod without fall-back. The `MINIMAX_API_KEY` → `minimax no API key` chain failure on 2026-08-05 was a CRLF `.env` parser bug; never change parsers in deployed code without testing both LF and CRLF inputs.

---

## 9b. Admin Frontend (added 2026-08-24)

The Bijou **Admin Console** lives at `static/admin.html` and is served by
the new `src/saas/admin_frontend_api.py` router (mounted at
`/admin/api/*`). It is **platform-facing** (the owner / owner's agent
team) — distinct from the tenant-facing dashboard at
`static/dashboard.html`.

| Surface | Path | Purpose |
|---|---|---|
| **Admin UI** | `/static/admin.html` | React/JSX console: health, tenants, users, billing, migrations, API keys, audit log |
| **Admin API** | `/admin/api/*` | 12 endpoints, gated on `public.platform_admins` (JWT) or `X-Admin-Key` (MCP) |
| **Admin MCP** | `src/core/admin_mcp_server.py` | 15 tools that wrap the Admin API for the owner's autonomous agent team |
| **Audit log** | `public.audit_log` | Append-only trail of every sensitive action; reviewed via the Audit Log tab |

**Key invariants** (added 2026-08-24):
- `admin.html` requires the user to be in `public.platform_admins` OR
  present `X-Admin-Key: <ADMIN_API_KEY>`. The legacy `/api/admin/*`
  surface (shared-secret only, 5 endpoints) is preserved for back-compat.
- **Never echo real secret values.** `/admin/api/keys` returns
  `***<last4>` + `configured: bool` only. Stripe keys additionally
  carry `mode: test|live`.
- **Every sensitive action writes an `audit_log` row** with
  `actor_type ∈ {platform_admin, mcp, service}`, the action name
  (`user.impersonate`, `migration.apply`, `billing.refund`, …), the
  target, and the request IP/UA.
- The migration that creates `platform_admins` and `audit_log` is
  `migrations-py/add_admin_console.sql` (applied by the existing
  `scripts/apply_migrations.py` flow). It is idempotent (`CREATE TABLE
  IF NOT EXISTS`).
- `force=True` on `/admin/api/migrations/apply` is **rejected in
  v0.1**. The owner must run the CLI `--force` path from a terminal
  with eyes on the diff.
- To grant a user admin access, run in the Supabase SQL editor:
  ```sql
  insert into public.platform_admins (user_id, email)
  values ('<auth.users.id>', '<email>');
  ```

**For the agent team (MCP)**: import `TOOLS` from
`src.core.admin_mcp_server` and register each entry. The MCP server
calls `/admin/api/*` with `X-Admin-Key` so it does NOT need a Supabase
JWT; set `ADMIN_API_KEY` and `BIJOU_ADMIN_BASE_URL` in the agent
host's environment.
- ❌ Don't trust cron reports about "548 inserted" when the actual DB count is 0. The Overpass scout was silently failing for 7+ days because `ignoreDuplicates: true` returned `data: []` with no error. Always check the actual count, not the script's own log.
- ❌ Don't use the same `i18n.ts` string for both pricing and features blocks. The KB doc count has been a 1-line fix for 9+ days because the same file says "200 documents" in one place and "50 FAQs + 2 documents" in another.
- ❌ Don't `git reset --hard origin/master` after a squash merge. The squash bundles everything into one commit on `origin/master`; your local feature branch tip is NOT in that commit. Recovery: `git checkout <old-sha> -- <files>`, then commit.
- ❌ Don't claim "fixed" without hitting the live URL. See §7.
- ❌ Don't autodeploy without a smoke test. The "all green CI, prod is broken" pattern is real.

---

## 10. Where to look first

| Question | Look here |
|---|---|
| What's deployed right now? | `topics/bijou-prod-health-state.md` |
| What's broken in the lead pipeline? | `topics/bijou-daily-pipeline-state.md` |
| What's the i18n drift? | `topics/bijou-pricing-drift-state.md` |
| What's my LLM costing? | `topics/bijou-cost-watchdog-state.md` |
| What changed in the codebase? | `git log --oneline -20` |
| What did past humans/agents do? | `docs/handoffs-and-audits/` (29 files) |
| What was the original plan? | `docs/PROJECT_EXECUTION_PLAN.md`, `docs/SWARM_ARCHITECTURE.md` |
| How do I deploy X? | `ops/README.md` + per-package AGENTS.md |
| Why is Y the way it is? | grep the original PR or handoff doc |
| What's the EU AI Act / GDPR / PDPA position? | `docs/compliance/` (3 docs) |
| What's the shared-nervous-system plan? | `docs/superpowers/specs/2026-08-23-competitive-teardown-and-genui-roadmap.md` § Shared-nervous-system |
| What 3rd-party repos are pending integration? | issues #22 (Connector-Hub) and #27 (Voice) |

---

## 12. Shared-nervous-system (in progress, locked 2026-08-23)

The plan is to absorb three external projects into this monorepo so
Bijou has a unified "connect your tools + talk to you anywhere" layer:

| Repo | Target path | Issue | Status |
|---|---|---|---|
| `W3J-BIJOU PROJECT/` (Telnyx MCP server + 3 voice AI agents) | `packages/voice/` | #27 | Not started — security audit complete (4 SECURITY.md files written) |
| `Connector-Hub v0.1/` (15 REST/MCP connectors + workflow engine) | `packages/connect/` | #22 | Not started — fragility audit pending (issue #30) |
| `Contact Center v0.2/` (already deployed at contact-center.getbijou.xyz) | stays separate MVP | n/a | Already deployed; needs escalation-bug fix (issue #29) before shared-ns integration |

**Decision lock (2026-08-23):** Nango (shipped today) becomes the short-term
Integrations backend until the Connector-Hub audit (#30) finishes. If the
audit recommends absorb, Nango is replaced. If not, Nango stays.

**A2A seam (foundation landed, design not yet done):** `public.shared_context`
table + `src/core/shared_context_api.py` is the data layer. The protocol doc
that defines the message envelope, read/write contract, privacy posture,
and conflict resolution is the next deliverable — issue #31.

---

## 13. Compliance posture (added 2026-08-23)

Three lawyer-ready documents live in `docs/compliance/`:

- `EU_AI_ACT_2024.md` — risk classification, Article-by-Article obligations,
  conformity assessment, post-market monitoring
- `DATA_SUBJECT_RIGHTS.md` — PDPA + GDPR + UK GDPR + MY PDPA 2010 rights matrix
- `MODEL_CARD.md` — Gemini 2.5 Flash lineage, intended use, evaluation, ethics

**Quick facts:**
- Bijou is **limited-risk** (Article 50 transparency only), not high-risk
- Right of access / erasure / portability exposed at `GET /data-request`
- Every AI reply has a Reasoning Trace (EU AI Act Article 13 transparency)
- Inbox Co-pilot is a human-in-the-loop gate (Article 14, voluntarily)
- Stripe + Supabase + Google + WhatsApp + Telnyx are the subprocessors

Sign-off blocks are TBD — owner action required.

---

## 11. The vibe

This codebase serves **Malaysian SMEs**. The product replies in **Manglish**.
The team is autonomous, the loop is tight, the safety nets are real.

When in doubt:
- Run `npx tsc --noEmit` (catches most things)
- Read the existing code in the file you're changing (the answer is usually there)
- Don't add new patterns when an existing one works
- Don't over-engineer — ship, learn, refactor
- The user is building a business, not a portfolio. Bias toward "this works in prod" over "this is theoretically elegant."

Welcome to the swarm. 🚀
