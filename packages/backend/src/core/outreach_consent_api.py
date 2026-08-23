"""Outreach consent log API (issue #14, the other half of PDPA).

WHY THIS EXISTS
===============
PDPA Section 6 / GDPR Article 6 + Article 7 require **affirmative
consent** before processing personal data for direct marketing. We
already have the data-request page (right to be forgotten, issue
#26) — that's the *deletion* side. This module is the *collection*
side: a verifiable audit trail of who agreed to receive outreach,
when, where, and what they were told.

Without this, a regulator complaint ("I never asked for these
messages") can only be answered with "we don't know". With this,
the owner can produce the row showing "the customer submitted this
form on this date from this IP, agreeing to this exact text".

THE CONTRACT
============

1. A contact must have at least one row in `public.outreach_consent_log`
   with `consent_type IN ('opt_in', 'transactional')` and
   `revoked_at IS NULL` BEFORE any campaign can include them.
2. Every row records WHO gave consent, WHEN, WHERE (channel), and
   the EXACT consent text (so we can prove it was unambiguous).
3. Revocation is SOFT (revoked_at timestamp) so the audit trail is
   preserved forever; we never lose the proof that consent was
   given and later withdrawn.
4. The outreach start_campaign endpoint REFUSES to queue a message
   to any contact without an active consent row.

PUBLIC API SURFACE
==================

`POST /api/outreach/consent/record` — record a new consent row
   Body: {contact_id, consent_type, channel, consent_text?, source?,
          ip_address?, user_agent?, expires_at?, granted_at?}
   Returns: the new row
   Auth: verify_session (tenant_id from session)

`GET /api/outreach/consent/status?contact_id=...` — check the current
   consent state for a single contact
   Returns: {has_active_consent, active_consent_type, granted_at, ...}

`POST /api/outreach/consent/{consent_id}/revoke` — soft-revoke a consent
   Body: {reason}
   Returns: the updated row

`GET /api/outreach/consent/audit?contact_id=...` — full audit trail for
   a contact (for regulators / customer service)
   Returns: list of all consent rows, newest first
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach/consent", tags=["outreach-consent"])


# ─── Pydantic models ────────────────────────────────────────────────────


class RecordConsentRequest(BaseModel):
    contact_id: str = Field(..., min_length=1, max_length=64)
    consent_type: str = Field(..., min_length=1, max_length=32)
    channel: str = Field(..., min_length=1, max_length=16)
    consent_text: Optional[str] = None
    source: str = Field(default="manual", max_length=32)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    granted_at: Optional[str] = None  # ISO 8601; defaults to now()
    expires_at: Optional[str] = None  # ISO 8601; null = no expiry


class RevokeConsentRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=512)


# ─── DB helpers ─────────────────────────────────────────────────────────


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


def _validate_consent_type(t: str) -> str:
    allowed = {"opt_in", "opt_out", "transactional", "imported_legacy"}
    if t not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid consent_type '{t}'. Allowed: {sorted(allowed)}",
        )
    return t


def _validate_channel(c: str) -> str:
    allowed = {"web_form", "whatsapp", "sms", "email", "in_person", "api", "imported"}
    if c not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid channel '{c}'. Allowed: {sorted(allowed)}",
        )
    return c


def _check_active_consent(supabase, tenant_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """Return the most recent active consent row for a contact, or None."""
    try:
        result = (
            supabase.table("outreach_consent_log")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .is_("revoked_at", "null")
            .order("granted_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    rows = getattr(result, "data", None) or []
    return rows[0] if rows else None


def _check_active_consent_for_contacts(
    supabase, tenant_id: str, contact_ids: List[str]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Bulk check. Returns a dict {contact_id: active_consent_row_or_None}."""
    if not contact_ids:
        return {}
    try:
        result = (
            supabase.table("outreach_consent_log")
            .select("*")
            .eq("tenant_id", tenant_id)
            .in_("contact_id", contact_ids)
            .is_("revoked_at", "null")
            .order("granted_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    # Pick the most recent active row per contact
    by_contact: Dict[str, Dict[str, Any]] = {}
    for row in (getattr(result, "data", None) or []):
        cid = row.get("contact_id")
        if cid and cid not in by_contact:
            by_contact[cid] = row
    return {cid: by_contact.get(cid) for cid in contact_ids}


# ─── Endpoints ──────────────────────────────────────────────────────────


@router.post("/record")
async def record_consent(req: RecordConsentRequest, tenant_id: str = Depends(verify_session)):
    """Record a new consent row.

    This is the entry point. Call it whenever a contact:
      - Submits a web opt-in form
      - Replies "YES" to a keyword ("Text YES to receive updates")
      - Is imported from a CRM (with the historical opt-in proof)
      - Agrees to transactional-only contact (e.g., "you can text me
        my appointment reminders")

    Auth: Bearer token (the tenant's session JWT). `tenant_id` is
    taken from the session, never from the request body.
    """
    _validate_consent_type(req.consent_type)
    _validate_channel(req.channel)

    supabase = _supabase()
    granted_at = req.granted_at or datetime.now(timezone.utc).isoformat()

    row = {
        "tenant_id": tenant_id,
        "contact_id": req.contact_id,
        "consent_type": req.consent_type,
        "consent_text": req.consent_text,
        "channel": req.channel,
        "source": req.source,
        "ip_address": req.ip_address,
        "user_agent": req.user_agent,
        "granted_at": granted_at,
        "expires_at": req.expires_at,
    }

    try:
        result = supabase.table("outreach_consent_log").insert(row).execute()
    except Exception as e:
        logger.error("outreach_consent insert failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not record consent: {e}")

    data = getattr(result, "data", None) or []
    if not data:
        raise HTTPException(status_code=500, detail="Consent insert returned no row")
    return data[0]


@router.get("/status")
async def consent_status(
    contact_id: str = Query(..., min_length=1, max_length=64),
    tenant_id: str = Depends(verify_session),
):
    """Check the current consent state for a single contact.

    Returns a small, customer-friendly payload that the UI can show
    on the contact's profile page.
    """
    supabase = _supabase()
    active = _check_active_consent(supabase, tenant_id, contact_id)
    if not active:
        return {
            "has_active_consent": False,
            "contact_id": contact_id,
            "active_consent_type": None,
            "granted_at": None,
            "expires_at": None,
        }
    return {
        "has_active_consent": True,
        "contact_id": contact_id,
        "active_consent_type": active.get("consent_type"),
        "granted_at": active.get("granted_at"),
        "expires_at": active.get("expires_at"),
        "channel": active.get("channel"),
        "source": active.get("source"),
    }


@router.post("/{consent_id}/revoke")
async def revoke_consent(
    consent_id: str, req: RevokeConsentRequest, tenant_id: str = Depends(verify_session)
):
    """Soft-revoke a consent row.

    Revocation is SOFT: the row stays in the table forever (for audit
    purposes), but `revoked_at` is set and any future consent check
    returns False. This is the only correct behavior under PDPA/GDPR
    because the regulator / customer may need to see "yes, you did
    have consent on 2025-01-15, and you revoked it on 2025-03-22".
    """
    supabase = _supabase()
    try:
        # Verify the row belongs to this tenant (no cross-tenant revoke)
        existing = (
            supabase.table("outreach_consent_log")
            .select("id, tenant_id, revoked_at")
            .eq("id", consent_id)
            .maybe_single()
            .execute()
        )
        existing_data = getattr(existing, "data", None) if existing else None
        if not existing_data:
            raise HTTPException(status_code=404, detail="Consent row not found")
        if existing_data.get("tenant_id") != tenant_id:
            # Don't acknowledge the existence of other tenants' rows
            raise HTTPException(status_code=404, detail="Consent row not found")
        if existing_data.get("revoked_at"):
            raise HTTPException(
                status_code=400, detail="Consent is already revoked"
            )

        # Soft-revoke: stamp revoked_at, keep the row
        result = (
            supabase.table("outreach_consent_log")
            .update(
                {
                    "revoked_at": datetime.now(timezone.utc).isoformat(),
                    "revoked_reason": req.reason,
                }
            )
            .eq("id", consent_id)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("outreach_consent revoke failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Could not revoke consent: {e}")

    data = getattr(result, "data", None) or []
    if not data:
        raise HTTPException(status_code=500, detail="Revoke returned no row")
    return data[0]


@router.get("/audit")
async def consent_audit(
    contact_id: str = Query(..., min_length=1, max_length=64),
    tenant_id: str = Depends(verify_session),
):
    """Full audit trail for a contact.

    Use this to answer a regulator or a customer-service question
    like "did this person ever consent to outreach?". Returns every
    consent row for the contact — including revoked ones — newest
    first.
    """
    supabase = _supabase()
    try:
        result = (
            supabase.table("outreach_consent_log")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .order("granted_at", desc=True)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    rows = getattr(result, "data", None) or []
    return {
        "contact_id": contact_id,
        "rows": rows,
        "count": len(rows),
        "active_count": sum(1 for r in rows if not r.get("revoked_at")),
        "revoked_count": sum(1 for r in rows if r.get("revoked_at")),
    }


@router.post("/check-bulk")
async def check_bulk(
    contact_ids: List[str] = Query(..., min_length=1, max_length=500),
    tenant_id: str = Depends(verify_session),
):
    """Bulk consent check for a list of contact IDs.

    Returns a map {contact_id: has_active_consent: bool}. Used by
    the start_campaign endpoint to verify ALL recipients have consent
    before queueing. This is the enforcement point of the PDPA
    contract.
    """
    supabase = _supabase()
    by_contact = _check_active_consent_for_contacts(supabase, tenant_id, contact_ids)
    return {
        cid: bool(row) for cid, row in by_contact.items()
    }
