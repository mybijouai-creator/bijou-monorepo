#!/usr/bin/env pwsh
# Issue batch -- Bijou AI -- 2026-08-23
# Generated from: docs/superpowers/specs/2026-08-23-competitive-teardown-and-genui-roadmap.md
# Run: pwsh -File .github/ISSUE_BATCH_2026-08-23.md
# OR: copy the gh commands below into a shell one by one

$repo = "mybijouai-creator/bijou-monorepo"
$issues = @(
    # ============ P0 / SECURITY ============
    @{
        title = "P0: Rotate Telnyx org API key + JWT + MiniMax key + SIP credentials (proactive)"
        labels = "bug,help wanted"
        body = @'
## Why
Three Telnyx-related projects in `w3j-projects/telnyx/` hold live credentials on local disk
in plaintext:
- `W3J-BIJOU PROJECT/.env` -- Telnyx JWT, org API key, public key, MiniMax key
- `W3J-BIJOU PROJECT/scripts/sip_credentials.json` -- live SIP username/password
- `W3J-BIJOU PROJECT/docs/KNOWLEDGE_BASE.md` -- org key pasted in markdown

**No secrets have been committed to git** (verified 2026-08-23: W3J-BIJOU PROJECT is not a
git repo; Contact-Center v0.2 has `.env` in `.gitignore` and 0 commits ever contained a
real `.env`; Connector-Hub has only `.env.example`). The exposure vector is **local disk
read access**, not git history.

## Acceptance criteria
- [ ] New Telnyx org API key generated (old revoked)
- [ ] New Telnyx JWT generated (old revoked)
- [ ] New MiniMax API key generated (old revoked)
- [ ] New SIP credentials rotated at Telnyx Portal → Voice → SIP Connections
- [ ] Local `.env` updated with new values in all three projects
- [ ] Local `scripts/sip_credentials.json` updated
- [ ] `docs/KNOWLEDGE_BASE.md` org key value **replaced with placeholder** (e.g. `<see 1Password>`)
- [ ] Each affected service restarted and end-to-end smoke tested
- [ ] Rotation logged in `docs/INCIDENTS.md` (date, service, by whom)

## Runbook
See `W3J-BIJOU PROJECT/SECURITY.md` for the full step-by-step.

## Out of scope
- Migrating to a proper secrets manager (1Password CLI, Infisical, Doppler). This is a
  follow-up issue -- see "Adopt secrets manager across all 3 projects" in the 30-day batch.
'@
    },
    @{
        title = "P0: Verify and document the manual flyctl deploy path (Fly billing lock)"
        labels = "bug"
        body = @'
## Context
Per CLAUDE.md (updated 2026-08-23), Fly.io billing is locked and the `flyctl deploy
--config fly.production.toml --remote-only` manual escape hatch is also failing with
"ensure depot builder failed... status 403: Your account has overdue invoices". There is
**currently no working backend deploy path.**

This issue tracks the verification + workaround path so the team isn't stuck.

## Acceptance criteria
- [ ] Confirm Fly invoice status: is the account actually locked or is it a token/role issue?
- [ ] If locked: document the payment-URL + owner action
- [ ] If token/role: re-authenticate `flyctl` from the project owner's terminal
- [ ] Confirm a fresh `flyctl deploy --remote-only` succeeds end-to-end (no code change,
      just a hello-world deploy, then revert)
- [ ] Document the verified manual deploy procedure in `docs/DEPLOY.md`
- [ ] Note the *actual* current primary deploy target (Coolify, per today's alignment)

## Out of scope
- Paying the invoice (owner action, not agent action)
- Migrating to a different platform (separate epic)
'@
    },

    # ============ SELL-TOMORROW (7-DAY) ============
    @{
        title = "[7d] Wire Integrations Connect UI to POST /api/nango/session"
        labels = "enhancement,good first issue"
        body = @'
## Why (from the 2026-08-23 teardown)
CLAUDE.md states: "the dashboard's Integrations tab still needs the frontend Connect UI
wired up to call it (not done as of 2026-08-23)." This is the only thing standing
between the dashboard and a usable "Connect Gmail / Calendar" claim -- the *one feature*
blocking the Integrations tab from being functional.

## Current state
- `packages/backend/static/dashboard.html` has `IntegrationsModule` at line 7280 (native
  tab, shipped in commit aa19ada)
- Backend has `src/connectors/nango_api.py` and `src/connectors/nango_client.py` per
  CLAUDE.md
- Frontend UI is rendered but the Connect button does not call the API

## Acceptance criteria
- [ ] `IntegrationsModule` Connect button calls `POST /api/nango/session` with the
      provider key (gmail, google_calendar, slack, etc.)
- [ ] On success, redirect the user to the returned Nango-hosted connect URL
- [ ] On error, surface a toast and stay in the Integrations tab
- [ ] After OAuth round-trip, the dashboard reflects the new connection (poll or webhook)
- [ ] Add a unit test for the frontend request shape (mock the API)
- [ ] Add a backend test for `nango_api.py` session-creation happy path (mock the Nango client)

## Files affected
- `packages/backend/static/dashboard.html` (IntegrationsModule)
- `packages/backend/src/connectors/nango_api.py` (may need a small change)
- `packages/backend/tests/unit/test_nango.py` (new)

## Estimate
Half day to 1 day.

## Verification
- Run dev server locally, click Connect on Gmail, complete the OAuth, see Gmail listed
  as connected in the dashboard
- Backend pytest: `cd packages/backend && make test` passes
'@
    },
    @{
        title = "[7d] Add public pricing tiers + competitor comparison page"
        labels = "enhancement,help wanted"
        body = @'
## Why
The teardown flagged: "Bijou pricing is unanchored -- no public comparison page, no
published tiers in 12 weeks of recent activity, vulnerable to 'what does it cost' being
the first question every prospect asks." No anchor = no close.

## Current state
- `packages/landing/pricing.html` exists (13K) but is unstyled vs the landing
- `packages/backend/src/saas/pricing_engine.py` exists (per CLAUDE.md) but its tiers
  aren't surfaced in the landing

## Acceptance criteria
- [ ] Add 3 named tiers to `packages/landing/pricing.html`: **Starter** (RM 99/mo,
      1 agent, 1k MAU), **Growth** (RM 299/mo, 5 agents, 10k MAU), **Scale** (Custom,
      unlimited). Display in MYR, USD, SGD.
- [ ] Add a 4th column: a "vs WATI / Respond.io / SleekFlow / Tidio" comparison table
      showing the same buyer would pay ~$79-249/mo + WhatsApp message fees for
      the closest competitor. Position Bijou as: "1.2× the price, 5× the value
      (4-locale voice + visible AI reasoning + EU-AI-Act-grade compliance)."
- [ ] Add a 1-line "Why we cost more" callout -- link to the agentic-GenUI page (new)
- [ ] Add a public "Bijou vs WATI" detailed comparison page at `/vs/wati`,
      `/vs/respond-io`, `/vs/sleekflow`, `/vs/tidio` (one page per competitor, same
      template, ~200 words each)
- [ ] Mobile-responsive: the comparison table collapses to a stacked view on narrow screens
- [ ] Verify `npm run typecheck:landing` passes

## Files affected
- `packages/landing/pricing.html`
- `packages/landing/vs/wati.html` (new)
- `packages/landing/vs/respond-io.html` (new)
- `packages/landing/vs/sleekflow.html` (new)
- `packages/landing/vs/tidio.html` (new)
- `packages/landing/i18n.ts` (add `pricing.starter` etc. keys for all 4 locales)

## Out of scope
- Real Stripe-backed self-serve billing (separate 30-day issue)
- Annual vs monthly toggle (nice-to-have, defer)

## Estimate
1 day.
'@
    },
    @{
        title = "[7d] Add 'What your AI just did' activity stream widget on Home"
        labels = "enhancement"
        body = @'
## Why
This is the **first Agentic GenUI primitive** to ship. The teardown named this as
the highest-value gap: "the entire product's promise ('set up in 5 minutes') is
undercut by a first screen that doesn't show the AI in action." The widget gives
a non-technical owner *visible evidence* their AI is doing work.

## Current state
- `HomeModule` (line 6656) already fetches `/api/dashboard/stats`, escalations, and
  WhatsApp status
- It shows 4 stat cards and the existing 'Needs you' panel
- It does NOT show a feed of recent AI actions

## Acceptance criteria
- [ ] Add a new "Recent activity" card below the stat cards on Home
- [ ] Pull from existing data (no new endpoints): combine `conversations` (last 5
      with AI-handled flag), `escalations` (already-fetched), and a new lightweight
      poll on `/api/dashboard/activity?since=24h` (or a synthesized view from
      `/api/dashboard/stats`)
- [ ] Each item shows: time (relative), emoji icon, one-line description, "undo"
      button where applicable (e.g., "Bijou captured a lead from +6012...")
- [ ] Empty state: "Your AI hasn't done anything yet. Connect WhatsApp to get started."
      (reuses the same setup CTA as Getting-Started)
- [ ] Polite polling every 30s (don't hammer the API)
- [ ] Add a backend `/api/dashboard/activity` endpoint if needed (15 lines: aggregate
      the existing queries into a sorted activity feed)

## Files affected
- `packages/backend/static/dashboard.html` (HomeModule)
- `packages/backend/src/saas/dashboard_api.py` (new `/api/dashboard/activity` route)
- `packages/backend/tests/unit/test_dashboard_activity.py` (new, ~10 tests)

## Estimate
1 day. Ship it ugly, polish later.

## Verification
- After deploy, open Home in a browser, see a live feed of recent AI activity
- Backend tests pass
'@
    },
    @{
        title = "[7d] Public changelog page at /changelog (render from CHANGELOG.md)"
        labels = "enhancement,good first issue"
        body = @'
## Why
Buyers and existing customers both want to see: "what changed this week?" A public
changelog is the cheapest trust signal in SaaS.

## Acceptance criteria
- [ ] Add a `/changelog` route in the landing site
- [ ] Render the top of `CHANGELOG.md` (the file already exists in the landing root)
- [ ] Style consistent with the rest of the landing (dark-emerald-gold Signal Gem theme)
- [ ] Show last 12 entries, link to "view full history on GitHub" (points to
      `https://github.com/mybijouai-creator/bijou-monorepo/blob/main/packages/landing/CHANGELOG.md`)
- [ ] Mobile responsive
- [ ] Add to landing nav (small "What's new" link, not in the primary CTA)

## Files affected
- `packages/landing/changelog.html` (new)
- `packages/landing/index.html` (nav link)
- `packages/landing/vite.config.ts` (no router -- add a hash route or just static link)

## Estimate
Half day.

## Out of scope
- RSS feed (defer)
- Auto-parse from commits (just render the markdown for now)
'@
    },
    @{
        title = "[7d] Inline 'Book a 15-min demo' Calendly on home CTA"
        labels = "enhancement,good first issue"
        body = @'
## Why
The landing has a CTA but no concrete next step. Calendly inline = 1-step conversion.

## Acceptance criteria
- [ ] Add a Calendly popup widget to the hero CTA "Book a 15-min demo" button
- [ ] The existing primary CTA "Get started" stays a link to `/signup` (or the
      `OnboardingModal`)
- [ ] New secondary CTA "Book a demo" opens Calendly
- [ ] Track the click event (PostHog already integrated per `POSTHOG_SETUP.md`)

## Files affected
- `packages/landing/index.html` (hero CTA)
- `packages/landing/components/Hero.tsx` (or whatever the hero is)
- `packages/landing/.env` (Calendly URL)

## Estimate
2-3 hours.

## Dependencies
- Calendly account with public booking link. Owner provides URL.

## Verification
- Click "Book a demo" → Calendly popup opens with the right 15-min slot
'@
    },
    @{
        title = "[7d] Fix landing duplicate-signup silent success + discarded lead data (regression test)"
        labels = "bug,enhancement"
        body = @'
## Context
Commit 58cc741 already shipped a fix for: "duplicate-signup silent success, dead error
UI, discarded lead data, dead files." Per the commit message, several landing-side bugs
were resolved. This issue tracks a regression test to make sure they don't come back,
plus any remaining issues from the bug class.

## Acceptance criteria
- [ ] Add a regression test that simulates a duplicate-signup POST and asserts the
      response is informative (not silent 200)
- [ ] Add a regression test for `OnboardingModal` lead-data capture (assert the
      payload contains all fields, none are silently dropped)
- [ ] Audit `packages/landing/api/` for any other dead endpoints and either wire them
      up or delete them (commit message mentioned "dead files")
- [ ] Verify the existing landing's "Get started" CTA does NOT post to a dead URL

## Files affected
- `packages/landing/api/` (audit + cleanup)
- `packages/landing/components/OnboardingModal.tsx` (regression test)
- `packages/landing/tests/` (new regression suite, or extend existing)

## Estimate
Half day.
'@
    },

    # ============ SELL-THIS-MONTH (30-day) ============
    @{
        title = "[30d] Reasoning Trace in Inbox -- visible AI 'why I said this' side panel"
        labels = "enhancement,help wanted"
        body = @'
## Why
**This is the #1 differentiator from the teardown.** When a non-technical owner asks
their AI "why did you tell that customer X?", the answer should be a 1-tap side panel
showing: which KB docs were retrieved, which tools were called, the model's confidence,
and 2-3 alternative replies considered.

This single feature is the **trust primitive**, the **EU AI Act 2024 compliance
primitive**, and the **fundable differentiator**.

## Acceptance criteria
- [ ] Inbox messages (line 795) -- every AI message is tappable
- [ ] On tap, a side panel slides in from the right showing:
  - KB documents retrieved (with relevance score)
  - Tool calls made (e.g., `cal.com.create_booking`, `contacts.add`)
  - Prompt tokens / completion tokens / model version
  - Confidence score (0-100, derived from logprobs or self-eval)
  - "Alternative replies considered" -- 2-3 drafts with "use this instead" button
- [ ] Side panel works on mobile (bottom sheet instead of side panel)
- [ ] Data is captured in a new `message_reasons` table (one row per AI message):
  ```sql
  create table message_reasons (
    id uuid primary key,
    message_id uuid references messages(id),
    retrieved_docs jsonb,
    tool_calls jsonb,
    model text,
    confidence numeric,
    alternatives jsonb,
    created_at timestamptz default now()
  );
  ```
- [ ] Add a regression test that asserts every AI response is recorded in
      `message_reasons` (no silent AI replies)

## Files affected
- `packages/backend/static/dashboard.html` (InboxModule -- message click handler)
- `packages/backend/src/core/bijou.py` (record the reason alongside the message)
- `packages/backend/src/saas/messages_api.py` (new `/api/dashboard/messages/{id}/reason` GET)
- `migrations-py/add_message_reasons.sql` (new)
- `packages/backend/tests/unit/test_message_reasons.py` (new, ~15 tests)

## Estimate
1 sprint (~10 days).

## Verification
- Open inbox, send a test message, see the AI reply, tap it, see the full reasoning
  panel with KB docs, tool calls, confidence, alternatives
- Run the regression test: every AI message in a test conversation has a corresponding
  `message_reasons` row

## Out of scope
- Showing the *original* prompt (privacy -- customers shouldn't see system prompts)
- Replay UI for the entire conversation as a trace (separate issue)
'@
    },
    @{
        title = "[30d] AI Activity Stream -- replace Updates tab with live AI-action feed"
        labels = "enhancement"
        body = @'
## Why
The teardown flagged Updates as "lowest-value surface" and proposed it become the
**AI-action feed** -- daily evidence the customer is getting value. This is the second
agentic-GenUI primitive.

## Acceptance criteria
- [ ] Replace the existing `UpdatesModule` (line 6411) with a new `ActivityStream` module
- [ ] Each item is a card showing: timestamp, emoji, one-line description, "View" link
- [ ] Stream items (synthesized from existing data):
  - "Bijou replied to +60 12-345 6789 in Bahasa"
  - "Bijou captured a lead from +60 12-345 6789"
  - "Bijou escalated 'pricing question' to you"
  - "Bijou booked a viewing for tomorrow 3pm with Anwar"
- [ ] Filter chips: Today / 7d / 30d
- [ ] "Email me a weekly summary" toggle in Settings
- [ ] Reuses the existing `/api/dashboard/activity` endpoint from the 7-day widget

## Files affected
- `packages/backend/static/dashboard.html` (ActivityStream module)
- `packages/backend/src/saas/dashboard_api.py` (extend activity endpoint)
- `packages/backend/tests/unit/test_activity_stream.py` (new, ~8 tests)

## Estimate
1 sprint (~10 days).

## Verification
- Open Activity, see 5+ real items from the last 24h
- Filter chip toggles work
- Weekly-summary email triggers (manual send first, then schedule)
'@
    },
    @{
        title = "[30d] Inbox Co-pilot -- proactive suggestions with explicit user-approval gate"
        labels = "enhancement"
        body = @'
## Why
The third agentic-GenUI primitive. The AI proactively suggests actions; the user
explicitly approves before anything is sent. This is the *human-in-the-loop* primitive
that makes Bijou usable by non-technical owners.

## Acceptance criteria
- [ ] While typing a reply, the AI watches the conversation and surfaces 1-3 suggestion
      cards in a small panel above the input
- [ ] Suggestions: "Looks like a price question -- use the template?", "Customer went
      quiet for 6h -- send a check-in?", "They mentioned 'viewing' 3 times -- book a slot?"
- [ ] Each suggestion has: "Use", "Edit first", "Dismiss"
- [ ] **No auto-send** -- the user must click "Use" (which puts the suggested text in
      the input) or "Send" (which actually sends)
- [ ] Behind a feature flag: `INBOX_COPILOT_ENABLED` per-tenant
- [ ] Audit log: every suggestion shown + user action (accept/edit/dismiss) is recorded

## Files affected
- `packages/backend/static/dashboard.html` (InboxModule -- co-pilot panel)
- `packages/backend/src/saas/inbox_copilot.py` (new module)
- `packages/backend/tests/unit/test_inbox_copilot.py` (new, ~20 tests covering all
  suggestion types)

## Estimate
1 sprint (~10 days).

## Verification
- Open a conversation, type a reply, see suggestion cards appear
- "Use" puts the text in the input (does NOT send)
- "Edit first" opens the input with the text
- "Dismiss" hides the card and records the dismiss
'@
    },
    @{
        title = "[30d] Outreach: broadcast + audience builder + PDPA consent gate"
        labels = "enhancement"
        body = @'
## Why
The teardown flagged Outreach as "has UI shell, lacks the blast feature. Cannot be
sold as 'outreach' without the broadcast." Plus a missing **PDPA consent gate** --
without it, sending broadcasts to non-consenting contacts is a legal violation
(PDPA Section 6 -- purpose limitation).

## Acceptance criteria
- [ ] Audience builder: pick by tag, by recent conversation, by lead source, by custom filter
- [ ] Template: WA-template compatible (header/body/footer/buttons), with placeholder
      syntax `{{customer_name}}`
- [ ] Send: schedule now or schedule for time; rate-limited (50/sec default)
- [ ] **PDPA consent gate**: each contact in the audience must have
      `marketing_consent_at` set; contacts without consent are excluded with a
      visible "excluded (no consent)" count
- [ ] Test mode: send to a 3-contact audience, see the actual messages on real WhatsApp
- [ ] Audit log: who sent, what template, to whom, when
- [ ] Per-tenant rate limit + per-Meta-template-status (approved/pending/rejected)

## Files affected
- `packages/backend/static/dashboard.html` (OutreachModule -- line 7391)
- `packages/backend/src/saas/outreach_api.py` (new or extend)
- `packages/backend/src/saas/messages_api.py` (reuse template send logic)
- `packages/backend/tests/unit/test_outreach.py` (new, ~20 tests)

## Estimate
1 sprint (~10 days).
'@
    },
    @{
        title = "[30d] Self-serve billing in Settings (Stripe Customer Portal)"
        labels = "enhancement,good first issue"
        body = @'
## Why
The teardown flagged: "No self-serve upgrade/downgrade. No billing/invoices tab. This
is the single biggest reason a customer churns -- they hit a limit, can't upgrade, leave."

## Acceptance criteria
- [ ] Add a "Billing" tab in Settings
- [ ] Shows current plan, next invoice date, payment method
- [ ] "Manage subscription" button opens the Stripe Customer Portal (pre-configured URL)
- [ ] "Download invoice" link for the last 12 months
- [ ] Per-tenant Stripe customer ID is set at signup
- [ ] Webhook handler updates the local `tenants` table on subscription change
- [ ] Graceful handling of cancelled subscriptions (read-only mode after 7 days)

## Files affected
- `packages/backend/static/dashboard.html` (SettingsModule)
- `packages/backend/src/saas/billing_api.py` (new)
- `packages/backend/src/saas/stripe_service.py` (extend)
- `packages/backend/tests/unit/test_billing.py` (new, ~10 tests)

## Estimate
1 sprint (~5 days, mostly Stripe integration).

## Dependencies
- Stripe account with Customer Portal configured (owner sets up)
- Per-tenant price IDs in the env

## Verification
- Open Settings → Billing, click "Manage subscription", land in Stripe Portal,
  upgrade, return to dashboard, see new plan
'@
    },
    @{
        title = "[30d] Adopt secrets manager across all 3 projects (1Password CLI / Infisical)"
        labels = "enhancement,help wanted"
        body = @'
## Why
The teardown + security audit found live credentials in plaintext `.env` files on
local disk. Rotation is a one-time fix; the *systemic* problem is "we put plaintext
secrets on disk." A secrets manager is the durable answer.

## Acceptance criteria
- [ ] Pick a tool: 1Password CLI (preferred -- already in Bold Business's stack per
      user profile), Infisical (open-source, self-hostable), or Doppler (managed)
- [ ] For each of the 3 projects, replace the live `.env` with a generated one from
      the secrets manager at startup
- [ ] `scripts/rotate-all.sh` (new) -- rotates every secret in one command
- [ ] CI uses a service-account token from the secrets manager, not a long-lived PAT
- [ ] Local dev: `op run -- python src/core/bijou.py` (or equivalent) injects the env
- [ ] Update each project's README + SECURITY.md with the new procedure

## Files affected
- All 3 projects
- `docs/SECRETS.md` (new -- master doc)
- CI workflows in each project

## Estimate
1 week (mostly setup + migration).

## Out of scope
- Per-tenant secret management (Connector-Hub already has the vault pattern -- reuse
  it in the future)
'@
    },

    # ============ 90-DAY / FUNDABLE ============
    @{
        title = "[90d] EU AI Act 2024 compliance package (transparency + traceability + eval)"
        labels = "enhancement,help wanted"
        body = @'
## Why
The teardown scored Bijou 2/5 on Security/Compliance and noted **0/5 explicit EU AI Act
controls**. EU AI Act 2024 makes AI traceability mandatory for customer-facing AI in
2026. Shipping this is the door to European expansion and is the
**fundable differentiator** vs every competitor that will be scrambling to comply.

## Requirements
- [ ] **Transparency** -- every AI reply is signed "-- Bijou"; settings has a
      "Customize AI signature" toggle
- [ ] **Traceability** -- every AI response is recorded with prompt hash, retrieved
      docs, tool calls, model version (uses the `message_reasons` table from the
      30-day Reasoning Trace issue)
- [ ] **Human oversight** -- Inbox Co-pilot is the primary; also add a per-tenant
      "human-in-the-loop required for: payments, cancellations, escalations" toggle
- [ ] **Quality management** -- eval set of 50 questions per vertical, regression
      test on every model change, weekly automated eval report
- [ ] **Bias monitoring** -- flag if AI response distribution shifts week-over-week
      (e.g., "Bijou escalated 40% more conversations this week -- investigate")
- [ ] Documentation: `docs/EU-AI-ACT-COMPLIANCE.md` enumerating each requirement
      and how Bijou meets it (for legal + investor due diligence)

## Files affected
- `packages/backend/src/core/bijou.py` (transparency, bias monitoring)
- `packages/backend/src/saas/eval/` (new module -- eval harness)
- `packages/backend/static/dashboard.html` (Co-pilot + signature)
- `docs/EU-AI-ACT-COMPLIANCE.md` (new)
- `packages/backend/tests/unit/test_eu_ai_act.py` (new, ~30 tests)

## Estimate
4-6 weeks.

## Verification
- Run the eval harness against the test set, get a 95%+ pass rate
- Open the compliance doc, hand to a lawyer, get a green light
'@
    },
    @{
        title = "[90d] Self-serve PDPA/GDPR data-request page (right to access + delete)"
        labels = "enhancement,compliance"
        body = @'
## Why
PDPA Section 12, GDPR Article 15: any data subject can request "give me all the data
you have on me." Section 13 / Article 17: right to deletion. Bijou currently has
**no self-serve path** for either. This is a legal floor, not a feature.

## Acceptance criteria
- [ ] New page `/data-request` (logged-out) -- enter phone number
- [ ] POST `/api/data-request/access` -- returns JSON of all data Bijou has on that
      phone (conversations, leads, escalations, KB doc usage)
- [ ] POST `/api/data-request/delete` -- soft-delete all data, returns a confirmation
      token, hard-deletes after 30-day grace period
- [ ] Email confirmation required for delete (not just phone-confirm; this is a
      destructive action and we want a real second channel)
- [ ] Audit log: every request, with the requester's IP, timestamp, and result
- [ ] Documented in `docs/PRIVACY.md` for legal review

## Files affected
- `packages/backend/static/data-request.html` (new)
- `packages/backend/src/saas/data_request_api.py` (new)
- `packages/backend/tests/unit/test_data_request.py` (new, ~10 tests covering
  access + delete + grace period + re-request after delete)

## Estimate
1 week.

## Verification
- Enter a phone number, receive a JSON export
- Confirm delete, see data marked deleted, verify it's gone from the inbox
'@
    },
    @{
        title = "[90d] Calls: recording + transcript + AI summary in dashboard"
        labels = "enhancement"
        body = @'
## Why
Voice calls are the highest-value per-event activity but currently a black box in the
dashboard. The teardown flagged this as the highest-revenue visibility gap.

## Acceptance criteria
- [ ] For each call (Retell / Telnyx), the Calls tab shows:
  - Duration, direction (in/out), from/to number
  - Recording playback (HTML5 audio element)
  - Transcript (auto-generated, editable)
  - AI summary: "Customer asked about viewing 3pm Tue, agreed to book, lead captured"
  - "Hot lead" auto-tag if the summary includes a buying signal
- [ ] Each call row links back to the related contact (Lead)
- [ ] Per-tenant opt-in: "Record calls" toggle (legal: some jurisdictions require
      two-party consent)
- [ ] Recordings stored in Supabase Storage, signed URLs only

## Files affected
- `packages/backend/static/dashboard.html` (CallsModule -- line 3192)
- `packages/backend/src/saas/calls_api.py` (new)
- `packages/backend/src/connectors/telnyx_webhooks.py` (extend to capture transcripts)
- `packages/backend/tests/unit/test_calls.py` (new, ~15 tests)

## Estimate
3-4 weeks (media storage is the slow part).

## Dependencies
- For the Telnyx integration: W3J-BIJOU PROJECT absorbed as `packages/voice/` first
  (separate issue in the telephony batch below).
'@
    },
    @{
        title = "[90d] Multi-region Supabase (EU + APAC + MENA pinning)"
        labels = "enhancement"
        body = @'
## Why
The teardown flagged data residency as a blocker for EU and MENA expansion. EU
customers often need EU residency; MENA (KSA NDMO) requires in-country storage for
some sectors.

## Acceptance criteria
- [ ] Set up Supabase projects in: ap-southeast-1 (current, MY), eu-west-1 (Ireland),
      me-central-1 (UAE -- closest MENA region)
- [ ] Per-tenant region pinning (new column `region` on `tenants`)
- [ ] Migration playbook: tenant can request region move; cross-region migration
      via logical replication
- [ ] Supavisor connection pooler per region
- [ ] Documented in `docs/MULTI-REGION.md`

## Files affected
- `packages/backend/src/saas/tenants.py` (add region)
- `packages/backend/src/core/db.py` (region-aware connection)
- `docs/MULTI-REGION.md` (new)
- New `migrations-py/add_tenant_region.sql`

## Estimate
4-6 weeks (mostly Supabase setup + testing).

## Dependencies
- Supabase organization permissions to create projects in new regions
'@
    },
    @{
        title = "[90d] Locale expansion: Bahasa (id), Vietnamese (vi), Arabic (ar)"
        labels = "enhancement,good first issue"
        body = @'
## Why
i18n.ts already covers en/ms/zh/ta (4 locales). The teardown recommended adding
Bahasa (Indonesia is the largest SEA WhatsApp market), Vietnamese (high growth), and
Arabic (MENA). Each locale needs native-speaker review -- *do not auto-translate*.

## Acceptance criteria
- [ ] Add `id`, `vi`, `ar` to `i18n.ts` for the landing site
- [ ] Add `id`, `vi`, `ar` to the dashboard `T` lookup table
- [ ] Manglish voice is preserved in `ms` and `id` (do NOT flatten to formal)
- [ ] Arabic: RTL layout support in the dashboard CSS
- [ ] Each locale: native-speaker review + sign-off before merge
- [ ] Document the localization workflow in `docs/I18N.md`

## Files affected
- `packages/landing/i18n.ts` (add 3 locales)
- `packages/backend/static/dashboard.html` (RTL support, add `T.id`, `T.vi`, `T.ar`)
- `docs/I18N.md` (new)

## Estimate
2-4 weeks per locale (3 locales in parallel: ~3 weeks total).
'@
    },

    # ============ TELEPHONY / SHARED-NERVOUS-SYSTEM ============
    @{
        title = "[shared-ns] EPIC: Shared-nervous-system integration (Bijou + Telnyx Voice + Connector-Hub)"
        labels = "enhancement,help wanted"
        body = @'
## What
This is the parent epic for the agreed **shared-nervous-system** integration approach.
Three sub-projects (W3J-BIJOU PROJECT, Contact-Center v0.2, Connector-Hub v0.1) get
absorbed into the Bijou monorepo in a way that shares a single tenant + memory layer.

## Architecture (locked in this session)
```
            ┌────────────────────┐
            │  Bijou (this repo) │
            │                    │
            │  WA + Telegram     │  ← brain
            │  dashboard.html    │
            │  auth_api          │
            └────────┬───────────┘
                     │ shared
        ┌────────────┼────────────┐
        ▼            ▼            ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐
  │  voice/  │ │ connect/ │ │  cc/     │
  │ (Telnyx) │ │ (Hub)    │ │ (center) │
  │          │ │          │ │          │
  │ 4th      │ │ replaces │ │ stays    │
  │ channel  │ │ Nango    │ │ separate │
  │          │ │          │ │ (MVP)    │
  └──────────┘ └──────────┘ └──────────┘
        │            │            │
        └────────────┼────────────┘
                     ▼
            ┌────────────────────┐
            │  Supabase (single) │
            │  shared_context    │
            │  table for A2A     │
            └────────────────────┘
```

## Sub-issues
- `[shared-ns] Move W3J-BIJOU PROJECT into packages/voice/ as Bijou Voice MVP`
- `[shared-ns] Move Connector-Hub into packages/connect/ as the integration layer (replace Nango)`
- `[shared-ns] Build the A2A shared_context table (Supabase schema + API)`
- `[shared-ns] Add .gitignore + SECURITY.md to the 3 telnyx projects` (DONE in this turn)

## Acceptance criteria for the epic
- [ ] All 3 sub-issues closed
- [ ] A single tenant in Bijou can have a WA conversation that escalates to a voice
      call (Telnyx concierge picks up the same context the WA agent had)
- [ ] The voice call is visible in the Bijou dashboard Inbox (cross-channel thread)
- [ ] The Connector-Hub exposes Gmail, Google Calendar, Slack, HubSpot, Stripe (the
      "Connect Your Tools" surface) -- all using the same OAuth flow as the rest of
      Bijou
- [ ] Contact-Center v0.2 stays a separate product on `contact-center.getbijou.xyz`
      for now, but its `backend/.env` reads from the same Coolify-managed secrets
- [ ] Documentation: `docs/ARCHITECTURE.md` is updated with the new layout

## Estimate
6 weeks end-to-end (some sub-issues in parallel).

## Out of scope
- Full Voice-as-4th-channel feature parity with the WA agent (separate epic;
  voice MVP first, parity second)
- Re-platforming the Contact Center into Bijou (defer until Voice MVP proves out)
'@
    },
    @{
        title = "[shared-ns] Move W3J-BIJOU PROJECT into packages/voice/ as Bijou Voice MVP"
        labels = "enhancement,telephony"
        body = @'
## Why
The W3J-BIJOU PROJECT is "80% there" -- a real, already-deployed Telnyx MCP server
with 3 live voice agents, one of which (`bijou-ai-concierge`) is already spec'd with
Bijou's Manglish voice. The file `connectors/supabase.py` is written to plug into
Bijou's existing multi-tenant Supabase backend.

The work is wiring, not building.

## Acceptance criteria
- [ ] Create `packages/voice/` (new) in the Bijou monorepo
- [ ] Move the concierge agent logic from W3J-BIJOU PROJECT into
      `packages/voice/concierge/` (Python, FastAPI)
- [ ] Wire `connectors/supabase.py` to read Bijou's Supabase (env-driven, no
      hard-coded keys)
- [ ] Add `packages/voice/concierge/Dockerfile` + Coolify deploy config
- [ ] Re-deploy the concierge as `voice.mybijou.xyz` (or similar)
- [ ] Verify end-to-end: call the live number, hear the Manglish voice, see the
      conversation logged in the shared Supabase
- [ ] Add a regression test: simulate a call, assert the Supabase row is created

## Files affected
- `packages/voice/` (new directory tree)
- `docs/ARCHITECTURE.md` (updated)
- Coolify → new service for `voice.mybijou.xyz`

## Estimate
1-2 weeks (mostly moving files + wiring env vars).

## Out of scope
- The other 2 voice agents (pricing, comparison) -- those can be absorbed later
  or stay in W3J-BIJOU PROJECT for now
- MCP server itself (it's a separate concern; absorb as `packages/voice/mcp/` later)
'@
    },
    @{
        title = "[shared-ns] Move Connector-Hub into packages/connect/ as the integration layer"
        labels = "enhancement,help wanted"
        body = @'
## Why
Connector-Hub v0.1 is "architecturally exactly the 'agent connector, plus API and
MCP' piece" -- 15 connectors, REST + MCP, credential vault, JSON workflow engine.
The teardown asked: "decide whether Connector-Hub becomes Bijou's generic 'connect
your tools' layer (replacing/absorbing the Nango work from earlier today) or stays
separate." **Decision: absorb it.**

This also *replaces* the unverified Nango work (per CLAUDE.md: "not yet verified
against the real Nango API ... built and unit-tested with mocks only").

## Acceptance criteria
- [ ] Create `packages/connect/` (new) in the Bijou monorepo
- [ ] Move Connector-Hub into `packages/connect/` (backend + frontend + infra)
- [ ] Update the dashboard `IntegrationsModule` (line 7280) to call
      `packages/connect` endpoints instead of `/api/nango/*`
- [ ] Keep the credential vault (this is the durable fix for the security
      problem)
- [ ] **Fix the fragile URL-guessing connectors**: Notion, HubSpot, Gmail, GCal,
      Airtable, GitHub -- replace with proper per-provider SDKs or hand-written
      API calls (test against real APIs)
- [ ] Add a `packages/connect/tests/` suite with live integration tests
      (gated on real credentials via env)
- [ ] Document in `docs/INTEGRATIONS.md` (which connectors ship, which are
      coming-soon, which require setup steps)

## Files affected
- `packages/connect/` (new directory tree)
- `packages/backend/src/connectors/nango_api.py` → DELETE (replaced)
- `packages/backend/src/connectors/nango_client.py` → DELETE (replaced)
- `packages/backend/static/dashboard.html` (IntegrationsModule -- update endpoints)
- `docs/INTEGRATIONS.md` (new)

## Estimate
2-3 weeks (1 week move + 1 week fix fragile connectors + 1 week tests).

## Out of scope
- The JSON workflow engine (defer -- Bijou's existing AI Setup wizard covers the
  primary use case; workflows are a power-user feature)
'@
    },
    @{
        title = "[shared-ns] Build the A2A shared_context table (Supabase schema + API)"
        labels = "enhancement"
        body = @'
## Why
The Bijou WA agent and the Telnyx voice agent are currently two independent AI
personas that don't share conversation state. The teardown identified this as the
critical A2A seam: "design the actual A2A seam between Bijou's WhatsApp agent and
the Telnyx voice agent -- right now they're two independent AI personas that don't
share conversation state."

## Acceptance criteria
- [ ] New `shared_context` table in Supabase:
  ```sql
  create table shared_context (
    id uuid primary key,
    tenant_id uuid references tenants(id),
    customer_phone text not null,
    channel text not null,        -- 'whatsapp', 'telegram', 'voice'
    thread_id text not null,      -- chat_jid for WA, call_id for voice
    role text not null,           -- 'user', 'assistant'
    content text not null,
    metadata jsonb default '{}',
    created_at timestamptz default now()
  );
  create index on shared_context (tenant_id, customer_phone, created_at desc);
  ```
- [ ] Every WA message and every voice transcript is written to `shared_context`
      with the same `(tenant_id, customer_phone)` key
- [ ] New API: `GET /api/shared-context?phone=X&since=24h` -- unified thread view
- [ ] Inbox module (line 795) renders the unified thread (WA + voice in one
      chronological view)
- [ ] On call arrival, the voice agent gets the last 10 messages from
      `shared_context` as its opening context

## Files affected
- `migrations-py/add_shared_context.sql` (new)
- `packages/backend/src/saas/shared_context_api.py` (new)
- `packages/backend/src/core/bijou.py` (write to shared_context on every message)
- `packages/voice/concierge/connectors/` (read shared_context on call arrival)
- `packages/backend/static/dashboard.html` (Inbox -- unified thread view)
- `packages/backend/tests/unit/test_shared_context.py` (new, ~15 tests)

## Estimate
1-2 weeks (schema is the easy part; the "voice reads WA context on arrival"
is the integration work).

## Verification
- A WA conversation escalates to a voice call (manually triggered)
- Voice agent greets the caller with the WA conversation's context
- After the call, the unified thread in the dashboard shows the full WA + voice
  exchange
'@
    },

    # ============ DOCS / HYGIENE ============
    @{
        title = "[docs] Update CLAUDE.md with new deploy topology (Coolify primary, Fly secondary)"
        labels = "documentation"
        body = @'
## Why
Per today's alignment: **Coolify is the primary deploy target**, Fly is secondary
(when billing clears). CLAUDE.md currently leads with Fly first, Coolify second.
This is a doc-only update but it matters because every future agent session
inherits this guidance.

## Acceptance criteria
- [ ] Update the "Deployment topology" table in CLAUDE.md
- [ ] Update the "Confirmed still locked" section to reflect Coolify as the
      *verified* path, not Fly
- [ ] Update the manual escape hatch section to add `coolify deploy` (or
      equivalent) as the primary, not `flyctl deploy`
- [ ] Update the "Commands" section with Coolify-specific deploy procedures
- [ ] Add a "Recent changes" section noting the 27 unpushed commits that need
      to land in canonical

## Files affected
- `CLAUDE.md`
'@
    },
    @{
        title = "[docs] Update AGENTS.md / docs/ARCHITECTURE.md with shared-nervous-system layout"
        labels = "documentation"
        body = @'
## Why
The current docs describe the 3-surface monorepo (landing/backend/bridge). After
the shared-nervous-system work, the monorepo will have 5 packages
(landing, backend, bridge, voice, connect). Docs need to catch up.

## Acceptance criteria
- [ ] `docs/ARCHITECTURE.md` (new) -- ASCII diagram + per-package responsibilities
- [ ] `AGENTS.md` updated to reference `packages/voice/` and `packages/connect/`
- [ ] `docs/INTEGRATIONS.md` (new) -- list of supported connectors, status, setup steps
- [ ] `docs/TELEPHONY.md` (new) -- voice channel architecture, billing, A2A seam
- [ ] All cross-references to the legacy `legacy/` folder removed or marked
      "removed 2026-08-23, see history"

## Files affected
- `AGENTS.md`
- `docs/ARCHITECTURE.md` (new)
- `docs/INTEGRATIONS.md` (new)
- `docs/TELEPHONY.md` (new)
'@
    }
)

# ============ ACTUALLY CREATE ============
Write-Output "Creating $($issues.Count) issues on $repo..."
$created = 0
$failed = 0
foreach ($issue in $issues) {
    $title = $issue.title
    $labels = $issue.labels
    $body = $issue.body
    Write-Output ""
    Write-Output "  Creating: $title"
    $tmpBody = New-TemporaryFile
    Set-Content -Path $tmpBody.FullName -Value $body -Encoding UTF8
    $out = gh issue create --repo $repo --title $title --body-file $tmpBody.FullName --label $labels 2>&1
    Remove-Item $tmpBody.FullName -Force -ErrorAction SilentlyContinue
    if ($out -match 'issues/(\d+)') {
        $created++
        Write-Output "    -> $($Matches[0])"
    } else {
        $failed++
        Write-Output "    FAILED: $out"
    }
}
Write-Output ""
Write-Output "=== SUMMARY ==="
Write-Output "  Created: $created"
Write-Output "  Failed:  $failed"
