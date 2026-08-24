"""Voice orchestrator — STUB.

The real implementation will be adapted from
`w3j-projects/telnyx/W3J-BIJOU PROJECT/voice/ai/orchestrator.py`:

    - The original reads from a `tenants` table in the standalone project.
      The Bijou version reads from `public.tenants` (same schema, different
      Supabase project) via `TenantConfigClient`.

    - The original writes to its own `transcript_chunks` table.
      The Bijou version writes to `public.shared_context` (channel='voice',
      thread_id=<telnyx_call_control_id>).

    - The original uses MiniMax as the LLM.
      The Bijou version uses Bijou's gateway (ai://reasoning alias) for
      consistency with the WhatsApp agent.

This file is a STUB so the package structure is correct + the FastAPI
app boots. The real orchestrator lands after Coolify backend+bridge
are deployed (gating condition per AGENT.md).
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from .shared_context import SharedContextClient, SharedContextTurn

logger = logging.getLogger(__name__)


class CallContext(BaseModel):
    """Per-call state passed through the orchestrator."""
    call_id: str
    tenant_id: str
    customer_phone: str
    voice_number: str
    started_at: float  # epoch seconds


class VoiceOrchestrator:
    """Coordinates one voice call: greeting, gather, LLM, TTS, hangup.

    Current state: skeleton. The real implementation (transcribed below
    as TODOs) lands when the W3J-BIJOU PROJECT orchestrator is ported.

    Lifecycle:
      1. call.initiated  -> __call__() resolves tenant + fetches recent
                            shared_context, returns a greeting text
      2. call.gather     -> on_user_turn() takes the transcribed text,
                            runs the LLM, returns the reply + actions
      3. call.hangup     -> on_call_end() writes the summary turn to
                            shared_context

    This stub does the read (so the greeting can mention prior history)
    and the write (so the summary lands) but returns a hard-coded reply.
    The LLM call is a TODO.
    """

    def __init__(self, shared_context: SharedContextClient, llm_gateway_url: Optional[str] = None):
        self._ctx = shared_context
        self._llm_url = llm_gateway_url or "http://bijou-backend:8080"

    async def greeting(self, ctx: CallContext) -> str:
        """Return the text the voice concierge should say when answering.

        Surfaces recent WhatsApp history if any (e.g. "Hi, last time we
        spoke you asked about X. Is that still the topic?").
        """
        recent = await self._ctx.get_recent_context(
            tenant_id=ctx.tenant_id,
            customer_phone=ctx.customer_phone,
            since_hours=24,
            limit=6,
        )
        if recent:
            last_wa = next((t for t in recent if t.channel == "whatsapp"), None)
            if last_wa:
                return (
                    f"Hi! Welcome back. Last time you messaged us about: "
                    f"{last_wa.content[:120]}. How can I help today?"
                )
        return "Hi! Thanks for calling. How can I help you today?"

    async def on_user_turn(
        self,
        ctx: CallContext,
        user_text: str,
    ) -> str:
        """Process one caller utterance, return the TTS reply.

        TODO: replace stub with LLM call. The Bijou LLM gateway is at
        self._llm_url + '/api/llm/complete', takes the alias='ai://reasoning'
        pattern, and supports function-calling for KB fetch + escalation.
        """
        logger.warning(
            "🤖 orchestrator.on_user_turn is a STUB — replying with placeholder. "
            "Replace with real LLM call after Coolify backend is up."
        )
        return f"You said: {user_text}. (STUB: real LLM reply lands after Coolify deploy.)"

    async def on_call_end(
        self,
        ctx: CallContext,
        transcript: List[Dict[str, str]],
    ) -> str:
        """Persist a summary turn of the call to shared_context.

        `transcript` is a list of {role, content, ts} dicts. We write ONE
        turn (the assistant summary) — the full transcript goes to the
        calls table once issue #18 (call recording + transcript UI) is done.
        """
        n_user = sum(1 for t in transcript if t.get("role") == "user")
        n_assistant = sum(1 for t in transcript if t.get("role") == "assistant")
        summary = (
            f"Voice call ended. {n_user} caller turns, {n_assistant} assistant turns. "
            f"Call ID: {ctx.call_id}."
        )
        return await self._ctx.append_voice_turn(
            tenant_id=ctx.tenant_id,
            customer_phone=ctx.customer_phone,
            call_id=ctx.call_id,
            role="system",
            content=summary,
            metadata={
                "duration_s": int(__import__("time").time() - ctx.started_at),
                "transcript_turns": len(transcript),
            },
        )
