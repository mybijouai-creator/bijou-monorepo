# Bijou — manual UX verification checklist (every menu page)

> The user said "you must confirm all sign in, signup, dashboard, our
> AI access, every menu pages, working". The `smoke-test-prod.ps1`
> script covers 9 automated checks. **This checklist covers the
> visual + UX + per-page state the automation can't see.**
>
> Run after `smoke-test-prod.ps1 -BaseUrl <coolify-url>` is green.
> Use a real Browser (Chrome/Edge) on the desktop, not curl.
>
> For each item, ✅ = passes, ❌ = fails (write the failure detail in
> the "Issue" column and report back to the agent).

## Pre-flight (5 min)

- [ ] The Coolify URL is the one you just deployed
      (e.g. `https://coolify-bijou.getbijou.xyz/`).
- [ ] You have a **real email** to sign up with (use a tenant you
      control; the magic-link email WILL go to a real inbox).
- [ ] You have an **existing tenant login** for at least one account
      (the staging or test tenant, not a real customer).

## A. Sign in + sign up flows (10 min)

### A1. Sign in (existing tenant)
- [ ] Navigate to `/` — landing loads, no 500, no obvious JS errors
      in the dev console.
- [ ] Click "Login" in the top nav.
- [ ] Land on `/static/login.html` (or the routing equivalent).
- [ ] Enter the **existing tenant email + password**.
- [ ] Submit → redirected to dashboard home, no "wrong domain" loop.
- [ ] The session token is in `localStorage` for the Coolify origin
      (not the Fly origin — that was the recurring bug class
      per CLAUDE.md §"Auth invariants").
- [ ] Click "Logout" in the user menu → returned to landing, no
      lingering session.

### A2. Sign up (new tenant)
- [ ] Click "Sign up" or "Get started".
- [ ] Land on the signup form.
- [ ] Enter a **fresh email** + a strong password + the tenant
      slug + the tenant name.
- [ ] Submit.
- [ ] Confirm the **magic-link email arrives** within 60 seconds.
      (If not, Resend is misconfigured — check the Coolify env group
      for `RESEND_API_KEY`.)
- [ ] Click the magic link in the email.
- [ ] Land on the dashboard, tenant is created, no 500.
- [ ] Navigate to Settings → confirm the new tenant is present
      under "tenants you administer".

### A3. Password reset
- [ ] Log out, click "Forgot password".
- [ ] Enter the existing tenant email.
- [ ] Confirm the reset email arrives.
- [ ] Click the link, set a new password, confirm you can log in
      with the new password.

## B. Dashboard menu (15 min)

Open the dashboard with the existing tenant. For each menu item:

### B1. Home / Overview
- [ ] Loads in <2s.
- [ ] Shows the tenant's basic stats (conversations, customers,
      active integrations).
- [ ] "Your AI just did" activity feed shows recent events
      (the GenUI primitive from the 2026-08-23 round 2 commit).

### B2. Customers
- [ ] List loads, paginated.
- [ ] Click a customer → conversation history loads.
- [ ] Search box filters the list.
- [ ] New customer form submits and appears in the list.

### B3. Conversations
- [ ] List of recent conversations loads.
- [ ] Click a conversation → full message thread renders.
- [ ] Reply box is present and accepts input.
- [ ] **Send a real test message** to the customer (via WhatsApp
      on your phone) and confirm it shows up in the conversation
      thread within 10s. This is the live end-to-end test.

### B4. AI
- [ ] The AI chat tab loads.
- [ ] Send a test prompt ("Hello, can you help me?").
- [ ] AI replies in **Manglish** (the cultural moat — see
      AGENTS.md §11). If the reply is in formal English, the
      `MANGLISH_DETECTION` or `CULTURAL_CONTEXT_ENABLED` flag is
      off in Coolify but was on in Fly.
- [ ] **Reasoning Trace** is visible (EU AI Act Article 13
      transparency requirement — see MODEL_CARD.md).

### B5. Knowledge Base
- [ ] List of KB docs loads.
- [ ] Upload a test PDF (or TXT) — should appear in the list
      within 5s.
- [ ] This is the path that **may use Appwrite storage** if
      `ENABLE_APPWRITE_STORAGE=true` was set in the Coolify env.
      If on, the upload should succeed and `appwrite_client.py`'s
      `health_check()` (exposed at `/admin/api/appwrite/health`)
      should report `reachable: true`.

### B6. Integrations
- [ ] The Integrations tab loads. (Per CLAUDE.md, this is Nango-
      backed as of 2026-08-22. Nango is feature-flagged — if
      `NANGO_SECRET_KEY` is empty, the tab will show "Integrations
      not configured".)
- [ ] If a Nango key is set, the Connect UI for at least one
      integration is present.

### B7. Billing
- [ ] Loads, shows the current plan (PRO/GROWTH/FREEMIUM).
- [ ] Pricing matches what `pricing.html` and the landing show
      (this is the `bijou-pricing-drift-state.md` monitor's
      check; 33 silent ticks = aligned).
- [ ] "Manage subscription" button → Stripe Customer Portal
      loads.

### B8. Settings
- [ ] Sub-tabs: Profile, Team, API keys, Compliance, Data Rights.
- [ ] **Data Rights** link (added 2026-08-23 round 3) → lands on
      `/data-request` (the public, no-login endpoint).
- [ ] Update the tenant name in Profile → save → reload → change
      persists.

### B9. Health
- [ ] Loads. Shows the 9-check self-test (or the `/api/self-test/summary`
      output).
- [ ] All checks green or warn. **No critical failures.** (Per
      CLAUDE.md, the Coolify healthcheck polls this endpoint; a
      critical failure triggers auto-rollback.)

### B10. Updates
- [ ] Loads. Shows the AI Activity Stream (issue #12, shipped
      2026-08-23 round 7).
- [ ] At least one entry is present (the test signup should
      appear here).

### B11. Help / Support
- [ ] Loads. The in-product `/api/help/chat` widget should work
      (aliased to `ai://helpdesk` per AGENTS.md §AI Gateway).
- [ ] Ask a question, get a relevant reply.

## C. Admin console (5 min)

- [ ] Navigate to `/static/admin.html`.
- [ ] Enter `X-Admin-Key: <the ADMIN_API_KEY from the Coolify env
      group>` (the admin API gates on this; per AGENTS.md §9b).
- [ ] The console loads. If it 401s, the key is wrong OR
      `BIJOU_ADMIN_BASE_URL` is missing.
- [ ] Each tab loads: Health, Tenants, Users, Billing, Migrations,
      API Keys, Audit Log.
- [ ] **Migrations** tab shows the 10 SQL migrations (per
      `apply_migrations.py`), all marked applied.
- [ ] **API Keys** tab shows the configured keys with `***<last4>`
      + `configured: bool` (NEVER real values — per the invariant
      added 2026-08-24).
- [ ] **Audit Log** tab shows recent admin actions (your login
      should be the most recent entry).

## D. Telnyx / WhatsApp integration (10 min)

- [ ] **Telnyx**: send a WhatsApp message to the connected
      number. Confirm the webhook reaches the bridge and the AI
      replies within 10s.
- [ ] **Telegram**: if `ENABLE_TELEGRAM_TOOL=true` and a Telegram
      bot is connected, send a Telegram message to the bot. Same
      expected behavior.

## E. End-to-end loop (5 min)

- [ ] **Customer WhatsApp → AI reply → customer sees the reply:**
      full round trip in <30s.
- [ ] **Customer asks for handover (e.g. "I want to talk to a
      person"):** the escalation fires, the dashboard's Inbox
      Co-pilot shows it, and the operator can take over.

## F. Mobile / responsive (3 min)

- [ ] Open the dashboard on your phone. The layout reflows.
- [ ] The menu collapses to a hamburger.
- [ ] No horizontal scroll on a 360px viewport.

## G. API health (3 min, automated)

From a terminal with `curl`:
```bash
curl -fsS https://app.mybijou.xyz/health
# Expected: {"status":"healthy","service":"bijou-ai-enterprise","version":"2.2.0",...}
curl -fsS https://app.mybijou.xyz/api/self-test/summary
# Expected: {"overall":"pass", ...}
```

Or run the full smoke test:
```bash
.\ops\coolify\smoke-test-prod.ps1 -BaseUrl 'https://app.mybijou.xyz'
```

---

## Reporting results

When you're done, paste the result table back to the agent:

```
A1 sign in              ✅
A2 sign up              ✅
A3 password reset       ✅
B1 home                 ✅
B2 customers            ❌ — search box returns 500
B3 conversations        ✅
...
```

If any ❌, do NOT mark the cutover done. The bridge can be cut
without the dashboard being perfect (rollout can be partial), but
the dashboard should be at least 90% green before flipping DNS to
100% of traffic.

If a "B" item is ❌ and it's a Supabase-side issue, the fix is
likely in `packages/backend/src/saas/<file>.py`. If it's a
static-asset issue (the page returns 200 but is blank), the fix
is in `packages/backend/static/<file>.html`.
