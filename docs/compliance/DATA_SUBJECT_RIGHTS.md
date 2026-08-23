# Data Subject Rights — PDPA / GDPR / UK GDPR / MY PDPA 2010

**Status:** Living document. Last reviewed 2026-08-23.

**Scope:** Every data subject (end-user customer) whose personal data
Bijou AI processes, regardless of jurisdiction. We treat the strictest
applicable law (GDPR) as the floor.

**Owner:** Compliance Officer + Engineering Lead

---

## 1. The data we hold on each end user

| Data | Where | Source | Retention |
|---|---|---|---|
| Phone number (E.164) | `public.customers.phone`, `public.messages.chat_jid` | WhatsApp/Telegram/voice onboarding | Per tenant's data-retention policy, default 2 years |
| Display name (if given) | `public.customers.display_name` | Customer onboarding | Same as phone |
| Conversation history (raw text) | `public.messages` (or `conversations`) | Every inbound/outbound message | Per tenant's policy, default 2 years |
| AI reasoning trace per message | `public.message_reasons` | Every AI reply | 2 years (exceeds Article 12 baseline) |
| Cross-channel shared context | `public.shared_context` | Every A2A seam write | 90 days |
| Inbox Co-pilot audit log | `public.inbox_copilot_events` | Every Co-pilot suggestion + action | 1 year |
| Stripe customer ID + billing events | Stripe | Self-serve billing | 7 years (financial legal hold) |
| IP address (auth events) | Supabase GoTrue logs | Login + signup | 90 days |

We do **not** collect: precise geolocation, contacts, device fingerprint,
browsing history outside Bijou, advertising IDs, biometric data, health
data, or any special-category data under GDPR Article 9.

We do **not** sell data. We do **not** share data with third parties for
their own purposes. Stripe is a data processor (billing only) under a DPA.

---

## 2. Right-by-right matrix

### 2.1 Right of access (PDPA s.12 / GDPR Art.15 / MY PDPA s.12)

**What it means:** The data subject can ask "what do you have on me?" and
get a copy within 30 days.

**How we satisfy it:**

- Public page at `GET /data-request` — no login required
- Form takes phone + matching email
- HMAC-SHA256 signed magic link sent to the email
- Link is one-time, expires in 24 hours
- Returns a JSON bundle with: every message we hold, every AI reasoning
  row, every cross-channel entry, every Co-pilot event, every billing event
- 30-day SLA, currently responds in <5 minutes (the data is just a Supabase
  query)

**API:** `POST /api/data-request/access` (gated by phone+email match)
**Download:** `GET /api/data-request/download/{token}` (one-time signed link)

### 2.2 Right of erasure (PDPA s.13 / GDPR Art.17 / MY PDPA s.13)

**What it means:** The data subject can ask "delete everything you have
on me" and we must do it within 30 days, with limited exceptions.

**How we satisfy it:**

- Public page at `GET /data-request` — same form as access
- Soft-delete with 30-day grace: the data is marked for deletion
  (`public.data_request_deletions.status = 'pending'`) but not hard-deleted
  for 30 days, so a typo or coerced request can be reversed
- After 30 days: hard delete across `customers`, `messages`, `message_reasons`,
  `shared_context`, `inbox_copilot_events`
- Stripe data: deleted via Stripe API (we cannot hard-delete financial
  records under tax law, but we anonymize the link to the customer)
- Auth logs: deleted from GoTrue logs after 90 days as part of the normal
  retention cycle

**Exceptions we will refuse on:**
- Ongoing dispute (e.g., a delivery complaint under investigation) —
  data retained until resolution, then deleted
- Legal hold (e.g., a court order) — data retained until the hold is
  released
- Financial records — anonymized but retained for 7 years per tax law

**API:** `POST /api/data-request/delete`
**Status:** `GET /api/data-request/status/{token}`

### 2.3 Right of rectification (GDPR Art.16 / PDPA s.12(2))

**What it means:** The data subject can ask "fix this wrong info about me"
and we must do it within 30 days.

**How we satisfy it:**

- Tenant-side: the business can edit customer profile data in their dashboard
  (Customers tab)
- End-user-side: the end user can request a correction via the same
  `GET /data-request` page (additional "Request correction" option), and
  the tenant is notified in the dashboard inbox

### 2.4 Right of portability (GDPR Art.20)

**What it means:** The data subject can ask for their data in a
machine-readable format.

**How we satisfy it:**

- The access response is JSON, structured as:
  ```json
  {
    "customer": {...},
    "messages": [...],
    "ai_reasons": [...],
    "shared_context": [...],
    "copilot_events": [...]
  }
  ```
- CSV export option is TBD (tracked as a 30-day enhancement)

### 2.5 Right to object (GDPR Art.21)

**What it means:** The data subject can object to processing for
direct marketing, profiling, or other legitimate-interest grounds.

**How we satisfy it:**

- We do not do direct marketing of Bijou to end users (we market to
  businesses)
- We do not do automated decision-making with legal or similarly
  significant effects on the data subject (Bijou is customer service, not
  credit decisions)
- For safety: Settings has a "Do not use my data for model training" toggle.
  We don't train on customer data, but the toggle exists for transparency

### 2.6 Right to restrict processing (GDPR Art.18)

**What it means:** The data subject can ask to pause processing while a
dispute is resolved.

**How we satisfy it:**

- Tenant-side: a "freeze" flag on a customer record halts AI replies and
  message logging. The customer is still able to read past messages.
- End-user-side: not directly exposed in v1 (they would go through the
  business). Tracked as a 30-day enhancement.

### 2.7 Right to lodge a complaint (GDPR Art.77 / PDPA s.13)

**What it means:** The data subject can complain to a supervisory authority.

**How we satisfy it:**

- The data-request page footer links to:
  - EU: the data subject's national Data Protection Authority
  - UK: the ICO
  - Malaysia: the JPDP (Jabatan Perlindungan Data Peribadi)
- We respond to all complaints within 7 days

---

## 3. Identity verification

For each right-exercise request, we verify the requester is who they say
they are:

- **Access / download:** phone + matching email that we already hold
  (the email is the auth)
- **Deletion:** phone + matching email + confirmation of the magic link
  (the email link is the "I really want this" signal)
- **Correction:** phone + email + business-side confirmation
- **Objection:** any channel (email, WhatsApp message to the business,
  Settings toggle) — we treat the request as a soft signal and the
  business may need to confirm

We do **not** require government ID for these requests. The phone+email
match is sufficient because the data we hold is the phone and email
already — if the requester knows the email associated with the phone,
they are by definition the data subject (or an authorized agent of).

---

## 3.5 Affirmative consent (the OTHER half of PDPA / GDPR)

Right of access / erasure is the **deletion** side of data-subject
rights. The other half is **affirmative consent** — proving that
the customer *agreed* to receive marketing / outreach messages
*before* we sent them.

This is the section most projects get wrong, and the section that
gets the most regulator attention.

### 3.5.1 The contract

A contact cannot be included in any outreach campaign unless there
is at least one row in `public.outreach_consent_log` with
`consent_type IN ('opt_in', 'transactional')` and
`revoked_at IS NULL`. This is enforced at the **API layer** in
`start_campaign` (refuses with HTTP 412 if any contact lacks consent),
not just at the database level. PDPA / GDPR failure modes are at the
**application**, not the database.

### 3.5.2 The API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/outreach/consent/record` | POST | Record a new consent (web opt-in, SMS keyword, CSV import with historical proof) |
| `/api/outreach/consent/status` | GET | Check current consent state for a single contact |
| `/api/outreach/consent/{id}/revoke` | POST | Soft-revoke (keeps the row for audit, stamps `revoked_at`) |
| `/api/outreach/consent/audit` | GET | Full audit trail for a contact (for regulators) |
| `/api/outreach/consent/check-bulk` | POST | Bulk check (used by `start_campaign` before queueing) |

Every row records:
- `consent_type` (opt_in / opt_out / transactional / imported_legacy)
- `consent_text` (the exact text the contact agreed to)
- `channel` (web_form / whatsapp / sms / email / in_person / api / imported)
- `source` (form / csv_import / api / whatsapp_keyword)
- `ip_address`, `user_agent` (when applicable)
- `granted_at`, `expires_at`, `revoked_at`, `revoked_reason`

### 3.5.3 Revocation is soft

We never DELETE a consent row. The regulator / customer may need to
see "yes, you did have consent on 2025-01-15, and you revoked it
on 2025-03-22" — that's the only correct behavior under PDPA /
GDPR. Soft-revocation is the only acceptable answer.

### 3.5.4 What the owner does

If a customer complains "I never opted in":

1. Open the customer's profile in the dashboard
2. Go to "Outreach consent" → see the audit trail
3. If the latest row is an active opt-in, point to the row: "you
   opted in on this date from this IP agreeing to this text"
4. If the latest row is a revocation, the customer is correct —
   the campaign that targeted them pre-dated the revocation; apologize
   and improve your segmentation

If the customer has **no rows at all**, the campaign should never have
targeted them. The `start_campaign` consent gate would have refused
the queue — investigate why the gate was bypassed (e.g., campaign was
started before the consent table existed, or contact was added to the
segment without going through a consent flow).

---

## 4. Breach notification

- **GDPR Art.33:** notify the supervisory authority within 72 hours
- **PDPA s.14:** notify the JPDP without undue delay
- **MY PDPA:** notify the JPDP without undue delay
- **Data subjects:** notify affected data subjects without undue delay
  if the breach poses a high risk to their rights

Runbook: `docs/runbooks/data-breach-response.md` (TBD)

---

## 5. Subprocessors

| Subprocessor | Purpose | DPA in place | Region |
|---|---|---|---|
| Supabase | Database + auth | Yes | EU (Frankfurt) or US (configurable) |
| Google (Gemini) | LLM inference | Yes (Google Cloud DPA) | US |
| Stripe | Billing | Yes (Stripe DPA) | US |
| WhatsApp / Telegram | Channel transport | Yes (Meta DPA / Telegram ToS) | US / SG |
| Telnyx (forthcoming) | Voice channel | TBD (in negotiation) | TBD |

Subprocessor list is published at `app.mybijou.xyz/subprocessors` (TBD
page) and the data-request footer links to it.

---

## 6. Open work / known gaps

- CSV export option (portability) — TBD, 30-day target
- `docs/runbooks/data-breach-response.md` — TBD
- `app.mybijou.xyz/subprocessors` public page — TBD
- Right to restrict processing self-service for end users — TBD
- Telnyx DPA negotiation — TBD (blocks issue #28)

---

## 7. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Compliance Officer | (TBD) | (TBD) | (TBD) |
| DPO (if appointed) | (TBD) | (TBD) | (TBD) |

---

## 8. References

- Personal Data Protection Act 2010 (Malaysia) — full text
- Regulation (EU) 2016/679 ("GDPR") — full text
- Data Protection Act 2018 (UK) — full text
- PDPC Malaysia's *Guidelines on the Processing of Personal Data in the
  Cloud* — referenced for the cloud-DPA position
- EDPB Guidelines 01/2022 on data subject rights — referenced for
  identity verification
