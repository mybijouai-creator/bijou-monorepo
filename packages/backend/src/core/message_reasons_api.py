"""FastAPI router for the Reasoning Trace API (issue #11).

The "why did Bijou say what it said" primitive. When the AI generates a
response, the message handler records the reasoning (retrieved KB docs,
tool calls, model, confidence, alternatives) to public.message_reasons.
The Inbox side panel (next step) calls GET to surface the trace on tap.

This is the EU AI Act 2024 Article 13 traceability primitive. Without it,
the agent is a black box; with it, every reply is auditable.

All routes are behind verify_session so tenant_id always comes from the
authenticated session, never client input.

Mount in src/core/bijou.py _include_routers():

    from src.core.message_reasons_api import router as message_reasons_router
    app.include_router(message_reasons_router)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard/messages", tags=["message-reasons"])


def _supabase():
    """Return a Supabase client using the service-role key.

    Same pattern as src/core/shared_context_api.py. service_role bypasses
    RLS; the API layer filters by tenant_id from verify_session for isolation.
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


# ── Pydantic models ───────────────────────────────────────────────────────


class RetrievedDoc(BaseModel):
    doc_id: Optional[str] = None
    title: Optional[str] = None
    relevance: Optional[float] = None  # 0.0..1.0


class ToolCall(BaseModel):
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None


class AlternativeReply(BaseModel):
    text: str
    score: Optional[float] = None  # 0.0..1.0


class RecordReasonRequest(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=256)
    chat_jid: str = Field(..., min_length=1, max_length=256)
    channel: str = Field(default="whatsapp", max_length=32)
    retrieved_docs: List[RetrievedDoc] = Field(default_factory=list)
    tool_calls: List[ToolCall] = Field(default_factory=list)
    model: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    alternatives: List[AlternativeReply] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MessageReason(BaseModel):
    id: str
    tenant_id: str
    message_id: str
    chat_jid: str
    channel: str
    retrieved_docs: List[Dict[str, Any]]
    tool_calls: List[Dict[str, Any]]
    model: Optional[str] = None
    confidence: Optional[float] = None
    alternatives: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    created_at: str


class ReasonListResponse(BaseModel):
    reasons: List[MessageReason]
    count: int


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/reasons", response_model=MessageReason)
async def record_reason(
    req: RecordReasonRequest,
    tenant_id: str = Depends(verify_session),
):
    """Record the reasoning for an AI message.

    Called by the message handler (Bijou.py post-response hook) after every
    AI-generated reply. The (tenant_id, message_id) is the deduplication key
    — if you call this twice with the same (tenant, message_id), the second
    call updates the first instead of duplicating.

    Why a soft upsert: the message handler may retry the same response on
    transient errors, and we want exactly one reason row per AI message.
    """
    row = {
        "tenant_id": tenant_id,
        "message_id": req.message_id,
        "chat_jid": req.chat_jid,
        "channel": req.channel,
        "retrieved_docs": [d.model_dump() for d in req.retrieved_docs],
        "tool_calls": [t.model_dump() for t in req.tool_calls],
        "model": req.model,
        "confidence": req.confidence,
        "alternatives": [a.model_dump() for a in req.alternatives],
        "metadata": req.metadata,
    }
    try:
        # Upsert on (tenant_id, message_id) so a retry doesn't double-record.
        result = (
            _supabase()
            .table("message_reasons")
            .upsert(row, on_conflict="tenant_id,message_id")
            .execute()
        )
    except Exception as e:
        logger.error(
            "message_reasons upsert failed tenant=%s message_id=%s: %s",
            tenant_id, req.message_id, e,
        )
        raise HTTPException(status_code=500, detail="Could not record reasoning")

    data = getattr(result, "data", None) or []
    if not data:
        raise HTTPException(status_code=500, detail="Reasoning upsert returned no row")
    return data[0]


@router.get("/{message_id}/reason", response_model=MessageReason)
async def get_reason(
    message_id: str = Path(..., min_length=1, max_length=256),
    tenant_id: str = Depends(verify_session),
):
    """Fetch the reasoning for a single AI message.

    Returns 404 if no reason was recorded (e.g., the message pre-dates this
    feature, or it was a user message, not an AI response). The Inbox side
    panel calls this on tap and gracefully renders an empty state on 404.
    """
    try:
        result = (
            _supabase()
            .table("message_reasons")
            .select(
                "id, tenant_id, message_id, chat_jid, channel, retrieved_docs, "
                "tool_calls, model, confidence, alternatives, metadata, created_at"
            )
            .eq("tenant_id", tenant_id)
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error(
            "message_reasons get failed tenant=%s message_id=%s: %s",
            tenant_id, message_id, e,
        )
        raise HTTPException(status_code=500, detail="Could not load reasoning")

    rows = list(getattr(result, "data", None) or [])
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No reasoning recorded for this message (it may pre-date this feature).",
        )
    return rows[0]


@router.get("/reasons", response_model=ReasonListResponse)
async def list_recent_reasons(
    chat_jid: Optional[str] = None,
    since_hours: int = 24,
    limit: int = 50,
    tenant_id: str = Depends(verify_session),
):
    """List recent reasoning rows for the authenticated tenant.

    Used by the AI Activity Stream tab (issue #12) to render "what the AI
    just did" with full reasoning visible. Optional chat_jid filter for
    per-conversation views. Capped at 200 rows for safety.
    """
    since = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=since_hours)
    limit = min(max(limit, 1), 200)
    try:
        q = (
            _supabase()
            .table("message_reasons")
            .select(
                "id, tenant_id, message_id, chat_jid, channel, retrieved_docs, "
                "tool_calls, model, confidence, alternatives, metadata, created_at"
            )
            .eq("tenant_id", tenant_id)
            .gte("created_at", since.isoformat())
            .order("created_at", desc=True)
            .limit(limit)
        )
        if chat_jid:
            q = q.eq("chat_jid", chat_jid)
        result = q.execute()
    except Exception as e:
        logger.error("message_reasons list failed tenant=%s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not list reasoning rows")

    rows = list(getattr(result, "data", None) or [])
    return ReasonListResponse(reasons=rows, count=len(rows))
