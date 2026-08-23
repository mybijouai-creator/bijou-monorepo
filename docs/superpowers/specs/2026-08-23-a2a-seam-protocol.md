# A2A Seam Protocol — Bijou AI ↔ Telnyx Voice Concierge (and any future channel)

**Version:** 1.0-draft
**Date:** 2026-08-23
**Author:** Bijou AI Engineering
**Status:** DRAFT — pending sign-off (Compliance Officer + Engineering Lead)
**Issue:** #31 (GitHub `mybijouai-creator/bijou-monorepo`)
**Related:** #23 (A2A foundation, closed), #21 (shared-ns EPIC), #28 (voice wiring)

---

## 0. Why this exists

Before the A2A layer shipped, Bijou's WhatsApp agent and the (forthcoming)
Telnyx voice concierge were two independent AI personas that didn't share
conversation state. A customer who messaged on WhatsApp about "viewing for
unit 12B" and then called the voice line 5 minutes later got the AI voice
agent to start from scratch — it had no idea what the WhatsApp side had
just discussed.

That was a real product bug, not an architecture preference. Customers
*expect* to be remembered across channels. The A2A seam is the fix.

This document is the **source of truth** for the seam. Every other
shared-ns issue references it. Any new channel integration (Telegram,
SMS, a future web-chat widget, an email-handling agent) must conform.

---

## 1. Design principles

The protocol is built on five principles. Every decision below maps back
to at least one.

| # | Principle | What it means in practice |
|---|---|---|
| 1 | **One customer, one thread.** | Across every channel, a single customer has a single ordered conversation history, scoped to one tenant. |
| 2 | **Append-only, last-write-wins.** | No editing, no deletions, no conflict resolution. The newest write for a `(channel, role, content)` tuple wins on display. (We use `created_at` ordering, not vector clocks — see §6.) |
| 3 | **Tenant boundary is the security boundary.** | A single RLS-locked table, `tenant_id` from `verify_session`, never from request body. The protocol is a security primitive as much as a UX one. |
| 4 | **Channel-agnostic envelope.** | The same envelope works for WhatsApp, voice, SMS, email, web chat. A new channel adds a new `channel` value + its own transport; the envelope never changes. |
| 5 | **Privacy by design.** | Content is PII-grade. Retention is bounded, encryption is at rest, audit trail is on every read. (See §5.) |

---

## 2. The data model

### 2.1 Table (canonical)

```sql
create table public.shared_context (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id) on delete cascade,
  customer_phone  text not null,            -- E.164 normalized, digits-only after stripping
  channel         text not null
    check (channel in ('whatsapp','telegram','voice','sms','email','web')),
  thread_id       text not null,            -- chat_jid (WA) | call_sid (voice) | chat_id (TG) | etc.
  role            text not null
    check (role in ('user','assistant','system')),
  content         text not null,            -- the message text, transcribed voice, etc.
  metadata        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);
```

The migration is at `packages/backend/migrations-py/add_shared_context.sql`.
RLS is **on** with no permissive policies — only `service_role` can read or
write. Tenant isolation is enforced at the API layer (`verify_session`
dependency). The data layer is the truth; the API is the contract.

### 2.2 The customer key

`(tenant_id, customer_phone)` is the **unified customer identifier**.
`customer_phone` is normalized to E.164 digits-only (`+60XXXXXXXXX`) at
write time — never store `01X-XXX XXXX` (Malaysian national format) or
`6017xxx` (missing the `+`). The `data_request_api.py` already does this
normalization; the A2A path reuses the same helper.

Why phone and not email or a Bijou-specific customer_id? Because:
- Phone is what the WhatsApp / voice / SMS channels already use
- Phone is the lowest-friction identifier for an end user ("I called
  from +60 17-XXX XXXX")
- A Bijou customer_id would require an identity-resolution step before
  the seam works, which would defeat the point

When a future channel uses a different identifier (e.g., email), the
`customer_phone` field becomes `customer_handle` and we add a parallel
`customer_email` column. Don't refactor preemptively.

### 2.3 The thread key

`(tenant_id, customer_phone, channel, thread_id)` is the **per-channel
conversation identifier**. `thread_id` values:

| Channel | thread_id value | Example |
|---|---|---|
| WhatsApp | The chat JID | `+60123456789@s.whatsapp.net` |
| Voice | The Telnyx call SID | `call_abc123` |
| Telegram | The Telegram chat ID | `123456789` |
| SMS | The Telnyx message thread ID | `msg_xyz789` |
| Email | The email thread ID (Message-ID header) | `<abc123@gmail.com>` |
| Web | The widget session ID | `sess_abc123` |

Multiple `thread_id`s per `(tenant, customer)` are normal — a customer
might have 3 parallel WhatsApp chats (group chats, individual chats with
the same number, etc.) AND a voice call. The seam sees all of them
interleaved.

---

## 3. The API contract

### 3.1 `POST /api/shared-context/append` — write a turn

**Request body:**

```json
{
  "customer_phone": "+60123456789",
  "channel": "whatsapp",
  "thread_id": "+60123456789@s.whatsapp.net",
  "role": "assistant",
  "content": "Sure, unit 12B is available. What time works?",
  "metadata": {
    "message_id": "msg_001",
    "model": "gemini-2.5-flash",
    "confidence": 0.87,
    "tool_calls": [{"name": "check_availability", "args": {"unit": "12B"}}]
  }
}
```

**Response:** the inserted row, including server-generated `id` and
`created_at`.

**Auth:** Bearer token (the tenant's session JWT). `tenant_id` is taken
from the session, **never** from the request body. A malicious client
cannot write into another tenant's thread by spoofing `tenant_id`.

**Validation:**
- `channel` ∈ `{whatsapp, telegram, voice, sms, email, web}` (400 if not)
- `role` ∈ `{user, assistant, system}` (400 if not)
- `customer_phone` non-empty (400 if not)
- `content` non-empty (400 if not)

**Side effects:** none. The append is pure write. It does NOT trigger a
model call, an outbound message, or a webhook. Channels that need to act
on the append (e.g., the Inbox Co-pilot showing the new turn) poll or
subscribe separately.

### 3.2 `GET /api/shared-context?phone=…` — read the unified thread

**Query parameters:**
- `phone` (required) — the E.164 customer phone
- `since_hours` (default 24, max 720 = 30 days) — how far back to look
- `limit` (default 50, max 500) — cap on rows returned

**Response:**

```json
{
  "entries": [
    {
      "id": "00000000-0000-0000-0000-000000000020",
      "tenant_id": "607690ec-4ff7-4ef4-b98e-bfb00442fe95",
      "customer_phone": "+60123456789",
      "channel": "voice",
      "thread_id": "call_abc123",
      "role": "assistant",
      "content": "Yes, I see we discussed unit 12B on WhatsApp...",
      "metadata": {"call_sid": "abc123"},
      "created_at": "2026-08-23T07:05:00+00:00"
    },
    { "...voice user msg..." },
    { "...whatsapp assistant msg..." },
    { "...whatsapp user msg..." }
  ],
  "count": 4
}
```

**Ordering:** newest first (`created_at desc`).

**Auth:** same as append. `tenant_id` from session, `customer_phone` from
query string. RLS at the DB level + API-level tenant_id filter = defense
in depth.

### 3.3 What the API does NOT do

- No `DELETE` endpoint. Erasure is a separate concern, handled by the
  PDPA/GDPR data-request flow (issue #26). Erasing A2A entries is
  part of the tenant-wide data deletion, not a per-row operation.
- No `UPDATE` endpoint. Append-only, forever.
- No cross-tenant reads. A single tenant can never see another tenant's
  entries, even if the customer phone is the same (this is the
  cross-tenant isolation test we added in `test_shared_context.py`).
- No streaming. Real-time is a v2 concern (see §8).

---

## 4. Channel-specific writers

Each channel integration has its own writer that knows the channel's
transport. The writer is responsible for:

1. Calling `POST /api/shared-context/append` with the right envelope
2. Normalizing the channel-specific identifier to `thread_id` format
3. Including channel-specific metadata (call SID, transcription
   confidence, etc.) in the `metadata` field

### 4.1 WhatsApp writer (current)

`src/core/bijou.py` is the message handler. Every AI-generated reply
already runs through the Reasoning Trace post-response hook
(`bijou.py:3574-3626`, per commit `b54958c`). The A2A append goes
**alongside** the reasoning write — the handler calls both:

```python
# After AI response generated:
record_reason(tenant_id, message_id, ...)  # Reasoning Trace (issue #11)
append_shared_context(tenant_id, customer_phone, "whatsapp", chat_jid,
                     "assistant", reply_text, metadata={...})  # A2A
```

We **do not** add inbound WhatsApp messages to the A2A — only outbound.
Inbound is already in `public.messages` (or `public.conversations`); the
A2A is the "what the AI said" log, not the full message log. (A future
enhancement could add inbound to the A2A for the full thread view;
tracked in §8.)

### 4.2 Voice writer (forthcoming, issue #28)

The Telnyx voice concierge needs a webhook handler that:

1. On inbound call: read prior A2A entries for the caller's phone to
   build the system prompt context ("you discussed unit 12B on WhatsApp
   with this customer at 14:00")
2. On each AI TTS line spoken: append to A2A with `channel=voice`,
   `role=assistant`
3. On call end: append a `role=system` summary entry for audit

The webhook is in the new `packages/voice/` (forthcoming) — see issue
#27 for the absorption plan.

### 4.3 Future channels

Telegram, SMS, email, and web-chat each get their own writer. The
envelope doesn't change. The metadata field is where channel-specific
context lives.

---

## 5. Privacy + retention

This is the security-and-compliance layer. **Every decision in this
section is auditable against `docs/compliance/DATA_SUBJECT_RIGHTS.md` and
`docs/compliance/EU_AI_ACT_2024.md`.**

### 5.1 Retention

Default: **90 days** for `shared_context` entries. After 90 days, a
nightly job (TBD, 30-day target) hard-deletes entries where
`created_at < now() - interval '90 days'`.

Per-tenant override: a tenant on the "jewel" plan can configure
retention from 7 to 365 days. Default for all plans is 90 days.

Rationale: 90 days is enough for typical customer disputes (most are
filed within 30 days of an interaction) and EU AI Act Article 12
default of 6 months. Hard delete is non-recoverable; we err on the
side of less retention for the PII-grade content.

### 5.2 Encryption

- **At rest:** Supabase Postgres tables are encrypted at rest via the
  Supabase-managed disk encryption. The `shared_context` table inherits
  this for free.
- **In transit:** all API calls are HTTPS. The service-role key never
  leaves the backend container.
- **Application-level:** we do NOT add per-row encryption. The threat
  model is "compromised DB read" — disk encryption is the right layer
  for that. If we ever need to defend against "compromised service-role
  key", per-row encryption (e.g., a `pgcrypto` column) is a v2 concern.

### 5.3 PII handling

- The `content` field is **PII-grade** (it can contain the customer's
  questions, the AI's answers, and any personal details they share)
- We do not redact before writing. The whole point of the seam is the
  full conversation, and redacting in the A2A breaks the AI's ability
  to recall prior context.
- The PII redaction happens **at inference time** (e.g., `+60***` in
  prompts sent to Gemini), not at storage time. The A2A stores the
  real content; the model sees the redacted version.

### 5.4 Data subject rights (PDPA / GDPR / MY PDPA)

`data_request_api.py` (issue #26) already handles the per-tenant
erasure flow. When a tenant deletes a customer, the A2A entries for
that customer are deleted in the same transaction:

```sql
-- Pseudocode for the deletion path
delete from public.shared_context
where tenant_id = :tenant_id
  and customer_phone = :customer_phone;
```

This is part of the existing `data_request_deletions` table's
expiry-triggered cascade. No new code needed for the A2A — it inherits
the existing erasure semantics.

### 5.5 Right of access

`/data-request` (public) already returns the full data bundle for a
phone+email pair. The A2A entries are part of that bundle. The
download JSON includes a `shared_context` array.

---

## 6. Conflict resolution

The protocol is **append-only with last-write-wins by `created_at`**:

- Two writers can race. The DB's primary key is a fresh UUID per
  insert; both rows are kept.
- The read order is `created_at desc`. A row with a later
  `created_at` is shown first.
- We do not deduplicate. If the same content is written twice (e.g.,
  the voice TTS happens twice due to a retry), we keep both. The
  read UI can dedupe by `content` if desired; the API doesn't.

Why no CRDT or vector clock? Because:
- The use case is human-readable cross-channel inbox. A simple
  chronological list is what users expect.
- True conflict resolution (e.g., a message edited mid-flight) is not
  in scope. Edits are not part of the protocol.
- CRDT adds significant complexity for zero observable benefit at
  this scale (single tenant, single customer, append-only).

If a future need arises (e.g., a customer edits a WhatsApp message
and we need to track the edit history), we can add a `superseded_by`
column without breaking v1.

---

## 7. Performance

Current expected scale (per tenant):
- 100 messages/day/tenant (most small businesses)
- 90-day retention = 9,000 rows/tenant
- Single Supabase read with the right indexes = <50ms

Indexes (already in the migration):
- `idx_shared_context_lookup` on `(tenant_id, customer_phone, created_at desc)`
- `idx_shared_context_tenant_time` on `(tenant_id, created_at desc)` for
  retention sweeps

If a tenant grows past 10K messages/day (huge), the read query might
need pagination. Currently the limit cap is 500 rows. We will revisit
if a real customer hits this.

---

## 8. Future work (v2, not v1)

- **Real-time streaming** of new entries to a connected dashboard (so
  the Inbox updates without a refresh). WebSocket or SSE.
- **Inbound message logging** — currently we only log outbound (AI
  replies). Adding inbound gives a true full-duplex view.
- **Customer-side identifiers** — extend the schema to support
  email or Bijou-customer-id in addition to phone.
- **Cross-tenant A2A** for marketplace scenarios (e.g., two Bijou
  businesses collaborating on a customer referral). Strictly
  opt-in, never default.
- **Voice mid-call context** — currently the voice writer reads prior
  context BEFORE the call. Real-time context streaming mid-call
  (e.g., the customer references "the WhatsApp about unit 12B" and
  the voice AI pulls it up in real-time) is a v2 capability that
  requires a streaming A2A read API.

---

## 9. Open questions (need owner / counsel input)

1. **Q1.** Do we need a separate `voice_transcripts` table for the
   raw voice audio + transcript, or is the A2A's `content` field
   enough? Currently leaning A2A-only (transcript is the source of
   truth; audio is discardable after transcription).
2. **Q2.** When Bijou offers a multi-tenant marketplace in v3 (a
   business partner can message a customer on behalf of another
   business), does the A2A seam become a data-sharing primitive, or
   does it stay strictly tenant-scoped? Current answer: stay scoped.
   Reopen if v3 needs cross-tenant.
3. **Q3.** The 90-day retention default is conservative. Some tenants
   (legal, medical) may need 7-year retention. Per-tenant override
   already supports this; do we want a default that varies by
   industry? Probably not — the override is enough.

---

## 10. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Engineering Lead | (TBD) | (TBD) | (TBD) |
| Compliance Officer | (TBD) | (TBD) | (TBD) |
| Product Lead | (TBD) | (TBD) | (TBD) |

---

## 11. References

- `packages/backend/src/core/shared_context_api.py` — the API
- `packages/backend/migrations-py/add_shared_context.sql` — the schema
- `packages/backend/tests/unit/test_shared_context.py` — the tests
  (including the 3 round-trip / isolation / channel tests from
  commit `62fdd12`)
- `docs/compliance/DATA_SUBJECT_RIGHTS.md` — data subject rights matrix
- `docs/compliance/EU_AI_ACT_2024.md` § Article 12 + 13 — record-keeping
  + transparency obligations
- Issue #23 — A2A foundation (closed)
- Issue #28 — voice concierge wiring (forthcoming)
- Issue #31 — this document
