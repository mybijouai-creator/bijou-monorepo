# Bijou Dashboard — UX Audit & Redesign Proposal

Date: 2026-08-22
Scope: `packages/backend/static/dashboard.html` (the real product UI — not `packages/landing`)
Audience for this doc: plain language, no design jargon. Every point below is something a
developer can act on directly.

## Who actually uses this

A Malaysian SME owner — a clinic, a restaurant, a property agent — who is not a software
person. They signed up because a WhatsApp AI promised to save them time. Every point below
is judged against: *does this help that person get value in the first 10 minutes, and every
day after?*

## What's already good (keep this)

- The "Signal Gem" audio/visual identity (idle/listening/thinking/speaking states, muteable)
  is a genuinely nice, distinctive touch — most SaaS dashboards are silent and static. Keep it.
- Mobile handling exists (`mobileOpen`/collapsed-sidebar states) — the app doesn't assume
  desktop-only.
- The stat cards on Home (Conversations, AI-handled %, Messages today, Leads today) are the
  right numbers — concrete, not vanity metrics.

## The four concrete problems, in priority order

### 1. There's no "what do I do first" moment

A brand-new client's Home screen right now is four stat cards showing zeros, and a 13-item
sidebar with no indication of order or importance. Nothing tells them: *connect WhatsApp →
teach your AI about your business → test it → you're live.* That's the single highest-value
gap here — the entire product's promise ("set up in 5 minutes") is undercut by a first
screen that doesn't guide anyone.

**Fix**: a small "Getting Started" checklist card at the top of Home, shown until dismissed
or until every step is done: (1) Connect WhatsApp, (2) Add your business info to the AI, (3)
Send a test message, (4) You're live. Each step links straight to the tab that does it. This
is maybe 150 lines of React and zero new backend endpoints — every piece of data it needs
(`whatsapp_connected_at`, whether a knowledge document exists, whether a test message was
ever sent) already exists somewhere in the API responses this page already fetches.

### 2. The sidebar has 13 flat items with no grouping

`Home, Inbox, Escalations, Updates, Analytics, Knowledge, Test Bijou, Media, Leads, Calls,
Outreach, AI Setup, Integrations, Settings, Help` — one flat list. A few of these
(Escalations, Updates) are things a day-one user will never touch; others (AI Setup,
Knowledge, Integrations) are setup-time actions, not daily-use ones. Mixing "things you do
once" with "things you check every day" in one undifferentiated list makes the sidebar
longer and more intimidating than it needs to be for the exact audience least equipped to
parse it.

**Fix** — four labeled groups, same items, no new pages:
- **Today** (default view): Home, Inbox, Escalations
- **Grow** (things that make money): Leads, Outreach, Calls, Analytics
- **Set up your AI**: AI Setup, Knowledge, Integrations, Test Bijou
- **Account**: Media, Settings, Help, Updates

This is a rendering change to the existing nav array (add a `group` key, render section
headers), not a data or routing change.

### 3. Some jargon that a non-technical SME owner won't parse on first read

- **"Escalations"** — internal support-ticket vocabulary. A shop owner doesn't know this
  means "a customer wants to talk to a real person." Rename the *label* to **"Needs You"**
  or **"Human Requests"** — keep the internal `escalations` id/table/API untouched, this is
  a display-string change only.
- **"AI Setup"** with a lightning-bolt icon reads like a technical settings page, not "teach
  your AI about your shop." Consider **"Teach My AI"**.
- **"Integrations"** is fine for a technical audience but means nothing to this one. Consider
  **"Connect Your Tools"** with a one-line subtitle ("Gmail, Google Calendar, and more").

None of this touches routes, ids, or the database — display strings only, and the existing
i18n system (`tl()`) is already the right place to change them for every language at once.

### 4. Four nav items leave the app entirely (fixed alongside this doc)

Outreach, AI Setup, Integrations, and Help all did a full-page browser navigation to a
separate standalone HTML file — the sidebar, the Signal Gem, the whole app frame disappears
and reappears. That's the "iframe-like" feeling flagged directly. Three of the four
(Outreach, AI Setup, Integrations) are being converted to native in-app tabs as part of this
same work session. **Help is being left as a standalone page deliberately** — a separate,
simple help/docs page is a normal, accepted pattern even in polished products, and converting
it adds no real value for the added engineering risk.

## What I'm NOT proposing (and why)

- **No visual redesign** (colors, fonts, layout grid) — the current dark-emerald-gold theme
  is coherent and on-brand; changing it for its own sake is exactly the kind of
  jargon-driven "modernization" that adds risk without adding value for this audience.
- **No new information architecture beyond grouping the existing 13 items** — SME owners
  need fewer decisions, not a cleverer taxonomy.
- **No dashboard framework rewrite** — the single-file-plus-Babel approach is unusual by
  2026 standards, but it works, loads fast, and a rewrite is a multi-week risk for zero
  user-visible benefit right now.

## Recommended implementation order

1. Nav grouping + label rename (#2, #3) — pure display change, lowest risk, do first.
2. Getting-Started checklist (#1) — highest value, moderate size, no backend changes needed.
3. (Separately, already in progress this session) native-tab conversions for #4.

## Not done in this pass

This document is the audit + plan. Implementing #1 and #2 above was not done in this same
session (time-boxed); flagging here so it isn't lost. Either is a good next task — #1
(grouping/renaming) is the faster win.
