"""
Bijou AI — Help Page Live Chat API
====================================

Endpoints:
  POST /api/help-chat/verify   — verify a tenant by email
  POST /api/help-chat/message  — send a chat message, get AI reply
  POST /api/help-chat/ticket   — escalate unresolved issue to support ticket

Two user types:
  public  → questions about Bijou/W3J platform only (no NDA, no internals)
  tenant  → verified client; gets context-aware help; unresolved issues → ticket
"""

import logging
import os
import re
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/help-chat", tags=["help-chat"])

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

PUBLIC_SYSTEM_PROMPT = """You are Bijou, the friendly AI support assistant for Bijou AI platform by W3J Sdn Bhd.

Your job: Answer questions about the Bijou AI platform and W3J services ONLY.

You CAN help with:
- What is Bijou AI, how it works
- Pricing: RM299/month (Pro plan), free trial available
- Features: WhatsApp AI, Knowledge Base, escalation, appointment booking, analytics
- How to sign up / onboard a business
- General troubleshooting tips (login, dashboard, WhatsApp connection)
- Directing users to get started at mybijou.xyz

You CANNOT share:
- Internal architecture, database schemas, passwords, or code
- Other clients' data or business details
- Pricing agreements, discounts, or NDA information
- Anything unrelated to Bijou AI or W3J

If you don't know, say so and suggest they submit a support ticket.

Keep answers short, friendly, and helpful. Use emojis sparingly."""

TENANT_SYSTEM_PROMPT = """You are Bijou, the AI support assistant for Bijou AI platform by W3J Sdn Bhd.

You are speaking with a verified Bijou client:
  Business: {business_name}
  Plan: {plan}
  Status: {status}

Your job: Help this client with their Bijou account issues.

You CAN help with:
- Dashboard usage, settings configuration
- WhatsApp connection troubleshooting
- Knowledge Base management
- Escalation and handover settings
- Appointment booking setup
- Billing and plan questions
- General feature usage

For technical issues you cannot resolve, say:
"I'll escalate this to our support team. Reply TICKET to create a support ticket."

Keep answers concise, specific, and action-oriented.
NEVER share other clients' data."""

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    email: str


class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class MessageRequest(BaseModel):
    message: str
    session_id: str
    user_type: str = "public"        # "public" or "tenant"
    tenant_email: Optional[str] = None
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    tenant_plan: Optional[str] = None
    history: List[ChatMessage] = []


class TicketRequest(BaseModel):
    name: str
    email: str
    issue_type: str = "chat-escalation"
    message: str
    tenant_id: Optional[str] = None
    session_transcript: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /api/help-chat/verify
# ---------------------------------------------------------------------------

@router.post("/verify")
async def verify_tenant(req: VerifyRequest):
    """
    Verify a visitor is a Bijou tenant by email.
    Returns masked tenant info if found.
    """
    email = (req.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Valid email required.")

    try:
        from supabase import create_client

        supabase_url = os.getenv("SUPABASE_URL", "").strip('"')
        supabase_key = (
            os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        ).strip('"')
        supabase = create_client(supabase_url, supabase_key)

        # Check tenants table by email column
        result = (
            supabase.table("tenants")
            .select("id, business_name, plan, status, email")
            .eq("email", email)
            .limit(1)
            .execute()
        )

        if not result.data:
            return {"verified": False, "message": "No account found for this email. Check the address or sign up at mybijou.xyz"}

        tenant = result.data[0]
        return {
            "verified": True,
            "tenant_id": tenant["id"],
            "tenant_name": tenant.get("business_name", "Your Business"),
            "plan": tenant.get("plan", "trial"),
            "status": tenant.get("status", "active"),
        }

    except Exception as e:
        logger.error(f"❌ help-chat verify error: {e}")
        raise HTTPException(status_code=500, detail="Verification failed. Try again or email support@mybijou.xyz")


# ---------------------------------------------------------------------------
# POST /api/help-chat/message
# ---------------------------------------------------------------------------

@router.post("/message")
async def chat_message(req: MessageRequest):
    """
    Send a chat message and get an AI response.
    Handles both public visitors and verified tenants.
    """
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message cannot be empty.")
    if len(message) > 2000:
        raise HTTPException(status_code=422, detail="Message too long (max 2000 chars).")

    # Build system prompt
    if req.user_type == "tenant" and req.tenant_name:
        system_prompt = TENANT_SYSTEM_PROMPT.format(
            business_name=req.tenant_name,
            plan=req.tenant_plan or "Pro",
            status="active",
        )
    else:
        system_prompt = PUBLIC_SYSTEM_PROMPT

    # Build conversation history for the AI gateway (OpenAI-style messages).
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for turn in req.history[-10:]:
        role = "user" if turn.role == "user" else "assistant"
        if turn.content:
            messages.append({"role": role, "content": turn.content})
    messages.append({"role": "user", "content": message})

    try:
        # Routes via the alias policy: gemini-2.5-flash primary -> openrouter
        # -> openai_compatible. See llm_gateway.yaml ai://helpdesk.
        from src.core.llm_gateway_v2 import llm

        result = await llm.complete("ai://helpdesk", messages)
        return {"reply": result.text, "status": "ok"}
    except Exception as e:
        logger.error(f"❌ help-chat gateway error: {e}")
        return {
            "reply": "I'm having trouble thinking right now 😅 Please try again in a moment, or email support@mybijou.xyz",
            "status": "error",
        }


# ---------------------------------------------------------------------------
# POST /api/help-chat/ticket
# ---------------------------------------------------------------------------

@router.post("/ticket")
async def create_chat_ticket(req: TicketRequest):
    """
    Escalate an unresolved chat session to a support ticket.
    Delegates to the existing web_support_tickets table.
    """
    name = (req.name or "Help Chat User").strip()
    email = (req.email or "").strip()
    message = (req.message or "").strip()

    if not email or not message:
        raise HTTPException(status_code=422, detail="Email and message are required.")

    full_message = message
    if req.session_transcript:
        full_message += f"\n\n--- Chat Transcript ---\n{req.session_transcript[:3000]}"

    try:
        from supabase import create_client

        supabase_url = os.getenv("SUPABASE_URL", "").strip('"')
        supabase_key = (
            os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        ).strip('"')
        supabase = create_client(supabase_url, supabase_key)

        # Get next ticket number
        existing = (
            supabase.table("web_support_tickets")
            .select("ticket_number")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        last_num = 0
        if existing.data:
            m = re.search(r"(\d+)$", existing.data[0].get("ticket_number", ""))
            if m:
                last_num = int(m.group(1))
        ticket_number = f"WEB-{(last_num + 1):04d}"

        ticket_data = {
            "ticket_number": ticket_number,
            "submitter_name": name,
            "submitter_email": email,
            "issue_type": req.issue_type or "chat-escalation",
            "message": full_message[:5000],
            "status": "open",
        }
        if req.tenant_id:
            ticket_data["tenant_id"] = req.tenant_id

        result = supabase.table("web_support_tickets").insert(ticket_data).execute()
        ticket_id = result.data[0].get("id") if result.data else "unknown"

        logger.info(f"✅ Chat escalation ticket: {ticket_number} | {email}")

        # Notify support team
        try:
            from src.api.support import _notify_support_team
            await _notify_support_team(ticket_id, name, email, req.issue_type or "chat-escalation", full_message)
        except Exception as e:
            logger.warning(f"⚠️ Chat ticket email notification failed: {e}")

        return {
            "success": True,
            "ticket_number": ticket_number,
            "ticket_id": str(ticket_id),
            "message": f"Ticket {ticket_number} created. Check your email for updates.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat ticket creation failed: {e}")
        raise HTTPException(status_code=500, detail="Could not create ticket. Email support@mybijou.xyz directly.")


# ---------------------------------------------------------------------------
# Internal: Gemini REST call
# ---------------------------------------------------------------------------

async def _call_gemini_chat(system_prompt: str, contents: list) -> str:
    """Call Gemini 1.5 Flash via REST with system instruction + conversation history."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured")

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 512,
        },
    }

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}",
            json=payload,
        )
        res.raise_for_status()
        data = res.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
