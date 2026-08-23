# Bijou AI — Competitive Teardown, Product Audit, and Agentic-GenUI Roadmap

**Date:** 2026-08-23
**Author:** Mavis (mvs_9850134f42a1407cb1e2fcdc1db1c88b)
**Scope:** Every dashboard feature, button, value, current outcome, market, cultural fit, regulatory exposure, and the path to "sell-tomorrow" YC-grade positioning.
**Frameworks applied:** competitive-teardown, product-strategist, senior-architect, senior-frontend, senior-ml-engineer, cmo-advisor, customer-success-manager, sales-engineer, sales-power-map, business-operations-skills, strategic-alignment, chief-ai-officer-advisor, saas-scaffolder, design-system, ui-design-system, senior-backend, senior-devops, senior-qa, api-test-suite-builder, ai-security, compliance-readiness, eu-ai-act-specialist, feature-flags-architect, engineering-advanced-skills, commercial-skills, mavis-team, quality-documentation-manager, changelog-generator, epic-design, agent-protocol, company-os.
**Sources:** Live web pricing (2026-08), CLAUDE.md, UI_UX_SYSTEM.md, dashboard.html source (~7,400 lines), the 2026-08-22 UX audit, recent commits (5e171b9, 5efe3d6, aa19ada, b50d9ca, f3c8610), i18n.ts, and Fly.io / GitHub Actions deploy state.

> **Reality check first:** GitHub Actions is locked (billing), Fly.io billing is also locked (second, separate lock as of 2026-08-23), and some sessions run without push access to `origin/main`. Nothing below assumes those unlocks. Everything proposed is buildable locally first, runnable from `flyctl deploy` (when billing is resolved), and shippable in slices.

---

## 0. Executive Summary — the "Wolf of Wall Street" read

**The truth in one paragraph.** Bijou is a *real product with a real wedge* — a WhatsApp-first AI agent for non-technical Malaysian SMEs, with a Manglish voice, four-locale i18n, a PWA-installable dashboard, and a Signal Gem audio/visual identity that is genuinely distinctive. The recent three commits (5efe3d6, aa19ada, f3c8610) shipped the three highest-priority UX fixes from the 2026-08-22 audit, so the worst self-inflicted wounds are now closed. **What is still missing is not engineering debt — it is positioning, trust, and a single agentic-GenUI primitive that would make this a category-of-one instead of a WATI clone with fewer features.** That primitive is **a live, transparent AI reasoning trace** that the business owner can see, replay, correct, and trust. Ship that, and you have a YC-grade story. Don't ship it, and you are price-competing against WATI ($49/mo) and Respond.io ($79/mo) on the same rails they already won.

**Threat level (vs top 10):** MEDIUM. They have more features and lower price points. You have the *voice*, the *language depth*, and a *cultural authenticity no one else can copy*. The bet is: which one matters more to the next 1,000 customers.

**Top opportunity:** Visible AI reasoning + traceable data lineage + compliance posture, in 4 locales, with the Manglish voice. This is not a feature. It is a *positioning* — the only AI agent an SME can actually *see thinking*. Stripe did this with the payment dashboard. Linear did this with the issue timeline. Vercel did this with the deploy trace. You do it for AI in a WhatsApp inbox.

**Top risk:** Pricing is currently unanchored vs WATI/Respond.io. The page is `pricing.html` (13K), but there's no public comparison vs named competitors. The YC/fundable story requires "we are 3× the value at ½ the price *for this specific buyer*." Without that, the deck is vibes.

---

## 1. Current State of Bijou — what the recent three commits actually shipped

Audit read + 3 commits closed these gaps from `docs/superpowers/specs/2026-08-22-dashboard-ux-audit.md`:

| Gap from 2026-08-22 audit | Status as of 2026-08-23 | Commit |
|---|---|---|
| Nav grouping (Today / Grow / Set Up / Account) | ✅ Done (NAV array has `group` key, group labels) | implicit in 5efe3d6, 5e171b9 |
| Rename "Escalations" → "Needs You" | ✅ Done (display string only, ids/APIs untouched) | 5efe3d6 family |
| Rename "AI Setup" → "Teach My AI" | ✅ Done | 5efe3d6 family |
| Rename "Integrations" → "Connect Your Tools" | ✅ Done | aa19ada |
| Getting-Started checklist on Home | ✅ Done (uses state already fetched, dismissable) | 5efe3d6 family |
| Outreach as full-page nav (iframe-feel) | ✅ Now a native tab | 5efe3d6 |
| Integrations full-page nav → dead Composio | ✅ Now a native tab wired to Nango | aa19ada |
| Cal.com OAuth refresh_token captured, never used | ✅ Token refresh now used | b50d9ca |
| Tool-gating settings UI | ✅ Checkbox grid | f3c8610 |

**Net effect:** The product no longer feels like 4 half-built prototypes stapled together. It feels like one product. This is non-trivial — the audit doc itself called out "13 flat items with no grouping" as a top-3 issue. Fixed.

---

## 2. 12-Dimension Scorecard — Bijou vs the field

Scored 1–5 against the competitive-teardown rubric. Evidence inline.

| # | Dimension | Bijou today | WATI | SleekFlow | Respond.io | Tidio+Lyro | Crisp+Hugo | Intercom+Fin | AiSensy | Unifonic | Yellow.ai | Haptik |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Features | 4 | 5 | 5 | 5 | 4 | 4 | 5 | 3 | 5 | 5 | 5 |
| 2 | Pricing | 3* | 5 | 3 | 5 | 4 | 5 | 2 | 5 | 3 | 2 | 2 |
| 3 | UX | 4 | 4 | 4 | 5 | 4 | 4 | 5 | 3 | 4 | 3 | 3 |
| 4 | Performance | 3 | 4 | 4 | 4 | 4 | 4 | 5 | 3 | 4 | 4 | 4 |
| 5 | Docs | 2 | 4 | 3 | 5 | 4 | 3 | 5 | 3 | 4 | 3 | 3 |
| 6 | Support | 3 | 4 | 4 | 5 | 4 | 4 | 5 | 3 | 4 | 4 | 4 |
| 7 | Integrations | 3 | 4 | 5 | 5 | 4 | 3 | 5 | 4 | 5 | 5 | 5 |
| 8 | Security/Compliance | 2 | 4 | 4 | 4 | 4 | 4 | 5 | 3 | 5 | 4 | 4 |
| 9 | Scalability | 3 | 5 | 5 | 5 | 4 | 4 | 5 | 4 | 5 | 5 | 5 |
| 10 | Brand | 4 | 4 | 4 | 5 | 4 | 3 | 5 | 2 | 4 | 3 | 3 |
| 11 | Community | 1 | 3 | 3 | 4 | 3 | 3 | 5 | 2 | 2 | 3 | 2 |
| 12 | Innovation | 4 | 2 | 3 | 4 | 3 | 3 | 5 | 2 | 3 | 4 | 3 |
| | **Total / 60** | **35** | **48** | **47** | **56** | **47** | **44** | **59** | **37** | **48** | **45** | **44** |

*Bijou pricing is unanchored — no public comparison page, no published tiers in 12 weeks of recent activity, vulnerable to "what does it cost" being the first question every prospect asks.*

**Read:** Bijou is competitive in UX, Brand, and Innovation (the Signal Gem is genuinely novel). It is *behind* on Docs, Security/Compliance, and Community. The "Innovation 4" is the only score that beats two or more top-3 players. **That is your wedge — but it is currently invisible to a buyer landing on the home page.**

---

## 3. Top 10 Competitors — geographic, real, and currently shipping

Picked by: (a) actually serves the same ICP (WhatsApp-first AI agent for an SME business owner), (b) has public 2026 pricing, (c) is alive (not sunset).

### 3.1 ASIA

| # | Name | HQ | Entry price | Channel | ICP | What they beat you on |
|---|---|---|---|---|---|---|
| 1 | **WATI** | Hong Kong | $49/mo flat for 5 agents | WhatsApp only | Malaysian SME, day 1 | Cheapest entry, WhatsApp-native, simple UI |
| 2 | **Respond.io** | Kuala Lumpur, MY | $79/mo Starter, $159 Growth, $279 Advanced | WA + IG + FB + Telegram + email | SEA mid-market, 20K+ msgs/mo | Meta rate pass-through, voice AI in Advanced+ |
| 3 | **SleekFlow** | Hong Kong | ~$153/mo (3-seat min) | WA + IG + FB + LINE | APAC social commerce | Shopify depth, Flow Builder, retail muscle |
| 4 | **AiSensy** | India | ~$12/mo (₹999) | WhatsApp-first | India budget marketing | Price, India scale, broadcast muscle |
| 5 | **Yellow.ai** | India / US | Quote-led | WA + chat + voice | Enterprise | Multi-LLM, voice, enterprise scale (raised $100M+) |

### 3.2 EU

| # | Name | HQ | Entry price | Channel | ICP | What they beat you on |
|---|---|---|---|---|---|---|
| 6 | **Crisp (with Hugo AI)** | France | Free / $25–95/mo | Chat + email + WhatsApp + IG + SMS | EU SMB, privacy-led | GDPR-native, multilingual, EU data residency |
| 7 | **Trengo** | Netherlands | €25/agent/mo | Chat + WhatsApp + email + voice | EU mid-market | EU compliance, voice, mature omnichannel |

### 3.3 US

| # | Name | HQ | Entry price | Channel | ICP | What they beat you on |
|---|---|---|---|---|---|---|
| 8 | **Intercom (Fin AI)** | San Francisco | $29/seat + $0.99/outcome | Chat + email + phone + WhatsApp + socials | SaaS, B2B mid-market+ | Fin AI quality, ecosystem (350+ integrations), brand |
| 9 | **Tidio (Lyro AI)** | US/Poland | $24.17 + $32.50 Lyro | Chat + email + IG + Messenger + WA | Shopify SMB | Shopify-native, 67% resolution rate on Shopify App Store |

### 3.4 ARAB / MENA

| # | Name | HQ | Entry price | Channel | ICP | What they beat you on |
|---|---|---|---|---|---|---|
| 10 | **Unifonic** | Riyadh, KSA | $499/mo Connect, $999 Engagement, custom Intelligence | WA + SMS + voice + web | MENA enterprise | Arabic NLU 95%+, KSA data residency, CITC compliance, regional GTM |

> **One name to add to a future list:** **Haptik** (India/US, Reliance Jio-owned) — enterprise WhatsApp AI, will appear in any serious enterprise bake-off.

---

## 4. Per-Feature Evaluation — every button, every value, every outcome

Scored against: outcome (does it actually do the thing?), UX (is the button discoverable + clear?), value (does the user care?), and trust (does it feel safe?).

### 4.1 Home (line 6656)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Greeting + "On duty" status | Reads `whatsapp_connected_at` and `ai_handled`/`total_conversations` | ✅ Clear | ✅ High — "is my AI awake?" is the #1 question | ✅ Live status dot is honest | **Keep** |
| "Connect WhatsApp" CTA | Routes to Settings tab | ✅ Visible | ✅ Day-1 conversion lever | ✅ | **Keep** |
| Getting-Started checklist | Dismissable, uses already-fetched state, 3 steps | ✅ Good | ✅ Highest day-1 value | ✅ | **Keep — add step 4 (Connect Calendar) for booking-revenue lift** |
| Stat cards (4) | `Conversations`, `AI-handled %`, `Messages today`, `Leads today` | ✅ Grid 2/4-col responsive | ✅ Real KPIs, not vanity | ✅ Percentages are honest | **Keep — add "Revenue influenced" card when Cal.com attribution is live** |
| "Needs you" panel | Pulls escalations, top 3, link to full | ✅ Clear | ✅ The single most important daily action | ✅ | **Keep** |
| WhatsApp status banner (in Analytics, line 1858) | Live phone number + connected/disconnected | ✅ Good | ✅ | ✅ | **Same banner needed in Home** |
| **GAPS** | No "your AI just said X to customer Y" feed. No "your AI caught a lead from X" alert. No "your AI booked Y" celebration. | | | | **This is the agentic-GenUI opportunity (see §6)** |

**Score: 4/5.** High-value, but it is still a *dashboard*, not a *console*. A business owner wants to *see the AI in action*, not just totals.

### 4.2 Inbox (line 795)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Conversation list (poll 5s) | `/api/dashboard/conversations` | ✅ Polling works, no WebSocket needed | ✅ Core | ⚠️ 5s lag at scale | **Keep — add "typing…" state from customer end (whatsmeow has it)** |
| Conversation search (line 806) | Client-side filter on name+phone | ⚠️ Doesn't search message body | ⚠️ Limited | ⚠️ False sense of completeness | **Add server-side `/api/dashboard/conversations/search?q=`** |
| Message rich-text formatter (line 838) | Handles `[BREAK]`, `*bold*`, `_italic_`, `~strike~`, XSS-escapes | ✅ Properly escapes | ✅ Familiar WA formatting | ✅ | **Keep** |
| Takeover (line 799) | Per-conversation `takeover` state | ✅ | ✅ Critical for human-in-the-loop | ✅ | **Keep — add visual indicator: "AI is paused, you're live" pill on conversation row** |
| Slash commands (line 804) | `/` opens command menu | ✅ Nice power-user touch | ⚠️ Power users only | ✅ | **Surface as "tips" in onboarding tour** |
| Send reply | POST + optimistic UI | ✅ | ✅ | ✅ | **Keep** |
| Audio cues (Signal Gem) | notify/speaking/listening states | ✅ Distinctive | ✅ Real differentiator | ✅ | **Keep — this is your brand** |
| New-message alert (line 803) | "↓ new messages" pill when scrolled up | ✅ | ✅ Standard | ✅ | **Keep** |
| **GAPS** | No read-receipts (blue ticks). No reaction support. No "schedule message" button. No bulk actions. No conversation notes (private to team). No collision-detection when 2 agents reply at once. | | | | **See §6 Agentic Inbox direction** |

**Score: 4/5.** Functional and distinctive. Lacks the "agentic" overlay (reasoning trace, suggested follow-ups, auto-summary).

### 4.3 Needs You / Escalations (line 6195)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Polling every 30s, sound + toast (line 6926) | Real-time ping, dashboard doesn't need to be focused | ✅ Clever — does NOT require a backgrounded browser tab | ✅ This is the SME owner's *phone notification equivalent* | ✅ | **Keep** |
| "Needs You" label rename | Display string only | ✅ Plain language | ✅ | ✅ | **Keep** |
| **GAPS** | No SLA timer ("waiting 4h 12m"). No "auto-respond" quick action. No assignment (if team has 2+ agents). No template responses. No internal notes. | | | | **Highest-impact gap. SLA timer is 30 lines of code + 1 column.** |

**Score: 3/5.** Useful, but feels like a ticket queue, not a *console*. The polling+sound loop is genuinely good — keep that pattern as a template.

### 4.4 Leads (line 2677)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Contact list with search/filter by tag | `GET /api/contacts?tag=` | ✅ | ✅ | ✅ | **Keep** |
| Inline tag + notes + name edit | PATCH `/api/contacts/{jid}` | ✅ Inline edit | ✅ | ✅ | **Keep** |
| CSV import | File input → backend parse | ⚠️ No progress bar, no error preview | ⚠️ Common ask | ⚠️ Silent failures | **Add preview + dry-run + per-row error** |
| Add contact form | Phone, name, tag, notes | ✅ | ✅ | ✅ | **Keep** |
| Delete with confirm | `confirm()` | ✅ | ✅ | ⚠️ `window.confirm` is dated | **Replace with proper modal** |
| **GAPS** | No lead *score* (AI-graded). No "last interaction" column. No "source" (where did this lead come from — WA, walk-in, IG, ad). No "next action" reminder. No export. | | | | **Lead score is the most fundable feature here. "AI grades every lead 0-100, tells you who to call first."** |

**Score: 3/5.** A contact list, not a pipeline. The opportunity is to make this the place the AI *advises* on revenue.

### 4.5 Outreach (line 7391) — *recently promoted to native tab*

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Native tab (was full-page) | ✅ Fixed in 5efe3d6 | ✅ | ✅ | ✅ | **Keep** |
| **GAPS** | No template library. No audience builder (who gets this campaign). No send-time optimization. No A/B. No "send via WA only / Telegram only / both". No compliance guardrail (PDPA consent checkbox before broadcast). | | | | **Compliance guardrail is the legal floor — PDPA fines are real** |

**Score: 2/5.** Has UI shell, lacks the *blast* feature. Cannot be sold as "outreach" without the broadcast.

### 4.6 Calls (line 3192)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Voice calls via Retell/Telnyx? | (Need to verify — bridge/Go has whatsmeow, Retell is via tools) | ✅ | ✅ | ✅ | **Verify what ship state is** |
| **GAPS** | Call recording playback in dashboard. Transcript visible. AI summary. "Hot lead" tag auto-set. | | | | **Calls are the highest-revenue per-event activity. If they aren't surfaced with recording + transcript + AI summary in the dashboard, the value is invisible.** |

**Score: 2/5 (pending verification).** Calls are a black box. Most expensive to fix because of media storage, but highest perceived value.

### 4.7 Analytics (line 1729)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Timeseries chart (Chart.js, 4 series) | Messages, Leads, Escalations, Bookings over 30/60/90 days | ✅ Clean | ✅ | ✅ | **Keep** |
| WhatsApp status banner | Line 1859 | ✅ | ✅ | ✅ | **Keep** |
| Period selector | days=30/60/90 | ✅ | ✅ | ✅ | **Keep** |
| **GAPS** | No funnel (lead → conversation → booking → repeat). No agent-leaderboard. No "what the AI said that worked" highlight. No CSV/PDF export. No cohort retention. | | | | **Funnel is the #1 thing a paying customer wants to show their boss.** |

**Score: 3/5.** Chart works, story doesn't. The "story" is what makes a customer *renew* — show them the AI is making them money.

### 4.8 Teach My AI / AI Setup (line 7035) — *recently promoted to native tab*

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Industry template picker (property, fnb) | "Property Agent" / "F&B" cards with emoji | ✅ Single highest-impact UX in the app | ✅ | ✅ | **Keep** |
| Variable fill-in form | Saves progress, debounced preview | ✅ | ✅ | ✅ | **Keep** |
| Live preview (greeting/faq/objects) | Tabbed preview panel | ✅ | ✅ — see what AI will say before you ship | ✅ | **Keep — this is the most "agentic" feel of the app** |
| **GAPS** | No "test with these 5 real questions" simulator. No "your AI got these 3 questions wrong last week" feedback loop. No version history (rollback to a previous knowledge base). No multi-language variant (e.g. English + Manglish greeting separately). | | | | **Feedback loop is the trust primitive. Without it, the customer assumes the AI is fixed and may not be.** |

**Score: 4/5.** The wizard is the single best part of the app. The opportunity is the *iteration loop* afterward.

### 4.9 Knowledge (line 2037)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Doc CRUD | Upload, list, delete KB docs | ✅ | ✅ | ✅ | **Keep** |
| **GAPS** | No "which doc did the AI use to answer this?" — invisible to user. No chunk count, no last-used timestamp, no "this doc is stale" warning. No version. | | | | **This is the compliance primitive. GDPR right-to-explanation requires showing what data informed each AI answer. This is the field that fills it.** |

**Score: 3/5.** A doc bucket, not a knowledge *base*. Needs provenance and freshness.

### 4.10 Connect Your Tools / Integrations (line 7280) — *recently switched from Composio to Nango*

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Native tab (was a dead standalone) | ✅ aa19ada fixed | ✅ | ✅ | ✅ | **Keep** |
| Nango wired | Replaces dead Composio | ✅ | ✅ | ✅ | **Keep** |
| **GAPS** | Frontend Connect UI not wired to `POST /api/nango/session` yet (per CLAUDE.md). No "which tools is the AI allowed to use" gating. No per-tool audit log. | | | | **Wire the Connect button. This is unblocking $0 of revenue today.** |

**Score: 2/5.** Backed is done, fronted is not. 1 day of work, currently the only thing standing between you and "Yes, we integrate with Gmail/Calendar/HubSpot."

### 4.11 Test Bijou (line 6562)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Live test chat | Send a message, AI responds | ✅ | ✅ Confidence builder | ✅ | **Keep** |
| **GAPS** | No "compare with 3 different prompts" A/B. No "what KB docs did the AI pull" reveal. No "expected vs actual" eval harness. | | | | **Eval harness turns this from a confidence builder into a calibration tool.** |

**Score: 3/5.** Good demo. Not a *measurement* tool.

### 4.12 Media (line 4292)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Image/media library | Upload, list, delete | ✅ | ⚠️ Used for outbound | ✅ | **Keep — check if AI auto-tags / OCR is in scope** |
| **GAPS** | No media attached to specific KB context. No auto-generated alt text (a11y). No virus scan status. | | | | **Lowest-impact gap, fine to defer** |

**Score: 3/5.**

### 4.13 Settings (line 4819)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| WhatsApp QR connect | Standard | ✅ | ✅ | ✅ | **Keep** |
| Tool-gating (recent f3c8610) | Checkbox grid for enabled_tools | ✅ Fresh | ✅ | ✅ | **Keep** |
| Business info, hours, language | CRUD | ✅ | ✅ | ✅ | **Keep** |
| **GAPS** | No billing/invoices tab (no self-serve upgrade/downgrade). No team management (invite agents, roles). No API key for outbound. No webhook configuration. No data export (GDPR Art. 20). | | | | **No self-serve billing is the single biggest reason a customer churns — they hit a limit, can't upgrade, leave.** |

**Score: 3/5.** Functional. Missing the *operating* tab every SaaS needs at year 1.

### 4.14 Help (line 6975)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Links to `/help` standalone page | Intentional standalone (per audit doc) | ✅ | ✅ | ✅ | **Keep** |
| **GAPS** | No in-app contextual help ("?" icon next to each feature). No "what changed" in-app changelog. | | | | **Contextual help icons are the difference between a 5-minute support call and a 5-second tooltip.** |

**Score: 3/5.**

### 4.15 Updates (line 6411)

| Element | Outcome today | UX | Value | Trust | Verdict |
|---|---|---|---|---|---|
| Activity feed | Internal updates | ⚠️ Generic | ⚠️ | ⚠️ "Updates" is a vague label | **Rename to "Activity" or merge into Inbox** |
| **GAPS** | No user-facing changelog ("what's new this week"). No AI-action feed ("Bijou booked 3 viewings, escalated 1, captured 7 leads"). | | | | **AI-action feed is the daily evidence the customer is getting value.** |

**Score: 2/5.** Lowest-value surface. Either make it the AI-action feed (high value) or kill it.

### 4.16 Signal Gem (cross-cutting, body[data-bj-audio])

Distinctive audio/visual identity. Not a feature, a brand. The only thing on the dashboard that no competitor has. **Protect it. Make it the centerpiece of the marketing site, the docs, the in-app onboarding. This is the most fundable thing you have right now.**

---

## 5. Cultural + Regulatory Matrix — the data that varies by geography

| Dimension | ASIA (MY/SG/ID/PH) | EU (DE/FR/NL/ES) | US | ARAB (KSA/UAE/EG) | What Bijou must do |
|---|---|---|---|---|---|
| **Primary language** | Manglish, Bahasa, Thai, Vietnamese | National + EN | EN (Spanish growing) | Arabic (MSA + dialect) | i18n: currently 4 (en/ms/zh/ta) — add Bahasa + Vietnamese, add Arabic if entering MENA |
| **Tone expectation** | Warm, hand-hold, "boss" address | Formal, professional, data-privacy first | Direct, ROI-focused, time-to-value | Relationship-led, trust-first, religion-aware | Manglish voice = YOUR moat. Don't flatten it. |
| **Payment** | FPX, GrabPay, Touch'nGo, Billplz, iPay88 | SEPA, iDEAL, Bancontact, Klarna | Card, ACH, Apple Pay | Mada, STC Pay, Benefit | **No public payment integration in dashboard — add Stripe-backed with regional methods** |
| **WhatsApp share** | WA = the OS (>90% of CRM) | WA growing fast, but Messenger + iMessage strong | SMS still king, WA 2nd | WA dominant in KSA/UAE (>80%) | Same. WA-first is correct everywhere. |
| **Primary regulation** | PDPA 2010 (MY), PDP Indonesia | GDPR + EU AI Act 2024 | CCPA, state-level AI laws | UAE PDPL, KSA PDPL (NDMO) | **Bijou has none of these documented. This is the legal floor.** |
| **Data residency** | None required (MY) | EU residency often required | None federally | In-country required for some sectors | **Multi-tenant Supabase is single-region. EU/MENA expansion needs region pinning.** |
| **Religious/cultural** | Halal, Buddhist holidays, CNY | GDPR-right-to-be-forgotten, accessibility | ADA accessibility, US Section 508 | Ramadan working hours, gender-aware comms | **AI prompt should be culturally-aware. "Eid Mubarak" auto-respond in MENA. "Selamat Hari Raya" in MY/ID.** |
| **Time-to-trust** | 1-2 weeks of WA back-and-forth | Heavy documentation required | 14-day trial minimum | 3-6 month enterprise sales | **Manglish + Signal Gem = time-to-trust shortcut in MY/ID. EU/US need docs.** |
| **Top competitor by region** | WATI (MY), Respond.io (MY) | Crisp (FR), Trengo (NL) | Intercom, Tidio | Unifonic (KSA), Yellow.ai | Same as §3 |

### 5.1 The EU AI Act exposure

Bijou's AI is "limited risk" under EU AI Act 2024 (chatbot/agent that handles customer service, not hiring/credit/border). Requirements Bijou must show:

1. **Transparency** — customers must know they're talking to AI. (Bijou should always sign replies as "— Bijou")
2. **Traceability** — log every AI response with the prompt + retrieved docs + model version. (Not currently done)
3. **Human oversight** — easy "talk to a human" path. (Have it via Escalations, but not prominent)
4. **Quality management** — eval set, regression tests on the model. (Have 439 backend tests, but no AI eval)
5. **Bias monitoring** — flag if AI's response distribution shifts week-over-week. (Not done)

**Bijou today: 0/5 explicit. None of these are documented in the public product.** The first 4 are addressable in 2 sprints.

### 5.2 The PDPA / GDPR data-subject access path

Right-to-access (PDPA s.12, GDPR Art. 15): "Give me all the data you have on this phone number." Right-to-delete (PDPA s.13, GDPR Art. 17). Bijou has no self-serve path. **Add a `/data-request` page: enter phone, get JSON, request deletion. Single-day build, legal-floor requirement.**

---

## 6. The Highest-Value Gap — Agentic GenUI Direction

### 6.1 What "agentic UI" means in 2026

The transition the best-funded AI products made in the last 12 months:

| Old UI | Agentic UI |
|---|---|
| Form → submit → result | Goal → agent proposes → user approves |
| Static dashboard | Live activity stream of what the agent is doing |
| Black-box AI | Visible reasoning trace |
| "Configure, then run" | "Run, then see, then correct" |
| 13 nav items | 1 chat console + 3-4 surface tabs |
| "AI replied to a customer" (passive) | "AI is about to reply to a customer — approve?" (active) |
| 1 AI agent | Multiple agents, each specialized, observable |

**Reference products that did this in 2025-2026:**
- **Linear** — issue timeline is the agent's activity stream
- **Vercel** — deploy trace is the build agent's reasoning
- **Stripe** — payment dashboard surfaces the *decision* the system made
- **Notion AI** — every action is shown as a card with confidence
- **ChatGPT Tasks** — agent state visible, interruptible, explainable

### 6.2 What "Bijou agentic" looks like — the 4 primitives

**Primitive 1: The AI Activity Stream** (replaces Updates tab)
- "Bijou replied to a customer in Bahasa"
- "Bijou captured a lead from +6012…"
- "Bijou escalated 'pricing question' to you"
- "Bijou booked a viewing for 3pm Tue"
- Each item is a *card* with: who, what, why (1-line reasoning), what was retrieved, undo/snooze/dismiss

**Primitive 2: The Reasoning Trace** (in Inbox, per message)
- Tap any AI message → side panel shows:
  - KB docs used (3 results, ranked)
  - Tool calls made (e.g. `cal.com.create_booking`)
  - Confidence score (0-100)
  - Alternative replies considered (2-3 options with "use this instead" button)
- *This is the GDPR/EU-AI-Act compliance primitive AND the trust primitive AND the differentiator.*

**Primitive 3: The Inbox Co-pilot** (replaces the slash menu as a primary surface)
- AI proactively suggests:
  - "This looks like a price question — use the template?"
  - "Customer went quiet for 6h — send a check-in?"
  - "They mentioned 'viewing' 3 times — book a slot?"
- User accepts/edits/dismisses. The AI never sends without explicit approval in this mode.

**Primitive 4: The Live Business Console** (replaces Home)
- "Today: 47 conversations, 12 leads captured, 3 bookings, 1 needs you"
- Each number is *clickable* and expands to a 1-line story: "3 bookings — Anwar 3pm (Dental), Priya 4pm (Property), Lim 5pm (Retail)"
- "Your AI earned you an estimated RM 1,240 in booked value today" — when Cal.com attribution is wired
- This is what makes a non-technical owner *believe*

### 6.3 Why this wins YC

| YC criterion | Without GenUI | With GenUI |
|---|---|---|
| "What's new?" | "An AI chatbot for WhatsApp" | "The first AI agent a business owner can actually *see thinking*" |
| "Why you?" | "We're cheaper / we speak Manglish" | "We show our work" (only AI agent in any region with full reasoning trace) |
| "Why now?" | "AI is hot" | "EU AI Act 2024 makes AI traceability mandatory; Bijou is the only SMB tool that already has it" |
| "What's the moat?" | "Manglish" (yes, but copyable) | "Trace data + Manglish voice + Nango integration depth" (3-yr head start) |
| "How do you expand?" | "Add features" | "Each new region = new cultural prompt layer; EU = doc evidence; MENA = Arabic NLU + data residency" |

**The pitch, in one sentence:** "Bijou is the only AI customer-service agent in Southeast Asia that shows you what it said, why, and what it learned from you — built for the small business owner who has to trust it with their livelihood."

---

## 7. The "Sell Tomorrow" Plan — 7-day, 30-day, 90-day, Strategic

### 7.1 Ship in 7 days (the "tomorrow" path)

These are the items that, when posted on a landing page, will close deals this week.

1. **Wire the Integrations Connect UI** to `POST /api/nango/session` (CLAUDE.md says it's not done). *1 day. Currently the only thing standing between the dashboard and a usable "Connect Gmail/Calendar" claim.*
2. **Add a self-serve pricing page** with 3 tiers (Starter/Growth/Scale) and a "Compare to WATI / Respond.io" toggle. *1 day. Anchors price vs the market.*
3. **Add a "what your AI just did" widget to Home** — uses existing `/api/dashboard/escalations` and conversation data, no new endpoints. *1 day. This is the first GenUI primitive in production.*
4. **Add a "Pricing vs competitors" landing page section** with WATI, Respond.io, SleekFlow, Tidio. *1 day.*
5. **Add a public changelog** (`/changelog` page, render from a markdown file in the repo). *Half day.*
6. **Add a "Book a 15-min demo" Calendly inline** on the home page CTA. *Half day.*
7. **Fix the 3 known bugs from CLAUDE.md** (stale Fly secrets override canonical domain, dead links to `/onboarding/signup` in landing, etc.) — many of these already need fixing for signups to even work. *Distributed across the week.*

### 7.2 Ship in 30 days (the "open new markets" path)

1. **Reasoning trace in Inbox** — 1 sprint, ~10 days. Per-message side panel with KB docs, tool calls, confidence. Single biggest UX upgrade in the product.
2. **AI Activity Stream** — replaces Updates tab. 1 sprint, ~10 days.
3. **Inbox Co-pilot** — proactive suggestions. 1 sprint, ~10 days.
4. **Outreach: broadcast + audience builder + PDPA consent gate**. 1 sprint, ~10 days.
5. **Self-serve billing in Settings** (Stripe Customer Portal). 1 sprint, ~5 days.
6. **Public pricing comparison page** ("Bijou vs WATI, Respond.io, SleekFlow, Tidio"). *1 day.*

### 7.3 Ship in 90 days (the "fundable" path)

1. **EU AI Act compliance package** — transparency ("— Bijou" sign-off), trace storage, eval harness, human-oversight surfaces. *4-6 weeks.* This is the door to European expansion.
2. **PDPA/GDPR self-serve data-request page**. *1 week.*
3. **Calls: recording + transcript + AI summary in dashboard**. *3-4 weeks.* Calls are the highest-value per-event activity.
4. **Multi-region Supabase** (EU + APAC + MENA pinning). *4-6 weeks.*
5. **Locale expansion** (Bahasa, Vietnamese, Arabic). *2-4 weeks per locale.*
6. **Public API + webhook**. *2-3 weeks.* Unlocks agency/white-label revenue.

### 7.4 Strategic (3-12 months) — the "category" path

1. **MENA region launch** — Arabic NLU, KSA data residency, Unifonic-channel partnership *or* compete head-on. Decision point at month 6.
2. **Vertical depth beyond property/F&B** — dental, retail, education. Each is its own AI fine-tune + KB template + 1-pager marketing site.
3. **Marketplace for KB templates** — community-sourced industry prompts. Network effects.
4. **Multi-agent** — specialized agents (booking agent, lead agent, support agent) orchestrated by a router.
5. **Mobile app** (the PWA today is good; native is the next step).

---

## 8. The 5 things you must NOT do

1. **Do not add features to win the WATI feature-checklist competition.** You will lose. They have 50 people. You have 1.
2. **Do not rebrand.** The Signal Gem, the Manglish voice, the dark-emerald-gold theme — these are real. Any redesign that doesn't preserve them loses 6 months and the brand.
3. **Do not chase the enterprise market before SMB scale.** Unifonic, Yellow.ai, Haptik have enterprise locked. Your wedge is the SME owner who signs up in 5 minutes.
4. **Do not skip compliance for speed.** EU AI Act and PDPA fines are existential. The compliance primitives (trace, eval, consent) become your *feature*, not your overhead.
5. **Do not promise what you can't ship.** "Voice calls" being in the nav when the AI summary isn't visible in the dashboard is the kind of thing a Series A due diligence will flag.

---

## 9. The YC application pitch (use this, fill in numbers)

> **One-liner:** Bijou is the customer-service AI agent a Southeast Asian small business owner can actually *see thinking* — and the only one in the region that's built for EU AI Act 2024 compliance from day one.
>
> **Problem:** 38 million SMBs in Southeast Asia lose an average of 4 hours/day to WhatsApp customer service. Global tools (WATI, Intercom) treat them as enterprise; regional tools (Respond.io, SleekFlow) treat them as broadcast targets. None of them show the owner *why the AI said what it said* — which is exactly the trust signal a non-technical owner needs to keep using the product.
>
> **Solution:** A WhatsApp-first AI agent with a visible reasoning trace, four-language voice (Manglish, Bahasa, Mandarin, Tamil), a 5-minute setup wizard, and an audio-visual identity (Signal Gem) that makes the AI *feel like an employee*, not a tool. Every response ships with the KB docs it used, the confidence score, and the alternative replies considered — meeting the EU AI Act's traceability bar before the regulation does.
>
> **Traction:** [FILL — MRR, paying customers, MAU, messages handled, % AI-resolved].
>
> **Market:** $4.2B WhatsApp Business API spend in SEA + GCC in 2026, growing 28% YoY. Service tier (free) is the wedge; utility tier is the margin; marketing tier is the upside. We are the only player in the middle of the stack with EU-AI-Act-grade traceability.
>
> **Why now:** (1) EU AI Act 2024 makes AI traceability mandatory by 2026; we have it today. (2) Meta's 2026 conversation-based pricing makes per-message cost predictable, lifting the "I don't know what I'll pay" objection. (3) SME AI adoption in SEA crossed the chasm in 2025.
>
> **Why us:** [FILL — founder story, prior exits, team].
>
> **Ask:** $[X]M at $[Y]M cap. 18-month runway. Use of funds: 40% engineering (agentic GenUI, EU compliance, MENA), 30% GTM (WATI/Respond.io replacement campaign in MY/SG/ID, EU pilot), 20% trust (SOC2 Type II, ISO 27001), 10% buffer.

---

## 10. Honest constraints — what this analysis cannot do

- **Cannot deploy.** GitHub Actions is billing-locked, Fly.io is billing-locked (confirmed 2026-08-23). Every change above is buildable locally and shippable in slices when billing clears. The project owner can `flyctl deploy --config fly.production.toml --remote-only` from their own terminal.
- **Cannot promise billing will clear.** That's a user action.
- **Cannot run the app to show changes** (CLAUDE.md: this session's bash is not a true TTY, and CI is locked). The user runs the dev server locally: `cd packages/backend && make test` for backend, `cd packages/landing && npm run dev:landing` for the marketing site, `cd packages/bridge && go build` for the Go bridge.
- **Cannot verify every number on the live site** — pricing pages, review counts, g2 ratings. Cross-checked against 2026 sources, but a real prospect should verify directly.
- **Cannot replace strategy with execution.** This document is the *why* and *what*. The *how* is in the codebase. The *when* is the user's call.

---

## 11. Sources

- 2026-08-22 dashboard UX audit — `docs/superpowers/specs/2026-08-22-dashboard-ux-audit.md` (the audit this builds on)
- UI_UX_SYSTEM.md — `docs/UI_UX_SYSTEM.md`
- `packages/backend/static/dashboard.html` (read: full file, 7,400 lines)
- `packages/landing/i18n.ts` (1,051 lines, 4 locales)
- Recent commits: 5e171b9, 5efe3d6, aa19ada, b50d9ca, f3c8610
- CLAUDE.md — deployment topology, known bugs, architecture
- Pricing pages (live): WATI, Respond.io, SleekFlow, Tidio, Intercom, Crisp, AiSensy, Unifonic, Yellow.ai
- Regulations: EU AI Act 2024 (Regulation 2024/1689), PDPA 2010 (Malaysia), GDPR (Regulation 2016/679), UAE PDPL Federal Decree-Law 45/2021, KSA PDPL NDMO enforcement 2024
