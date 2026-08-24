"""Shared context client — the A2A bridge between voice and WhatsApp.

Reads the most recent cross-channel turns for a phone (so a voice caller
with prior WhatsApp history gets greeted with that context) and writes
a summary turn when the voice call ends (so the next WhatsApp message
from the same phone sees the voice-call summary).

Schema (packages/backend/migrations-py/add_shared_context.sql):
  public.shared_context(
    id uuid pk,
    tenant_id uuid not null,
    customer_phone text not null,
    channel text check in ('whatsapp','telegram','voice','sms','email'),
    thread_id text not null,         -- chat_jid for WA, call_id for voice
    role text check in ('user','assistant','system'),
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz default now()
  )

RLS is enabled (service_role bypasses). All writes go through
SUPABASE_SERVICE_KEY. We never accept a `tenant_id` from the caller —
it always comes from the authenticated webhook or the JWT.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from supabase import Client, create_client

logger = logging.getLogger(__name__)


# ─── Channel + role enums (mirror the SQL CHECK constraints) ───────────
CHANNELS = ("whatsapp", "telegram", "voice", "sms", "email")
ROLES = ("user", "assistant", "system")


class SharedContextTurn(BaseModel):
    """One turn in the cross-channel conversation history."""
    id: str
    tenant_id: str
    customer_phone: str
    channel: str
    thread_id: str
    role: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# ─── Client ─────────────────────────────────────────────────────────────

class SharedContextClient:
    """Thin wrapper around the Bijou Supabase `shared_context` table.

    Constructed once per process (the Supabase client is connection-pooled
    under the hood). All methods are async-safe; Supabase-py 2.x is sync
    but the per-call latency is dominated by the network round-trip so
    we wrap in `asyncio.to_thread` for the hot paths.
    """

    def __init__(self, supabase_url: str, supabase_service_key: str):
        if not supabase_url or not supabase_service_key:
            raise ValueError(
                "SharedContextClient requires SUPABASE_URL and "
                "SUPABASE_SERVICE_KEY (service role, not anon)"
            )
        self._url = supabase_url
        self._key = supabase_service_key
        self._sb: Client = create_client(supabase_url, supabase_service_key)
        logger.info("📋 SharedContextClient initialised against %s", _safe_host(supabase_url))

    @staticmethod
    def _validate(channel: str, role: str) -> None:
        if channel not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}, got {channel!r}")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, got {role!r}")

    async def get_recent_context(
        self,
        *,
        tenant_id: str,
        customer_phone: str,
        since_hours: int = 24,
        limit: int = 20,
        channels: Optional[List[str]] = None,
    ) -> List[SharedContextTurn]:
        """Return the most recent cross-channel turns for this phone, newest first.

        Args:
            tenant_id: From the authenticated webhook or JWT — NEVER from caller input.
            customer_phone: E.164 or local — the phone number we're looking up.
            since_hours: Window of recency. Default 24h covers a full day of WA traffic.
            limit: Hard cap on returned rows. Default 20 (≈ 10 exchanges).
            channels: Optional filter; default returns all channels.
        """
        if not tenant_id or not customer_phone:
            raise ValueError("tenant_id and customer_phone are required")

        def _query():
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
            q = (
                self._sb.table("shared_context")
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("customer_phone", customer_phone)
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if channels:
                q = q.in_("channel", channels)
            return q.execute()

        result = await _async(_query)
        rows = result.data or []
        turns = [SharedContextTurn(**row) for row in rows]
        logger.debug(
            "📋 get_recent_context tenant=%s phone=%s -> %d turns",
            tenant_id[:8], customer_phone[-4:], len(turns),
        )
        return turns

    async def append_voice_turn(
        self,
        *,
        tenant_id: str,
        customer_phone: str,
        call_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append one turn to the voice thread. Returns the new turn's id.

        Convenience wrapper around the more general `append_turn` that
        hard-codes `channel='voice'` and `thread_id=<call_id>`.
        """
        return await self.append_turn(
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            channel="voice",
            thread_id=call_id,
            role=role,
            content=content,
            metadata=metadata,
        )

    async def append_turn(
        self,
        *,
        tenant_id: str,
        customer_phone: str,
        channel: str,
        thread_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append one turn. Validates channel + role against SQL CHECKs.

        Returns the inserted row's id. Raises on DB error (the caller
        should buffer to disk if the error is transient — see AGENT.md
        "Failure modes" table).
        """
        self._validate(channel, role)
        if not tenant_id or not customer_phone or not thread_id:
            raise ValueError("tenant_id, customer_phone, thread_id are required")
        if not content:
            raise ValueError("content is required (empty messages are not stored)")

        row = {
            "tenant_id": tenant_id,
            "customer_phone": customer_phone,
            "channel": channel,
            "thread_id": thread_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }

        def _insert():
            return self._sb.table("shared_context").insert(row).execute()

        result = await _async(_insert)
        if not result.data:
            raise RuntimeError("shared_context insert returned no rows (RLS denial?)")
        inserted_id = result.data[0]["id"]
        logger.info(
            "📋 shared_context.INSERT tenant=%s phone=%s channel=%s role=%s -> %s",
            tenant_id[:8], customer_phone[-4:], channel, role, inserted_id[:8],
        )
        return inserted_id


# ─── helpers ────────────────────────────────────────────────────────────

import asyncio
from typing import Callable, TypeVar

T = TypeVar("T")


async def _async(fn: Callable[[], T]) -> T:
    """Run a sync callable in a thread, await the result.

    Supabase-py 2.x is sync; offloading to a thread keeps the event loop
    free. We use a small wrapper rather than `asyncio.to_thread` directly
    so the call site reads naturally as `await client.get_recent_context(...)`.
    """
    return await asyncio.to_thread(fn)


def _safe_host(url: str) -> str:
    """Return just the host part of a Supabase URL for log lines (avoids
    leaking the project ref into every log message)."""
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        return u.netloc or url
    except Exception:
        return url[:32] + "…"


# ─── Module-level singleton ────────────────────────────────────────────
_client: Optional[SharedContextClient] = None


def get_shared_context_client() -> SharedContextClient:
    """Return (or create) the process-wide SharedContextClient singleton.

    Reads SUPABASE_URL + SUPABASE_SERVICE_KEY from env at first call.
    Raises if the env vars are missing.
    """
    import os
    global _client
    if _client is None:
        _client = SharedContextClient(
            supabase_url=os.environ["SUPABASE_URL"],
            supabase_service_key=os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client
