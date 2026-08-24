# Bijou AI Gateway

> Single source of truth for how Bijou talks to LLMs. No code in the codebase
> should ever name a provider or model directly — everything goes through
> `await llm.complete("ai://<alias>", messages)`.

**Status:** Production. The v1 key-rotator (`src/core/llm_gateway.py`) is still
used internally to rotate **keys** within the Gemini provider. v2 adds the
**alias + cross-provider fallback** layer on top of it.

**Files:**
- Config: `packages/backend/llm_gateway.yaml`
- Module: `packages/backend/src/core/llm_gateway_v2.py`
- Tests:  `packages/backend/tests/unit/test_llm_gateway_v2.py` (28 tests)
- Usage log table: `public.llm_usage` (migration: `migrations-py/add_llm_usage.sql`)

---

## The four core aliases

| Alias         | Primary                          | When to use                                                                 | Privacy  | Daily cap |
|---------------|----------------------------------|-----------------------------------------------------------------------------|----------|-----------|
| `ai://fast`   | Gemini 2.5 Flash                 | Default chat replies — short, friendly, low-latency.                        | standard | $25       |
| `ai://reasoning` | Gemini 2.5 Flash (max 2048 tok) | Agent loop, tool-calling, complex KB lookups. Higher token cap.              | standard | $50       |
| `ai://extract`  | Gemini 2.5 Flash (temp 0.2)    | Structured JSON — handover detection, lead analysis, emotion tagging.        | standard | $10       |
| `ai://private`  | Gemini 2.5 Flash (temp 0.3)    | PDPA-sensitive customer PII. **Strict-only** — no OpenRouter fallback.       | strict   | $20       |

Plus two specialised aliases shipped in the same file:

- `ai://helpdesk` — `/api/help/chat` support widget (in-product).
- `ai://vision`   — image / document understanding (multimodal).

---

## Public surface

```python
from src.core.llm_gateway_v2 import llm

result = await llm.complete(
    "ai://reasoning",
    messages=[{"role": "user", "content": "What time does the clinic open?"}],
    temperature=0.7,        # optional override
    max_output_tokens=1024, # optional override
    tools=[...],           # optional OpenAI-format function declarations
    tenant_id="...",       # for per-tenant cost tracking
)

result.text           # str — the model's reply
result.provider       # "gemini" | "openai_compatible" | "openrouter"
result.model          # exact model that answered
result.alias          # the alias the caller used
result.fallback_reason  # None on primary, else "http_429" / "http_503" / ...
result.prompt_tokens  # int
result.completion_tokens  # int
result.cost_usd       # estimated USD
result.latency_ms     # int
result.function_calls  # [{"name": ..., "args": ...}] for tool calling
```

### Exceptions

- `BudgetExceeded(alias, spent, cap)` — daily cap hit. The caller should
  surface a 429 with `Retry-After` to the user.
- `NoProviderAvailable` — alias unknown, or every strict provider is missing
  keys. A config bug, not a transient failure.
- `ProviderError(status_code)` — every provider in the chain returned a
  non-fallback status (4xx). Config bug; do **not** retry automatically.

---

## How the fallback chain works

Each alias lists a `primary` and an ordered list of `fallbacks`. The gateway
walks the chain in order. The status codes that **trigger a fallback** are:

```
429, 500, 502, 503, 504
```

400/401/403/404 are **config bugs** and do **not** fall back — retrying would
hit the same wall. They surface to the caller as `ProviderError`.

A transport error (timeout, DNS, connection reset) is treated like a 5xx and
moves to the next provider.

If every provider in the chain fails, the gateway raises the last `ProviderError`.

---

## Privacy levels

Two values:

- `standard` (default) — any provider is allowed, including OpenRouter.
- `strict` — only `gemini` and `openai_compatible` (direct, paid APIs we
  control) are allowed. OpenRouter and free-pool aggregators are filtered out
  even if they're declared in the alias's fallback list.

Use `ai://private` for any prompt that contains:
- Customer PII (NRIC, phone, address, payment info)
- Account credentials
- Health or financial data subject to PDPA / GDPR / HIPAA-equivalents

If `ai://private` has no usable provider, the gateway refuses the call rather
than leaking to a multi-tenant aggregator. Better to return a friendly "I
can't help with that right now" than to log customer PII on someone else's
infrastructure.

---

## Adding a new provider

1. **Implement the adapter** in `src/core/llm_gateway_v2.py` if the new
   provider doesn't speak OpenAI's `/v1/chat/completions` shape. If it does,
   add an entry under `providers:` in `llm_gateway.yaml`:
   ```yaml
   providers:
     my_new_provider:
       type: openai_compatible
       env_keys: "MY_NEW_PROVIDER_API_KEY"
       base_url: "https://api.mynewprovider.com/v1"
   ```
   The existing `_call_openai_compatible` adapter handles the wire format
   automatically.

2. **Add cost data** under `cost_per_1k:`:
   ```yaml
   cost_per_1k:
     openai_compatible/my-fancy-model:
       input_usd: 0.001
       output_usd: 0.003
   ```

3. **Reference it** in any alias:
   ```yaml
   ai://fast:
     primary:
       provider: my_new_provider
       model: my-fancy-model
   ```

4. **Add a test** in `tests/unit/test_llm_gateway_v2.py` that injects a fake
   adapter for the new provider and asserts the alias resolves to it.

---

## Adding a new alias

1. Open `packages/backend/llm_gateway.yaml` and copy any block under
   `aliases:`. Change the key (e.g. `ai://booking`), pick a primary, list
   fallbacks, set a budget, set a privacy level.

2. In your code, call:
   ```python
   from src.core.llm_gateway_v2 import llm
   result = await llm.complete("ai://booking", messages)
   ```

3. Done. No Python code in the gateway needs to change — it's data-driven.

**Naming convention:** `ai://<role>`. The `<role>` is the *purpose* of the
call, not the model. `ai://booking`, `ai://summary`, `ai://moderation` are
good. Avoid `ai://gemini-2.5-flash` — that defeats the point of an alias.

---

## Budget enforcement

Each alias declares a `daily_budget_usd`. The gateway tracks per-alias daily
spend in process memory (`_UsageTracker`). When the next call would push
spend over the cap, it raises `BudgetExceeded` **before** hitting any
provider.

To persist daily spend to `public.llm_usage` (so the dashboard can chart it
and alerts can fire on overruns), call `llm.drain_usage()` periodically and
bulk-insert the rows. Recommended: a 1-minute cron, or a hook on the FastAPI
shutdown event.

```python
# cron / shutdown handler
rows = llm.drain_usage()
if rows:
    supabase.table("llm_usage").insert(rows).execute()
```

`llm.spent_today("ai://fast")` returns the current in-process spend (for
debugging or for the dashboard's "remaining budget" display).

---

## Cost observability

The dashboard reads from `public.llm_usage` (the migration creates the
table with three indexes optimised for the queries the dashboard actually
runs):

1. **Per-day per-alias spend** (for budget charts):
   ```sql
   select alias, sum(cost_usd) from public.llm_usage
   where created_at >= now() - interval '7 days'
   group by alias, date_trunc('day', created_at);
   ```
   Uses index `idx_llm_usage_alias_day`.

2. **Per-tenant per-day cost** (for billing / fairness):
   ```sql
   select tenant_id, sum(cost_usd) from public.llm_usage
   where tenant_id is not null
     and created_at >= now() - interval '30 days'
   group by tenant_id, date_trunc('day', created_at);
   ```
   Uses index `idx_llm_usage_tenant_day`.

3. **Failure triage** (which aliases are falling back most today?):
   ```sql
   select alias, fallback_reason, count(*) from public.llm_usage
   where fallback_reason is not null
     and created_at >= now() - interval '24 hours'
   group by alias, fallback_reason
   order by count(*) desc;
   ```
   Uses index `idx_llm_usage_fallback`.

The table is **service-role only** (RLS hardened per `CLAUDE.md`). The
dashboard reads via a server-side endpoint, not directly from the browser.

---

## Migration plan for new callsites

1. Identify the LLM call (look for `genai.Client`, `client.models.generate_content`,
   `chat.completions.create`, etc.).
2. Pick the right alias from the four core ones (or add a new one).
3. Convert the prompt to OpenAI-style messages: `[{"role", "content"}, ...]`.
4. For Gemini-specific `Part.from_bytes()` multimodal, use the OpenAI vision
   shape: `[{"type": "image_url", "image_url": {"url": "data:..."}}, {"type": "text", "text": "..."}]`.
5. Replace the call with `await llm.complete("ai://<alias>", messages, **opts)`.
6. For tool-calling, pass `tools=[{"type": "function", "function": {...}}]`
   and read `result.function_calls` instead of digging into provider-specific
   response objects.
7. Add a regression test using the test-seam (`gw._dispatch_override[provider] = fake`).

---

## What is NOT in scope

- **Streaming.** The gateway returns a single `CompletionResult` per call. If
  a feature needs streaming, that's a future `complete_stream()` method —
  not in this iteration.
- **Per-key load-balancing across providers.** v2's primary concern is
  *cross-provider* fallback. The existing `RoundRobinRotator` in
  `llm_gateway.py` still handles Gemini **key**-level rotation.
- **Prompt caching.** Not implemented. Add a `cache_key` opt later if the
  Gemini cache-control feature proves valuable.
- **Automatic model selection from prompt content.** The user picks the
  alias; the gateway picks the provider. There's no "use the cheapest model
  that can do X" logic in v2.
