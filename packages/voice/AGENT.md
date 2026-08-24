# Bijou Voice (packages/voice/)

Bijou's voice concierge — Telnyx-backed voice AI that shares conversation
state with the WhatsApp agent via the A2A shared_context table.

## What this package is

A FastAPI service that:
- Receives Telnyx voice webhooks (call.started, call.answered, call.ended)
- Runs an LLM-based voice orchestrator (the existing `AIOrchestrator` from
  `w3j-projects/telnyx/W3J-BIJOU PROJECT/voice/ai/orchestrator.py`, adapted
  to read tenant config + KB from Bijou Supabase)
- Reads the latest `shared_context` turns for the caller's phone so a
  voice caller with prior WhatsApp history gets greeted with that context
- Writes a summary turn to `shared_context` (channel='voice') when the
  call ends, so the next WhatsApp message from the same phone sees the
  voice-call summary
- Mints a service-to-service JWT signed with `BIJOU_API_KEY` for calls
  back to the Bijou backend (knowledge base fetch, billing events, etc.)

## What this package is NOT

- A wholesale copy of `w3j-projects/telnyx/W3J-BIJOU PROJECT/`. That
  project stays standalone for now; the move is tracked in issue #27.
- A deployment-ready service. The Coolify path needs to be unblocked first
  (runbook: `ops/coolify/FIRST-DEPLOY-30MIN.md`). The current state is
  "shape that matches Bijou's other packages; service to be wired and
  deployed after Coolify backend+bridge are live".

## Layout (planned)

```
packages/voice/
  src/
    main.py                — FastAPI app, mounts all routers
    orchestrator.py        — voice AI loop (adapted from W3J-BIJOU PROJECT)
    telnyx_webhook.py      — call.started/ended handlers
    shared_context.py      — Supabase client (read/write shared_context)
    tenant_config.py       — read tenant + KB from Bijou Supabase
    escalation.py          — human handoff (per tenant's on-call agent)
    auth.py                — service-to-service JWT (BIJOU_API_KEY signed)
    models.py              — Pydantic models for the public API
  tests/
    unit/
      test_orchestrator.py
      test_shared_context.py
  Dockerfile.voice
  requirements.txt
  pyproject.toml           — package metadata (for type-check + future pip install -e)
  AGENT.md                 — this file
  README.md                — quickstart for the user
```

## Shared context contract (A2A with WhatsApp agent)

The WhatsApp agent writes to `shared_context` with:
- `channel = 'whatsapp'`
- `thread_id = <chat_jid>` (e.g. `60174106981@s.whatsapp.net`)
- `role = 'user' | 'assistant' | 'system'`
- `content = <message text>`
- `metadata = { "msg_id": "..." }`

The voice concierge reads these for the caller's phone and writes
back with:
- `channel = 'voice'`
- `thread_id = <telnyx_call_control_id>` (e.g. `v3:abc123`)
- `role = 'assistant'` for AI turns, `'user'` for caller turns (transcribed)
- `content = <text>`
- `metadata = { "duration_s": 123, "transferred": false, "agent_id": "..." }`

Read API (used by voice orchestrator at call pickup):

```python
async def get_recent_context(
    supabase: Client,
    tenant_id: str,
    customer_phone: str,
    since_hours: int = 24,
    limit: int = 20,
) -> list[SharedContextTurn]:
    """Returns the most recent cross-channel turns for this phone, newest first.
    Used for the voice greeting: 'Hi, last time we spoke you asked about X.'"""
```

Write API (called at call end):

```python
async def append_voice_turn(
    supabase: Client,
    tenant_id: str,
    customer_phone: str,
    call_id: str,
    role: str,           # 'user' | 'assistant' | 'system'
    content: str,
    metadata: dict = {},
) -> None:
    """Append one turn to the voice thread in shared_context."""
```

## Telnyx integration (one-page)

Voice service binds to a single Telnyx phone number per tenant. Webhook
URL: `https://<voice-host>/webhook/telnyx/{tenant_id}`. Events handled:

| Telnyx event | Voice service action |
|---|---|
| `call.initiated` | Look up tenant + on-call agent; start orchestrator |
| `call.answered` | TTS greeting with prior `shared_context` if any |
| `call.gather.ended` (DTMF/speech) | Send to LLM, TTS reply |
| `call.speak.ended` | (passive) wait for next gather |
| `call.hangup` | End orchestrator, write summary turn |
| `call.dtmf` | Forward to orchestrator (for IVR-style flows) |

Outbound events: `call.speak`, `call.gather`, `call.hangup`, `call.transfer`.

## Env vars (set in Coolify env-group)

| Var | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | yes | same as backend |
| `SUPABASE_SERVICE_KEY` | yes | service-role key, RLS bypass |
| `BIJOU_API_KEY` | yes | used to sign service-to-service JWTs |
| `BIJOU_BACKEND_URL` | yes | e.g. `http://bijou-backend:8080` |
| `TELNYX_API_KEY` | yes | org API key from Telnyx portal |
| `TELNYX_PUBLIC_KEY` | yes | for webhook signature verification |
| `TELNYX_WEBHOOK_SECRET` | optional | if set, verify HMAC on every webhook |
| `VOICE_DEFAULT_VOICE` | optional | Telnyx TTS voice_id, default `en-US-Neural2-A` |
| `VOICE_MAX_CALL_SECONDS` | optional | hard cap, default 900 (15 min) |
| `BIJOU_GEMINI_FALLBACK_KEY` | optional | key to use if primary is suspended |

## Gating conditions (none of this works without these)

1. **Coolify backend + bridge deployed and healthy** — the voice service
   needs `bijou-backend` reachable at `http://bijou-backend:8080` for
   knowledge-base fetch, billing events, and `shared_context` reads.
2. **Migrations applied** to Bijou Supabase — `add_shared_context.sql` is
   in `packages/backend/migrations-py/`.
3. **Real Gemini key** (or other LLM provider) — current `.env` key is
   suspended by Google (`CONSUMER_SUSPENDED`).

## Failure modes (handled)

| Failure | Behavior |
|---|---|
| Voice service can't reach Bijou backend | Use local LLM with cached tenant config; log warning; continue |
| Bijou backend down | Use in-memory cache (last 5 tenants seen); fail closed on write |
| shared_context write fails | Buffer turn in local file `/tmp/voice-buffered.jsonl`; replay on next successful write |
| Schema drift (table missing column) | Refuse to start; surface clear error in health check |
| Telnyx webhook signature invalid | Drop the event; log; never process unverified webhooks |
| Caller phone matches no Bijou tenant | Route to platform-admin tenant (if configured) or play "sorry, we don't recognize this number" |

## Acceptance criteria (when this ships)

- Voice caller with prior WhatsApp history (last 24h, ≤ 20 turns) gets
  that history surfaced in the voice greeting
- WhatsApp message arriving during an active voice call surfaces the
  call status in the Bijou dashboard's Call tab
- Call records (caller, transcript, summary) appear in `shared_context`
  with `channel='voice'`, queryable from Bijou's API
- Idempotent tests for the shared_context read/write
- One live demo call per tenant (manual), verified end-to-end
