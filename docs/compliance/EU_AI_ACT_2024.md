# EU AI Act 2024 — Compliance Position (Bijou AI)

**Status:** Living document. Last reviewed 2026-08-23 against the published
Regulation (EU) 2024/1689 text and the Commission's conformity-assessment
guidance for limited-risk AI systems.

**Owner:** Bijou AI Engineering + designated Compliance Officer
**Scope:** Bijou AI's WhatsApp/Telegram/voice customer-service agent as deployed
to EU-resident end users (also covers MY/UK/SEA deployments, which are
*more* permissive than the EU baseline; we treat the EU position as floor).
**Risk class:** **Limited risk** (Article 50 transparency obligations only).
Bijou is not a high-risk system (Annex III) and does not fall under prohibited
practices (Article 5). This classification is reassessed quarterly and on any
material change in capability (model upgrade, new channel, new autonomous
action).

> The single sentence that matters most: *Bijou discloses its AI nature to
> every end user, logs every AI-generated message with its reasoning, and
> never auto-sends without human approval for any consequential action.*

---

## 1. Risk classification

| Test | Bijou position |
|---|---|
| Article 5 prohibited? | No. No subliminal manipulation, exploitation of vulnerabilities, social scoring, real-time biometric ID, etc. |
| Annex III high-risk? | No. We are a general-purpose customer-service chatbot, not used in critical infrastructure, education, employment, law enforcement, migration, or justice. |
| General-purpose model (GPAI) provider? | Indirectly. We use Google Gemini 2.5 Flash as a building block. Google's GPAI obligations sit with Google, not Bijou. We inherit Article 50 transparency obligations as a downstream deployer. |
| **Net classification** | **Limited risk** (Article 50 chatbot transparency) |

If at any point Bijou takes on a use case that *would* fall into Annex III
(e.g., credit decisions, employment screening, medical triage), the
risk posture jumps to **high-risk** and the controls below must be upgraded
to the Annex IV technical-documentation standard. A change-control gate
exists for this in `docs/architecture/change-control.md` (TBD).

---

## 2. Article-by-article obligations and how we satisfy them

### Article 9 — Risk management system (continuous, iterative)

**Obligation:** Establish a risk management system run as a continuous
iterative process across the lifecycle.

**How we satisfy it:**

- **Identify risks** — pre-deployment: red-team prompt set covering prompt
  injection, jailbreaks, PII extraction, hallucinated prices/dates, off-topic
  drift, brand-voice violations. Post-deployment: 100% of AI replies are
  logged with reasoning (see Article 12/13).
- **Evaluate risks** — every `public.message_reasons` row carries a
  `confidence` score (0.0–1.0). The dashboard surfaces low-confidence
  messages to the human agent for review.
- **Estimate and mitigate** — Inbox Co-pilot flags 8 high-risk reply
  patterns (refund demands, legal threats, escalation requests) so the
  human agent can intercept before send.
- **Document residual risk** — `docs/compliance/residual-risk-register.md`
  (TBD) tracks accepted risks with sign-off.

### Article 10 — Data and data governance

**Obligation:** Training, validation, and testing datasets must be relevant,
representative, and free of errors to the extent possible.

**How we satisfy it:**

- We do **not** train our own model. Gemini 2.5 Flash is Google's.
- Bijou's RAG knowledge base (`public.kb_documents`) is **per-tenant** and
  **content uploaded by the tenant**. Each tenant's KB is isolated, RLS-locked,
  and only the tenant's own agent + end users can read it.
- KB ingestion has a quality gate: documents are chunked, embedded, and
  scored for relevance before they enter retrieval. Bad chunks are flagged
  in the dashboard.
- See `docs/compliance/MODEL_CARD.md` for full model data lineage.

### Article 11 — Technical documentation (Annex IV)

**Obligation:** Maintain technical documentation demonstrating conformity,
updated throughout the lifecycle.

**How we satisfy it:**

This document, plus the linked sub-documents, constitute the Annex IV
technical file. Sub-documents:

- `docs/compliance/MODEL_CARD.md` — model identity, training data lineage,
  intended purpose, evaluation results
- `docs/compliance/DATA_SUBJECT_RIGHTS.md` — PDPA + GDPR + Article 10
- `docs/architecture/architecture.md` — system design and data flows
- `docs/SECURITY.md` — security posture
- `docs/RUNBOOKS/` — operational runbooks (incident response, model rollback,
  data breach)

### Article 12 — Record-keeping (automatic logging)

**Obligation:** Automatic logging of events over the lifecycle, sufficient
to ensure traceability of the system's functioning.

**How we satisfy it:**

| Log | Where | Retention | Purpose |
|---|---|---|---|
| Every AI reply with full reasoning | `public.message_reasons` | 2 years | Traceability of what the system said, why, and what it knew |
| Every cross-channel message | `public.shared_context` | 90 days | A2A seam audit |
| Every Inbox Co-pilot suggestion + action | `public.inbox_copilot_events` | 1 year | Human-oversight audit log |
| Every customer message (raw) | `public.messages` (or `conversations`) | per tenant data-retention policy | Conversation record |
| Auth events | Supabase GoTrue logs | 90 days | Security audit |
| Data-subject requests | `public.data_request_deletions` | 7 years (legal hold) | PDPA/GDPR audit |
| Stripe billing events | Stripe dashboard | 7 years | Financial audit |

The 2-year retention on `message_reasons` exceeds the Article 12 default
(6 months) because the Reasoning Trace is the primary transparency primitive
and we want it long enough to handle end-of-year compliance reviews.

### Article 13 — Transparency to deployers

**Obligation:** High-risk AI systems must be designed to enable deployers
to interpret outputs and use appropriately. *We are not high-risk*, but
the reasoning-trace primitive is built to this standard anyway because it's
also the customer-facing differentiator.

**How we satisfy it:**

- The Inbox side panel shows, for every AI reply, *why* the AI said what
  it said: which KB docs were retrieved, which tool calls were made, the
  model version, the confidence score, and 2-3 alternative replies that
  were considered. See `src/core/message_reasons_api.py` and the dashboard
  Reasoning Trace panel.
- The Activity Stream widget on the Home tab shows the same trace for the
  most recent AI actions, so the deployer (the business owner) always knows
  what Bijou just did.
- Every API call to `record_reason` is tenant-scoped via `verify_session`,
  so a deployer can only see their own reasoning data — no cross-tenant
  leakage possible at the API layer.

### Article 14 — Human oversight (mandatory for high-risk; we apply voluntarily)

**Obligation:** High-risk systems must be designed to allow effective human
oversight. *We are not high-risk*, but the Inbox Co-pilot implements the
exact human-in-the-loop pattern that Article 14 requires.

**How we satisfy it:**

- **Never auto-send.** The Inbox Co-pilot surfaces 1–3 suggestions as the
  human agent types, but every suggestion requires the agent to click
  "Accept" before it is sent. Accept/edit/dismiss are all logged in
  `public.inbox_copilot_events`.
- **Easy to override.** Any AI reply can be edited before send, or
  replaced with a manual reply. The system never queues an AI message for
  later send.
- **Easy to stop.** The Settings tab has a one-click "Pause AI" toggle.
  When paused, the system forwards inbound messages to a human queue and
  generates no AI replies until the toggle is flipped back.
- **Escalation to human.** The escalation detector (a pattern match on
  "speak to a person", "manager", "lawyer", etc.) routes the conversation
  to the human queue immediately. The escalation event is logged with
  the trigger phrase.

### Article 15 — Accuracy, robustness, cybersecurity

**Obligation:** High-risk systems must be accurate, robust, secure.

**How we satisfy it:**

- **Accuracy** — the dashboard shows the model's confidence per reply.
  Replies below the tenant's configured threshold are flagged for review.
  Tenants can set their own threshold in Settings.
- **Robustness** — every API endpoint has request validation (Pydantic),
  tenant isolation (RLS + `verify_session`), and rate limiting.
- **Cybersecurity** — see `docs/SECURITY.md`. Highlights: service-role key
  never exposed to the client, secrets in env vars only, secrets rotation
  runbook in `docs/runbooks/secrets-rotation.md`, dependency scanning in CI
  (issue #16 tracks a formal secrets-manager adoption).

### Article 50 — Transparency to end-users (the critical one for chatbots)

**Obligation:** Providers must ensure that AI systems intended to interact
directly with natural persons are designed to make the AI nature of the
system clear to those persons.

**How we satisfy it:**

- **First-message disclosure.** Every new WhatsApp conversation starts with
  a Manglish-language message: "Hi, I'm Bijou, an AI assistant for
  [Business Name]. I can help with questions, orders, and bookings. A
  human can take over anytime — just ask."
- **Per-message disclosure on opt-in.** If a customer enables verbose mode
  in their WhatsApp settings, every Bijou reply is prefixed with
  "🤖 Bijou (AI):". Default is the first-message disclosure only, to keep
  the conversation natural.
- **Brand-voice consistency.** The voice is the same Manglish personality
  everywhere, so a user can always tell when they're talking to Bijou
  (the persona is the disclosure).
- **Easy opt-out.** A "talk to a human" message at any point routes the
  conversation to a human queue within 5 seconds.

---

## 3. End-user rights

See `docs/compliance/DATA_SUBJECT_RIGHTS.md` for the full PDPA + GDPR + UK
GDPR + MY PDPA 2010 rights matrix. Summary:

- Right of access (PDPA s.12, GDPR Art.15) — via `GET /data-request` page,
  returns all data we hold on a phone+email pair within 30 days
- Right of erasure (PDPA s.13, GDPR Art.17) — via `POST /api/data-request/delete`,
  30-day grace period before hard delete (allows recovery from accidental
  requests)
- Right of portability (GDPR Art.20) — the access response is JSON
- Right to object (GDPR Art.21) — Settings tab has a "Do not use my data
  for model training" toggle (we don't train on customer data anyway, but
  the toggle exists for transparency)

---

## 4. Conformity assessment

Because Bijou is **limited-risk** (not high-risk), the Regulation does not
require a third-party conformity assessment. The self-assessment in this
document, signed by the Compliance Officer, is sufficient.

A signature block at the bottom of this document is renewed annually or on
material change.

---

## 5. Post-market monitoring

- **Quarterly review** — every quarter, the Compliance Officer reviews
  this document, re-runs the red-team prompt set, and signs off.
- **Incident-triggered review** — any incident in `docs/runbooks/incident-response.md`
  that affects transparency, human oversight, or accuracy triggers an
  out-of-cycle review.
- **Material change review** — any model upgrade, new channel, or new
  autonomous action triggers an out-of-cycle review.

---

## 6. Open work / known gaps

- `docs/compliance/residual-risk-register.md` — TBD. Owner: Compliance Officer.
- Formal red-team prompt set versioned in repo — TBD. Owner: ML Engineer.
- Annual sign-off renewal — schedule TBD. Owner: Compliance Officer.
- Article 14 settings: configurable confidence threshold per tenant —
  exists in dashboard, needs to be wired to the API. Issue tracked.
- Secrets manager adoption (issue #16) — currently using env vars; 1Password
  CLI or Infisical is the target.

---

## 7. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Engineering Lead | (TBD) | (TBD) | (TBD) |
| Compliance Officer | (TBD) | (TBD) | (TBD) |
| CEO | (TBD) | (TBD) | (TBD) |

---

## 8. References

- Regulation (EU) 2024/1689 (the "AI Act") — full text
- Commission Implementing Decision on the standard contractual clauses —
  not applicable to limited-risk systems
- EDPB Guidelines on automated decision-making — referenced for
  human-oversight design
- Google's Gemini 2.5 Flash model card — see `docs/compliance/MODEL_CARD.md`

---

*This document is intended to be readable by outside counsel with no
Bijou-specific context. Every claim is backed by a file path or a runbook
reference. If a claim is not backed, it should be marked TBD.*
