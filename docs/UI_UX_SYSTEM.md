# UI_UX_SYSTEM.md — screens, blocks, fields, and API events

**Status:** verified against code 2026-08-10. **[GAP]** = does not exist.
**[PROPOSED]** = design recommendation, not built.
Companion: [`USER_JOURNEY.md`](./USER_JOURNEY.md).

---

## 1. Two design systems (this is a real problem)

| | Marketing (`packages/landing`) | Product (`packages/backend/static`) |
|---|---|---|
| Build | Vite + React 19 | none — hand-written HTML, in-browser JSX |
| CSS | Tailwind **via CDN**, config inline in `index.html` | Tailwind CDN, **its own** token set |
| Surface | `#0a0f0d` dark green-black | `#0a0f0e` main, `#0c1211` sidebar, `#12181a` card |
| Type | Inter + Optima display | Plus Jakarta Sans |
| Components | hand-rolled + `lucide-react` + `framer-motion` | hand-rolled |

They share brand intent but no code and no tokens. A change to one does not
propagate. **[PROPOSED]** extract the token block into one `brand-tokens.css`
imported by both — `index.html:326-327` already instructs mirroring it into
`dashboard.html`, which is a manual process nobody performs.

### Canonical tokens (`index.html:236-264`, `:299-328`)

| Token | Value | Use |
|---|---|---|
| `--bg-deep` | `#072A1F` | page ground |
| `--bg-surface` | `#0B3B2E` | raised surface |
| `--bg-elevated` | `#093025` | cards |
| `gold.400` | `#E3B457` | primary accent, CTAs |
| `emerald.500` | `#10b981` | success, live states |
| `deep-green.500` | `#0B3B2E` | brand ground |
| `--text-primary` | `#F7F4EC` (cream) | body copy |
| `--text-secondary` | `#a0a8a3` | supporting |
| `--text-muted` | `#6b7370` | meta |

Utilities: `.glass-panel`, `.glass-panel-3d`, `.glossy-pill{,-emerald,-gold}`,
`.text-gradient-{premium,emerald,gold}`, `.text-glow{,-strong}`, `.touch-target`,
`.pb-safe` / `.pt-safe`.

> **Known inconsistency:** `App.tsx:92` hardcodes `#030810` (blue-black), in
> neither the Tailwind palette nor the CSS variables, overriding the `--bg-deep`
> green. `LanguageSwitcher.tsx:53-55` uses `#0A1E1C` and `#C9A961`, also
> undefined. Fix these before extracting tokens or the drift is baked in.

---

## 2. Marketing site

Single scroll page, no router. Only hash target: `#/admin/outreach-queue`.

```
┌──────────────────────────────────────────────────────────────┐
│ NAVBAR (sticky)                                              │
│ [BijouLogo]      Features  Roadmap  Demo   [EN v] [ CTA ]    │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ HERO                                                         │
│  ┌────────────────────────┐  ┌─────────────────────────────┐ │
│  │ > badge                │  │  WhatsApp chat simulation   │ │
│  │ Split headline         │  │  (4 canned messages)        │ │
│  │ Subtitle               │  ├─────────────────────────────┤ │
│  │ [Primary CTA][Second.] │  │  Monthly Savings RM2,700+   │ │
│  │ PDPA · trust row       │  └─────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
   v Pain · Story(2am) · Story(clinic) · Features · Comparison
   v ViralPillars(3 tabs) · RevenueCalculator · Pricing
   v VoiceComingSoon · HowItWorks · Playbooks · CaseStudies
┌──────────────────────────────────────────────────────────────┐
│ DEMO CHAT  #demo          <- the conversion asset            │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ transcript (user right / Bijou left, Manglish)           │ │
│ │ [ type a message…                              ] [Send]  │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
   v FAQ(accordion) · FinalCTA(+LeadCaptureForm) · Footer
[floating WhatsApp bubble]        [WaitlistStrip: email + Join]
```

| Block | Inputs | Action | API event |
|---|---|---|---|
| Navbar CTA | — | `openModal('signup','navbar')` | — |
| DemoChat | free text | send | `POST /api/chat` → always 200 |
| Pricing | monthly/yearly toggle | — | `GET /api/spots` (scarcity badge) |
| RevenueCalculator | sliders | — | client-only |
| WaitlistStrip | `email` | join | `POST /api/leads` |
| VoiceComingSoon | `email` | join | `POST /api/voice-waitlist` |
| SlideDeckModal | `name`, `email*` | send deck | `POST /api/slide-deck` |
| LeadCaptureForm | `name*`, `email*`, `phone`, `company`, `industry`, `marketing_consent` | submit | `POST /api/leads` |
| Footer forms ×3 | contact fields | submit | **none** — builds a `mailto:` and sets `window.location.href` |

### OnboardingModal — the signup surface

```
┌─────────────── Get Bijou for your business ───────────┐
│  [ Business name *                                  ] │
│  [ Email address *                                  ] │
│  [ WhatsApp number (optional)                       ] │
│  [ Industry                                       v ] │
│  [ Preferred demo time *      ]  <- demo mode only    │
│                                                       │
│              [    Get Started    ]                    │
│  PDPA Compliant · No credit card                      │
└───────────────────────────────────────────────────────┘
```
Submit → `POST /api/leads` (all three modes). Errors render one of four panels
(duplicate / validation / server / network), each with a WhatsApp escape hatch.

> **[GAP]** Success is not an account — it shows "Check your email" and links to
> `app.mybijou.xyz/signup`. See `USER_JOURNEY.md` § Stage 2.

### `#/admin/outreach-queue`

Founder-only review queue. **Now secret-gated** (2026-08-10) — prompts once per
tab, held in `sessionStorage`, sent as `X-Cron-Secret`.

| Block | Action | API event |
|---|---|---|
| Header | toggle pending/approved, refresh | `GET /api/agents?action=review-queue&status=…` |
| Item card | Approve / Reject / Mark sent | `POST /api/agents?action=review-queue` `{id, action, reason?}` |

> **[GAP]** Reject reason uses `window.prompt()`. No pagination.

---

## 3. Product — dashboard shell

```
┌────────────┬─────────────────────────────────────────────────┐
│ SIDEBAR    │ TOPBAR: [page title]        [tenant v] [avatar] │
│ #0c1211    ├─────────────────────────────────────────────────┤
│            │                                                 │
│ > Home     │              VIEWPORT                           │
│ > Inbox    │              #0a0f0e                            │
│ > Escalat. │              cards #12181a                      │
│ > Updates  │                                                 │
│ > Analytics│                                                 │
│ > Knowledge│                                                 │
│ > Test     │                                                 │
│ > Media    │                                                 │
│ > Leads    │                                                 │
│ > Calls    │                                                 │
│ > Outreach │                                                 │
│ > AI Setup │                                                 │
│ > Settings │                                                 │
│ > Help     │                                                 │
└────────────┴─────────────────────────────────────────────────┘
```
Auth: JWT in `localStorage` (`access_token`, `refresh_token`, `tenant_id`),
magic-link `?token=` fallback. 401 → `POST /api/auth/refresh` → retry → else
`/login`.

### Home
```
┌─ Today ─────────────────────────────────────────────┐
│ [Messages] [Escalations] [Avg response] [Resolved]  │
├─────────────────────────────────────────────────────┤
│ Volume — last 7 days (line)                         │
├──────────────────────────┬──────────────────────────┤
│ Needs you now (list)     │ WhatsApp: * Connected    │
└──────────────────────────┴──────────────────────────┘
```
`GET /api/dashboard/stats` · `GET /analytics/timeseries` · `GET /whatsapp/status`

### Inbox
```
┌── conversations ──┬───────── thread ──────────────────┐
│ [ search        ] │ Ali · +60… · * Bijou handling     │
│ * Ali      2m     │ ───────────────────────────────── │
│   Siti     1h     │  messages…                        │
│                   │ [ reply…                 ] [Send] │
│                   │ [Take over] [Resolve] [Blacklist] │
└───────────────────┴───────────────────────────────────┘
```
`GET /conversations` · `POST /send-message {conversation_id, text}` ·
`POST /takeover {conversation_id}` · `POST /blacklist`

### Escalations
List of what Bijou couldn't answer: customer, question, reason, age, and
[Reply] [Resolve] **[Add to Knowledge]**. `GET /escalations`

> **[PROPOSED]** *Add to Knowledge* should open an inline drawer pre-filled with
> the question, writing straight to `POST /knowledge`. Today the operator must
> leave for the Knowledge page and retype it — the single highest-value UX fix
> in the product, because it gates the learning loop that makes Bijou improve.

### Knowledge
Search + list of Q/A and documents; add/edit modal (`question`, `answer`,
`tags`, `vertical`), upload (PDF/DOCX/TXT). `GET|POST|PUT|DELETE /knowledge`

### Leads · Calls · Media · Analytics · Outreach
`GET /api/contacts` (+ CSV export) · `GET /api/call-booking/*` ·
`GET /api/media` · `GET /analytics/timeseries` · `/outreach`

### Settings
Business profile (`name`, `vertical`, `hours`, `timezone`), notification email,
calendar, WhatsApp connect/disconnect + QR, password change.
`GET|PUT /api/business/profile` · `/settings/{email,vertical,calendar}` ·
`/whatsapp/{qr,status,disconnect}` · `POST /api/auth/change-password`

---

## 4. Missing screens, ranked

| # | Screen | Backend ready? | Note |
|---|---|---|---|
| 1 | Email verification + resend | partial | No UI anywhere; users who miss the mail are stuck |
| 2 | Billing / subscription | **yes** — `/api/payment/portal`, `/api/payment/tenant/usage` | Endpoints exist, nothing links to them. Cheapest revenue unlock |
| 3 | Password reset entry from marketing | yes — `reset-password.html` | Landing's duplicate-email error only opens WhatsApp |
| 4 | Team / multi-user | **no** | Nothing anywhere; caps each tenant at one operator |
| 5 | PDPA data export + account deletion | **no** | Site claims "PDPA Compliant"; only contact CSV exists |
| 6 | Usage / quota meter | yes — `/api/payment/tenant/usage` | No surface; users hit limits blind |
| 7 | Legal pages as routes | — | Content lives inside `InfoModal.tsx`, not linkable |

## 5. Accessibility + responsive [GAP]

No audit has been performed. Known risks: gold `#E3B457` on `#072A1F` must be
checked for WCAG AA on small text; `window.prompt()` in the reject flow is not
accessible; no skip-link; focus management on modal open/close is unverified;
`.touch-target` exists but is not applied uniformly. Marketing is mobile-first
(PWA, `pb-safe`); `dashboard.html`'s sidebar behaviour under 375 px is
unverified.

## 6. Dead components — do not extend

Not imported anywhere (verified by import grep): `CalBooking.tsx`, `Icons.tsx`,
`LeadCaptureModal.tsx`, `Roadmap.tsx`, `SetupGuide.tsx`, `TrustSection.tsx`,
`WhatsAppLinkGenerator.tsx` (22 KB). Note `Roadmap.tsx` defines
`<section id="roadmap">` but is unrendered, so the navbar's `#roadmap` link
resolves to an empty div at `Pricing.tsx:401`.
