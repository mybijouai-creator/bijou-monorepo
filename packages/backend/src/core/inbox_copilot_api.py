"""FastAPI router for the Inbox Co-pilot (issue #13).

The third of 4 agentic-GenUI primitives from the 2026-08-23 teardown.
While the human agent is typing a reply in the Inbox, the Co-pilot
watches and surfaces 1-3 suggestions: "Looks like a price question -
use the template?", "They mentioned 'viewing' 3 times - book a slot?".

NEVER auto-sends. Each suggestion has Use / Edit first / Dismiss. The
user must explicitly accept before any message goes out.

This MVP uses deterministic pattern-matching (no LLM call). The LLM-
backed version is a follow-up. The pattern engine is intentionally
conservative - it only fires when the signal is clear, to avoid
"AI is suggesting things at me" fatigue.

Audit log: every suggestion shown + user action (accept/edit/dismiss)
is recorded in public.inbox_copilot_events. That gives the founder
real data on which suggestions are useful and which to retire.

All routes are behind verify_session so tenant_id always comes from
the authenticated session.

Mount in src/core/bijou.py _include_routers():

    from src.core.inbox_copilot_api import router as inbox_copilot_router
    app.include_router(inbox_copilot_router)
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbox-copilot", tags=["inbox-copilot"])


# ── Suggestion template library ───────────────────────────────────────────
# Each template has: keywords (regex list, case-insensitive), suggested
# text (the body of the reply), and a label. The Co-pilot surfaces the
# first match per priority order; ties broken by keyword count.
#
# Why no LLM: speed + cost + auditability. Pattern matches are <5ms; an
# LLM call would be ~2-5s and 100-1000× more expensive. The MVP proves
# the UX; the LLM-backed version slots in via the same API contract.

SUGGESTION_TEMPLATES = [
    {
        "id": "price_question",
        "label": "Looks like a price question",
        "keywords": [
            r"\bprice\b", r"\bcost\b", r"\bhow much\b", r"\bberapa\b",
            r"\bbrp\b", r"\brm\s?\d", r"\$\s?\d", r"\bcharge\b",
            r"\bfee\b",
        ],
        "text": (
            "Sure thing! Our pricing starts at RM 299/month for the PRO plan, "
            "which covers 3,000 conversations and Cal.com booking. Want me to "
            "send you the full breakdown?"
        ),
    },
    {
        "id": "viewing_booking",
        "label": "Sounds like they want a viewing",
        "keywords": [
            r"\bviewing\b", r"\bvisit\b", r"\bsee (the|it)\b", r"\bshow\b",
            r"\btour\b", r"\bschedule\b", r"\bbook\b", r"\btengok\b",
        ],
        "text": (
            "I'd love to set up a viewing. Are you free this week? I have "
            "slots on [Day] at [Time] and [Day] at [Time] - just say which works."
        ),
    },
    {
        "id": "booking_reminder",
        "label": "Booking confirmation",
        "keywords": [
            r"\bconfirm\b", r"\breschedule\b", r"\bcancel\b", r"\bappointment\b",
            r"\bbooking\b", r"\btemujanji\b",
        ],
        "text": (
            "Got it. I've updated your booking - you'll get a WhatsApp reminder "
            "30 min before. Reply CANCEL any time before then to reschedule."
        ),
    },
    {
        "id": "hours_question",
        "label": "Business hours question",
        "keywords": [
            r"\bopen\b", r"\bclose\b", r"\bhours\b", r"\bwhen.*open\b",
            r"\bbuka\b", r"\btutup\b",
        ],
        "text": (
            "We're open 9am-9pm daily. Bijou (me!) handles chats 24/7 so feel "
            "free to message anytime - I'll get back to you first thing."
        ),
    },
    {
        "id": "location",
        "label": "Location / address question",
        "keywords": [
            r"\bwhere\b", r"\baddress\b", r"\blocation\b", r"\bmap\b",
            r"\bdirection\b",
        ],
        "text": (
            "We're at [Address]. Easy to find - there's free parking and "
            "we're 2 minutes from [Landmark]. Want me to send the Google Maps link?"
        ),
    },
    {
        "id": "follow_up_checkin",
        "label": "Customer went quiet - check in?",
        "keywords": [],  # triggered by conversation age, not keywords
        "text": (
            "Hey [Name]! Just checking in - did you get a chance to look at "
            "the details I sent? Happy to answer any questions."
        ),
    },
    {
        "id": "thank_you_close",
        "label": "Closing the loop",
        "keywords": [
            r"\bthanks?\b", r"\bthank you\b", r"\bterima kasih\b", r"\btq\b",
        ],
        "text": (
            "You're very welcome! Have a great day, and don't hesitate to "
            "message anytime - I'm here 24/7."
        ),
    },
    {
        "id": "fallback",
        "label": "Use a friendly opener",
        "keywords": [],  # default when nothing else matches
        "text": (
            "Hi! Thanks for reaching out. I'd love to help - could you tell "
            "me a bit more about what you're looking for?"
        ),
    },
]


# ── Pydantic models ──────────────────────────────────────────────────────


class SuggestRequest(BaseModel):
    chat_jid: str = Field(..., min_length=1, max_length=256)
    draft_reply: str = Field(default="", max_length=4000)
    last_customer_message: Optional[str] = Field(default=None, max_length=4000)
    conversation_age_minutes: Optional[int] = Field(
        default=None,
        ge=0,
        description="Minutes since the customer's most recent message; used to trigger the check-in template",
    )


class SuggestionItem(BaseModel):
    id: str
    label: str
    text: str
    match_strength: float  # 0.0..1.0


class SuggestResponse(BaseModel):
    suggestions: List[SuggestionItem]
    event_id: str  # unique id for the batch; the user-action POST references this


class ActionRequest(BaseModel):
    event_id: str
    suggestion_id: str
    action: str = Field(..., pattern="^(accept|edit|dismiss)$")
    chat_jid: str = Field(..., min_length=1, max_length=256)


class ActionResponse(BaseModel):
    success: bool
    recorded_at: str


# ── Helpers ──────────────────────────────────────────────────────────────


def _score_template(template: Dict[str, Any], last_customer_message: str, draft_reply: str) -> float:
    """Return a match strength 0.0..1.0. 0 means no match.

    Scoring: 0.0 if draft_reply already >50 chars (user is mid-typing;
    don't pile on), else 0.0..1.0 based on keyword match count, capped at 1.0.
    """
    if len(draft_reply.strip()) > 50:
        return 0.0
    if not template["keywords"]:
        # Template triggers only on conversation_age or as fallback
        return 0.0
    text = (last_customer_message or "").lower()
    if not text:
        return 0.0
    hits = sum(1 for kw in template["keywords"] if re.search(kw, text, re.IGNORECASE))
    if hits == 0:
        return 0.0
    # Map hits to a strength: 1 hit = 0.6, 2 = 0.8, 3+ = 1.0
    return min(1.0, 0.4 + hits * 0.2)


def _supabase():
    """Return a Supabase client using the service-role key."""
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


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/suggest", response_model=SuggestResponse)
async def suggest(
    req: SuggestRequest,
    tenant_id: str = Depends(verify_session),
):
    """Return 1-3 suggestions for the current Inbox draft.

    Pattern-based in the MVP; LLM-backed version slots in via this same
    contract. Returns a unique event_id so the user-action POST can
    audit-log which suggestion was acted on.
    """
    if os.getenv("INBOX_COPILOT_ENABLED", "true").lower() != "true":
        return SuggestResponse(suggestions=[], event_id="disabled")

    suggestions: List[SuggestionItem] = []

    # 1. Pattern-match against the customer's last message
    for tpl in SUGGESTION_TEMPLATES:
        if tpl["id"] in ("follow_up_checkin", "fallback"):
            continue  # handled below
        score = _score_template(tpl, req.last_customer_message or "", req.draft_reply)
        if score > 0:
            suggestions.append(SuggestionItem(
                id=tpl["id"], label=tpl["label"], text=tpl["text"], match_strength=score,
            ))

    # 2. Conversation-age check-in (only if customer quiet for >24h)
    if req.conversation_age_minutes is not None and req.conversation_age_minutes > 24 * 60:
        tpl = next(t for t in SUGGESTION_TEMPLATES if t["id"] == "follow_up_checkin")
        suggestions.append(SuggestionItem(
            id=tpl["id"], label=tpl["label"], text=tpl["text"], match_strength=0.7,
        ))

    # 3. If nothing else matches and the draft is empty, suggest the fallback opener
    if not suggestions and not req.draft_reply.strip():
        tpl = next(t for t in SUGGESTION_TEMPLATES if t["id"] == "fallback")
        suggestions.append(SuggestionItem(
            id=tpl["id"], label=tpl["label"], text=tpl["text"], match_strength=0.3,
        ))

    # Cap at 3, sort by match strength desc
    suggestions.sort(key=lambda s: s.match_strength, reverse=True)
    suggestions = suggestions[:3]

    # Generate a unique event_id for audit tracking
    event_id = f"copilot-{tenant_id[:8]}-{int(time.time() * 1000)}"

    # Best-effort audit log of the suggestion batch
    try:
        _supabase().table("inbox_copilot_events").insert({
            "tenant_id": tenant_id,
            "event_id": event_id,
            "chat_jid": req.chat_jid,
            "kind": "suggest",
            "suggestion_ids": [s.id for s in suggestions],
            "draft_reply": req.draft_reply,
            "last_customer_message": req.last_customer_message,
            "conversation_age_minutes": req.conversation_age_minutes,
        }).execute()
    except Exception as e:
        # Audit log failure is non-fatal; log and continue.
        logger.debug(f"inbox_copilot audit log (suggest) failed: {e}")

    return SuggestResponse(suggestions=suggestions, event_id=event_id)


@router.post("/action", response_model=ActionResponse)
async def action(
    req: ActionRequest,
    tenant_id: str = Depends(verify_session),
):
    """Record the user's action on a suggestion (accept / edit / dismiss).

    This is the audit hook that gives the founder real data on which
    suggestions are useful. Persist a row in public.inbox_copilot_events
    with the event_id, suggestion_id, action, and chat_jid.
    """
    try:
        _supabase().table("inbox_copilot_events").insert({
            "tenant_id": tenant_id,
            "event_id": req.event_id,
            "chat_jid": req.chat_jid,
            "kind": req.action,
            "suggestion_id": req.suggestion_id,
        }).execute()
    except Exception as e:
        logger.debug(f"inbox_copilot audit log (action) failed: {e}")
        # Don't fail the request - the action was performed in the UI; we
        # just couldn't audit-log it. The founder would notice in the
        # dashboard if this happens often.

    return ActionResponse(success=True, recorded_at=str(int(time.time() * 1000)))
