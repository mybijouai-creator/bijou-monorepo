"""
Bijou AI - Agent Assist Dashboard API (Simplified)
===================================================

REST API endpoints for human agents to monitor and manage conversations.
Enterprise version with Supabase Auth integration.

Author: W3J Bijou AI
Version: 2.1.0 (Auth Integrated)
"""

import asyncio
import base64
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import requests
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# In-memory debounce cache for repeated auth failures.
# Prevents Supabase DB lookups and ERROR-level log spam from stale PWA sessions
# that keep polling after their token expires. Key: (tenant_id, token). TTL: 5 min.
_auth_failure_cache: dict = {}
_AUTH_FAILURE_COOLDOWN_SECS = 300


def _is_auth_recently_failed(tenant_id: str, token: str) -> bool:
    """Return True if this tenant+token combo failed auth within the last 5 minutes."""
    key = (tenant_id, token or "")
    return (time.time() - _auth_failure_cache.get(key, 0)) < _AUTH_FAILURE_COOLDOWN_SECS


def jsonable_errors(e: ValidationError) -> list:
    """Convert a Pydantic ValidationError to the standard FastAPI 422 detail shape."""
    try:
        return e.errors()
    except Exception:
        return [{"type": "validation_error", "msg": str(e)}]


def _mark_auth_failed(tenant_id: str, token: str) -> None:
    """Record an auth failure and prune stale entries."""
    key = (tenant_id, token or "")
    _auth_failure_cache[key] = time.time()
    # Prune to prevent unbounded growth
    if len(_auth_failure_cache) > 500:
        cutoff = time.time() - _AUTH_FAILURE_COOLDOWN_SECS
        expired = [k for k, v in _auth_failure_cache.items() if v < cutoff]
        for k in expired:
            del _auth_failure_cache[k]


async def _send_dashboard_recovery_msg(tenant_id: str) -> None:
    """Fire-and-forget: send the tenant owner a WhatsApp message with their correct dashboard link.
    Only called on the FIRST 401 in a 5-min window so the owner gets one helpful notification,
    not a flood.
    """
    try:
        supabase = get_supabase()
        row = await asyncio.to_thread(
            lambda: supabase.table("tenants")
                .select("owner_phone, name, signup_token")
                .eq("id", tenant_id)
                .maybe_single()
                .execute()
        )
        rdata = getattr(row, "data", None) if row else None
        if not rdata:
            return
        owner_phone = _normalize_phone_for_bridge(rdata.get("owner_phone") or "")
        signup_token = rdata.get("signup_token") or ""
        biz_name = rdata.get("name") or "your business"
        if not owner_phone or not signup_token:
            logger.warning(f"⚠️ Recovery msg skipped for {tenant_id}: missing owner_phone or signup_token")
            return

        public_url = os.getenv("PUBLIC_URL", "https://app.mybijou.xyz").rstrip("/")
        dashboard_url = f"{public_url}/dashboard?tenant_id={tenant_id}&token={signup_token}"

        bridge_url = os.getenv("BRIDGE_URL", "").rstrip("/")
        if not bridge_url:
            logger.warning("⚠️ Recovery msg skipped: BRIDGE_URL not set")
            return

        bridge_api_key = os.getenv("BRIDGE_API_KEY", "")
        bridge_user = os.getenv("BRIDGE_USER", "")
        bridge_password = os.getenv("BRIDGE_PASSWORD", "")
        _no_key = {"", "your-api-key-here", "none"}
        headers: dict = {"Content-Type": "application/json"}
        if bridge_api_key and bridge_api_key not in _no_key and ":" in bridge_api_key:
            auth_str = base64.b64encode(bridge_api_key.encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"
        elif bridge_user and bridge_password:
            auth_str = base64.b64encode(f"{bridge_user}:{bridge_password}".encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"
        elif bridge_api_key and bridge_api_key not in _no_key:
            headers["X-API-Key"] = bridge_api_key
        else:
            logger.warning("⚠️ Recovery msg skipped: no bridge credentials configured")
            return

        # Resolve WhatsApp device for this tenant
        try:
            dev = await asyncio.to_thread(
                lambda: supabase.table("whatsapp_devices")
                    .select("device_id")
                    .eq("tenant_id", tenant_id)
                    .limit(1)
                    .execute()
            )
            device_id = dev.data[0]["device_id"] if dev.data else os.getenv("WHATSAPP_DEVICE_ID", "default")
        except Exception:
            device_id = os.getenv("WHATSAPP_DEVICE_ID", "default")
        headers["X-Device-Id"] = device_id

        message = (
            f"🔐 *{biz_name} — Bijou Dashboard*\n\n"
            f"Your dashboard session has expired or was accessed with an invalid link.\n\n"
            f"Tap here to open your dashboard:\n"
            f"{dashboard_url}\n\n"
            f"_This link is unique to your account. Do not share it._"
        )
        phone_jid = f"{owner_phone}@s.whatsapp.net"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{bridge_url}/send/message",
                json={"phone": phone_jid, "message": message},
                headers=headers,
            )
        if resp.status_code < 300:
            logger.info(f"✅ Dashboard recovery link sent via WhatsApp to {owner_phone} (tenant {tenant_id})")
        else:
            logger.warning(f"⚠️ Recovery msg send failed: HTTP {resp.status_code} for tenant {tenant_id}")
    except Exception as e:
        logger.warning(f"⚠️ Dashboard recovery msg error for tenant {tenant_id}: {e}")


# Create router
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# Initialize Supabase client directly
def get_supabase() -> Client:
    """Get Supabase client from environment"""
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv(
        "NEXT_PUBLIC_SUPABASE_URL", ""
    ).strip('"')
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip('"')
        or os.getenv("SUPABASE_KEY")
    )

    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Missing Supabase configuration")

    return create_client(supabase_url, supabase_key)


def format_phone_number(phone: str) -> str:
    """Format phone number for display"""
    # Remove any non-digit characters
    clean_phone = "".join(filter(str.isdigit, phone))

    if not clean_phone:
        return phone

    # Strong Malaysian-first formatting:
    # - 0XXXXXXXXX / 01XXXXXXXXX → +60 ...
    # - 60XXXXXXXXX → +60 ...
    # Other regions: keep country code but still format nicely.
    if clean_phone.startswith("0") and len(clean_phone) in (10, 11):
        # Strip leading 0 and prefix with 60 (Malaysia)
        clean_phone = "60" + clean_phone[1:]

    if clean_phone.startswith("60") and len(clean_phone) >= 11:
        # +60 11-234 5678 style
        return f"+{clean_phone[:2]} {clean_phone[2:4]} {clean_phone[4:7]} {clean_phone[7:]}"

    # Generic international formatting fallback
    if len(clean_phone) > 2:
        return f"+{clean_phone[:2]} {clean_phone[2:]}"

    return f"+{clean_phone}" if not phone.startswith("+") else phone


def _normalize_phone_for_bridge(phone: str) -> str:
    """Return a clean international phone number suitable for the WhatsApp bridge.
    The bridge rejects numbers starting with 0 — this fixes Malaysian 01x/0x → 60x.
    Examples: '0174106981' → '60174106981', '+60174106981' → '60174106981'
    """
    clean = "".join(filter(str.isdigit, phone))
    if not clean:
        return ""
    if clean.startswith("0"):
        clean = "60" + clean[1:]  # Malaysian local → international
    return clean


# ==================== MODELS ====================


class AgentData(BaseModel):
    agent_name: str
    agent_email: Optional[str] = None
    agent_whatsapp: Optional[str] = None
    agent_role: Optional[str] = "Support Agent"
    priority_level: Optional[int] = 3
    working_hours: Optional[Dict[str, str]] = None  # No hardcoded default hours
    skills: Optional[List[str]] = []
    is_active: Optional[bool] = True


class TakeoverRequest(BaseModel):
    customer_jid: Optional[str] = None
    agent_name: Optional[str] = "Agent"
    reason: Optional[str] = None


class KnowledgeRequest(BaseModel):
    content: str
    source_name: str = "manual_entry"
    title: Optional[str] = None   # UI sends this as the document title
    source: Optional[str] = None  # UI sends this as the source/origin label
    note: Optional[str] = None    # "when to use" / trigger context for Bijou


class KnowledgeEditRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    note: Optional[str] = None
    change_summary: Optional[str] = None  # e.g. "Updated pricing"


class SendMessageRequest(BaseModel):
    customer_jid: str
    message: str
    agent_name: str = "Dashboard User"  # Optional, defaults to "Dashboard User"


# ==================== SECURITY ====================


async def get_current_user(authorization: str = Header(None)):
    """Validate Supabase JWT session from Authorization header"""
    if not authorization:
        return None

    try:
        token = authorization.replace("Bearer ", "")
        supabase = get_supabase()
        # NOTE (2026-08-06): pass `jwt=` explicitly. The positional
        # form `get_user(token)` is silently ignored in some
        # supabase-py versions (the SDK treated it as "get current
        # session user" and returned None), which made the dashboard
        # 401 every authenticated request even when the token was
        # valid. Using `jwt=token` actually verifies the token.
        user_response = supabase.auth.get_user(jwt=token)

        if user_response and user_response.user:
            return user_response.user
    except Exception as e:
        # Common scenario: expired tokens are refreshed automatically by frontend
        # Only log at debug level to avoid spam
        if "token is expired" not in str(e):
            logger.warning(f"⚠️ JWT verification failed: {e}")
        else:
            logger.debug(f"🔄 JWT token expired (will auto-refresh): {e}")

    return None


async def verify_session(
    tenant_id: Optional[str] = Query(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    token: Optional[str] = Query(None),
    user: Optional[Any] = Depends(get_current_user),
) -> str:
    """
    DUAL AUTH: Validates either Supabase JWT session OR legacy URL token.
    Returns the validated tenant_id.

    Authentication Methods (in order of priority):
    1. Supabase JWT (professional login/logout) - NEW
    2. signup_token in URL (magic link) - LEGACY, backwards compatible
    """
    # Dashboard mode controls how strict we are about tenant resolution.
    # pilot  -> allow legacy fallbacks (for development/testing only)
    # strict -> require explicit tenant (session or token), no hard-coded default (PRODUCTION)
    dashboard_mode = os.getenv("DASHBOARD_MODE", "strict").lower().strip()

    # Prefer header over query param for tenant_id
    tenant_id = x_tenant_id or tenant_id

    # METHOD 1: Supabase Auth JWT (NEW - Primary for logged-in users)
    if user:
        try:
            supabase = get_supabase()
            # Get tenant_id from tenant_users table
            link_response = (
                supabase.table("tenant_users")
                .select("tenant_id")
                .eq("user_id", user.id)
                .limit(1)
                .execute()
            )

            if link_response.data:
                session_tenant_id = link_response.data[0]["tenant_id"]

                # Strict isolation: if URL tenant_id is different, block access
                if tenant_id and tenant_id != session_tenant_id:
                    logger.warning(
                        f"🚨 Security: User {user.email} attempted access to tenant {tenant_id}, authorized for {session_tenant_id}"
                    )
                    raise HTTPException(
                        status_code=403, detail="Unauthorized tenant access"
                    )

                logger.debug(f"✅ JWT auth: User {user.email} -> Tenant {session_tenant_id}")
                return session_tenant_id
            else:
                logger.warning(f"⚠️ User {user.id} has no tenant link in tenant_users table")
                # Fail closed in strict mode: an authenticated user with no tenant link
                # must NOT fall through to a URL-supplied tenant_id (cross-tenant access).
                if dashboard_mode == "strict":
                    raise HTTPException(status_code=403, detail="Unauthorized tenant access")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"⚠️ JWT tenant lookup failed: {e}")
            # Fail closed in strict mode: if we cannot resolve/authorize an authenticated
            # user's tenant, deny rather than fall back to the URL-supplied tenant_id.
            if dashboard_mode == "strict":
                raise HTTPException(status_code=403, detail="Unauthorized tenant access")

    # Legacy / Pilot Fallback (to be removed in GA)
    if not tenant_id:
        if dashboard_mode == "strict":
            logger.error("❌ Missing tenant_id in strict dashboard mode")
            raise HTTPException(
                status_code=400,
                detail="Missing tenant_id for dashboard access. Please use a valid tenant portal link.",
            )
        # Pilot / dev default tenant — read from env, fail secure if not configured
        tenant_id = os.getenv("DEFAULT_TENANT_ID")
        if not tenant_id:
            logger.error("❌ No tenant_id and DEFAULT_TENANT_ID not set — rejecting dashboard access")
            raise HTTPException(
                status_code=401,
                detail="Tenant not identified. Please access the dashboard via your tenant portal link.",
            )

    # Check simple token if provided
    if token:
        # Fast-path: skip Supabase lookup for recently-failed token combos (stale PWA sessions)
        if _is_auth_recently_failed(tenant_id, token):
            raise HTTPException(
                status_code=401,
                detail="Authentication required. Please log in to access the dashboard."
            )
        try:
            supabase = get_supabase()
            response = (
                supabase.table("tenants")
                .select("signup_token, settings")
                .eq("id", tenant_id)
                .maybe_single()
                .execute()
            )
            rdata = getattr(response, "data", None) if response else None
            if rdata:
                # Primary: match against signup_token column
                if rdata.get("signup_token") == token:
                    return tenant_id
                # Fallback: match against settings->dashboard_token (legacy)
                settings = rdata.get("settings") or {}
                if isinstance(settings, dict) and settings.get("dashboard_token") == token:
                    logger.info(f"✅ Token matched via settings.dashboard_token for tenant {tenant_id}")
                    return tenant_id
        except Exception as token_err:
            logger.warning(
                f"⚠️ Token validation error for tenant {tenant_id}: {type(token_err).__name__}"
            )

    # If no valid session and token matching failed, require authentication in strict mode
    require_auth = os.getenv("REQUIRE_DASHBOARD_TOKEN", "true").lower() == "true"
    if require_auth and not user:
        first_failure = not _is_auth_recently_failed(tenant_id, token or "")
        _mark_auth_failed(tenant_id, token or "")
        logger.warning(f"⚠️ Unauthorized access to tenant {tenant_id} - session expired or invalid (will suppress for 5 min)")
        if first_failure:
            # Non-blocking: send owner a WhatsApp with their correct dashboard link (once per 5-min window)
            asyncio.create_task(_send_dashboard_recovery_msg(tenant_id))
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in to access the dashboard."
        )

    return tenant_id


# ==================== DASHBOARD ENDPOINTS ====================


@router.get("/stats")
async def get_dashboard_stats(tenant_id: str = Depends(verify_session)):
    """Get dashboard statistics scoped by tenant"""
    logger.info(f"📊 Stats request for: {tenant_id}")

    try:
        supabase = get_supabase()

        # Try conversations table first
        conv_response = (
            supabase.table("conversations")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        active_conversations = conv_response.count or 0

        # If conversations table is empty, fallback to messages table
        if active_conversations == 0:
            logger.info(f"📨 Conversations empty, using messages table for stats")
            # Count unique chat_jids in messages
            messages_response = (
                supabase.table("messages")
                .select("chat_jid")
                .eq("tenant_id", tenant_id)
                .execute()
            )
            if messages_response.data:
                unique_chats = set(msg["chat_jid"] for msg in messages_response.data)
                active_conversations = len(unique_chats)

        # Count human handled (status in escalations)
        esc_response = (
            supabase.table("escalations")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("status", "in_progress")
            .execute()
        )
        human_handled = esc_response.count or 0

        # Count leads/messages today
        today = datetime.now().date().isoformat()
        leads_response = (
            supabase.table("conversations")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .gte("timestamp", today)
            .execute()
        )
        leads_today = leads_response.count or 0

        # Fallback to messages table if empty
        if leads_today == 0:
            messages_today_response = (
                supabase.table("messages")
                .select("id", count="exact")
                .eq("tenant_id", tenant_id)
                .gte("created_at", today)
                .execute()
            )
            leads_today = messages_today_response.count or 0

        # Calculate total_conversations (same as active for now)
        total_conversations = active_conversations

        # Calculate messages_today
        messages_today_response = (
            supabase.table("messages")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .gte("created_at", today)
            .execute()
        )
        messages_today = messages_today_response.count or 0

        # Count call bookings today — isolated so a missing table doesn't crash stats
        bookings_today = 0
        try:
            bookings_today_res = (
                supabase.table("call_bookings")
                .select("id", count="exact")
                .eq("tenant_id", tenant_id)
                .gte("created_at", today)
                .execute()
            )
            bookings_today = bookings_today_res.count or 0
        except Exception:
            pass  # call_bookings table may not exist for all tenants

        # Compute real avg response time from recent user→assistant message pairs
        avg_response_time = None
        try:
            rt_res = (
                supabase.table("messages")
                .select("chat_jid, role, created_at")
                .eq("tenant_id", tenant_id)
                .in_("role", ["user", "assistant"])
                .order("created_at", desc=False)
                .limit(300)
                .execute()
            )
            if rt_res.data and len(rt_res.data) >= 2:
                from datetime import datetime as _dt
                chat_msgs: Dict[str, list] = {}
                for row in rt_res.data:
                    chat_msgs.setdefault(row["chat_jid"], []).append(row)
                deltas = []
                for msgs in chat_msgs.values():
                    for i in range(len(msgs) - 1):
                        if msgs[i]["role"] == "user" and msgs[i + 1]["role"] == "assistant":
                            try:
                                t0 = _dt.fromisoformat(msgs[i]["created_at"].replace("Z", "+00:00"))
                                t1 = _dt.fromisoformat(msgs[i + 1]["created_at"].replace("Z", "+00:00"))
                                gap = (t1 - t0).total_seconds()
                                if 0 < gap < 300:  # ignore gaps > 5 min
                                    deltas.append(gap)
                            except Exception:
                                pass
                if deltas:
                    avg_s = sum(deltas) / len(deltas)
                    if avg_s < 2:
                        avg_response_time = "< 2s"
                    elif avg_s < 10:
                        avg_response_time = f"~{avg_s:.0f}s"
                    elif avg_s < 60:
                        avg_response_time = f"{avg_s:.0f}s"
                    else:
                        avg_response_time = f"{avg_s / 60:.1f}m"
        except Exception as rt_err:
            logger.debug(f"Could not compute avg_response_time: {rt_err}")

        # CSAT from the feedback table (defensive — table/column may be absent for some tenants).
        satisfaction_rate = None
        try:
            fb = (
                supabase.table("feedback")
                .select("rating")
                .eq("tenant_id", tenant_id)
                .limit(500)
                .execute()
            )
            ratings = [
                r.get("rating") for r in (fb.data or [])
                if isinstance(r.get("rating"), (int, float))
            ]
            if ratings:
                # ratings are 1-5 → percentage
                satisfaction_rate = round((sum(ratings) / len(ratings)) / 5 * 100)
        except Exception as _fb_err:
            logger.debug(f"CSAT unavailable: {_fb_err}")

        # AI containment: share of conversations handled without a human escalation.
        containment_rate = (
            round((max(0, total_conversations - human_handled) / total_conversations) * 100)
            if total_conversations else None
        )

        return {
            "active_conversations": active_conversations,
            "total_conversations": total_conversations,
            "ai_handled": max(0, active_conversations - human_handled),
            "human_handled": human_handled,
            "leads_generated_today": leads_today,
            "messages_today": messages_today,
            "bookings_today": bookings_today,
            "avg_response_time": avg_response_time,
            "satisfaction_rate": satisfaction_rate,
            "containment_rate": containment_rate,
        }
    except Exception as e:
        logger.error(f"❌ Failed to fetch stats: {e}")
        return {
            "active_conversations": 0,
            "total_conversations": 0,
            "ai_handled": 0,
            "human_handled": 0,
            "leads_generated_today": 0,
            "messages_today": 0,
            "bookings_today": 0,
            "avg_response_time": None,
            "satisfaction_rate": None,
        }


@router.get("/conversations")
async def get_active_conversations(
    limit: int = Query(50), tenant_id: str = Depends(verify_session)
):
    """Get list of active conversations for tenant (with fallback to messages table)"""
    try:
        supabase = get_supabase()

        # Try conversations table first
        # NOTE: we fetch message_content + sender so we can populate last_message preview
        # and derive a display name for @lid JIDs (sender has the real phone number)
        response = (
            supabase.table("conversations")
            .select("id, chat_jid, created_at, contact_name, message_content, sender")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(limit * 2)
            .execute()
        )

        # If conversations table is empty, fallback to messages table
        if not response.data or len(response.data) == 0:
            logger.info(f"📨 Conversations table empty, querying messages table for tenant {tenant_id}")
            messages_response = (
                supabase.table("messages")
                .select("chat_jid, created_at, role, content")
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )

            if messages_response.data:
                # Group messages by chat_jid
                from collections import defaultdict
                grouped = defaultdict(list)
                for msg in messages_response.data:
                    grouped[msg["chat_jid"]].append(msg)

                # Create conversation records from grouped messages
                conversations = []
                for chat_jid, msgs in list(grouped.items())[:limit]:
                    latest_msg = msgs[0]  # Already sorted by created_at desc

                    # Extract phone number and name
                    phone = chat_jid.split("@")[0]
                    # Format phone number
                    if '@lid' in chat_jid:
                        customer_phone = f"DEVICE_{phone}"
                        contact_name = None  # Let frontend handle device ID formatting
                    else:
                        customer_phone = f"+{phone}" if not phone.startswith('+') else phone
                        contact_name = format_phone_number(phone)

                    # Find last user message for preview
                    last_user_msg = next((m for m in msgs if m.get("role") == "user"), None)
                    last_message_text = last_user_msg.get("content", "No message") if last_user_msg else "No message"

                    conversations.append({
                        "id": f"msg_{chat_jid}",  # Temporary ID
                        "chat_jid": chat_jid,
                        "customer_jid": chat_jid,
                        "customer_name": contact_name,
                        "customer_phone": customer_phone,
                        "last_message": last_message_text[:100],  # Truncate long messages
                        "last_message_time": latest_msg["created_at"],
                        "unread_count": 0,  # Can't determine from messages table
                        "status": "active",
                        "is_ai_mode": True,  # Default for messages from AI system
                        "assigned_agent": None,
                        "tags": [],
                    })

                logger.info(f"✅ Found {len(conversations)} conversations from messages table")
                return conversations
            else:
                logger.warning(f"⚠️ No data in messages OR conversations table for tenant {tenant_id}")
                return []

        conversations = []
        seen_jids = set()

        for conv in response.data:
            chat_jid = conv.get("chat_jid")
            if not chat_jid or chat_jid in seen_jids:
                continue

            seen_jids.add(chat_jid)
            if len(conversations) >= limit:
                break

            contact_name = conv.get("contact_name")
            # For @lid JIDs the numeric part is a device ID, not a phone number.
            # The real phone number is in the 'sender' column — use it for display.
            # For @g.us group JIDs the numeric part is a group ID — label as "Group".
            sender = conv.get("sender") or ""
            if chat_jid.endswith("@lid"):
                if sender:
                    sender_phone = sender.split("@")[0]
                    contact_name = format_phone_number(sender_phone)
                else:
                    contact_name = None  # frontend will render "Customer …"
            elif chat_jid.endswith("@g.us"):
                contact_name = None  # frontend renders "Group …"
            elif not contact_name or contact_name == chat_jid.split("@")[0]:
                contact_name = format_phone_number(chat_jid.split("@")[0])

            # Last message preview from message_content (latest row per JID due to ORDER BY timestamp DESC)
            last_message = (conv.get("message_content") or "")[:80]

            conversations.append(
                {
                    "id": conv["id"],
                    "chat_jid": chat_jid,
                    "customer_name": contact_name,
                    "customer_jid": chat_jid,
                    "last_message": last_message,
                    "updated_at": conv.get("timestamp", conv["created_at"]),
                    "status": "ai",
                }
            )

        # Enrich with saved contact names and tags from the contacts table
        if seen_jids:
            try:
                contacts_res = (
                    supabase.table("contacts")
                    .select("jid, name, tag")
                    .eq("tenant_id", tenant_id)
                    .in_("jid", list(seen_jids))
                    .execute()
                )
                contact_map = {r["jid"]: r for r in (contacts_res.data or [])}
                for c in conversations:
                    jid = c["chat_jid"]
                    if jid in contact_map:
                        ct = contact_map[jid]
                        if ct.get("name"):
                            c["contact_name"] = ct["name"]
                        if ct.get("tag"):
                            c["contact_tag"] = ct["tag"]
            except Exception as enrich_err:
                logger.warning(f"⚠️ Contacts enrichment failed (non-fatal): {enrich_err}")

        return conversations
    except Exception as e:
        logger.error(f"❌ Conversations fetch error: {e}")
        return []


@router.get("/conversation/{customer_jid}")
async def get_conversation_detail(
    customer_jid: str, tenant_id: str = Depends(verify_session)
):
    """Get detailed message history for a specific customer (with fallback to messages table)"""
    try:
        supabase = get_supabase()
        # Try conversations table first
        msg_response = (
            supabase.table("conversations")
            .select("*")
            .eq("chat_jid", customer_jid)
            .eq("tenant_id", tenant_id)
            .order("timestamp", desc=False)
            .limit(100)
            .execute()
        )

        messages = []

        # If conversations table is empty, fallback to messages table
        if not msg_response.data or len(msg_response.data) == 0:
            logger.info(f"📨 Conversations table empty for {customer_jid}, falling back to messages table")
            messages_response = (
                supabase.table("messages")
                .select("role, content, created_at")
                .eq("chat_jid", customer_jid)
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=False)
                .limit(100)
                .execute()
            )

            if not messages_response.data:
                raise HTTPException(
                    status_code=404, detail="Conversation not found or access denied"
                )

            # Convert messages table format to conversation detail format
            for msg in messages_response.data:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("created_at"),
                })
        else:
            # Original conversations table logic
            for msg in msg_response.data:
                messages.append(
                    {
                        "role": "user",
                        "content": msg.get("message_content", ""),
                        "timestamp": msg.get("timestamp"),
                    }
                )
                if msg.get("ai_response"):
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.get("ai_response"),
                            "timestamp": msg.get("timestamp"),
                        }
                    )

        # Status from escalations
        esc_response = (
            supabase.table("escalations")
            .select("status")
            .eq("chat_jid", customer_jid)
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        status = (
            "human"
            if esc_response.data and esc_response.data[0]["status"] == "in_progress"
            else "ai"
        )

        return {
            "customer_jid": customer_jid,
            "customer_name": format_phone_number(customer_jid.split("@")[0]),
            "status": status,
            "messages": messages,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/takeover")
async def takeover_conversation(
    request: TakeoverRequest, tenant_id: str = Depends(verify_session)
):
    """Switch conversation to human agent mode"""
    try:
        if not request.customer_jid:
            raise HTTPException(
                status_code=400,
                detail="customer_jid is required"
            )

        agent_name = request.agent_name or "Agent"
        supabase = get_supabase()

        # Verify conversation exists for this tenant
        res = (
            supabase.table("conversations")
            .select("id")
            .eq("chat_jid", request.customer_jid)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )

        if not res.data:
            logger.warning(f"⚠️ Takeover denied: customer {request.customer_jid} not found for tenant {tenant_id}")
            raise HTTPException(
                status_code=403,
                detail="Customer not found in your account"
            )

        # Upsert escalation record to mark conversation as human-controlled
        existing_esc = (
            supabase.table("escalations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("chat_jid", request.customer_jid)
            .limit(1)
            .execute()
        )

        escalation_data = {
            "tenant_id": tenant_id,
            "chat_jid": request.customer_jid,
            "status": "in_progress",
            "assigned_to": agent_name,
            "reason": request.reason or "Manual takeover",
            "updated_at": datetime.now().isoformat(),
        }

        if existing_esc.data:
            supabase.table("escalations").update(escalation_data).eq("id", existing_esc.data[0]["id"]).eq("tenant_id", tenant_id).execute()
        else:
            supabase.table("escalations").insert(escalation_data).execute()

        # NOTE: conversations table has no 'status' column — AI silence is controlled
        # via the escalations table (PHASE 2.25 guard checks escalations.status = 'in_progress')

        logger.info(f"✅ Conversation taken over by {agent_name} for {request.customer_jid}")
        return {"status": "success", "message": f"Taken over by {agent_name}"}

    except HTTPException:
        raise  # Re-raise validation errors as-is
    except Exception as e:
        logger.error(f"❌ Takeover failed for {request.customer_jid}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to takeover conversation: {str(e)}"
        )


@router.post("/return-to-ai/{customer_jid}")
async def return_to_ai(
    customer_jid: str,
    agent_name: str = Query(default="Agent"),   # ✅ FIX: was Query(...) — now optional with default
    tenant_id: str = Depends(verify_session),
):
    """Return control to the AI agent"""
    try:
        # Validate inputs
        if not customer_jid:
            raise HTTPException(
                status_code=400,
                detail="customer_jid is required"
            )

        # Normalise agent_name
        if not agent_name or not agent_name.strip():
            agent_name = "Agent"

        supabase = get_supabase()

        # Verify ownership — conversations table has no "status" column, only check existence
        res = (
            supabase.table("conversations")
            .select("id")
            .eq("chat_jid", customer_jid)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )

        if not res.data:
            logger.warning(f"⚠️ Return to AI denied: customer {customer_jid} not found for tenant {tenant_id}")
            raise HTTPException(
                status_code=403,
                detail="Customer not found in your account"
            )

        # Resolve the open escalation (if any)
        supabase.table("escalations").update(
            {
                "status": "resolved",
                "resolved_at": datetime.now().isoformat(),
                "resolution_notes": f"Returned to AI by {agent_name}",
            }
        ).eq("chat_jid", customer_jid).eq("tenant_id", tenant_id).eq(
            "status", "in_progress"
        ).execute()

        # NOTE: conversations table has NO "status" column — do NOT update it here.
        # AI simply resumes when the next message arrives.

        logger.info(f"✅ Conversation returned to AI by {agent_name} for {customer_jid}")
        return {"status": "success", "message": "Returned to AI"}

    except HTTPException:
        raise  # Re-raise validation errors as-is
    except Exception as e:
        logger.error(f"❌ Return to AI failed for {customer_jid}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to return conversation to AI: {str(e)}"
        )


@router.post("/send-message")
async def send_message_as_agent(
    request: SendMessageRequest, tenant_id: str = Depends(verify_session)
):
    """Send message to customer via WhatsApp bridge"""
    # ✅ FIX #5: Add comprehensive validation and bridge connectivity check
    logger.info(
        f"📤 Agent {request.agent_name} sending to {request.customer_jid} (Tenant: {tenant_id})"
    )

    try:
        # Validate request body
        if not request.customer_jid:
            raise HTTPException(
                status_code=400,
                detail="customer_jid is required"
            )

        if not request.message or not request.message.strip():
            raise HTTPException(
                status_code=400,
                detail="message cannot be empty"
            )

        # Get bridge URL from environment
        bridge_url = os.getenv("BRIDGE_URL") or os.getenv("WHATSAPP_BRIDGE_URL")

        if not bridge_url:
            logger.error("❌ BRIDGE_URL not configured")
            raise HTTPException(
                status_code=503,
                detail="WhatsApp bridge is not configured. Contact administrator."
            )

        bridge_url = bridge_url.rstrip("/")

        # Build auth headers — mirrors bijou.py send_message() auth logic exactly.
        # Priority: BRIDGE_USER+BRIDGE_PASSWORD (Basic Auth) > BRIDGE_API_KEY with colon > BRIDGE_API_KEY as X-API-Key
        headers = {"Content-Type": "application/json"}
        bridge_user = os.getenv("BRIDGE_USER", "")
        bridge_password = os.getenv("BRIDGE_PASSWORD", "")
        bridge_api_key = os.getenv("BRIDGE_API_KEY", "")
        _no_key = ("NOT_SET", "", None)

        if bridge_api_key and bridge_api_key not in _no_key and ':' in bridge_api_key:
            # PRIMARY (matches bijou.py): BRIDGE_API_KEY in "user:pass" format → Basic Auth
            auth_str = base64.b64encode(bridge_api_key.encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"
            logger.debug("🔑 Bridge auth: Basic Auth (from BRIDGE_API_KEY user:pass)")
        elif bridge_user and bridge_password:
            # SECONDARY: explicit BRIDGE_USER + BRIDGE_PASSWORD → Basic Auth
            credentials = f"{bridge_user}:{bridge_password}"
            auth_str = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"
            logger.debug(f"🔑 Bridge auth: Basic Auth (BRIDGE_USER={bridge_user})")
        elif bridge_api_key and bridge_api_key not in _no_key:
            # TERTIARY: BRIDGE_API_KEY as plain X-API-Key header
            headers["X-API-Key"] = bridge_api_key
            logger.debug("🔑 Bridge auth: X-API-Key")
        else:
            logger.error("❌ No bridge credentials configured (need BRIDGE_API_KEY or BRIDGE_USER+BRIDGE_PASSWORD)")
            raise HTTPException(
                status_code=503,
                detail="WhatsApp bridge authentication not configured. Contact administrator."
            )

        # Resolve @lid JIDs → @s.whatsapp.net before sending to bridge.
        # GOWA bridge cannot deliver to @lid format — needs the real phone JID.
        # We look up the most recent message with phone_jid set for this chat.
        bridge_phone = request.customer_jid
        if request.customer_jid.endswith("@lid"):
            try:
                _lid_supabase = get_supabase()
                _lid_msg = (
                    _lid_supabase.table("messages")
                    .select("phone_jid")
                    .eq("tenant_id", tenant_id)
                    .eq("chat_jid", request.customer_jid)
                    .not_.is_("phone_jid", "null")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if _lid_msg.data and _lid_msg.data[0].get("phone_jid"):
                    bridge_phone = _lid_msg.data[0]["phone_jid"]
                    logger.info(f"🔗 Resolved @lid {request.customer_jid} → {bridge_phone}")
                else:
                    logger.warning(
                        f"⚠️ Could not resolve @lid {request.customer_jid} to phone_jid — "
                        f"bridge may reject this send"
                    )
            except Exception as _lid_err:
                logger.warning(f"⚠️ @lid resolution failed: {_lid_err}")

        # Prepare payload for bridge (GOWA expects "phone" and "message" fields)
        url = f"{bridge_url}/send/message"
        payload = {
            "phone": bridge_phone,
            "message": request.message,
        }

        # Add device ID header — look up device_id UUID (not whatsapp_jid) from whatsapp_devices table.
        # GOWA bridge identifies devices by their UUID device_id, not by JID.
        try:
            _supabase = get_supabase()
            _dev = _supabase.table("whatsapp_devices")\
                .select("device_id")\
                .eq("tenant_id", tenant_id)\
                .limit(1)\
                .execute()
            whatsapp_device_id = _dev.data[0]["device_id"] if _dev.data else os.getenv("WHATSAPP_DEVICE_ID", "")
        except Exception:
            whatsapp_device_id = os.getenv("WHATSAPP_DEVICE_ID", "")

        # Auto-discover device_id from bridge if local lookup returned invalid value
        if not whatsapp_device_id or whatsapp_device_id in ("default", ""):
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=5) as _disc_client:
                    _disc_resp = await _disc_client.get(
                        f"{bridge_url}/app/devices",
                        headers={k: v for k, v in headers.items() if k != "Content-Type"},
                    )
                if _disc_resp.status_code == 200:
                    _devs = _disc_resp.json()
                    if isinstance(_devs, list) and _devs:
                        whatsapp_device_id = _devs[0].get("device_id") or _devs[0].get("id", "")
                        logger.info(f"🔍 Auto-discovered device_id={whatsapp_device_id} from bridge for tenant {tenant_id}")
                        # Cache to DB
                        if whatsapp_device_id:
                            try:
                                _supabase = get_supabase()
                                _supabase.table("whatsapp_devices").upsert({
                                    "tenant_id": tenant_id,
                                    "device_id": whatsapp_device_id,
                                    "updated_at": datetime.now().isoformat(),
                                }, on_conflict="tenant_id").execute()
                            except Exception as _cache_err:
                                logger.debug(f"⚠️ Could not cache device_id: {_cache_err}")
            except Exception as _disc_err:
                logger.warning(f"⚠️ device_id auto-discovery failed: {_disc_err}")

        if whatsapp_device_id and whatsapp_device_id not in ("default", ""):
            headers["X-Device-Id"] = whatsapp_device_id
            logger.debug(f"🔑 Bridge device_id: {whatsapp_device_id}")
        else:
            logger.error(f"❌ No valid device_id for tenant {tenant_id} — bridge will reject send")

        # Retry logic with exponential backoff (same as bijou.py)
        max_retries = 3
        retry_delays = [2, 5, 10]  # seconds
        success = False
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.debug(
                    f"📤 Attempt {attempt + 1}/{max_retries}: POST {url} "
                    f"with device_id={whatsapp_device_id}, phone={request.customer_jid}"
                )

                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    logger.info(f"✅ Message sent successfully to {request.customer_jid}")
                    success = True
                    break

                # Check if error is retryable
                error_text = response.text if response.text else ""

                # Client errors (400-499) are NOT retryable - these are validation errors
                if 400 <= response.status_code < 500:
                    logger.error(f"❌ Client error from bridge: {response.status_code} - {error_text}")
                    # Check for INVALID_JID specifically
                    if "INVALID_JID" in error_text:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid WhatsApp phone number format. Use format: 60123456789@s.whatsapp.net"
                        )
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid request: {error_text[:200]}"
                    )

                is_retryable = (
                    "driver: bad connection" in error_text
                    or "failed to save cached sessions" in error_text
                    or "context deadline exceeded" in error_text
                    or response.status_code == 500
                )

                last_error = f"status {response.status_code}: {error_text}"

                if not is_retryable or attempt == max_retries - 1:
                    break

                # Wait before retry
                delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                logger.warning(
                    f"⚠️ Bridge error (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay}s: {error_text[:100]}"
                )
                await asyncio.sleep(delay)

            except httpx.TimeoutException as e:
                last_error = f"timeout: {e}"
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.warning(
                        f"⚠️ Timeout (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
            except HTTPException:
                raise  # Re-raise validation errors immediately (don't retry 4xx errors)
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.warning(
                        f"⚠️ Connection error (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)

        if not success:
            logger.error(
                f"❌ Send failed after {max_retries} attempts to {request.customer_jid}"
            )
            logger.error(f"   Last error: {last_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to send message: {last_error}"
            )

        # Write the sent message to the messages table so it appears in the chat UI
        # Note: messages_role_check constraint only allows "user" and "assistant"
        # We use "assistant" and flag it as dashboard-sent in metadata
        try:
            _supabase = get_supabase()
            _supabase.table("messages").insert({
                "tenant_id": tenant_id,
                "chat_jid": request.customer_jid,
                "role": "assistant",
                "content": request.message,
                "customer_name": request.agent_name or "Agent",
                "metadata": {"sent_by": "dashboard", "agent_name": request.agent_name or "Agent"},
            }).execute()
        except Exception as db_err:
            logger.warning(f"⚠️ Could not save agent message to DB (non-fatal): {db_err}")

        return {"status": "success", "message": "Message sent successfully"}

    except HTTPException:
        raise  # Re-raise validation errors as-is
    except Exception as e:
        logger.error(f"❌ Send message error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send message: {str(e)}"
        )


@router.get("/tool-errors")
async def get_tool_errors(
    tenant_id: str = Depends(verify_session),
    limit: int = 50,
):
    """
    Get recent tool call failures for error visibility

    Provides clients visibility into:
    - Failed escalations (customer wanted human, tool didn't fire)
    - Failed calendar bookings (customer wanted appointment, booking failed)
    - Other tool failures

    Args:
        tenant_id: Tenant ID (from session)
        limit: Max number of errors to return (default 50)

    Returns:
        List of failed tool calls with metadata
    """
    try:
        db = get_supabase()

        # Get failed tool calls
        result = db.table("conversation_logs")\
            .select("*")\
            .eq("tenant_id", tenant_id)\
            .eq("success", False)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()

        errors = result.data or []

        # Format for dashboard display
        formatted_errors = []
        for error in errors:
            formatted_errors.append({
                "id": error["id"],
                "time": error["created_at"],
                "customer": error.get("chat_jid", "").split("@")[0],  # Phone number only
                "tool": error.get("tool_name", "unknown"),
                "error": error.get("error_message", "Unknown error"),
                "event_type": error.get("event_type", "tool_failure"),
                "metadata": error.get("metadata", {}),
            })

        return {
            "success": True,
            "errors": formatted_errors,
            "total": len(formatted_errors),
        }

    except Exception as e:
        logger.error(f"Error fetching tool errors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tool-stats")
async def get_tool_stats(
    tenant_id: str = Depends(verify_session),
    days: int = 7,
):
    """
    Get tool call statistics for monitoring

    Shows:
    - Total tool calls
    - Success rate
    - Failure breakdown by tool
    - Common error patterns

    Args:
        tenant_id: Tenant ID (from session)
        days: Number of days to analyze (default 7)

    Returns:
        Tool call statistics and health metrics
    """
    try:
        db = get_supabase()

        # Get recent tool calls
        from datetime import datetime, timedelta
        since = (datetime.now() - timedelta(days=days)).isoformat()

        result = db.table("conversation_logs")\
            .select("event_type, tool_name, success")\
            .eq("tenant_id", tenant_id)\
            .gte("created_at", since)\
            .execute()

        logs = result.data or []

        # Calculate statistics
        total_calls = len(logs)
        successful = sum(1 for log in logs if log.get("success"))
        failed = total_calls - successful
        success_rate = (successful / total_calls * 100) if total_calls > 0 else 0

        # Breakdown by tool
        tool_breakdown = {}
        for log in logs:
            tool = log.get("tool_name", "unknown")
            if tool not in tool_breakdown:
                tool_breakdown[tool] = {"total": 0, "success": 0, "failed": 0}
            tool_breakdown[tool]["total"] += 1
            if log.get("success"):
                tool_breakdown[tool]["success"] += 1
            else:
                tool_breakdown[tool]["failed"] += 1

        return {
            "success": True,
            "stats": {
                "total_calls": total_calls,
                "successful_calls": successful,
                "failed_calls": failed,
                "success_rate": round(success_rate, 1),
                "tool_breakdown": tool_breakdown,
            },
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Error fetching tool stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge/list")
async def list_knowledge(tenant_id: str = Depends(verify_session)):
    """List all knowledge documents for this tenant from the database."""
    try:
        supabase = get_supabase()
        resp = (
            supabase.table("knowledge_documents")
            .select("id, filename, content_extracted, uploaded_at, file_type, file_size_kb, metadata")
            .eq("tenant_id", tenant_id)
            .order("uploaded_at", desc=True)
            .limit(100)
            .execute()
        )
        docs = []
        for row in (resp.data or []):
            content = row.get("content_extracted") or ""
            # Strip the [WHEN TO USE:...] prefix from preview
            preview = content
            if preview.startswith("[WHEN TO USE:"):
                preview = preview.split("]", 1)[-1].lstrip("\n").strip()
            docs.append({
                "id": row.get("id"),
                "title": row.get("filename") or "Untitled",
                "name": row.get("filename") or "Untitled",
                "content": preview[:300],
                "file_type": row.get("file_type"),
                "file_size_kb": row.get("file_size_kb"),
                "created_at": row.get("uploaded_at"),
                "metadata": row.get("metadata") or {},
            })
        return {"success": True, "tenant_id": tenant_id, "documents": docs, "total_count": len(docs)}
    except Exception as e:
        logger.error(f"❌ Knowledge list failed: {e}")
        return {"success": False, "tenant_id": tenant_id, "documents": [], "total_count": 0}


@router.post("/knowledge")
async def add_knowledge(
    request: KnowledgeRequest, tenant_id: str = Depends(verify_session)
):
    """Add training data / context for the AI agent"""
    try:
        from src.core.knowledge_engine import KnowledgeEngine

        engine = KnowledgeEngine()
        source_name = request.source or request.source_name or "dashboard_entry"
        note = (request.note or "").strip()
        final_content = f"[WHEN TO USE: {note}]\n\n{request.content}" if note else request.content

        success = engine.add_context(
            tenant_id=tenant_id, content=final_content, source_name=source_name
        )
        if not success:
            return {"status": "error"}

        # Also persist to knowledge_documents table so the list endpoint can show it
        try:
            supabase = get_supabase()
            title = request.title or source_name or "Text Entry"
            supabase.table("knowledge_documents").insert({
                "tenant_id": tenant_id,
                "filename": title,
                "file_type": "text/plain",
                "content_extracted": final_content,
                "uploaded_by": "dashboard",
                "file_size_kb": max(1, int(len(final_content.encode()) / 1024)),
                "metadata": {"note": note},
            }).execute()
            asyncio.create_task(_notify_owner_doc_uploaded(supabase, tenant_id, title, note))
        except Exception as db_err:
            logger.warning(f"⚠️ Knowledge DB insert failed (non-fatal): {db_err}")

        return {"status": "success"}
    except Exception as e:
        logger.error(f"❌ Knowledge add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge/{doc_id}")
async def delete_knowledge_doc(
    doc_id: str,
    tenant_id: str = Depends(verify_session),
):
    """Delete a knowledge document by ID (both DB record and knowledge engine context)."""
    try:
        supabase = get_supabase()

        # Verify ownership before deleting
        existing = (
            supabase.table("knowledge_documents")
            .select("id, filename")
            .eq("id", doc_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            # Return success if already gone — idempotent delete
            logger.info(f"ℹ️ Knowledge doc {doc_id} not found (already deleted or wrong tenant)")
            return {"status": "success", "message": "Document not found or already deleted"}

        doc_title = existing.data[0].get("filename", "Untitled")

        # Delete from DB
        supabase.table("knowledge_documents").delete().eq("id", doc_id).eq("tenant_id", tenant_id).execute()

        # Best-effort: remove from KnowledgeEngine filesystem
        try:
            from src.core.knowledge_engine import KnowledgeEngine
            engine = KnowledgeEngine()
            if hasattr(engine, "delete_context"):
                engine.delete_context(tenant_id=tenant_id, source_name=doc_title)
        except Exception as ke:
            logger.debug(f"KnowledgeEngine delete skipped: {ke}")

        logger.info(f"✅ Knowledge doc deleted: {doc_id} ({doc_title}) for tenant {tenant_id}")
        return {"status": "success", "deleted_id": doc_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Knowledge delete failed for {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not delete document: {str(e)}")


@router.put("/knowledge/{doc_id}")
async def edit_knowledge_doc(
    doc_id: str,
    request: KnowledgeEditRequest,
    tenant_id: str = Depends(verify_session),
):
    """Edit a knowledge document. Saves the previous version to history before updating."""
    try:
        supabase = get_supabase()
        # Verify ownership.
        # NOTE (2026-08-06): use `.maybe_single()` so a missing doc returns
        # `None` cleanly instead of a 500 PGRST116 "result contains 0 rows".
        existing = (
            supabase.table("knowledge_documents")
            .select("id, filename, content_extracted, metadata, uploaded_at")
            .eq("id", doc_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        # NOTE (2026-08-06): check both `existing` (None on transport error)
        # and `existing.data` (None on no row). Previously the bare
        # `.data` access crashed with `'NoneType' object has no attribute
        # 'data'` when the supabase call itself failed.
        if not existing or not getattr(existing, "data", None):
            raise HTTPException(status_code=404, detail="Document not found")

        old = existing.data

        # Get current max version for this doc
        ver_resp = (
            supabase.table("knowledge_doc_versions")
            .select("version_number")
            .eq("document_id", doc_id)
            .order("version_number", desc=True)
            .limit(1)
            .execute()
        )
        next_version = (ver_resp.data[0]["version_number"] + 1) if ver_resp.data else 1

        # Snapshot the current state as a version
        supabase.table("knowledge_doc_versions").insert({
            "document_id": doc_id,
            "tenant_id": tenant_id,
            "version_number": next_version,
            "filename": old.get("filename"),
            "content": old.get("content_extracted"),
            "metadata": old.get("metadata") or {},
            "changed_by": "dashboard",
            "change_summary": request.change_summary or "Edited via dashboard",
        }).execute()

        # Build update payload
        update: dict = {"updated_at": datetime.utcnow().isoformat()}
        if request.title is not None:
            update["filename"] = request.title
        if request.content is not None:
            note = (request.note or "").strip()
            final_content = f"[WHEN TO USE: {note}]\n\n{request.content}" if note else request.content
            update["content_extracted"] = final_content
            meta = dict(old.get("metadata") or {})
            if note:
                meta["note"] = note
            update["metadata"] = meta
            # Sync to KnowledgeEngine
            try:
                from src.core.knowledge_engine import KnowledgeEngine
                engine = KnowledgeEngine()
                if hasattr(engine, "update_context"):
                    engine.update_context(tenant_id=tenant_id, source_name=old.get("filename", doc_id), content=final_content)
            except Exception as ke:
                logger.debug(f"KnowledgeEngine update skipped: {ke}")

        supabase.table("knowledge_documents").update(update).eq("id", doc_id).eq("tenant_id", tenant_id).execute()

        logger.info(f"✅ Knowledge doc edited: {doc_id} -> version {next_version} for tenant {tenant_id}")
        return {"status": "success", "doc_id": doc_id, "version_saved": next_version}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Knowledge edit failed for {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not edit document: {str(e)}")


@router.get("/knowledge/{doc_id}/history")
async def get_knowledge_history(
    doc_id: str,
    tenant_id: str = Depends(verify_session),
):
    """Return version history for a knowledge document, newest first."""
    try:
        supabase = get_supabase()
        # Verify ownership.
        # NOTE (2026-08-06): use `.maybe_single()` so a missing doc returns
        # `None` cleanly instead of a 500 PGRST116 "result contains 0 rows".
        doc = (
            supabase.table("knowledge_documents")
            .select("id, filename")
            .eq("id", doc_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not doc or not getattr(doc, "data", None):
            raise HTTPException(status_code=404, detail="Document not found")

        versions = (
            supabase.table("knowledge_doc_versions")
            .select("id, version_number, filename, content, metadata, changed_by, change_summary, created_at")
            .eq("document_id", doc_id)
            .eq("tenant_id", tenant_id)
            .order("version_number", desc=True)
            .limit(50)
            .execute()
        )
        return {
            "status": "success",
            "doc_id": doc_id,
            "doc_title": doc.data.get("filename"),
            "versions": versions.data or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Knowledge history failed for {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _notify_owner_doc_uploaded(supabase: Client, tenant_id: str, doc_title: str, note: str) -> None:
    """Best-effort: send WA notification to owner when a new knowledge doc is uploaded."""
    try:
        tenant = supabase.table("tenants").select("owner_phone, business_name").eq("id", tenant_id).limit(1).execute()
        if not tenant.data:
            return
        owner_phone = (tenant.data[0].get("owner_phone") or "").strip()
        if not owner_phone:
            return
        # Normalise: fix leading 0 and ensure JID format
        phone = _normalize_phone_for_bridge(owner_phone)
        if not phone:
            return
        if "@" not in phone:
            phone = f"{phone}@s.whatsapp.net"

        biz_name = tenant.data[0].get("business_name") or "Your business"
        msg_lines = [
            f"📚 *New Knowledge Doc Added* — {biz_name}",
            f"📄 *Title:* {doc_title}",
        ]
        if note:
            msg_lines.append(f"🎯 *When to use:* {note}")
        msg_lines.append("\nBijou will now use this doc to answer customer questions.")
        msg = "\n".join(msg_lines)

        bridge_url = (os.getenv("BRIDGE_URL") or "").rstrip("/")
        if not bridge_url:
            return
        # Build auth headers
        headers = {"Content-Type": "application/json"}
        bridge_user = os.getenv("BRIDGE_USER", "")
        bridge_password = os.getenv("BRIDGE_PASSWORD", "")
        bridge_api_key = os.getenv("BRIDGE_API_KEY", "")
        if bridge_api_key and ":" in bridge_api_key:
            headers["Authorization"] = "Basic " + base64.b64encode(bridge_api_key.encode()).decode()
        elif bridge_user and bridge_password:
            headers["Authorization"] = "Basic " + base64.b64encode(f"{bridge_user}:{bridge_password}".encode()).decode()
        elif bridge_api_key:
            headers["X-API-Key"] = bridge_api_key
        else:
            return
        # Get device ID
        try:
            dev = supabase.table("whatsapp_devices").select("device_id").eq("tenant_id", tenant_id).limit(1).execute()
            headers["X-Device-Id"] = dev.data[0]["device_id"] if dev.data else os.getenv("WHATSAPP_DEVICE_ID", "default")
        except Exception:
            headers["X-Device-Id"] = os.getenv("WHATSAPP_DEVICE_ID", "default")

        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"{bridge_url}/send/message", json={"phone": phone, "message": msg}, headers=headers)
        logger.info(f"✅ Owner notified of doc upload: {doc_title}")
    except Exception as e:
        logger.debug(f"Owner doc notification skipped: {e}")


@router.post("/knowledge/upload-file")
async def upload_knowledge_file(
    tenant_id: str = Depends(verify_session),
    file: UploadFile = File(...),
    title: str = Form(default=""),
    note: str = Form(default=""),  # "when to use" / trigger context
):
    """Upload a knowledge document. Supported: PDF, TXT, DOCX, MD, CSV, XLSX — max 10 MB."""
    ALLOWED_TYPES = {
        "text/plain": "txt",
        "text/markdown": "md",
        "text/x-markdown": "md",
        "text/csv": "csv",
        "text/x-csv": "csv",
        "application/csv": "csv",
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.ms-excel": "xls",
    }
    # Images are NOT accepted here — they can't be read as text.
    # Direct users to the Media Library to share images with customers.
    IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}
    MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

    content_type = (file.content_type or "").split(";")[0].strip().lower()

    # Friendly redirect for image uploads
    if content_type in IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Images can't be used to train Bijou (no text to extract). "
                "To share images with customers, upload them to the Media Library instead."
            ),
        )

    # Guess type from filename if browser sends generic octet-stream
    if content_type in ("application/octet-stream", "") and file.filename:
        ext = (file.filename.rsplit(".", 1)[-1] or "").lower()
        ext_map = {
            "md": "text/markdown", "csv": "text/csv", "txt": "text/plain",
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
        }
        content_type = ext_map.get(ext, content_type)

    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {file.filename or content_type}. "
                "Allowed: PDF, TXT, DOCX, MD, CSV, XLSX. "
                "For images use the Media Library. For PPT, convert to PDF first."
            ),
        )

    raw = await file.read()
    if len(raw) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Max 10 MB.")

    # Extract text
    extracted_text = ""
    import io as _io
    try:
        if content_type in ("text/plain", "text/markdown", "text/x-markdown", "text/csv", "text/x-csv", "application/csv"):
            # Plain text, markdown, CSV — all readable as UTF-8
            extracted_text = raw.decode("utf-8", errors="replace")
        elif content_type == "application/pdf":
            try:
                import PyPDF2  # type: ignore
                reader = PyPDF2.PdfReader(_io.BytesIO(raw))
                pages = [page.extract_text() or "" for page in reader.pages]
                extracted_text = "\n".join(pages)
                if not extracted_text.strip():
                    extracted_text = f"[PDF: {file.filename}] — Content could not be extracted (may be scanned/image-based). Add a text description instead."
            except ImportError:
                extracted_text = f"[PDF file: {file.filename}]\n(Install PyPDF2 for text extraction)"
        elif "wordprocessingml" in content_type:
            try:
                import docx  # type: ignore
                doc = docx.Document(_io.BytesIO(raw))
                extracted_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                extracted_text = f"[DOCX file: {file.filename}]\n(Install python-docx for text extraction)"
        elif content_type in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"):
            try:
                import openpyxl  # type: ignore
                wb = openpyxl.load_workbook(_io.BytesIO(raw), data_only=True)
                rows = []
                for sheet in wb.worksheets:
                    rows.append(f"[Sheet: {sheet.title}]")
                    for row in sheet.iter_rows(values_only=True):
                        row_text = "\t".join(str(c) if c is not None else "" for c in row)
                        if row_text.strip():
                            rows.append(row_text)
                extracted_text = "\n".join(rows)
            except ImportError:
                raise HTTPException(
                    status_code=422,
                    detail="Excel extraction requires openpyxl. Convert your sheet to CSV first, then upload.",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ File text extraction failed: {e}")
        raise HTTPException(status_code=422, detail=f"Could not extract text from file: {e}")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="File appears to be empty or unreadable. Add the content as text instead.")

    doc_title = title.strip() or file.filename or "Uploaded Document"

    # Prepend "when to use" note so Bijou sees it as context
    final_content = extracted_text
    if note.strip():
        final_content = f"[WHEN TO USE: {note.strip()}]\n\n{extracted_text}"

    # Persist via KnowledgeEngine (filesystem) AND knowledge_documents table (DB)
    try:
        from src.core.knowledge_engine import KnowledgeEngine
        engine = KnowledgeEngine()
        success = engine.add_context(
            tenant_id=tenant_id, content=final_content, source_name=doc_title
        )
        if not success:
            raise HTTPException(status_code=500, detail="Knowledge engine failed to store document.")

        # Also write to knowledge_documents table so the list endpoint shows it
        try:
            supabase = get_supabase()
            supabase.table("knowledge_documents").insert({
                "tenant_id": tenant_id,
                "filename": doc_title,
                "file_type": content_type,
                "content_extracted": final_content,
                "uploaded_by": "dashboard",
                "file_size_kb": max(1, int(len(raw) / 1024)),
                "metadata": {"note": note.strip(), "original_filename": file.filename},
            }).execute()

            # Fire owner notification (best-effort, non-blocking)
            asyncio.create_task(_notify_owner_doc_uploaded(supabase, tenant_id, doc_title, note.strip()))
        except Exception as db_err:
            logger.warning(f"⚠️ Knowledge DB insert failed (non-fatal): {db_err}")

        return {"status": "success", "title": doc_title, "chars": len(extracted_text), "note": note.strip()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Knowledge file upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ESCALATIONS API ====================


@router.get("/escalations")
async def get_escalations(
    tenant_id: str = Depends(verify_session),
    status: Optional[str] = Query(None)
):
    """List escalations for the tenant (optionally filtered by status)"""
    try:
        supabase = get_supabase()

        # Build query — select all escalation columns (no FK join to conversations)
        query = (
            supabase.table("escalations")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
        )

        # Only filter by status if provided and it's a real status value
        if status and status != "all":
            query = query.eq("status", status)

        response = query.execute()
        return response.data or []
    except Exception as e:
        logger.error(f"Error fetching escalations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch escalations: {str(e)}")


@router.post("/escalations/{escalation_id}/claim")
async def claim_escalation(
    escalation_id: str,
    tenant_id: str = Depends(verify_session),
    user: Any = Depends(get_current_user),
):
    """Agent claims a ticket"""
    try:
        supabase = get_supabase()
        user_email = user.email if user else "system"

        update_data = {
            "status": "claimed",
            "assigned_to": user_email,
            "updated_at": datetime.now().isoformat(),
        }

        response = (
            supabase.table("escalations")
            .update(update_data)
            .eq("id", escalation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

        return {"status": "success", "data": response.data}
    except Exception as e:
        logger.error(f"Error claiming escalation: {e}")
        raise HTTPException(status_code=500, detail="Failed to claim ticket")


# NOTE: The complete /escalations/{escalation_id}/resolve handler (which also
# writes resolved_at + resolution_notes so resolution metrics work) is defined
# later in this file. The earlier incomplete duplicate was removed — with two
# handlers registered on the same path, the first-registered wins, so the
# incomplete one silently shadowed the complete one and dropped resolution
# metadata.


# ==================== WHATSAPP OPERATIONS ====================


@router.get("/whatsapp/qr")
async def get_whatsapp_qr(tenant_id: str = Depends(verify_session)):
    """Get linking QR code from the bridge using device mapping"""
    import base64

    import httpx

    bridge_url = os.getenv("BRIDGE_URL", "http://localhost:8080").rstrip("/")
    bridge_api_key = os.getenv("BRIDGE_API_KEY", "")

    try:
        # Look up device_id from mapping table
        supabase = get_supabase()
        device_result = supabase.table("whatsapp_devices")\
            .select("device_id, device_name")\
            .eq("tenant_id", tenant_id)\
            .execute()

        if not device_result.data:
            raise HTTPException(
                status_code=404,
                detail="No WhatsApp device configured for this tenant. Please contact support."
            )

        device_id = device_result.data[0]["device_id"]
        logger.info(f"📱 Using device {device_id} for tenant {tenant_id}")

        headers = {}
        if bridge_api_key:
            # Use Basic Auth instead of Bearer (bridge expects username:password)
            auth_b64 = base64.b64encode(bridge_api_key.encode()).decode()
            headers["Authorization"] = f"Basic {auth_b64}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            # Get QR code using mapped device_id
            response = await client.get(
                f"{bridge_url}/app/login",
                params={"device_id": device_id},
                headers=headers,
                timeout=15.0
            )
            if response.status_code == 200:
                if "application/json" in response.headers.get("content-type", ""):
                    return response.json()

                b64_qr = base64.b64encode(response.content).decode("utf-8")
                return {"status": "success", "qr": f"data:image/png;base64,{b64_qr}"}
            return {
                "status": "error",
                "message": f"Bridge rejected: {response.status_code} - {response.text}",
            }
    except Exception as e:
        logger.error(f"❌ QR code error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/whatsapp/init")
async def init_whatsapp(tenant_id: str = Depends(verify_session)):
    """Initialize session in bridge for this tenant"""
    import httpx

    bridge_url = os.getenv("BRIDGE_URL", "http://localhost:8080").rstrip("/")
    bridge_api_key = os.getenv("BRIDGE_API_KEY", "")

    try:
        headers = {}
        if bridge_api_key:
            headers["Authorization"] = f"Bearer {bridge_api_key}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(
                f"{bridge_url}/api/init",
                params={"tenant_id": tenant_id},
                headers=headers,
                timeout=10.0
            )
            return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/whatsapp/status")
async def get_whatsapp_status(tenant_id: str = Depends(verify_session)):
    """Strict status check for this tenant's WhatsApp connection"""
    import base64
    import httpx

    bridge_url = os.getenv("BRIDGE_URL", "http://localhost:8080").rstrip("/")
    bridge_user = os.getenv("BRIDGE_USER", "bijou")
    bridge_pass = os.getenv("BRIDGE_PASSWORD")
    if not bridge_pass:
        logger.error("❌ BRIDGE_PASSWORD environment variable is not set")
        return {"connected": False, "status": "error", "detail": "Bridge not configured"}

    try:
        supabase = get_supabase()

        # --- Always read ground-truth from tenants table first ---
        tenant_result = supabase.table("tenants")\
            .select("whatsapp_connected, whatsapp_jid, device_id, session_active")\
            .eq("id", tenant_id)\
            .maybe_single()\
            .execute()

        tenant_connected = False
        tenant_jid = None
        tenant_device_id = None
        tr_data = getattr(tenant_result, "data", None) if tenant_result else None
        if tr_data:
            tenant_connected = bool(tr_data.get("whatsapp_connected", False))
            tenant_jid = tr_data.get("whatsapp_jid")
            tenant_device_id = tr_data.get("device_id")
            logger.info(
                f"📋 Tenant DB status: connected={tenant_connected}, "
                f"jid={tenant_jid}, device_id={tenant_device_id}"
            )

        # --- Look up device_id from whatsapp_devices table (more reliable) ---
        device_result = supabase.table("whatsapp_devices")\
            .select("device_id, device_name, whatsapp_jid")\
            .eq("tenant_id", tenant_id)\
            .execute()

        if not device_result.data or len(device_result.data) == 0:
            # No bridge device row — fall back to tenants table as source of truth
            logger.warning(f"⚠️ No whatsapp_devices row for tenant {tenant_id}, using tenants table")
            if tenant_connected and tenant_jid:
                phone = tenant_jid.split("@")[0] if tenant_jid else None
                return {
                    "connected": True,
                    "status": "connected",
                    "phone_number": phone,
                    "whatsapp_jid": tenant_jid,
                    "jid": tenant_jid,
                    "device_id": tenant_device_id,
                    "source": "tenants_table",
                }
            return {"connected": False, "status": "not_configured", "whatsapp_jid": None}

        device_id = device_result.data[0]["device_id"]
        stored_whatsapp_jid = device_result.data[0].get("whatsapp_jid") or tenant_jid
        logger.info(f"✅ Found device {device_id} for tenant {tenant_id}")

        # --- Try bridge for live status ---
        auth_string = base64.b64encode(f"{bridge_user}:{bridge_pass}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_string}",
            "X-Device-Id": device_id
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            logger.info(f"🔍 Checking bridge device status: {bridge_url}/app/status")
            response = await client.get(
                f"{bridge_url}/app/status",
                headers=headers,
                timeout=5.0
            )
            logger.info(f"📡 Status response: status={response.status_code}, body={response.text[:200]}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    results = data.get("results", {})
                    is_connected = results.get("is_connected", False)
                    is_logged_in = results.get("is_logged_in", False)
                    logger.info(f"✅ Bridge status: connected={is_connected}, logged_in={is_logged_in}")

                    if is_connected and is_logged_in:
                        live_jid = results.get("jid") or results.get("phone_number")
                        final_jid = live_jid or stored_whatsapp_jid
                        phone = final_jid.split("@")[0] if final_jid else results.get("phone_number")
                        return {
                            "connected": True,
                            "status": "connected",
                            "phone_number": phone,
                            "whatsapp_jid": final_jid,
                            "jid": final_jid,
                            "device_id": device_id,
                            "source": "bridge",
                        }
                except Exception as parse_err:
                    logger.error(f"❌ Failed to parse /app/status response: {parse_err}")

            # --- Bridge QR fallback: ALREADY_LOGGED_IN means connected ---
            logger.info(f"🔍 Bridge status inconclusive, checking QR endpoint...")
            qr_response = await client.get(
                f"{bridge_url}/app/login",
                params={"device_id": device_id},
                headers=headers,
                timeout=5.0
            )
            logger.info(f"📡 QR response: status={qr_response.status_code}, body={qr_response.text[:200]}")

            if qr_response.status_code == 400 and "ALREADY_LOGGED_IN" in qr_response.text:
                logger.info(f"✅ Device {device_id} is already logged in (QR error confirms)")
                phone = stored_whatsapp_jid.split("@")[0] if stored_whatsapp_jid else None
                return {
                    "connected": True,
                    "status": "connected",
                    "phone_number": phone,
                    "whatsapp_jid": stored_whatsapp_jid,
                    "jid": stored_whatsapp_jid,
                    "device_id": device_id,
                    "source": "bridge_qr_fallback",
                }

        # --- Final fallback: trust tenants.whatsapp_connected ---
        logger.warning(
            f"⚠️ Bridge unreachable/inconclusive for tenant {tenant_id}. "
            f"Falling back to tenants table (connected={tenant_connected})"
        )
        if tenant_connected and stored_whatsapp_jid:
            phone = stored_whatsapp_jid.split("@")[0] if stored_whatsapp_jid else None
            return {
                "connected": True,
                "status": "connected",
                "phone_number": phone,
                "whatsapp_jid": stored_whatsapp_jid,
                "jid": stored_whatsapp_jid,
                "device_id": device_id,
                "source": "tenants_table_fallback",
            }

        return {"connected": False, "status": "disconnected", "whatsapp_jid": stored_whatsapp_jid}

    except Exception as e:
        logger.error(f"❌ WhatsApp status error: {e}")
        return {"connected": False, "status": "error"}


# ==================== GOOGLE OAUTH ====================


@router.get("/google/auth-url")
async def get_google_auth_url(tenant_id: str = Depends(verify_session)):
    """Start Google OAuth flow"""
    from pathlib import Path

    # NOTE (2026-08-06): the `google_auth_oauthlib` package is optional and
    # not in requirements.txt. A bare `import` here used to raise
    # `ModuleNotFoundError` and 500 the endpoint. We try the import and
    # return a clean 503 if it's not installed.
    try:
        from google_auth_oauthlib.flow import Flow  # noqa: F401
    except ImportError:
        logger.warning("⚠️ google_auth_oauthlib not installed; Google OAuth disabled")
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured on this server. Please contact your administrator to enable Google Calendar integration.",
        )

    # ✅ FIX #1: Validate Google OAuth credentials before proceeding
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not google_client_id or not google_client_secret:
        logger.warning("⚠️ Google OAuth not configured (missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET)")
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured. Please contact your administrator to enable Google Calendar integration."
        )

    try:
        # Define scopes
        scopes = [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/spreadsheets",
        ]

        public_url = os.getenv("PUBLIC_URL", "https://app.mybijou.xyz").rstrip("/")
        redirect_uri = f"{public_url}/api/dashboard/google/callback"

        client_config = {
            "web": {
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "project_id": os.getenv("GOOGLE_PROJECT_ID", "bijou-ai"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            }
        }

        flow = Flow.from_client_config(
            client_config, scopes=scopes, redirect_uri=redirect_uri
        )

        auth_url, _ = flow.authorization_url(
            access_type="offline", prompt="consent", state=tenant_id
        )

        logger.info(f"✅ Generated Google OAuth URL for tenant {tenant_id}")
        return {"auth_url": auth_url}

    except Exception as e:
        logger.error(f"❌ Failed to generate Google OAuth URL: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize Google OAuth flow: {str(e)}"
        )


@router.get("/google/callback")
async def google_callback(code: str, state: str):
    """Callback for Google OAuth - state is tenant_id"""
    # ✅ FIX #2: Validate required parameters
    if not code or not state:
        logger.warning("⚠️ Google OAuth callback missing required parameters")
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: code and state are required for OAuth callback"
        )

    # Note: State is tenant_id passed in auth-url
    import pickle
    from pathlib import Path

    from google_auth_oauthlib.flow import Flow

    # Allow insecure transport ONLY in non-production environments.
    # OAUTHLIB_INSECURE_TRANSPORT disables TLS verification globally for the
    # entire process — it must never be set in production.
    if os.getenv("ENVIRONMENT", "production").lower() in ("development", "testing", "dev", "test"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    else:
        # Ensure the flag is explicitly OFF in production (in case it was set
        # during a prior dev session that was promoted without a clean restart).
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

    try:
        tenant_id = state

        # Validate Google OAuth credentials
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

        if not google_client_id or not google_client_secret:
            logger.error("❌ Google OAuth credentials not configured")
            raise HTTPException(
                status_code=503,
                detail="Google OAuth is not configured on the server"
            )

        scopes = [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        public_url = os.getenv("PUBLIC_URL", "https://app.mybijou.xyz").rstrip("/")
        redirect_uri = f"{public_url}/api/dashboard/google/callback"

        client_config = {
            "web": {
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "project_id": os.getenv("GOOGLE_PROJECT_ID", "bijou-ai"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            }
        }

        flow = Flow.from_client_config(
            client_config, scopes=scopes, redirect_uri=redirect_uri
        )

        flow.fetch_token(code=code)

        token_dir = Path("/data/tenants") / tenant_id
        token_dir.mkdir(parents=True, exist_ok=True)
        with open(token_dir / "google_token.pickle", "wb") as f:
            pickle.dump(flow.credentials, f)

        logger.info(f"✅ Google OAuth completed for tenant {tenant_id}")
        return {"status": "success", "message": "Google Account Linked Successfully"}

    except HTTPException:
        raise  # Re-raise validation errors as-is
    except Exception as e:
        logger.error(f"❌ OAuth callback error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to complete Google OAuth: {str(e)}"
        )


# ==================== AGENT MANAGEMENT ====================


@router.get("/agents")
async def get_agents(tenant_id: str = Depends(verify_session)):
    try:
        supabase = get_supabase()
        res = supabase.table("agents").select("*").eq("tenant_id", tenant_id).execute()
        return res.data or []
    except Exception:
        return []


@router.post("/agents")
async def create_agent(agent: AgentData, tenant_id: str = Depends(verify_session)):
    """Create a new agent for the tenant"""
    # ✅ FIX #6: Add validation and error handling
    try:
        # Validate required fields
        if not agent.agent_name or not agent.agent_name.strip():
            raise HTTPException(
                status_code=400,
                detail="agent_name is required and cannot be empty"
            )

        supabase = get_supabase()

        # Prepare agent data
        data = agent.dict()
        data["tenant_id"] = tenant_id

        # Insert into database
        res = supabase.table("agents").insert(data).execute()

        logger.info(f"✅ Agent created: {agent.agent_name} for tenant {tenant_id}")
        return res.data[0] if res.data else {"status": "success"}

    except HTTPException:
        raise  # Re-raise validation errors as-is
    except Exception as e:
        logger.error(f"❌ Failed to create agent: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create agent: {str(e)}"
        )


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, tenant_id: str = Depends(verify_session)):
    try:
        supabase = get_supabase()
        # NOTE (2026-08-06): the `agents` table doesn't exist in the
        # current schema (only `agent_runs` does). The previous code raised
        # a 500 PGRST205 "Could not find the table 'public.agents' in the
        # schema cache" on every call. Map that specific error to a 404
        # so the dashboard doesn't 500; the other /agents endpoints stay
        # unchanged (they already swallow the same error in the GET path
        # and surface validation errors in the POST path).
        try:
            supabase.table("agents").delete().eq("id", agent_id).eq(
                "tenant_id", tenant_id
            ).execute()
        except Exception as inner:
            msg = str(inner)
            if "PGRST205" in msg or "Could not find the table" in msg:
                raise HTTPException(status_code=404, detail="Agent not found")
            raise
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CONVERSATIONS ====================


@router.get("/conversations")
async def get_conversations(
    tenant_id: str = Depends(verify_session),
    page: int = 1,
    page_size: int = 20,
):
    """
    Paginated list of distinct conversations for the tenant.

    Returns one row per unique chat_jid, ordered by the most recent
    message timestamp descending.  Uses the `messages` table (active
    persistence layer) rather than `conversations`.

    Query params:
        page      – 1-based page number (default: 1)
        page_size – rows per page, max 100 (default: 20)
    """
    try:
        if page < 1:
            page = 1
        page_size = min(max(page_size, 1), 100)
        offset = (page - 1) * page_size

        supabase = get_supabase()

        # Fetch messages for this tenant ordered newest-first, then collapse
        # to distinct chat_jids in Python (Supabase JS SDK doesn't expose
        # DISTINCT ON easily via the REST API).
        response = (
            supabase.table("messages")
            .select(
                "chat_jid, tenant_id, role, content, customer_phone, "
                "customer_name, device_jid, phone_jid, chat_type, created_at"
            )
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(page_size * 10)   # over-fetch to allow dedup in Python
            .execute()
        )

        rows = response.data or []

        # Collapse to one entry per chat_jid (most-recent message wins)
        seen: dict = {}
        for row in rows:
            jid = row.get("chat_jid")
            if jid and jid not in seen:
                seen[jid] = row

        # Apply pagination on the deduplicated list
        unique = list(seen.values())
        total = len(unique)
        page_data = unique[offset : offset + page_size]

        return {
            "data": page_data,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": (offset + page_size) < total,
        }

    except Exception as e:
        logger.error(f"❌ get_conversations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== CONVERSATION THREADS ====================


@router.get("/conversations/threads")
async def get_conversation_threads(
    tenant_id: str = Depends(verify_session),
    device_jid: str = None,
    limit: int = 50,
):
    """
    Return conversation thread summaries via the `get_conversation_threads`
    SQL function (created in migration 020).

    Each row represents one unique (device_jid, chat_jid) thread with:
      - last_message_at
      - message_count
      - last_content  (latest message snippet)
      - chat_type     (individual | group)
      - phone_jid     (resolved phone JID for @lid contacts, or null)

    Query params:
        device_jid – filter to a specific business device (optional)
        limit      – max rows returned, capped at 200 (default: 50)
    """
    try:
        limit = min(max(limit, 1), 200)
        supabase = get_supabase()

        # Build RPC params
        params: dict = {"p_tenant_id": tenant_id, "p_limit": limit}
        if device_jid:
            params["p_device_jid"] = device_jid

        response = supabase.rpc("get_conversation_threads", params).execute()
        return {"data": response.data or [], "limit": limit}

    except Exception as e:
        logger.error(f"❌ get_conversation_threads error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== JID MAPPINGS ====================


class JidMappingPayload(BaseModel):
    """Payload for upserting a LID-to-phone JID mapping."""

    lid_jid: str = Field(..., description="Linked-device JID ending with @lid")
    phone_jid: str = Field(
        ..., description="Resolved phone JID, e.g. 60174106981@s.whatsapp.net"
    )
    source: str = Field(
        default="manual",
        description="Origin of the mapping: 'manual', 'webhook', 'bridge', etc.",
    )


@router.post("/jid-mappings")
async def upsert_jid_mapping(
    payload: JidMappingPayload,
    tenant_id: str = Depends(verify_session),
):
    """
    Upsert a LID → phone JID mapping in the `jid_mappings` table.

    Called by the dashboard operator when they know which real phone number
    corresponds to a ``@lid`` contact.  The mapping is used by
    ``resolve_phone_jid()`` in ``jid_utils.py`` to enrich future messages.

    Raises 400 if ``lid_jid`` does not end with ``@lid``.
    """
    try:
        if not payload.lid_jid.endswith("@lid"):
            raise HTTPException(
                status_code=400,
                detail="lid_jid must end with @lid",
            )

        supabase = get_supabase()
        supabase.table("jid_mappings").upsert(
            {
                "tenant_id": tenant_id,
                "lid_jid": payload.lid_jid,
                "phone_jid": payload.phone_jid,
                "source": payload.source,
            },
            on_conflict="tenant_id,lid_jid",
        ).execute()

        logger.info(
            f"✅ jid_mapping upserted: {payload.lid_jid} → {payload.phone_jid} "
            f"(tenant={tenant_id}, source={payload.source})"
        )
        return {
            "status": "success",
            "lid_jid": payload.lid_jid,
            "phone_jid": payload.phone_jid,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ upsert_jid_mapping error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== MESSAGES ENDPOINT ====================


@router.get("/messages/{chat_jid}")
async def get_messages_for_chat(
    chat_jid: str,
    tenant_id: str = Depends(verify_session),
):
    """
    Fetch message history for a specific chat_jid from the messages table.

    chat_jid is URL-encoded in the path (e.g. %40 → @). FastAPI decodes it
    automatically via path parameter extraction, so no manual decoding needed.

    Returns a JSON array of {id, role, content, timestamp, media_url,
    media_type} ordered ASC by created_at. media_url/media_type are the
    customer's raw WhatsApp attachment (see add_message_media_columns.sql,
    2026-08-23) — null for text-only messages. Returns [] on any error so
    the dashboard never crashes.
    """
    try:
        supabase = get_supabase()
        response = (
            supabase.table("messages")
            .select("id, role, content, created_at, media_url, media_type")
            .eq("tenant_id", tenant_id)
            .eq("chat_jid", chat_jid)
            .order("created_at", desc=False)
            .limit(100)
            .execute()
        )

        rows = response.data or []
        return [
            {
                "id": row.get("id"),
                "role": row.get("role", "user"),
                "content": row.get("content", ""),
                "timestamp": row.get("created_at"),
                "media_url": row.get("media_url"),
                "media_type": row.get("media_type"),
            }
            for row in rows
        ]

    except Exception as e:
        logger.error(
            f"❌ get_messages_for_chat error (chat_jid={chat_jid}, tenant={tenant_id}): {e}"
        )
        return []


# ==================== LEADS ENDPOINT ====================


@router.get("/leads")
async def get_leads(
    tenant_id: str = Depends(verify_session),
):
    """
    Return escalations as a leads list for the dashboard Leads tab.
    Joins conversations to get contact_name where available.
    """
    try:
        supabase = get_supabase()
        response = (
            supabase.table("escalations")
            .select(
                "id, chat_jid, reason, priority, status, created_at, metadata"
            )
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )

        rows = response.data or []

        # Fetch contact names from conversations in bulk
        jids = list({row.get("chat_jid") for row in rows if row.get("chat_jid")})
        name_map: dict = {}
        if jids:
            try:
                conv_resp = (
                    supabase.table("conversations")
                    .select("chat_jid, contact_name, customer_jid")
                    .eq("tenant_id", tenant_id)
                    .in_("chat_jid", jids)
                    .execute()
                )
                for conv in (conv_resp.data or []):
                    jid = conv.get("chat_jid") or ""
                    name = conv.get("contact_name")
                    if not jid:
                        continue
                    if jid in name_map:
                        continue
                    if name and "@" not in name:
                        # Stored contact name (rare but possible)
                        name_map[jid] = name
                    elif jid.endswith("@lid"):
                        # Device-linked ID — derive from phone if resolvable, else use last-6
                        digits = jid.replace("@lid", "")
                        name_map[jid] = "Customer …" + digits[-6:]
                    elif jid.endswith("@g.us"):
                        name_map[jid] = "Group …" + jid[:8]
                    else:
                        # Standard JID: extract phone number
                        phone = jid.split("@")[0]
                        name_map[jid] = format_phone_number(phone) if phone else jid
            except Exception as name_map_err:
                logger.debug(f"name_map build failed, falling back to JID display: {name_map_err}")

        leads = []
        for row in rows:
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    import json as _json
                    metadata = _json.loads(metadata)
                except Exception:
                    metadata = {}
            chat_jid = row.get("chat_jid", "")
            leads.append(
                {
                    "id": row.get("id"),
                    "chat_jid": chat_jid,
                    "reason": row.get("reason"),
                    "priority": row.get("priority"),
                    "status": row.get("status"),
                    "created_at": row.get("created_at"),
                    "customer_name": name_map.get(chat_jid),
                    "interest": metadata.get("leadstatus") if metadata else None,
                }
            )
        return leads

    except Exception as e:
        logger.error(
            f"❌ get_leads error (tenant={tenant_id}): {e}"
        )
        return []


# ==================== BLACKLIST / BLOCKED NUMBERS ====================


class BlockedNumberRequest(BaseModel):
    phone_number: str
    reason: Optional[str] = None
    notes: Optional[str] = None
    customer_jid: Optional[str] = None   # auto-derived from phone_number if omitted
    blocked_by: Optional[str] = None     # defaults to "dashboard"


@router.get("/blacklist")
async def get_blacklist(tenant_id: str = Depends(verify_session)):
    """Return all blocked numbers for this tenant."""
    try:
        supabase = get_supabase()
        result = (
            supabase.table("blocked_numbers")
            .select("id, phone_number, customer_jid, reason, notes, is_active, blocked_at, blocked_by")
            .eq("tenant_id", tenant_id)
            .order("id", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"❌ get_blacklist error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch blocked numbers")


@router.post("/blacklist")
async def add_to_blacklist(
    request: BlockedNumberRequest, tenant_id: str = Depends(verify_session)
):
    """Add a phone number to this tenant's blocked list."""
    if not request.phone_number or not request.phone_number.strip():
        raise HTTPException(status_code=400, detail="phone_number is required")

    # Normalise: strip @s.whatsapp.net suffix if accidentally included
    phone = request.phone_number.strip().split("@")[0]

    try:
        supabase = get_supabase()

        # Upsert so duplicate adds just re-activate rather than error
        existing = (
            supabase.table("blocked_numbers")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone_number", phone)
            .limit(1)
            .execute()
        )

        # Derive NOT NULL column values with safe defaults
        customer_jid = request.customer_jid or f"{phone}@s.whatsapp.net"
        blocked_by = request.blocked_by or "dashboard"
        reason = request.reason or ""   # reason column is NOT NULL in DB
        notes = request.notes           # notes is nullable

        if existing.data:
            # Re-activate if previously soft-deleted
            supabase.table("blocked_numbers").update(
                {
                    "is_active": True,
                    "reason": reason,
                    "notes": notes,
                    "customer_jid": customer_jid,
                    "blocked_by": blocked_by,
                }
            ).eq("id", existing.data[0]["id"]).eq("tenant_id", tenant_id).execute()
            logger.info(f"✅ Re-activated blocked number {phone} (tenant={tenant_id})")
            return {"status": "success", "message": f"{phone} is now blocked"}

        supabase.table("blocked_numbers").insert(
            {
                "tenant_id": tenant_id,
                "phone_number": phone,
                "customer_jid": customer_jid,
                "blocked_by": blocked_by,
                "block_type": "permanent",
                "reason": reason,
                "notes": notes,
                "is_active": True,
            }
        ).execute()
        logger.info(f"✅ Blocked number added: {phone} (tenant={tenant_id})")
        return {"status": "success", "message": f"{phone} has been blocked"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ add_to_blacklist error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to block number")


@router.delete("/blacklist/{entry_id}")
async def remove_from_blacklist(
    entry_id: str, tenant_id: str = Depends(verify_session)
):
    """Soft-delete (deactivate) a blocked-number entry by its UUID."""
    import re
    if not re.match(r"^[0-9a-f-]{36}$", entry_id):
        raise HTTPException(status_code=400, detail="Invalid entry ID")

    try:
        supabase = get_supabase()

        # Verify ownership before modifying
        check = (
            supabase.table("blocked_numbers")
            .select("id")
            .eq("id", entry_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Entry not found")

        supabase.table("blocked_numbers").update({"is_active": False}).eq(
            "id", entry_id
        ).eq("tenant_id", tenant_id).execute()

        logger.info(f"✅ Unblocked number entry {entry_id} (tenant={tenant_id})")
        return {"status": "success", "message": "Number unblocked"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ remove_from_blacklist error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to unblock number")


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str,
    resolution_notes: Optional[str] = None,
    tenant_id: str = Depends(verify_session)
):
    """
    Close/resolve an escalation manually via dashboard.
    This allows human agents to return chat control to AI.
    """
    import re
    if not re.match(r"^[0-9a-f-]{36}$", escalation_id):
        raise HTTPException(status_code=400, detail="Invalid escalation ID")

    try:
        supabase = get_supabase()

        # Security: Verify escalation belongs to this tenant
        # NOTE (2026-08-06): use `.maybe_single()` instead of `.single()`
        # — `.single()` raises an APIError when zero rows match, which
        # was bubbling up as 500 "Failed to resolve escalation" instead
        # of a clean 404. `.maybe_single()` returns None cleanly.
        try:
            escalation = (
                supabase.table("escalations")
                .select("*")
                .eq("id", escalation_id)
                .eq("tenant_id", tenant_id)
                .maybe_single()
                .execute()
            )
        except Exception as lookup_err:
            logger.warning(
                "Escalation lookup raised for %s (tenant=%s): %s",
                escalation_id, tenant_id, lookup_err,
            )
            escalation = None

        if not escalation or not getattr(escalation, "data", None):
            raise HTTPException(status_code=404, detail="Escalation not found")

        # Update escalation to resolved
        supabase.table("escalations").update({
            "status": "resolved",
            "resolved_at": datetime.utcnow().isoformat() + "Z",
            "resolution_notes": resolution_notes or "Closed via dashboard"
        }).eq("id", escalation_id).eq("tenant_id", tenant_id).execute()

        logger.info(f"✅ Escalation {escalation_id} resolved via dashboard (tenant={tenant_id})")
        return {
            "status": "success",
            "message": "Escalation resolved - AI will now respond to this customer",
            "escalation_id": escalation_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ resolve_escalation error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to resolve escalation")


# ==================== EMAIL NOTIFICATIONS TEST ====================


@router.post("/settings/test-email")
async def test_email_notification(
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """
    Send a test escalation-notification email via SMTP.
    Uses the same env vars as EscalationNotifier:
      SMTP_HOST  (default: smtp.gmail.com)
      SMTP_PORT  (default: 587)
      SMTP_USER
      SMTP_PASSWORD
      EMAIL_FROM (default: same as SMTP_USER)

    Body JSON: { "to": "recipient@example.com" }
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    body = await request.json()
    to_addr = (body.get("to") or "").strip()
    if not to_addr or "@" not in to_addr:
        raise HTTPException(status_code=400, detail="A valid 'to' email address is required")

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_from = os.environ.get("EMAIL_FROM", smtp_user)

    if not smtp_user or not smtp_password:
        return {
            "configured": False,
            "message": "Email notification via SMTP is not configured on this server. Contact your administrator.",
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "[Bijou AI] Test Email — Escalation Notifications Active ✅"
        msg["From"] = email_from
        msg["To"] = to_addr

        html = f"""\
<html><body style="font-family:Arial,sans-serif;color:#333;padding:24px">
  <h2 style="color:#10b981">✅ Email Notifications Working</h2>
  <p>This is a test message from <strong>Bijou AI</strong> for tenant <code>{tenant_id}</code>.</p>
  <p>When a customer is escalated to a human agent, a notification email will be sent
  to the agent's email address configured in the Agents panel.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
  <p style="font-size:12px;color:#999">Sent via SMTP from {email_from}</p>
</body></html>"""

        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, [to_addr], msg.as_string())

        logger.info(f"📧 Test email sent to {to_addr} (tenant={tenant_id})")
        return {"configured": True, "success": True, "message": f"Test email sent to {to_addr}"}

    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=401, detail="SMTP authentication failed. Check SMTP_USER / SMTP_PASSWORD.")
    except smtplib.SMTPException as exc:
        raise HTTPException(status_code=502, detail=f"SMTP error: {exc}")
    except Exception as exc:
        logger.error(f"❌ test_email_notification failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {exc}")


# ==================== ANALYTICS TIMESERIES ====================


@router.get("/analytics/timeseries")
async def get_analytics_timeseries(
    tenant_id: str = Depends(verify_session),
    days: int = Query(default=30, ge=7, le=90),
):
    """
    Return daily message volume, lead captures, and escalations for the past N
    days.  Aggregation is done in Python because the Supabase Python SDK does not
    support GROUP BY directly.
    """
    try:
        supabase = get_supabase()
        since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()

        # Fetch raw rows — only created_at needed for aggregation
        msg_res = (
            supabase.table("messages")
            .select("created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", since)
            .execute()
        )
        lead_res = (
            supabase.table("contacts")
            .select("created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", since)
            .execute()
        )
        esc_res = (
            supabase.table("escalations")
            .select("created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", since)
            .execute()
        )
        booking_res_data: list = []
        try:
            booking_res = (
                supabase.table("call_bookings")
                .select("created_at")
                .eq("tenant_id", tenant_id)
                .gte("created_at", since)
                .execute()
            )
            booking_res_data = booking_res.data or []
        except Exception:
            pass  # call_bookings table may not exist for all tenants

        # Build ordered label list (oldest → today)
        today = datetime.utcnow().date()
        labels = [
            (today - timedelta(days=days - 1 - i)).isoformat()
            for i in range(days)
        ]

        def bucket(rows: list, labels: list) -> list:
            counts: Dict[str, int] = {l: 0 for l in labels}
            for row in rows:
                d = (row.get("created_at") or "")[:10]
                if d in counts:
                    counts[d] += 1
            return [counts[l] for l in labels]

        return {
            "labels": labels,
            "messages": bucket(msg_res.data or [], labels),
            "leads": bucket(lead_res.data or [], labels),
            "escalations": bucket(esc_res.data or [], labels),
            "bookings": bucket(booking_res_data, labels),
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"❌ analytics_timeseries error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch analytics timeseries")


# ==================== CALENDAR & EMAIL CONFIG (Self-Service) ====================


@router.get("/settings/calendar")
async def get_calendar_configuration(tenant_id: str = Depends(verify_session)):
    """
    GET tenant's Cal.com configuration.
    Returns masked API key for security (only last 4 chars visible).
    """
    try:
        from src.core.dashboard_settings_endpoints import get_calendar_config

        supabase = get_supabase()
        config = get_calendar_config(supabase, tenant_id)

        if not config:
            return {
                "configured": False,
                "message": "No calendar configuration found. Please add your Cal.com credentials."
            }

        return {
            "configured": True,
            "config": config
        }

    except Exception as e:
        logger.error(f"❌ get_calendar_configuration error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve calendar configuration")


@router.put("/settings/calendar")
async def update_calendar_configuration(
    request: Request,
    tenant_id: str = Depends(verify_session)
):
    """
    PUT (create or update) tenant's Cal.com configuration.

    Body JSON:
    {
        "cal_username": "getbijou",
        "cal_api_key": "cal_live_xxxxxx",
        "default_event_type_id": null,
        "send_confirmation_email": true
    }
    """
    try:
        from src.core.dashboard_settings_endpoints import (
            CalendarConfigRequest,
            upsert_calendar_config
        )

        body = await request.json()
        data = CalendarConfigRequest(**body)

        supabase = get_supabase()
        result = upsert_calendar_config(supabase, tenant_id, data)

        return result

    except HTTPException:
        raise
    except Exception as e:
        # Pydantic ValidationError -> 422 (unprocessable entity, not 500)
        from pydantic import ValidationError
        if isinstance(e, ValidationError):
            raise HTTPException(status_code=422, detail=jsonable_errors(e))
        logger.error(f"❌ update_calendar_configuration error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save calendar configuration: {str(e)}")


@router.post("/settings/calendar/test")
async def test_calendar_connection(
    request: Request,
    tenant_id: str = Depends(verify_session)
):
    """
    Test Cal.com API connection with provided credentials.

    Body JSON:
    {
        "cal_username": "getbijou",
        "cal_api_key": "cal_live_xxxxxx"
    }

    Returns:
        {
            "success": true,
            "message": "Connected successfully",
            "username": "getbijou",
            "event_types_count": 3
        }
    """
    # NOTE (2026-08-06): the previous version did `import httpx` *inside* the
    # `try` block, AFTER the early `raise HTTPException(400, ...)` for missing
    # creds. The `except httpx.TimeoutException` clause below then hit
    # `UnboundLocalError: cannot access local variable 'httpx'` and the whole
    # endpoint 500'd on the very case it's supposed to return a clean 400 for.
    # Hoisting the import out of the try/except fixes that.
    import httpx

    try:
        body = await request.json()
        cal_username = body.get("cal_username", "").strip()
        cal_api_key = body.get("cal_api_key", "").strip()

        if not cal_username or not cal_api_key:
            raise HTTPException(status_code=400, detail="Username and API key are required")

        # Test connection by fetching event types
        # Cal.com uses query parameter authentication, not Bearer token
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.cal.com/v1/event-types?apiKey={cal_api_key}"
            )

            if response.status_code == 200:
                data = response.json()
                event_types = data.get("event_types", [])

                logger.info(f"✅ Cal.com connection test successful for {cal_username} (tenant={tenant_id[:8]}...)")

                return {
                    "success": True,
                    "message": f"Connected successfully to {cal_username}'s Cal.com account",
                    "username": cal_username,
                    "event_types_count": len(event_types),
                    "event_types": [
                        {"id": et.get("id"), "title": et.get("title", "Untitled")}
                        for et in event_types[:5]  # Show first 5 event types
                    ]
                }
            elif response.status_code == 401:
                logger.warning(f"❌ Cal.com auth failed for {cal_username} (invalid API key)")
                return {
                    "success": False,
                    "error": "Invalid API key. Please check your credentials.",
                    "status_code": 401
                }
            else:
                logger.error(f"❌ Cal.com API error: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "error": f"Cal.com API error: {response.status_code}",
                    "status_code": response.status_code
                }

    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger.error(f"❌ Cal.com connection timeout (tenant={tenant_id})")
        raise HTTPException(status_code=504, detail="Connection timeout. Please try again.")
    except Exception as e:
        logger.error(f"❌ test_calendar_connection error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Connection test failed: {str(e)}")


@router.get("/calendar/oauth-status")
async def get_calendar_oauth_status(tenant_id: str = Depends(verify_session)):
    """
    GET OAuth connection status for tenant's calendar.
    Returns whether connected via OAuth and the linked account email.
    """
    try:
        supabase = get_supabase()
        result = supabase.table("tenant_calendars") \
            .select("is_oauth_connected,oauth_user_email,cal_username,updated_at") \
            .eq("tenant_id", tenant_id) \
            .eq("is_active", True) \
            .limit(1) \
            .execute()

        if result.data and result.data[0].get("is_oauth_connected"):
            row = result.data[0]
            return {
                "connected": True,
                "email": row.get("oauth_user_email") or row.get("cal_username") or "Connected",
                "connected_at": row.get("updated_at"),
            }
        return {"connected": False}
    except Exception as e:
        logger.error(f"❌ get_calendar_oauth_status error: {e}")
        return {"connected": False}


@router.post("/calendar/oauth-exchange")
async def calendar_oauth_exchange(
    request: Request,
    tenant_id: str = Depends(verify_session)
):
    """
    Exchange cal.com OAuth authorization code for access + refresh tokens.
    Called by the /callback page after user authorizes on cal.com.

    Body: { "code": "...", "code_verifier": "...", "redirect_uri": "..." }
    """
    import httpx
    import os

    CAL_CLIENT_ID = "3195ffcf36e5fbac1d894f625a96270418d36afb5578e051dae8b64330346652"
    # Cal.com standard OAuth token endpoint (per Cal.com OAuth docs)
    EXCHANGE_URL = "https://app.cal.com/api/auth/oauth/token"

    try:
        body = await request.json()
        code          = body.get("code", "").strip()
        code_verifier = body.get("code_verifier", "").strip()
        redirect_uri  = body.get("redirect_uri", "https://app.mybijou.xyz/callback")

        if not code or not code_verifier:
            raise HTTPException(status_code=400, detail="code and code_verifier are required")

        # Exchange with cal.com — standard OAuth2 PKCE token request
        async with httpx.AsyncClient(timeout=15.0) as client:
            exchange_resp = await client.post(
                EXCHANGE_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": CAL_CLIENT_ID,
                    "code": code,
                    "code_verifier": code_verifier,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if exchange_resp.status_code not in (200, 201):
                logger.error(f"❌ cal.com exchange failed: {exchange_resp.status_code} — {exchange_resp.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"cal.com OAuth exchange failed ({exchange_resp.status_code}): {exchange_resp.text[:200]}"
                )

            tokens = exchange_resp.json()

        # Standard OAuth2 response: { access_token, refresh_token, token_type, expires_in }
        # Cal.com may also wrap in { data: ... } — handle both
        data          = tokens.get("data", tokens)
        access_token  = data.get("access_token") or data.get("accessToken")
        refresh_token = data.get("refresh_token") or data.get("refreshToken")
        expires_in    = data.get("expires_in") or data.get("accessTokenExpiresAt")
        expires_at    = expires_in  # store as-is; could be timestamp or seconds
        user_data     = data.get("user", {})
        user_email    = user_data.get("email") or data.get("email") or ""
        user_id       = str(user_data.get("id") or data.get("userId") or "")
        cal_username  = user_data.get("username") or (user_email.split("@")[0] if user_email else "")

        if not access_token:
            raise HTTPException(status_code=502, detail="cal.com did not return an access token")

        # Upsert into tenant_calendars
        supabase = get_supabase()
        existing = supabase.table("tenant_calendars") \
            .select("id") \
            .eq("tenant_id", tenant_id) \
            .limit(1) \
            .execute()

        payload = {
            "tenant_id":          tenant_id,
            "provider":           "cal.com",
            "is_active":          True,
            "is_oauth_connected": True,
            "oauth_access_token": access_token,
            "oauth_refresh_token": refresh_token,
            "oauth_expiry":        expires_at,
            "oauth_scope":         "READ_PROFILE READ_BOOKING READ_AVAILABILITY READ_EVENT_TYPE BOOK_BOOKING",
            "oauth_user_email":    user_email,
            "oauth_user_id":       user_id,
            "cal_username":        cal_username,
        }

        if existing.data:
            supabase.table("tenant_calendars").update(payload).eq("tenant_id", tenant_id).execute()
        else:
            supabase.table("tenant_calendars").insert(payload).execute()

        logger.info(f"✅ cal.com OAuth connected for tenant {tenant_id[:8]}... ({user_email})")

        return {
            "success": True,
            "email":    user_email,
            "username": cal_username,
            "message":  "Calendar connected successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ calendar_oauth_exchange error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail=f"OAuth exchange failed: {str(e)}")


@router.delete("/calendar/oauth-disconnect")
async def calendar_oauth_disconnect(tenant_id: str = Depends(verify_session)):
    """Remove OAuth tokens and mark calendar as disconnected."""
    try:
        supabase = get_supabase()
        supabase.table("tenant_calendars").update({
            "is_oauth_connected":  False,
            "oauth_access_token":  None,
            "oauth_refresh_token": None,
            "oauth_expiry":        None,
            "oauth_user_email":    None,
            "oauth_user_id":       None,
        }).eq("tenant_id", tenant_id).execute()
        logger.info(f"✅ cal.com OAuth disconnected for tenant {tenant_id[:8]}...")
        return {"success": True, "message": "Calendar disconnected"}
    except Exception as e:
        logger.error(f"❌ calendar_oauth_disconnect error: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect calendar")


@router.get("/settings/email")
async def get_email_configuration(tenant_id: str = Depends(verify_session)):
    """
    GET tenant's SMTP configuration.
    Returns masked password for security.
    """
    try:
        from src.core.dashboard_settings_endpoints import get_email_config

        supabase = get_supabase()
        config = get_email_config(supabase, tenant_id)

        if not config:
            return {
                "configured": False,
                "message": "No email configuration found. Please add your SMTP credentials."
            }

        return {
            "configured": True,
            "config": config
        }

    except Exception as e:
        logger.error(f"❌ get_email_configuration error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve email configuration")


@router.delete("/whatsapp/disconnect")
async def disconnect_whatsapp(tenant_id: str = Depends(verify_session)):
    """
    Disconnect WhatsApp session for this tenant.

    Workflow:
    1. Get device_id from whatsapp_devices table
    2. Call bridge DELETE /device/{device_id}
    3. Update tenant: whatsapp_connected = false, session_active = false
    4. Delete device mapping from whatsapp_devices

    Returns:
        {"success": true, "message": "WhatsApp disconnected successfully"}
    """
    try:
        supabase = get_supabase()

        # Get device_id from whatsapp_devices
        device_result = (
            supabase.table("whatsapp_devices")
            .select("device_id")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )

        # If device mapping exists, disconnect from bridge
        if device_result.data:
            device_id = device_result.data[0]["device_id"]
            logger.info(f"🔌 Disconnecting WhatsApp device {device_id} for tenant {tenant_id}")

            # Call bridge to delete device
            bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-production-v2.fly.dev")
            bridge_user = os.getenv("BRIDGE_USER", "bijou-prod")
            bridge_password = os.getenv("BRIDGE_PASSWORD", "")

            import base64
            auth_str = base64.b64encode(f"{bridge_user}:{bridge_password}".encode()).decode()

            # Delete device from bridge
            async with httpx.AsyncClient(timeout=10.0) as client:
                bridge_response = await client.delete(
                    f"{bridge_url}/device/{device_id}",
                    headers={"Authorization": f"Basic {auth_str}"},
                )
                logger.info(f"🌉 Bridge disconnect response: {bridge_response.status_code}")
        else:
            logger.warning(f"⚠️ No device mapping found for tenant {tenant_id}, will only update tenant status")

        # Update tenant status (regardless of bridge response - allow manual recovery)
        supabase.table("tenants").update({
            "whatsapp_connected": False,
            "session_active": False,
            "whatsapp_jid": None,
        }).eq("id", tenant_id).execute()

        # Delete device mapping
        supabase.table("whatsapp_devices").delete().eq("tenant_id", tenant_id).execute()

        logger.info(f"✅ WhatsApp disconnected successfully for tenant {tenant_id}")
        return {
            "success": True,
            "message": "WhatsApp disconnected successfully. You can reconnect by scanning QR code again.",
        }

    except Exception as e:
        logger.error(f"❌ Error disconnecting WhatsApp for tenant {tenant_id}: {e}")
        return {
            "success": False,
            "message": f"Failed to disconnect WhatsApp: {str(e)}",
        }


@router.put("/settings/email")
async def update_email_configuration(
    request: Request,
    tenant_id: str = Depends(verify_session)
):
    """
    PUT (create or update) tenant's SMTP configuration.

    Body JSON:
    {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "your-email@gmail.com",
        "smtp_pass": "your-app-password",
        "smtp_use_tls": true,
        "from_email": "your-email@gmail.com",
        "from_name": "Bijou Properties",
        "reply_to_email": null
    }
    """
    try:
        from src.core.dashboard_settings_endpoints import (
            EmailConfigRequest,
            upsert_email_config
        )

        body = await request.json()
        data = EmailConfigRequest(**body)

        supabase = get_supabase()
        result = upsert_email_config(supabase, tenant_id, data)

        return result

    except HTTPException:
        raise
    except Exception as e:
        # Pydantic ValidationError -> 422 (unprocessable entity, not 500)
        if isinstance(e, ValidationError):
            raise HTTPException(status_code=422, detail=jsonable_errors(e))
        logger.error(f"❌ update_email_configuration error (tenant={tenant_id}): {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save email configuration: {str(e)}")


# ============================================================================
# Vertical / Industry Vertical Settings
# ============================================================================

@router.get("/settings/vertical")
async def get_tenant_vertical(tenant_id: str = Depends(verify_session)):
    """Get the current industry vertical assigned to this tenant."""
    try:
        supabase = get_supabase()
        result = supabase.table("tenant_verticals") \
            .select("vertical_id, enabled") \
            .eq("tenant_id", tenant_id) \
            .eq("enabled", True) \
            .limit(1) \
            .execute()

        if result.data:
            vertical_id = result.data[0]["vertical_id"]
            # Also fetch the label from vertical_templates
            tmpl = supabase.table("vertical_templates") \
                .select("vertical_id, vertical_name, emoji, description") \
                .eq("vertical_id", vertical_id) \
                .limit(1) \
                .execute()
            label_data = tmpl.data[0] if tmpl.data else {}
            return {
                "vertical_id": vertical_id,
                "vertical_name": label_data.get("vertical_name", vertical_id),
                "emoji": label_data.get("emoji", "🏢"),
            }
        return {"vertical_id": None, "vertical_name": None, "emoji": None}

    except Exception as e:
        logger.error(f"❌ get_tenant_vertical error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/settings/vertical")
async def set_tenant_vertical(
    request: Request,
    tenant_id: str = Depends(verify_session),
):
    """Assign or change the industry vertical for this tenant."""
    try:
        body = await request.json()
        vertical_id = body.get("vertical_id", "").strip()
        if not vertical_id:
            raise HTTPException(status_code=400, detail="vertical_id is required")

        supabase = get_supabase()

        # Verify vertical exists
        tmpl = supabase.table("vertical_templates") \
            .select("vertical_id, vertical_name") \
            .eq("vertical_id", vertical_id) \
            .limit(1) \
            .execute()
        if not tmpl.data:
            raise HTTPException(status_code=404, detail=f"Vertical '{vertical_id}' not found")

        # Disable any previous verticals for this tenant
        supabase.table("tenant_verticals") \
            .update({"enabled": False}) \
            .eq("tenant_id", tenant_id) \
            .execute()

        # Upsert the new vertical
        supabase.table("tenant_verticals").upsert({
            "tenant_id": tenant_id,
            "vertical_id": vertical_id,
            "enabled": True,
        }, on_conflict="tenant_id,vertical_id").execute()

        logger.info(f"✅ Tenant {tenant_id[:8]} vertical set to '{vertical_id}'")
        return {"success": True, "vertical_id": vertical_id, "vertical_name": tmpl.data[0]["vertical_name"]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ set_tenant_vertical error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings/verticals")
async def list_available_verticals():
    """List all available industry verticals for the picker UI."""
    try:
        supabase = get_supabase()
        # Select * and normalize in Python — the table's columns (emoji, is_active, sort_order)
        # vary by environment/migration state; referencing absent ones 500s. Try the rich query,
        # then fall back to a bare select so the picker still populates on a minimal schema.
        try:
            result = supabase.table("vertical_templates") \
                .select("*").eq("is_active", True).order("sort_order").execute()
        except Exception:
            result = supabase.table("vertical_templates").select("*").execute()
        verticals = [
            {
                "vertical_id": v.get("vertical_id"),
                "vertical_name": v.get("vertical_name"),
                "emoji": v.get("emoji") or "🏢",
                "description": v.get("description"),
            }
            for v in (result.data or [])
        ]
        return {"verticals": verticals}
    except Exception as e:
        logger.error(f"❌ list_available_verticals error: {e}")
        # Non-fatal for the UI — return an empty picker rather than a 500 that logs as an error.
        return {"verticals": [], "error": str(e)}
