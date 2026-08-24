# Bijou Voice

Telnyx-backed voice AI that shares conversation state with the
WhatsApp agent. See `AGENT.md` for the full design + A2A contract.

## Status: 2026-08-24 — skeleton only

This directory contains:
- `AGENT.md` — full design + A2A contract
- `Dockerfile.voice` — container build (for the Coolify path)
- `requirements.txt` — Python deps
- `pyproject.toml` — package metadata
- `src/` — code modules (orchestrator, telnyx_webhook, shared_context, etc.)

It does NOT yet contain:
- A working voice orchestrator (needs to be adapted from
  `w3j-projects/telnyx/W3J-BIJOU PROJECT/voice/ai/orchestrator.py`)
- Tests (will be added when the orchestrator is ported)
- A live Telnyx webhook receiver (needs real API keys + HTTPS endpoint)

## Local dev

```bash
# Install deps
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run with mock env (won't make real calls)
SUPABASE_URL=http://localhost:54321 \
SUPABASE_SERVICE_KEY=dummy \
TELNYX_API_KEY=dummy \
BIJOU_API_KEY=dummy \
uvicorn src.main:app --reload --port 8100
```

Then:
- `GET /health` — 200 OK
- `GET /api/voice/tenants` — list tenants the voice service knows about
- `POST /webhook/telnyx/{tenant_id}` — Telnyx webhook receiver (returns
  400 if signature invalid, 200 OK if accepted)

## When this becomes real

1. Coolify backend + bridge deployed (runbook: `ops/coolify/FIRST-DEPLOY-30MIN.md`)
2. Adapt `voice/ai/orchestrator.py` from W3J-BIJOU PROJECT — replace its
   `orgs` lookup with Bijou `tenants` lookup, share the `shared_context`
   table instead of the standalone `shared_context` (or migrate)
3. Add the 4th Coolify resource for `bijou-voice` (see `docker-compose.coolify.yml`)
4. Wire Telnyx webhook on a real phone number
5. Add tests + runbook

## Out of scope (separate issues)

- Issue #27 — full W3J-BIJOU PROJECT move into `packages/voice/`
- Issue #28 — wire Telnyx voice concierge to Bijou Supabase
- Issue #21 — shared-nervous-system EPIC
