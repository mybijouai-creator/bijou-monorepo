#!/usr/bin/env python3
"""
Outreach API - REST endpoints for WhatsApp outreach campaign management.
=========================================================================

Provides 12 endpoints for:
- System status & daily limit monitoring
- Contact import (JSON + CSV)
- Campaign CRUD (create, list, start, pause, stats)
- Queue monitoring

All routes are tenant-isolated via X-Tenant-ID header or query param.

Author: W3J Bijou AI
Version: 1.0.0
"""

import base64
import csv
import io
import logging
import os
import random
import string
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

import httpx

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])

# ──────────────────────────────────────────────
# Dependency: Supabase client
# ──────────────────────────────────────────────

def _get_supabase():
    """Get Supabase client for outreach operations."""
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Database not configured")
    return create_client(url, key)


# ──────────────────────────────────────────────
# Dependency: Tenant resolution
# ──────────────────────────────────────────────

async def get_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    tenant_id: Optional[str] = Query(None),
) -> str:
    """Resolve tenant_id from header or query param."""
    tid = x_tenant_id or tenant_id
    if not tid:
        raise HTTPException(
            status_code=401,
            detail="tenant_id required (X-Tenant-ID header or ?tenant_id= query param)",
        )
    return tid


# ──────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────

class ContactIn(BaseModel):
    phone: str
    name: Optional[str] = None
    tag: Optional[str] = None
    business_type: Optional[str] = None
    area: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    # ── Outreach intelligence fields (all optional, backward-compatible) ────
    industry_type: Optional[str] = None
    sub_type: Optional[str] = None
    country: Optional[str] = "MY"
    language_pref: Optional[str] = "auto"
    business_size: Optional[str] = None
    estimated_revenue: Optional[str] = None
    whatsapp_active: Optional[str] = "unknown"
    online_presence: Optional[str] = "unknown"
    pain_point_hint: Optional[str] = None
    competitor_used: Optional[str] = None
    persona: Optional[str] = "direct"
    priority: Optional[str] = "normal"
    custom_note: Optional[str] = None
    max_followups: Optional[int] = 3


class ContactImportRequest(BaseModel):
    segment_name: str
    contacts: List[ContactIn]
    tag: Optional[str] = None
    campaign_config_id: Optional[str] = None   # UUID of outreach_campaign_configs row
    use_ai_generation: Optional[bool] = False  # reserved — AI gen happens at campaign-start


class CampaignConfigCreateRequest(BaseModel):
    """Request body for POST /api/outreach/configs."""
    campaign_id: str
    name: str
    industry_type: str
    sub_type: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    industry_config: Dict[str, Any] = Field(default_factory=dict)
    qualification_config: Dict[str, Any] = Field(default_factory=dict)
    sequence_config: Dict[str, Any] = Field(default_factory=dict)
    persona_config: Dict[str, Any] = Field(default_factory=dict)
    reveal_config: Dict[str, Any] = Field(default_factory=dict)
    escalation_config: Dict[str, Any] = Field(default_factory=dict)


class CampaignCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    # Validated against the DB CHECK constraint in 032_outreach_system.sql
    campaign_type: Literal["outreach", "nurture", "reactivation", "event"] = "outreach"
    segment_id: Optional[str] = None
    daily_limit: int = Field(default=50, ge=5, le=200)
    send_window_start: str = "09:00"
    send_window_end: str = "18:00"
    min_delay_seconds: int = Field(default=120, ge=30, le=600)
    max_delay_seconds: int = Field(default=300, ge=60, le=3600)
    stop_on_reply: bool = True
    template_ids: Optional[List[str]] = None
    sequence_type: str = "single"
    follow_up_days: Optional[List[int]] = None


class CampaignStartRequest(BaseModel):
    immediate: bool = False


# ──────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Normalize Malaysian phone number to JID format."""
    phone = phone.strip().replace("+", "").replace("-", "").replace(" ", "")
    if not phone.startswith("60"):
        phone = "60" + phone.lstrip("0")
    return phone


def _phone_to_jid(phone: str) -> str:
    """Convert normalized phone to WhatsApp JID."""
    normalized = _normalize_phone(phone)
    return f"{normalized}@s.whatsapp.net"


def _get_tenant_outreach_settings(db, tenant_id: str) -> Dict:
    """Fetch tenant's outreach configuration."""
    try:
        result = db.table("tenants") \
            .select("daily_outreach_limit, outreach_enabled, outreach_start_time, outreach_end_time, outreach_timezone") \
            .eq("id", tenant_id) \
            .maybe_single() \
            .execute()
        rdata = getattr(result, "data", None) if result else None
        return rdata if isinstance(rdata, dict) else {}
    except Exception:
        return {}


def _get_sent_today(db, tenant_id: str) -> int:
    """Count messages sent today for this tenant."""
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = db.table("outbound_queue") \
            .select("id", count="exact") \
            .eq("tenant_id", tenant_id) \
            .in_("status", ["sent", "delivered", "read"]) \
            .gte("sent_at", today_start.isoformat()) \
            .execute()
        return result.count if hasattr(result, "count") and result.count else 0
    except Exception:
        return 0


# ──────────────────────────────────────────────
# 1. SYSTEM STATUS
# ──────────────────────────────────────────────

@router.get("/status")
async def get_outreach_status(tenant_id: str = Depends(verify_session)):
    """Get outreach system status, daily counts, and business hours info."""
    db = _get_supabase()
    settings = _get_tenant_outreach_settings(db, tenant_id)
    sent_today = _get_sent_today(db, tenant_id)
    daily_limit = settings.get("daily_outreach_limit", 100)

    # Check active campaigns
    try:
        active = db.table("campaigns") \
            .select("id", count="exact") \
            .eq("tenant_id", tenant_id) \
            .in_("status", ["running", "scheduled"]) \
            .execute()
        active_count = active.count if hasattr(active, "count") and active.count else 0
    except Exception:
        active_count = 0

    return {
        "outreach_enabled": settings.get("outreach_enabled", False),
        "daily_limit": daily_limit,
        "sent_today": sent_today,
        "remaining_today": max(0, daily_limit - sent_today),
        "business_hours": {
            "start": str(settings.get("outreach_start_time", "09:00")),
            "end": str(settings.get("outreach_end_time", "18:00")),
            "timezone": settings.get("outreach_timezone", "Asia/Kuala_Lumpur"),
        },
        "active_campaigns": active_count,
    }


# ──────────────────────────────────────────────
# 2. CONTACT IMPORT — JSON
# ──────────────────────────────────────────────

@router.post("/contacts/import")
async def import_contacts(
    body: ContactImportRequest,
    tenant_id: str = Depends(verify_session),
):
    """Import contacts from JSON and create or update a segment."""
    db = _get_supabase()

    # Create/upsert segment
    try:
        seg_result = db.table("contact_segments") \
            .upsert({
                "tenant_id": tenant_id,
                "name": body.segment_name,
                "segment_type": "imported",
                "source": "api",
            }, on_conflict="tenant_id,name") \
            .execute()
        segment_id = seg_result.data[0]["id"] if seg_result.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create segment: {e}")

    if not segment_id:
        raise HTTPException(status_code=500, detail="Segment creation failed — no ID returned")

    successful = 0
    failed = 0
    errors = []

    for contact in body.contacts:
        try:
            phone_clean = _normalize_phone(contact.phone)
            jid = _phone_to_jid(contact.phone)
            tag = contact.tag or body.tag or "lead"

            # Upsert into contacts
            contact_data = {
                "tenant_id": tenant_id,
                "jid": jid,
                "phone": phone_clean,
                "name": contact.name or phone_clean,
                "tags": [tag] if tag else [],
                "lead_temperature": "cold",
                "source": "outreach_import",
                "last_outreach_at": None,
            }
            if contact.business_type:
                contact_data["business_type"] = contact.business_type
            if contact.area:
                contact_data["area"] = contact.area
            if contact.metadata:
                contact_data["metadata"] = contact.metadata
            # Persist new intelligence fields if provided
            if contact.industry_type:
                contact_data["industry_type"] = contact.industry_type
            if contact.sub_type:
                contact_data["sub_type"] = contact.sub_type
            if contact.country:
                contact_data["country"] = contact.country
            if contact.language_pref and contact.language_pref != "auto":
                contact_data["language_pref"] = contact.language_pref
            if contact.business_size:
                contact_data["business_size"] = contact.business_size
            if contact.estimated_revenue:
                contact_data["estimated_revenue"] = contact.estimated_revenue
            if contact.whatsapp_active and contact.whatsapp_active != "unknown":
                contact_data["whatsapp_active"] = contact.whatsapp_active
            if contact.online_presence and contact.online_presence != "unknown":
                contact_data["online_presence"] = contact.online_presence
            if contact.pain_point_hint:
                contact_data["pain_point_hint"] = contact.pain_point_hint
            if contact.competitor_used:
                contact_data["competitor_used"] = contact.competitor_used
            if contact.persona and contact.persona != "direct":
                contact_data["persona"] = contact.persona
            if contact.priority and contact.priority != "normal":
                contact_data["priority"] = contact.priority
            if contact.custom_note:
                contact_data["custom_note"] = contact.custom_note
            if contact.max_followups and contact.max_followups != 3:
                contact_data["max_followups"] = contact.max_followups
            if body.campaign_config_id:
                contact_data["campaign_config_id"] = body.campaign_config_id

            c_result = db.table("contacts") \
                .upsert(contact_data, on_conflict="tenant_id,jid") \
                .execute()

            if c_result.data:
                contact_id = c_result.data[0]["id"]

                # Link to segment
                db.table("contact_segment_members") \
                    .upsert({
                        "segment_id": segment_id,
                        "contact_id": contact_id,
                        "added_via": "import",
                    }, on_conflict="segment_id,contact_id") \
                    .execute()

                successful += 1
            else:
                failed += 1
                errors.append(f"No data returned for {contact.phone}")

        except Exception as e:
            failed += 1
            errors.append(f"{contact.phone}: {str(e)[:100]}")

    # Update segment contact count
    try:
        db.table("contact_segments") \
            .update({"contact_count": successful, "last_calculated_at": datetime.utcnow().isoformat()}) \
            .eq("id", segment_id) \
            .execute()
    except Exception:
        pass

    return {
        "segment_id": segment_id,
        "segment_name": body.segment_name,
        "total_imported": len(body.contacts),
        "successful": successful,
        "failed": failed,
        "errors": errors[:10],  # Limit error list
    }


# ──────────────────────────────────────────────
# 3. CONTACT IMPORT — CSV
# ──────────────────────────────────────────────

@router.post("/contacts/import-csv")
async def import_contacts_csv(
    file: UploadFile = File(...),
    segment_name: str = Query(...),
    tag: Optional[str] = Query(None),
    tenant_id: str = Depends(verify_session),
):
    """Import contacts from a CSV file. Required columns: phone. Optional: name, business_type, area."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    contacts = []
    for row in reader:
        phone = row.get("phone") or row.get("Phone") or row.get("PHONE")
        if not phone:
            continue
        contacts.append(ContactIn(
            phone=phone.strip(),
            name=(row.get("name") or row.get("Name") or "").strip() or None,
            tag=tag,
            business_type=(row.get("business_type") or row.get("Business Type") or "").strip() or None,
            area=(row.get("area") or row.get("Area") or "").strip() or None,
        ))

    if not contacts:
        raise HTTPException(status_code=400, detail="No valid contacts found in CSV (missing 'phone' column?)")

    # Reuse JSON import logic
    import_request = ContactImportRequest(segment_name=segment_name, contacts=contacts, tag=tag)
    return await import_contacts(import_request, tenant_id)


# ──────────────────────────────────────────────
# 4. LIST SEGMENTS
# ──────────────────────────────────────────────

@router.get("/segments")
async def list_segments(tenant_id: str = Depends(verify_session)):
    """List all contact segments for this tenant."""
    db = _get_supabase()
    try:
        result = db.table("contact_segments") \
            .select("*") \
            .eq("tenant_id", tenant_id) \
            .order("created_at", desc=True) \
            .execute()
        # Normalize: DB column is `name` but frontend expects `segment_name`
        segments = []
        for seg in (result.data or []):
            seg["segment_name"] = seg.get("segment_name") or seg.get("name", "")
            segments.append(seg)
        return {"segments": segments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# 5. CREATE CAMPAIGN
# ──────────────────────────────────────────────

@router.post("/campaigns")
async def create_campaign(
    body: CampaignCreateRequest,
    tenant_id: str = Depends(verify_session),
):
    """Create a new outreach campaign."""
    db = _get_supabase()

    # Validate segment if provided
    if body.segment_id:
        try:
            seg = db.table("contact_segments") \
                .select("id, contact_count") \
                .eq("id", body.segment_id) \
                .eq("tenant_id", tenant_id) \
                .maybe_single() \
                .execute()
            seg_data = getattr(seg, "data", None) if seg else None
            if not seg_data:
                raise HTTPException(status_code=404, detail="Segment not found")
            total_recipients = seg_data.get("contact_count", 0)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Segment not found: {e}")
    else:
        total_recipients = 0

    campaign_data = {
        "tenant_id": tenant_id,
        "name": body.name,
        "description": body.description,
        "campaign_type": body.campaign_type,
        "target_segment_id": body.segment_id,
        "status": "draft",
        "daily_limit": body.daily_limit,
        "send_window_start": body.send_window_start,
        "send_window_end": body.send_window_end,
        "min_delay_seconds": body.min_delay_seconds,
        "max_delay_seconds": body.max_delay_seconds,
        "stop_on_reply": body.stop_on_reply,
        "sequence_type": body.sequence_type,
        "follow_up_days": body.follow_up_days or [],
        "total_recipients": total_recipients,
        "sent_count": 0,
        "failed_count": 0,
        "reply_count": 0,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    try:
        result = db.table("campaigns").insert(campaign_data).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Campaign insertion failed")
        campaign = result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        # Map common Supabase/Postgres errors to honest status codes instead
        # of always returning 500.
        msg = str(e).lower()
        if "check constraint" in msg or "violates" in msg:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid campaign field. Allowed campaign_type values are "
                    "'outreach', 'nurture', 'reactivation', 'event'."
                ),
            )
        if "duplicate" in msg or "unique" in msg:
            raise HTTPException(status_code=409, detail="A campaign with this name already exists.")
        if "permission" in msg or "rls" in msg or "policy" in msg:
            raise HTTPException(status_code=403, detail="You don't have permission to create a campaign for this tenant.")
        raise HTTPException(status_code=500, detail=f"Failed to create campaign: {e}")

    campaign_id = campaign["id"]

    # Link templates if provided
    if body.template_ids:
        for step, template_id in enumerate(body.template_ids, start=1):
            try:
                db.table("campaign_templates").insert({
                    "campaign_id": campaign_id,
                    "template_id": template_id,
                    "sequence_step": step,
                    "step_name": f"Step {step}",
                    "delay_days": (body.follow_up_days[step - 1] if body.follow_up_days and step <= len(body.follow_up_days) else 0),
                }).execute()
            except Exception:
                pass  # Template link failure is non-fatal

    return {
        "campaign_id": campaign_id,
        "name": campaign["name"],
        "status": "draft",
        "total_recipients": total_recipients,
        "message": "Campaign created. Use /start to queue messages.",
    }


# ──────────────────────────────────────────────
# 6. START CAMPAIGN
# ──────────────────────────────────────────────

@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: str,
    body: CampaignStartRequest = CampaignStartRequest(),
    tenant_id: str = Depends(verify_session),
):
    """Start a campaign — queues messages with smart scheduling."""
    db = _get_supabase()

    # Fetch campaign
    try:
        c_result = db.table("campaigns") \
            .select("*, campaign_templates(template_id, sequence_step)") \
            .eq("id", campaign_id) \
            .eq("tenant_id", tenant_id) \
            .maybe_single() \
            .execute()
        c_data = getattr(c_result, "data", None) if c_result else None
        if not c_data:
            raise HTTPException(status_code=404, detail="Campaign not found")
        campaign = c_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    if campaign["status"] not in ("draft", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Campaign is '{campaign['status']}' — can only start from draft or paused",
        )

    segment_id = campaign.get("target_segment_id")
    if not segment_id:
        raise HTTPException(status_code=400, detail="Campaign has no target segment")

    # Get template content — fall back to campaign description if no linked templates
    templates = campaign.get("campaign_templates", [])
    primary_template_id = None
    if not templates:
        # Use description as inline message template (allows campaigns without separate template records)
        template_content = campaign.get("description", "").strip()
        if not template_content:
            raise HTTPException(
                status_code=400,
                detail="Campaign has no message template and no description — edit the campaign to add a message",
            )
    else:
        # Load first template content
        try:
            primary_template_id = sorted(templates, key=lambda t: t["sequence_step"])[0]["template_id"]
            t_result = db.table("message_templates") \
                .select("template_content, template_name") \
                .eq("id", primary_template_id) \
                .maybe_single() \
                .execute()
            t_data = getattr(t_result, "data", None) if t_result else None
            if not t_data:
                raise HTTPException(status_code=404, detail="Template content not found")
            template_content = t_data["template_content"]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Template fetch error: {e}")

    # Fetch contacts in segment
    try:
        members = db.table("contact_segment_members") \
            .select("contacts(id, jid, phone, name)") \
            .eq("segment_id", segment_id) \
            .execute()
        contacts = [m["contacts"] for m in (members.data or []) if m.get("contacts")]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch segment contacts: {e}")

    if not contacts:
        raise HTTPException(status_code=400, detail="Segment has no contacts")

    # PDPA / GDPR consent gate (issue #14, 2026-08-23). Refuse to start
    # the campaign if ANY contact lacks an active outreach consent row.
    # This is the enforcement point of the contract documented in
    # outreach_consent_api.py — without this, "the customer complained
    # they never opted in" is unanswerable. The owner can either:
    #   a) record consent for the missing contacts first via
    #      POST /api/outreach/consent/record, or
    #   b) remove the contacts from the segment.
    contact_ids = [c["id"] for c in contacts if c.get("id")]
    if contact_ids:
        try:
            sb = _get_supabase()
            consent_rows = (
                sb.table("outreach_consent_log")
                .select("contact_id, consent_type, revoked_at")
                .eq("tenant_id", tenant_id)
                .in_("contact_id", contact_ids)
                .is_("revoked_at", "null")
                .in_("consent_type", ["opt_in", "transactional"])
                .execute()
            )
            consented = {r["contact_id"] for r in (getattr(consent_rows, "data", None) or [])}
        except Exception as e:
            # Fail closed: if we can't verify consent, we don't send.
            # This is the safe default under PDPA.
            logger.error("start_campaign: could not verify consent, failing closed: %s", e)
            raise HTTPException(
                status_code=503,
                detail=f"Could not verify outreach consent (PDPA gate). Try again or contact support. Error: {e}",
            )

        missing = [c for c in contacts if c.get("id") and c["id"] not in consented]
        if missing:
            # Build a friendly error showing the first 10 names + the
            # record endpoint so the operator knows what to do.
            sample = ", ".join(
                (m.get("name") or m.get("phone") or m.get("jid") or m.get("id"))[:30]
                for m in missing[:10]
            )
            more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
            raise HTTPException(
                status_code=412,  # Precondition Failed
                detail=(
                    f"PDPA consent gate: {len(missing)} of {len(contacts)} contact(s) have no active opt-in or transactional consent. "
                    f"Record consent via POST /api/outreach/consent/record before starting the campaign. "
                    f"Missing: {sample}{more}"
                ),
            )

    # Calculate business-hours start times
    min_delay = campaign.get("min_delay_seconds", 120)
    max_delay = campaign.get("max_delay_seconds", 300)
    daily_limit = campaign.get("daily_limit", 50)

    now = datetime.utcnow()
    # If not immediate, schedule from next 9am MYT (UTC+8)
    if not body.immediate:
        # Next 9am UTC+8 = 01:00 UTC
        next_send = now.replace(hour=1, minute=0, second=0, microsecond=0)
        if now.hour >= 1:  # Already past 9am MYT today
            next_send += timedelta(days=1)
    else:
        next_send = now + timedelta(seconds=30)

    queued = 0
    queue_records = []

    for i, contact in enumerate(contacts):
        if i > 0 and i % daily_limit == 0:
            # Next day batch
            next_send += timedelta(days=1)
            next_send = next_send.replace(hour=1, minute=0, second=0, microsecond=0)

        # ── AI generation (opt-in per campaign) ────────────────────────────
        # Check if AI generation is requested via campaign settings JSONB
        use_ai = campaign.get("settings", {}).get("use_ai_generation", False)
        campaign_config_id = campaign.get("settings", {}).get("campaign_config_id")
        ai_config = None
        ai_engine = None

        if use_ai and campaign_config_id:
            try:
                from src.saas.outreach_template_engine import TemplateEngine
                db_cfg = _get_supabase()
                cfg_result = db_cfg.table("outreach_campaign_configs") \
                    .select("*") \
                    .eq("id", campaign_config_id) \
                    .eq("tenant_id", tenant_id) \
                    .maybe_single() \
                    .execute()
                cfg_data = getattr(cfg_result, "data", None) if cfg_result else None
                if cfg_data:
                    ai_config = cfg_data
                    ai_engine = TemplateEngine(gemini_api_key=os.getenv("GEMINI_API_KEY"))
                else:
                    logger.warning(f"campaign_config_id {campaign_config_id} not found — falling back to template")
            except Exception as ai_init_err:
                logger.warning(f"AI engine init failed (non-blocking): {ai_init_err}")
                ai_engine = None

        # Personalize message — support both {name} and {{name}} placeholder styles
        # If AI engine is loaded, generate per-contact; else use string replacement (existing fallback)
        first_name = contact.get("name", "").split()[0] if contact.get("name") else "boss"
        if ai_engine and ai_config:
            import asyncio
            try:
                enriched = ai_engine.enrich_contact(dict(contact), ai_config)
                enriched["contact_name"] = enriched.get("contact_name") or enriched.get("name")
                loop = asyncio.get_event_loop()
                message = loop.run_until_complete(
                    ai_engine.generate_message(enriched, step=0, campaign_config=ai_config)
                )
            except Exception as gen_err:
                logger.warning(f"AI message gen failed for {contact.get('jid')}: {gen_err} — using template fallback")
                message = (
                    template_content
                    .replace("{{name}}", first_name)
                    .replace("{name}", first_name)
                    .replace("{Name}", first_name.capitalize())
                )
        else:
            message = (
                template_content
                .replace("{{name}}", first_name)
                .replace("{name}", first_name)
                .replace("{Name}", first_name.capitalize())
            )

        delay = random.randint(min_delay, max_delay)
        scheduled_at = next_send + timedelta(seconds=i * delay % 86400)  # spread within day

        queue_records.append({
            "tenant_id": tenant_id,
            "campaign_id": campaign_id,
            "contact_id": contact["id"],
            "recipient_jid": contact["jid"],
            "recipient_name": contact.get("name"),
            "recipient_phone": contact.get("phone"),
            "message_content": message,
            "message_template_id": primary_template_id,
            "sequence_step": 1,
            "status": "pending",
            "scheduled_at": scheduled_at.isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })

    # Batch insert (100 at a time)
    for i in range(0, len(queue_records), 100):
        batch = queue_records[i:i + 100]
        try:
            db.table("outbound_queue").insert(batch).execute()
            queued += len(batch)
        except Exception as e:
            logger.error(f"❌ Outreach queue batch insert error: {e}")

    # Update campaign status (don't let a transient Supabase error here
    # kill the request — the messages are already queued, the scheduler
    # will pick them up regardless of the campaign row's status column).
    try:
        db.table("campaigns") \
            .update({
                "status": "scheduled",
                "total_recipients": len(contacts),
                "started_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }) \
            .eq("id", campaign_id) \
            .execute()
    except Exception as e:
        logger.warning(f"⚠️ Could not update campaign status after queueing: {e}")

    # Enable outreach for this tenant if not already (non-blocking)
    try:
        db.table("tenants") \
            .update({"outreach_enabled": True}) \
            .eq("id", tenant_id) \
            .execute()
    except Exception as e:
        logger.warning(f"⚠️ Could not enable outreach for tenant {tenant_id}: {e}")

    return {
        "campaign_id": campaign_id,
        "status": "scheduled",
        "contacts_queued": queued,
        "first_send_at": next_send.isoformat(),
        "estimated_days": max(1, len(contacts) // daily_limit),
        "message": f"✅ {queued} messages queued. Scheduler will process during business hours.",
    }


# ──────────────────────────────────────────────
# 7. PAUSE CAMPAIGN
# ──────────────────────────────────────────────

@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, tenant_id: str = Depends(verify_session)):
    """Pause a running campaign — pending messages stay in queue but won't be sent."""
    db = _get_supabase()
    try:
        db.table("campaigns") \
            .update({"status": "paused", "updated_at": datetime.utcnow().isoformat()}) \
            .eq("id", campaign_id) \
            .eq("tenant_id", tenant_id) \
            .execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"campaign_id": campaign_id, "status": "paused"}


# ──────────────────────────────────────────────
# 8. LIST CAMPAIGNS
# ──────────────────────────────────────────────

@router.get("/campaigns")
async def list_campaigns(
    tenant_id: str = Depends(verify_session),
    status: Optional[str] = Query(None),
):
    """List all campaigns for this tenant, optionally filtered by status."""
    db = _get_supabase()
    try:
        query = db.table("campaigns") \
            .select("id, name, status, campaign_type, total_recipients, sent_count, failed_count, reply_count, created_at, started_at") \
            .eq("tenant_id", tenant_id) \
            .order("created_at", desc=True)
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return {"campaigns": result.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# 9. CAMPAIGN STATS
# ──────────────────────────────────────────────

@router.get("/campaigns/{campaign_id}/stats")
async def get_campaign_stats(campaign_id: str, tenant_id: str = Depends(verify_session)):
    """Get detailed stats for a single campaign."""
    db = _get_supabase()
    try:
        # NOTE (2026-08-06): use `.maybe_single()` so a missing campaign
        # returns `None` cleanly instead of a 500 PGRST116.
        c = db.table("campaigns") \
            .select("*") \
            .eq("id", campaign_id) \
            .eq("tenant_id", tenant_id) \
            .maybe_single() \
            .execute()
        # NOTE (2026-08-06): guard against `c` being None (transport
        # error / no row). The previous `if not c.data:` crashed on
        # `None.data` with a 500.
        if not c or not getattr(c, "data", None):
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Live queue counts
        q = db.table("outbound_queue") \
            .select("status") \
            .eq("campaign_id", campaign_id) \
            .execute()

        counts: Dict[str, int] = {}
        for row in (q.data or []):
            s = row.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        campaign = c.data
        delivery_rate = 0.0
        if campaign["total_recipients"] > 0:
            delivered = counts.get("delivered", 0) + counts.get("read", 0)
            delivery_rate = round(delivered / campaign["total_recipients"] * 100, 1)

        reply_rate = 0.0
        if campaign.get("sent_count", 0) > 0:
            reply_rate = round(campaign.get("reply_count", 0) / campaign["sent_count"] * 100, 1)

        return {
            "campaign": {
                "id": campaign["id"],
                "name": campaign["name"],
                "status": campaign["status"],
                "total_recipients": campaign["total_recipients"],
                "sent_count": campaign["sent_count"],
                "failed_count": campaign["failed_count"],
                "reply_count": campaign["reply_count"],
                "daily_limit": campaign["daily_limit"],
                "started_at": campaign.get("started_at"),
                "completed_at": campaign.get("completed_at"),
            },
            "queue_breakdown": counts,
            "metrics": {
                "delivery_rate_pct": delivery_rate,
                "reply_rate_pct": reply_rate,
                "pending": counts.get("pending", 0),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# 10. CANCEL CAMPAIGN
# ──────────────────────────────────────────────

@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, tenant_id: str = Depends(verify_session)):
    """Cancel a campaign and mark all pending messages as cancelled."""
    db = _get_supabase()
    try:
        # Cancel pending queue items
        db.table("outbound_queue") \
            .update({"status": "cancelled", "updated_at": datetime.utcnow().isoformat()}) \
            .eq("campaign_id", campaign_id) \
            .eq("tenant_id", tenant_id) \
            .eq("status", "pending") \
            .execute()

        db.table("campaigns") \
            .update({"status": "cancelled", "updated_at": datetime.utcnow().isoformat()}) \
            .eq("id", campaign_id) \
            .eq("tenant_id", tenant_id) \
            .execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"campaign_id": campaign_id, "status": "cancelled"}


# ──────────────────────────────────────────────
# 11. QUEUE STATUS
# ──────────────────────────────────────────────

@router.get("/queue/status")
async def get_queue_status(tenant_id: str = Depends(verify_session)):
    """Get overall queue status for this tenant."""
    db = _get_supabase()
    try:
        result = db.table("outbound_queue") \
            .select("status") \
            .eq("tenant_id", tenant_id) \
            .execute()

        counts: Dict[str, int] = {}
        for row in (result.data or []):
            s = row.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        return {
            "total_messages": sum(counts.values()),
            "by_status": counts,
            "pending": counts.get("pending", 0),
            "sent_today": _get_sent_today(db, tenant_id),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# 12. HEALTH CHECK (unauthenticated)
# ──────────────────────────────────────────────

@router.get("/health")
async def outreach_health():
    """Quick health check for outreach system."""
    return {"status": "ok", "system": "outreach", "version": "1.0.0"}


# ──────────────────────────────────────────────
# 14. INDUSTRY TEMPLATES (read-only metadata)
# ──────────────────────────────────────────────

@router.get("/templates")
async def get_industry_templates():
    """
    Return metadata for all built-in industry intelligence packs.
    Used by the frontend to populate industry-type dropdowns and
    show which CSV columns are required/recommended per industry.
    Unauthenticated — public metadata only.
    """
    from src.saas.outreach_template_engine import TemplateEngine
    engine = TemplateEngine()
    return {"industry_packs": engine.list_industry_packs()}


# ──────────────────────────────────────────────
# 15–18. CAMPAIGN CONFIG CRUD
# ──────────────────────────────────────────────

@router.post("/configs")
async def create_campaign_config(
    body: CampaignConfigCreateRequest,
    tenant_id: str = Depends(verify_session),
):
    """Create a new AI campaign config in outreach_campaign_configs."""
    db = _get_supabase()
    try:
        result = db.table("outreach_campaign_configs").insert({
            "tenant_id": tenant_id,
            "campaign_id": body.campaign_id,
            "name": body.name,
            "industry_type": body.industry_type,
            "sub_type": body.sub_type,
            "meta": body.meta,
            "industry_config": body.industry_config,
            "qualification_config": body.qualification_config,
            "sequence_config": body.sequence_config,
            "persona_config": body.persona_config,
            "reveal_config": body.reveal_config,
            "escalation_config": body.escalation_config,
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Insert returned no data")
        return {"success": True, "config": result.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/configs")
async def list_campaign_configs(tenant_id: str = Depends(verify_session)):
    """List all active AI campaign configs for this tenant."""
    db = _get_supabase()
    try:
        result = db.table("outreach_campaign_configs") \
            .select("id, campaign_id, name, industry_type, sub_type, is_active, created_at") \
            .eq("tenant_id", tenant_id) \
            .order("created_at", desc=True) \
            .execute()
        return {"configs": result.data or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/configs/{config_id}")
async def get_campaign_config(
    config_id: str,
    tenant_id: str = Depends(verify_session),
):
    """Get a single AI campaign config by ID."""
    db = _get_supabase()
    try:
        # NOTE (2026-08-06): use `.maybe_single()` so a missing config
        # returns `None` cleanly instead of a 500 PGRST116.
        result = db.table("outreach_campaign_configs") \
            .select("*") \
            .eq("id", config_id) \
            .eq("tenant_id", tenant_id) \
            .maybe_single() \
            .execute()
        if not result or not getattr(result, "data", None):
            raise HTTPException(status_code=404, detail="Config not found")
        return {"config": result.data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/configs/{config_id}")
async def update_campaign_config(
    config_id: str,
    body: CampaignConfigCreateRequest,
    tenant_id: str = Depends(verify_session),
):
    """Update an AI campaign config. To deactivate, set is_active=false via a PATCH instead."""
    db = _get_supabase()
    try:
        result = db.table("outreach_campaign_configs").update({
            "campaign_id": body.campaign_id,
            "name": body.name,
            "industry_type": body.industry_type,
            "sub_type": body.sub_type,
            "meta": body.meta,
            "industry_config": body.industry_config,
            "qualification_config": body.qualification_config,
            "sequence_config": body.sequence_config,
            "persona_config": body.persona_config,
            "reveal_config": body.reveal_config,
            "escalation_config": body.escalation_config,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", config_id).eq("tenant_id", tenant_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Config not found or no change")
        return {"success": True, "config": result.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ──────────────────────────────────────────────
# 13. SEND TEST MESSAGE (direct, skips queue)
# ──────────────────────────────────────────────

class TestMessageRequest(BaseModel):
    message: str
    phone: Optional[str] = None  # if None, uses tenant owner_phone


@router.post("/send-test")
async def send_test_message(
    request: TestMessageRequest,
    tenant_id: str = Depends(verify_session),
):
    """
    Send a test WhatsApp message to the tenant's own phone (or a specified phone).
    Bypasses the scheduler — immediate direct bridge send. No daily limit consumed.
    """
    db = _get_supabase()

    # Resolve target phone
    target_phone = request.phone
    if not target_phone:
        tenant_row = db.table("tenants").select("owner_phone").eq("id", tenant_id).maybe_single().execute()
        tr_data = getattr(tenant_row, "data", None) if tenant_row else None
        if not tr_data or not tr_data.get("owner_phone"):
            raise HTTPException(status_code=400, detail="No owner_phone configured for this tenant")
        target_phone = tr_data["owner_phone"]

    normalized = _normalize_phone(target_phone)
    if not normalized:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    # Replace template tags with test values
    message_text = (
        request.message
        .replace("{name}", "Test User")
        .replace("{business}", "Your Business")
        .replace("{agent}", "Bijou AI")
    )

    # Direct bridge send (no queue)
    bridge_url = (os.getenv("BRIDGE_URL") or "").rstrip("/")
    if not bridge_url:
        raise HTTPException(status_code=503, detail="WhatsApp bridge not configured")

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    bridge_user = os.getenv("BRIDGE_USER", "")
    bridge_pass = os.getenv("BRIDGE_PASSWORD", "")
    if bridge_user and bridge_pass:
        auth_str = base64.b64encode(f"{bridge_user}:{bridge_pass}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_str}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{bridge_url}/send/message",
                json={"phone": normalized, "message": message_text},
                headers=headers,
            )
        if resp.status_code in (200, 201):
            return {"success": True, "sent_to": f"+{normalized}", "message": message_text}
        raise HTTPException(status_code=502, detail=f"Bridge returned {resp.status_code}: {resp.text[:200]}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="WhatsApp bridge timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"\u274c Test message send error: {e}")
        # Surface the underlying reason (bridge misconfig is the common case
        # here, not a generic 500). If it was a connection failure to the
        # bridge, return 503; otherwise 502.
        msg = str(e).lower()
        if "bridge" in msg or "connect" in msg or "unreachable" in msg:
            raise HTTPException(
                status_code=503,
                detail="WhatsApp bridge is unreachable right now. Please try again in a moment.",
            )
        raise HTTPException(status_code=502, detail=f"Bridge error: {e}"[:200])
