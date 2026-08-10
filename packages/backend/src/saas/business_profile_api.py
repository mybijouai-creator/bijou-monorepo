"""
Bijou AI - Business Profile API
================================

REST API endpoints for managing tenant business information and handover details.

Endpoints:
- GET /api/business/profile - Get business profile for tenant
- POST /api/business/profile - Create or update business profile

Author: W3J Consulting - Muhammad Nurunnabi (Jewel)
Version: 1.0.0
Date: 2026-02-25
"""

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

# 2026-08-10 SECURITY: these routes previously had NO authentication. Anyone
# who knew (or guessed) a tenant UUID could read AND overwrite a business's
# name, owner name, owner email and handover_contacts — i.e. staff names,
# phone numbers and emails. tenant_id now comes from the verified session and
# any client-supplied value is ignored.
from src.core.dashboard_api_simple import verify_session
from datetime import datetime

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/business", tags=["business"])


# ════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════


def get_supabase() -> Client:
    """Get Supabase admin client"""
    supabase_url = os.getenv("SUPABASE_URL", "").strip('"')
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip('"')

    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

    return create_client(supabase_url, supabase_key)


async def verify_tenant(tenant_id: str) -> bool:
    """Verify tenant exists"""
    try:
        supabase = get_supabase()
        result = supabase.table("tenants").select("id").eq("id", tenant_id).execute()
        return bool(result.data)
    except Exception as e:
        logger.error(f"❌ Tenant verification failed: {e}")
        return False


# ════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ════════════════════════════════════════════════════════════════


class HandoverContact(BaseModel):
    """Handover contact information"""
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = "Owner"


class BusinessProfileRequest(BaseModel):
    """Request to create/update business profile"""
    tenant_id: str
    business_name: Optional[str] = None
    owner_name: Optional[str] = None
    # Primary WhatsApp number for the business — also written to tenants.phone
    phone: Optional[str] = None
    # Business vertical (e.g. "restaurant", "retail", "service", "salon")
    # NOTE: business_type column does NOT exist on business_profiles yet
    # (verified 2026-08-10). TODO: add the column via Supabase dashboard and
    # re-enable persistence below. For now, business_type is accepted but
    # stored in the notes field as a structured hint.
    business_type: Optional[str] = None
    handover_contacts: Optional[List[HandoverContact]] = Field(default_factory=list)
    business_hours: Optional[str] = None
    notes: Optional[str] = None


class BusinessProfileResponse(BaseModel):
    """Business profile response"""
    success: bool
    tenant_id: str
    profile: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ════════════════════════════════════════════════════════════════


@router.get("/profile", response_model=BusinessProfileResponse)
async def get_business_profile(tenant_id: str = Depends(verify_session)):
    """
    Get business profile for a tenant.

    Args:
        tenant_id: Tenant UUID (query parameter)

    Returns:
        BusinessProfileResponse with profile data or None if not found
    """
    try:
        logger.info(f"📋 Fetching business profile for tenant {tenant_id}")

        # Verify tenant exists
        if not await verify_tenant(tenant_id):
            raise HTTPException(status_code=404, detail="Tenant not found")

        supabase = get_supabase()

        # Query business_profiles table
        result = (
            supabase.table("business_profiles")
            .select("*")
            .eq("tenant_id", tenant_id)
            .execute()
        )

        if result.data:
            profile = result.data[0]  # type: ignore[union-attr]
            logger.info(f"✅ Found business profile for tenant {tenant_id}")

            # Also pull owner email from tenants table (stored as 'email' column)
            # Use maybe_single() so a zero-row result returns None instead of
            # raising APIError and turning this into a 500.
            t_row = supabase.table("tenants").select("email").eq("id", tenant_id).maybe_single().execute()
            t_data = getattr(t_row, "data", None) if t_row else None
            owner_email: Optional[str] = t_data.get("email") if isinstance(t_data, dict) else None

            return BusinessProfileResponse(
                success=True,
                tenant_id=tenant_id,
                profile={
                    "business_name": profile.get("business_name"),
                    "owner_name": profile.get("owner_name"),
                    "owner_email": owner_email,
                    "handover_contacts": profile.get("handover_contacts", []),
                    "business_hours": profile.get("business_hours"),
                    "notes": profile.get("notes"),
                    "created_at": profile.get("created_at"),
                    "updated_at": profile.get("updated_at"),
                }
            )
        else:
            logger.info(f"📭 No business profile found for tenant {tenant_id}")

            # Still return owner_email from tenants even when no business_profile row exists
            t_row = supabase.table("tenants").select("email").eq("id", tenant_id).maybe_single().execute()
            t_data = getattr(t_row, "data", None) if t_row else None
            owner_email = t_data.get("email") if isinstance(t_data, dict) else None

            return BusinessProfileResponse(
                success=True,
                tenant_id=tenant_id,
                profile={"owner_email": owner_email} if owner_email else None,
                message="No business profile configured yet"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching business profile for tenant {tenant_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while fetching business profile."
        )


@router.post("/profile", response_model=BusinessProfileResponse)
async def upsert_business_profile(
    request: BusinessProfileRequest,
    session_tenant_id: str = Depends(verify_session),
):
    """
    Create or update business profile for a tenant (upsert).

    Args:
        request: BusinessProfileRequest with profile data

    Returns:
        BusinessProfileResponse with updated profile
    """
    try:
        # Trust ONLY the session. The body still carries tenant_id (the
        # dashboard sends it), but honouring it would let any caller write to
        # any tenant. Overwrite it before anything downstream reads it.
        if request.tenant_id and request.tenant_id != session_tenant_id:
            logger.warning(
                "Ignoring client-supplied tenant_id %s; using session tenant %s",
                request.tenant_id, session_tenant_id,
            )
        request.tenant_id = session_tenant_id

        logger.info(f"💾 Upserting business profile for tenant {request.tenant_id}")

        # Verify tenant exists
        if not await verify_tenant(request.tenant_id):
            raise HTTPException(status_code=404, detail="Tenant not found")

        supabase = get_supabase()

        # Convert handover_contacts to JSON-serializable format
        handover_contacts_json = [
            {
                "name": contact.name,
                "phone": contact.phone,
                "email": contact.email,
                "role": contact.role,
            }
            for contact in (request.handover_contacts or [])
        ]

        # Check if profile already exists
        existing = (
            supabase.table("business_profiles")
            .select("id")
            .eq("tenant_id", request.tenant_id)
            .execute()
        )

        # Build profile_data. The business_type column was added to
        # business_profiles via Supabase SQL editor on 2026-08-10
        # (ALTER TABLE business_profiles ADD COLUMN business_type text).
        # We write it directly to the column. We still also keep a structured
        # hint in notes for backwards compatibility (existing rows that were
        # saved before the column existed).
        notes_payload = request.notes or ""
        if request.business_type:
            structured = f"business_type={request.business_type}"
            if structured not in notes_payload:
                if notes_payload:
                    notes_payload = f"{structured}\n{notes_payload}"
                else:
                    notes_payload = structured

        profile_data = {
            "tenant_id": request.tenant_id,
            "business_name": request.business_name,
            "owner_name": request.owner_name,
            "business_type": request.business_type,  # column now exists
            "handover_contacts": handover_contacts_json,
            "business_hours": request.business_hours,
            "notes": notes_payload or None,
            "updated_at": datetime.now().isoformat(),
        }

        if existing.data:
            # Update existing profile
            logger.info(f"📝 Updating existing business profile for tenant {request.tenant_id}")
            result = (
                supabase.table("business_profiles")
                .update(profile_data)
                .eq("tenant_id", request.tenant_id)
                .execute()
            )
        else:
            # Insert new profile
            logger.info(f"✨ Creating new business profile for tenant {request.tenant_id}")
            result = (
                supabase.table("business_profiles")
                .insert(profile_data)
                .execute()
            )

        # Sync phone/business_name to the tenants row so the status endpoint
        # and WhatsApp bridge see the same canonical values.
        # NOTE: tenants.business_type and tenants.owner_name columns don't exist
        # (verified 2026-08-10). tenants.owner_phone / tenants.owner_email
        # would be the analogous columns, but we only sync phone (verified to
        # exist) and business_name.
        tenant_patch: Dict[str, Any] = {}
        if request.phone is not None:
            tenant_patch["phone"] = request.phone
        if request.business_name is not None:
            tenant_patch["business_name"] = request.business_name
        if tenant_patch:
            tenant_patch["updated_at"] = datetime.now().isoformat()
            supabase.table("tenants").update(tenant_patch).eq("id", request.tenant_id).execute()
            logger.info(f"🔄 Synced {list(tenant_patch.keys())} to tenants row {request.tenant_id}")

        if result.data:
            profile = result.data[0]
            logger.info(f"✅ Business profile saved for tenant {request.tenant_id}")
            return BusinessProfileResponse(
                success=True,
                tenant_id=request.tenant_id,
                profile={
                    "business_name": profile.get("business_name"),
                    "owner_name": profile.get("owner_name"),
                    "business_type": profile.get("business_type") or request.business_type,
                    "handover_contacts": profile.get("handover_contacts", []),
                    "business_hours": profile.get("business_hours"),
                    "notes": profile.get("notes"),
                    "created_at": profile.get("created_at"),
                    "updated_at": profile.get("updated_at"),
                },
                message="Business profile saved successfully"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to save business profile"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error saving business profile for tenant {request.tenant_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while saving business profile."
        )


# ════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════════════


@router.get("/health")
async def business_profile_health():
    """Health check for business profile API"""
    try:
        supabase = get_supabase()
        return {
            "status": "healthy",
            "service": "business_profile_api",
            "supabase_connected": True,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "business_profile_api",
            "error": str(e),
        }
