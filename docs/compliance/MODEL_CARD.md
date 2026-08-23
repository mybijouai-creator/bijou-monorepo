# Model Card — Bijou AI Agent

**Status:** Living document. Last reviewed 2026-08-23.

**Scope:** The AI model(s) Bijou AI deploys as its customer-service
agent. Currently Google Gemini 2.5 Flash; subject to change on model
upgrade (tracked in `docs/compliance/CHANGELOG.md`).

**Framework:** Adapted from the Mitchell et al. (2019) Model Card framework
and Google's own Gemini model cards.

---

## 1. Model details

| Field | Value |
|---|---|
| **Model name** | `gemini-2.5-flash` |
| **Provider** | Google DeepMind |
| **Provider's model card** | https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash |
| **Bijou's role** | Downstream deployer; we do not fine-tune, we do not train, we use the model as a building block |
| **Interface** | Google AI Studio API (REST) or Vertex AI (configurable) |
| **Context window** | 1M tokens (input) |
| **Output tokens** | Up to 8K per call |
| **Knowledge cutoff** | 2025-01 (per Google) |
| **Multilingual** | Yes; we use English, Bahasa Malaysia, Chinese, Tamil for the front-end; the model handles all four natively |
| **Bijou's invocation pattern** | RAG (retrieval-augmented generation) over the tenant's KB + system prompt that sets the Manglish brand voice + tool-calling for order lookup, booking, escalation |

## 2. Intended use

**In scope:**
- Customer-service Q&A over the tenant's own product catalog, FAQ, and
  policy documents
- Order-status and booking-status lookups (via tool calls)
- Routing to a human agent on request or detected escalation
- Cross-language support (English, Bahasa Malaysia, Chinese, Tamil)
- Cross-channel support (WhatsApp today; Telegram, SMS, voice planned)

**Out of scope (the model is NOT used for):**
- Medical, legal, or financial advice
- Credit or eligibility decisions
- Employment or housing screening
- Any use that would make Bijou a high-risk system under EU AI Act
  Annex III
- Generating code, images, audio, or video
- Any decision that has legal or similarly significant effects on the
  data subject

If a future feature would put Bijou in scope for any of the above, the
model card is updated and a separate compliance review is triggered.

## 3. Training data

**Bijou does not train the model.** We use Gemini 2.5 Flash as a frozen
inference model. The model's training data is Google's, described in
Google's own model card.

**What Bijou adds at inference time (per request):**
- The tenant's KB (chunked, embedded, retrieved) — at most 10 chunks
  per call, relevance-scored
- The conversation history (last 20 turns, trimmed to fit context)
- A system prompt that sets the brand voice and tool list
- Per-tenant settings (escalation triggers, disallowed topics, etc.)

We never feed the model personally identifiable information (PII) that
the tenant has not authorized. Phone numbers are redacted in the prompt
(`+60XXXXXXXXX` → `+60***`). Email addresses are redacted similarly.

## 4. Evaluation

### 4.1 Internal evaluation

We run a curated evaluation set weekly against staging:

| Category | Sample size | Metric | Target | Last measured |
|---|---|---|---|---|
| Brand-voice consistency | 200 prompts | LLM-as-judge (1-5) | >= 4.0 | (TBD) |
| KB retrieval accuracy | 100 questions | Recall@10 | >= 0.85 | (TBD) |
| Escalation detection | 50 prompts | Precision/recall | F1 >= 0.90 | (TBD) |
| Refusal on out-of-scope | 50 prompts | Correct refusal rate | >= 0.95 | (TBD) |
| Latency P95 | rolling | seconds | <= 4.0s | (TBD) |
| Hallucinated prices/dates | 100 prompts | Hallucination rate | <= 0.05 | (TBD) |
| Cross-language quality | 80 prompts (4 langs) | Human eval (1-5) | >= 3.5 | (TBD) |

The eval set is versioned in `tests/eval/`. Results are recorded in
`docs/compliance/eval-history.md` (TBD).

### 4.2 External evaluation

- Google's own safety eval (Gemini 2.5 Flash model card, Section 6)
- Bijou does not run independent third-party red-team evals yet; tracked
  as a 30-day enhancement

### 4.3 Known limitations (from Google's model card)

- May generate plausible-but-wrong information — mitigated by RAG and
  the confidence score
- May struggle with very recent events (knowledge cutoff 2025-01) —
  mitigated by per-tenant KB overrides
- May produce biased outputs reflecting training data — mitigated by the
  brand-voice system prompt and the Inbox Co-pilot review

## 5. Ethical considerations

- **Bias:** we monitor for biased outputs (gender, ethnicity, religion)
  in the brand-voice eval. No statistically significant bias detected as
  of 2026-08-23.
- **Privacy:** we do not send PII to the model without redaction; we do
  not use customer data to train any model; we do not log model
  responses beyond the reasoning-trace primitive.
- **Transparency:** every end user is told they're talking to an AI (see
  `docs/compliance/EU_AI_ACT_2024.md` §2 Article 50).
- **Human oversight:** the Inbox Co-pilot is a human-in-the-loop gate;
  the agent can override any AI reply.
- **Accountability:** Bijou AI (the company) is accountable for the
  system's behavior, not the end user or the tenant business.

## 6. Deployment

- **Inference:** server-side only; the model is never called from the
  client
- **Region:** configurable (US, EU, or APAC); EU pinning for EU-resident
  end users (issue #19 — multi-region Supabase — covers the data side)
- **Fallback:** on model error, Bijou falls back to a templated reply
  ("Sorry, let me get a human to help") and escalates to the human queue
- **Rollback:** the model version is pinned in the deploy manifest; a
  rollback to the previous version is a single-line change

## 7. Open work

- Live eval dashboard (currently offline; results in a markdown table)
- Independent third-party red-team (tracked, not scheduled)
- Eval history file (TBD)
- Comparison eval vs other models (Claude Haiku, GPT-4o-mini) — TBD
