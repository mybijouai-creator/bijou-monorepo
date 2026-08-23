"""FastAPI router for the A2A shared-context layer.

Stores cross-channel conversation state per (tenant_id, customer_phone) so
the WhatsApp agent and the forthcoming Telnyx voice agent can hand off
context to each other. Foundation step of issue #23
(https://github.com/mybijouai-creator/bijou-monorepo/issues/23).

All routes are behind verify_session so tenant_id always comes from the
authenticated session, never client input. The DB layer enforces the same
tenant_id filter on every query — a request that somehow lost its session
cannot see another tenant's rows.

Mount in the main app (see src/core/bijou.py _include_routers()):

    from src.core.shared_context_api import router as shared_context_router
    app.include_router(shared_context_router)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shared-context", tags=["shared-context"])

# Allowed channel and role values. Kept in sync with the DB CHECK constraints
# defined in migrations-py/add_shared_context.sql. The Python-side check lets
# us return a clean 400 before the round-trip to Supabase; the DB check is the
# last line of defence.
_ALLOWED_CHANNELS = {"whatsapp", "telegram", "voice", "sms", "email"}
_ALLOWED_ROLES = {"user", "assistant", "system"}


def _supabase():
    """Return a Supabase client using the service-role key.

    Mirrors the pattern in src/connectors/nango_api.py — read the URL and
    service key from env at call time, raise if either is missing. service_role
    bypasses RLS (RLS is enabled on public.shared_context but has no
    permissive policies, per the v6 RLS hardening pass).
    """
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


# ── Pydantic models ──────────────────────────────────────────────────────────


class AppendRequest(BaseModel):
    customer_phone: str = Field(..., min_length=1, max_length=64)
    channel: str = Field(..., min_length=1, max_length=32)
    thread_id: str = Field(..., min_length=1, max_length=256)
    role: str = Field(..., min_length=1, max_length=32)
    content: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AppendResponse(BaseModel):
    id: str
    tenant_id: str
    customer_phone: str
    channel: str
    thread_id: str
    role: str
    content: str
    metadata: Dict[str, Any]
    created_at: str


class ContextEntry(BaseModel):
    id: str
    tenant_id: str
    customer_phone: str
    channel: str
    thread_id: str
    role: str
    content: str
    metadata: Dict[str, Any]
    created_at: str


class ContextListResponse(BaseModel):
    entries: List[ContextEntry]
    count: int


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/append", response_model=AppendResponse)
async def append_entry(req: AppendRequest, tenant_id: str = Depends(verify_session)):
    """Append a new shared-context entry for the authenticated tenant.

    Used by the WhatsApp agent and the forthcoming Telnyx voice agent to log
    every user/assistant/system turn. The (tenant_id, customer_phone) pair
    is the unified thread key; thread_id is the per-channel handle
    (chat_jid for WhatsApp, call_id for voice, etc.).
    """
    if req.channel not in _ALLOWED_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel '{req.channel}'. Allowed: {sorted(_ALLOWED_CHANNELS)}",
        )
    if req.role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{req.role}'. Allowed: {sorted(_ALLOWED_ROLES)}",
        )

    row = {
        "tenant_id": tenant_id,
        "customer_phone": req.customer_phone,
        "channel": req.channel,
        "thread_id": req.thread_id,
        "role": req.role,
        "content": req.content,
        "metadata": req.metadata,
    }
    try:
        result = _supabase().table("shared_context").insert(row).execute()
    except Exception as e:
        logger.error("shared_context append failed for tenant=%s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not append shared-context entry")

    data = getattr(result, "data", None) or []
    if not data:
        # Supabase returned no row — treat as a hard error so the caller knows
        # the write didn't land (otherwise silent data loss is worse).
        raise HTTPException(status_code=500, detail="Shared-context insert returned no row")
    return data[0]


@router.get("", response_model=ContextListResponse)
async def list_entries(
    phone: str = Query(..., min_length=1, max_length=64, description="Customer phone, normalized digits-only"),
    since_hours: int = Query(24, ge=1, le=24 * 30, description="Look back this many hours; max 30 days"),
    limit: int = Query(50, ge=1, le=500, description="Max rows to return"),
    tenant_id: str = Depends(verify_session),
):
    """Unified thread view across all channels for a given customer.

    Returns the most recent entries for the authenticated tenant + the
    requested phone, sorted newest first. Channels are interleaved in the
    result so a UI can render a single chronological transcript.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    try:
        result = (
            _supabase()
            .table("shared_context")
            .select(
                "id, tenant_id, customer_phone, channel, thread_id, role, "
                "content, metadata, created_at"
            )
            .eq("tenant_id", tenant_id)
            .eq("customer_phone", phone)
            .gte("created_at", since.isoformat())
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as e:
        logger.error("shared_context list failed for tenant=%s phone=%s: %s", tenant_id, phone, e)
        raise HTTPException(status_code=500, detail="Could not load shared-context entries")

    rows = list(getattr(result, "data", None) or [])
    return ContextListResponse(entries=rows, count=len(rows))
