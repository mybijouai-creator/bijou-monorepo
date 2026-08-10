"""
Bijou AI - WhatsApp QR Onboarding API
======================================

Self-serve property agent onboarding with WhatsApp QR connection.

Flow:
1. POST /api/onboarding/signup → Create tenant, return token + onboarding URL
2. GET /api/onboarding/status/{token} → Check WhatsApp connection status
3. GET /api/onboarding/qr/{token} → Get QR code image from bridge
4. POST /api/onboarding/complete/{token} → Mark onboarding complete

Author: W3J Bijou AI
Version: 2.0.0 (WhatsApp QR)
"""

import logging
import os
import re
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr, validator

from supabase import create_client

# Import email service (Resend-backed)
try:
    from src.saas.email_service import get_email_service
    EMAIL_SERVICE_AVAILABLE = True
except ImportError:
    get_email_service = None  # type: ignore[assignment]
    EMAIL_SERVICE_AVAILABLE = False

# Import WhatsApp Bridge Client for GOWA integration
try:
    from src.core.whatsapp_bridge_client import WhatsAppBridgeClient
    BRIDGE_CLIENT_AVAILABLE = True
except ImportError:
    WhatsAppBridgeClient = None
    BRIDGE_CLIENT_AVAILABLE = False

# Import SessionManager for device session management
try:
    from src.saas.session_manager import SessionManager
    SESSION_MANAGER_AVAILABLE = True
except ImportError:
    SessionManager = None
    SESSION_MANAGER_AVAILABLE = False

logger = logging.getLogger(__name__)

# Admin notification settings
ADMIN_EMAIL = os.getenv("EMAIL_NOTIFY", "")  # Set EMAIL_NOTIFY in env
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP_NUMBER", "")  # Set in env

# Create router
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# ════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ════════════════════════════════════════════════════════════════


class SignupRequest(BaseModel):
    """Property agent signup form data"""

    business_name: str
    email: EmailStr
    phone: str

    @validator("business_name")
    def validate_business_name(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError("Business name must be at least 2 characters")
        return v.strip()

    @validator("phone")
    def validate_phone(cls, v):
        # Remove all non-digits
        cleaned = re.sub(r"\D", "", v)
        if len(cleaned) < 10:
            raise ValueError("Phone number must be at least 10 digits")
        return cleaned


class SignupResponse(BaseModel):
    """Response after successful signup"""

    success: bool
    tenant_id: str
    onboarding_url: str
    message: str


class StatusResponse(BaseModel):
    """WhatsApp connection status + business-info completeness flag"""

    tenant_id: str
    business_name: str
    email: Optional[str] = None
    status: str  # pending, qr_ready, connecting, connected, error
    whatsapp_connected: bool
    onboarding_completed: bool
    whatsapp_jid: Optional[str] = None
    created_at: str
    # Business-info fields — used by the onboard page to decide whether to
    # show the "Tell us about your business" form before the QR step.
    # phone exists on tenants (set by both email + Google signups, though
    # Google signups set it to ""). owner_name is only on business_profiles.
    phone: Optional[str] = None
    owner_name: Optional[str] = None
    needs_business_info: bool = False  # True when phone is empty (the signal we can rely on)


# ════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════


def get_supabase():
    """Get Supabase admin client"""
    supabase_url = os.getenv("SUPABASE_URL", "").strip('"')
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip('"')

    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

    return create_client(supabase_url, supabase_key)


def generate_signup_token() -> str:
    """Generate secure random token for onboarding"""
    return secrets.token_urlsafe(32)


def generate_slug(business_name: str) -> str:
    """Generate URL-friendly slug from business name"""
    # Convert to lowercase, replace spaces with hyphens
    slug = business_name.lower().strip()
    # Remove special characters, keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    # Add random suffix to ensure uniqueness
    suffix = secrets.token_hex(4)
    return f"{slug}-{suffix}"


def get_whatsapp_bridge_url() -> str:
    """Get WhatsApp bridge URL from environment.

    Falls back to BRIDGE_URL — the var the rest of the app uses (bijou.py,
    bridge_client.py, dashboard_api_simple.py:990) — so onboarding can't break
    from env-name drift when only BRIDGE_URL is set.
    """
    bridge_url = (os.getenv("WHATSAPP_BRIDGE_URL") or os.getenv("BRIDGE_URL", "")).strip('"')
    if not bridge_url:
        raise RuntimeError("Missing WHATSAPP_BRIDGE_URL / BRIDGE_URL environment variable")
    return bridge_url.rstrip("/")


def get_bridge_auth_headers() -> dict:
    """Bridge auth headers — mirrors dashboard_api_simple.py:1002 / bijou.py priority:
    BRIDGE_API_KEY 'user:pass' -> Basic > BRIDGE_USER+BRIDGE_PASSWORD -> Basic > BRIDGE_API_KEY -> X-API-Key.
    Without this the bridge (behind auth) 401s and the QR renders as a broken image.
    """
    import base64
    headers: dict = {}
    bridge_user = os.getenv("BRIDGE_USER", "")
    bridge_password = os.getenv("BRIDGE_PASSWORD", "")
    bridge_api_key = os.getenv("BRIDGE_API_KEY", "")
    _no_key = ("NOT_SET", "", None)
    if bridge_api_key and bridge_api_key not in _no_key and ":" in bridge_api_key:
        headers["Authorization"] = "Basic " + base64.b64encode(bridge_api_key.encode()).decode()
    elif bridge_user and bridge_password:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{bridge_user}:{bridge_password}".encode()).decode()
    elif bridge_api_key and bridge_api_key not in _no_key:
        headers["X-API-Key"] = bridge_api_key
    return headers


def get_public_url() -> str:
    """Get public URL for this service — must be production URL for magic links."""
    url = os.getenv("PUBLIC_URL", "https://app.mybijou.xyz").rstrip("/")
    if "staging" in url and os.getenv("ENVIRONMENT", "production") == "production":
        logger.error(
            "⚠️  CRITICAL: PUBLIC_URL contains 'staging' in production environment! "
            "Magic links will point to the wrong domain. Set PUBLIC_URL=https://app.mybijou.xyz"
        )
    return url


async def send_admin_email_notification(business_name: str, email: str, phone: str, tenant_id: str):
    """
    Send email notification to admin when new customer signs up.
    Uses Resend via get_email_service() — no SMTP credentials required.

    Args:
        business_name: Customer's business name
        email: Customer's email
        phone: Customer's phone
        tenant_id: Generated tenant ID
    """
    if not EMAIL_SERVICE_AVAILABLE or get_email_service is None:
        logger.warning("⚠️ Email service not available - skipping admin notification")
        return

    try:
        html_body = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
              <h2 style="color: #10b981; border-bottom: 2px solid #10b981; padding-bottom: 10px;">
                🎉 New Customer Signup!
              </h2>

              <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Business Name:</strong> {business_name}</p>
                <p style="margin: 5px 0;"><strong>Email:</strong> {email}</p>
                <p style="margin: 5px 0;"><strong>Phone:</strong> {phone}</p>
                <p style="margin: 5px 0;"><strong>Tenant ID:</strong>
                  <code style="background: #e5e7eb; padding: 2px 6px; border-radius: 3px;">{tenant_id}</code>
                </p>
              </div>

              <div style="background: #dbeafe; padding: 15px; border-radius: 8px; border-left: 4px solid #3b82f6;">
                <p style="margin: 0;"><strong>⚡ Action Required:</strong></p>
                <p style="margin: 10px 0;">Customer is waiting for WhatsApp QR code on onboarding page.</p>
                <p style="margin: 0;">They will scan QR and start testing Bijou AI automatically.</p>
              </div>

              <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280;">
                <p>This is an automated notification from Bijou AI onboarding system.</p>
                <p>Tenant created at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
              </div>
            </div>
          </body>
        </html>
        """

        svc = get_email_service()
        svc.send_internal_notification(
            subject=f"🆕 New Bijou AI Signup - {business_name}",
            body=html_body,
        )
        logger.info(f"✅ Admin signup notification sent for {business_name}")

    except Exception as e:
        logger.error(f"❌ Failed to send admin email: {e}", exc_info=True)
        # Don't fail signup if email fails


async def send_admin_whatsapp_notification(business_name: str, email: str, phone: str):
    """
    Send WhatsApp message to admin (Bijou) when new customer signs up

    Args:
        business_name: Customer's business name
        email: Customer's email
        phone: Customer's phone
    """
    try:
        if not ADMIN_WHATSAPP or not BRIDGE_CLIENT_AVAILABLE:
            logger.warning("⚠️ Admin WhatsApp not configured - skipping WhatsApp notification")
            return

        bridge_url = get_whatsapp_bridge_url()
        bridge_api_key = os.getenv("BRIDGE_API_KEY", "")
        bridge_client = WhatsAppBridgeClient(base_url=bridge_url, api_key=bridge_api_key)

        message = f"""🎉 *New Bijou AI Signup!*

📋 *Business:* {business_name}
📧 *Email:* {email}
📱 *Phone:* {phone}

⏳ Customer is on onboarding page waiting to scan QR code.

_Automated notification from Bijou AI_"""

        result = bridge_client.send_text(
            phone=ADMIN_WHATSAPP,
            message=message
        )

        if result.get("code") == "SUCCESS":
            logger.info(f"✅ Admin WhatsApp sent to {ADMIN_WHATSAPP}")
        else:
            logger.warning(f"⚠️ WhatsApp notification failed: {result}")

    except Exception as e:
        logger.error(f"❌ Failed to send WhatsApp notification: {e}", exc_info=True)
        # Don't fail signup if WhatsApp fails


# ════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ════════════════════════════════════════════════════════════════


@router.post("/signup", response_model=SignupResponse)
async def signup_property_agent(request: SignupRequest):
    """
    Step 1: Create new tenant and initiate WhatsApp session

    Returns onboarding URL with token for QR display page
    """
    logger.info(f"🆕 New signup: {request.business_name} ({request.email})")

    try:
        supabase = get_supabase()

        # Check if email already exists
        existing = (
            supabase.table("tenants")
            .select("id, email")
            .eq("email", request.email)
            .execute()
        )
        if existing.data:
            logger.warning(f"⚠️ Duplicate signup attempt: {request.email}")
            raise HTTPException(
                status_code=400,
                detail=f"Email {request.email} is already registered. Please contact support.",
            )

        # Generate unique token and slug
        signup_token = generate_signup_token()
        slug = generate_slug(request.business_name)

        # Create tenant record
        tenant_data = {
            "name": request.business_name,  # Required field
            "slug": slug,  # Required field
            "business_name": request.business_name,
            "email": request.email,
            "phone": request.phone,
            "status": "active",  # Must be 'active', 'suspended', or 'cancelled'
            "plan": "basic",
            "signup_token": signup_token,
            "onboarding_completed": False,
            "created_by": "self-signup",
            "created_at": datetime.utcnow().isoformat(),
        }

        result = supabase.table("tenants").insert(tenant_data).execute()

        if not result.data:
            raise HTTPException(
                status_code=500, detail="Failed to create tenant record"
            )

        tenant_id = result.data[0]["id"]
        logger.info(f"✅ Tenant created: {tenant_id}")

        # Create tenant_users entry (owner)
        user_data = {
            "tenant_id": tenant_id,
            "email": request.email,
            "role": "owner",
            "is_main_contact": True,
            "created_at": datetime.utcnow().isoformat(),
        }

        supabase.table("tenant_users").insert(user_data).execute()
        logger.info(f"✅ Owner user created for tenant {tenant_id}")

        # Initialize WhatsApp session with bridge
        try:
            bridge_url = get_whatsapp_bridge_url()
            async with httpx.AsyncClient(timeout=10.0) as client:
                init_response = await client.post(
                    f"{bridge_url}/api/init", params={"tenant_id": tenant_id},
                    headers=get_bridge_auth_headers()
                )

                if init_response.status_code == 200:
                    logger.info(f"✅ WhatsApp session initialized for {tenant_id}")
                    # Status remains 'active' - no need to update
                else:
                    logger.error(f"❌ Bridge init failed: {init_response.text}")
                    # Continue anyway - user can retry

        except Exception as bridge_error:
            logger.error(f"❌ WhatsApp bridge error: {bridge_error}")
            # Continue - user will see error on onboarding page

        # Build onboarding URL
        public_url = get_public_url()
        onboarding_url = f"{public_url}/onboard/{signup_token}"

        # Send notifications to admin (non-blocking - don't fail signup if notifications fail)
        try:
            await send_admin_email_notification(
                business_name=request.business_name,
                email=request.email,
                phone=request.phone,
                tenant_id=tenant_id
            )
        except Exception as e:
            logger.error(f"Email notification failed: {e}")

        # Send welcome email to the new customer (Bug 3 fix)
        try:
            if EMAIL_SERVICE_AVAILABLE and get_email_service is not None:
                email_svc = get_email_service()
                email_svc.send_welcome_email(
                    to=request.email,
                    business_name=request.business_name,
                    onboarding_url=onboarding_url,
                )
                logger.info(f"✅ Welcome email queued for {request.email}")
        except Exception as e:
            logger.error(f"Welcome email failed (non-fatal): {e}")

        try:
            await send_admin_whatsapp_notification(
                business_name=request.business_name,
                email=request.email,
                phone=request.phone
            )
        except Exception as e:
            logger.error(f"WhatsApp notification failed: {e}")

        return SignupResponse(
            success=True,
            tenant_id=tenant_id,
            onboarding_url=onboarding_url,
            message="Tenant created successfully. Redirecting to WhatsApp setup...",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Signup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")


@router.get("/status/{token}", response_model=StatusResponse)
async def get_onboarding_status(token: str):
    """
    Step 2: Check WhatsApp connection status + business-info completeness

    Called by onboarding page every 3 seconds to detect when QR is scanned
    and to decide whether the "Tell us about your business" form should be shown.
    """
    try:
        supabase = get_supabase()

        # Find tenant by token. NOTE: do NOT select business_type or owner_name
        # from tenants — those columns don't exist on tenants (verified 2026-08-10
        # via Supabase PostgREST schema cache error 42703). business_type lives on
        # business_profiles; owner_name also lives on business_profiles.
        result = (
            supabase.table("tenants")
            .select(
                "id, business_name, email, status, whatsapp_jid, "
                "whatsapp_connected_at, onboarding_completed, created_at, phone"
            )
            .eq("signup_token", token)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Invalid or expired token")

        tenant = result.data[0]

        # Determine connection status
        whatsapp_connected = bool(tenant.get("whatsapp_connected_at"))

        # Determine onboarding status for UI
        if whatsapp_connected:
            onboarding_status = "connected"
        elif tenant.get("status") == "active":
            onboarding_status = "qr_ready"
        else:
            onboarding_status = "pending"

        # Business-info completeness: check tenants.phone (always present) and
        # business_profiles.owner_name (set after the form is filled). We
        # intentionally skip business_type because that column doesn't exist yet.
        phone_val = (tenant.get("phone") or "").strip()

        # Look up owner_name from business_profiles (may not exist yet for
        # fresh signups; that's fine)
        owner_name_val: Optional[str] = None
        try:
            bp_row = (
                supabase.table("business_profiles")
                .select("owner_name")
                .eq("tenant_id", tenant["id"])
                .limit(1)
                .execute()
            )
            if bp_row.data and bp_row.data[0].get("owner_name"):
                owner_name_val = bp_row.data[0]["owner_name"].strip() or None
        except Exception as bp_err:
            logger.debug(f"business_profiles lookup failed (non-fatal): {bp_err}")

        # The user needs the form if either the phone is empty (Google signup
        # default) OR no business_profiles row exists yet (no owner_name set).
        needs_info = (not phone_val) or (owner_name_val is None)

        return StatusResponse(
            tenant_id=tenant["id"],
            business_name=tenant["business_name"],
            email=tenant["email"],
            status=onboarding_status,
            whatsapp_connected=whatsapp_connected,
            onboarding_completed=tenant.get("onboarding_completed", False),
            whatsapp_jid=tenant.get("whatsapp_jid"),
            created_at=tenant.get("created_at", ""),
            phone=phone_val or None,
            owner_name=owner_name_val,
            needs_business_info=needs_info,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Status check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qr/{token}")
async def get_qr_code(token: str):
    """
    Step 3: Proxy QR code image from WhatsApp bridge

    Returns PNG image that updates when tenant_id changes.

    IMPORTANT: The GOWA v8+ bridge requires `device_id` (via X-Device-Id header
    OR device_id query param) for ALL API calls. The legacy `tenant_id` param
    no longer works — the bridge returns 400 "device_id is required" if you
    forget. The device_id is derived predictably as `bijou-{tenant_id}` in
    provision_whatsapp_device() and stored in the whatsapp_devices table.
    """
    try:
        supabase = get_supabase()

        # Find tenant by token
        result = (
            supabase.table("tenants").select("id").eq("signup_token", token).execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Invalid token")

        tenant_id = result.data[0]["id"]

        # Look up the device_id for this tenant. Fall back to the predictable
        # mapping `bijou-{tenant_id}` if the table lookup misses (e.g. the
        # signup happened before the table existed, or the device was deleted).
        device_id = f"bijou-{tenant_id}"
        try:
            dev_row = (
                supabase.table("whatsapp_devices")
                .select("device_id")
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            if dev_row.data and dev_row.data[0].get("device_id"):
                device_id = dev_row.data[0]["device_id"]
        except Exception as lookup_err:
            logger.warning(f"⚠️ device_id lookup failed for {tenant_id}, using predictable mapping: {lookup_err}")

        bridge_url = get_whatsapp_bridge_url()
        bridge_headers = get_bridge_auth_headers()
        # GOWA bridge accepts the device_id via X-Device-Id header OR
        # device_id query param. Use the header — it works on every endpoint.
        bridge_headers["X-Device-Id"] = device_id

        # 2026-08-10 FIX: this used to call `{bridge_url}/qr` and, on 404, retry
        # via `POST {bridge_url}/api/init`. NEITHER endpoint exists on the
        # deployed GOWA v8 bridge — /api/init belongs to the older Go bridge in
        # packages/bridge/main.go, which is not what runs in production. So the
        # QR always 404'd and the onboarding page showed a broken image.
        #
        # The correct contract is `GET /app/login?device_id=...`, which every
        # working caller already uses (dashboard_api_simple.py:1947,
        # core/whatsapp_bridge_client.py:210, onboarding_complete.py:289).
        # It returns JSON {code, results:{qr_link}}; that link is an ephemeral
        # PNG the bridge deletes after ~30s, so proxy the bytes ourselves.
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            qr_response = await client.get(
                f"{bridge_url}/app/login",
                params={"device_id": device_id},
                headers=bridge_headers,
            )

            if qr_response.status_code != 200:
                logger.error(
                    f"❌ Bridge /app/login failed for {device_id}: "
                    f"{qr_response.status_code} {qr_response.text[:200]}"
                )
                # Never pass the bridge's status through. The page treats 404
                # as "invalid or expired link" and tells the user to start over,
                # but a bridge that is still waking up is transient.
                raise HTTPException(
                    status_code=503,
                    detail="WhatsApp session is still starting. Please wait a moment.",
                )

            content_type = qr_response.headers.get("content-type", "")

            # Some bridge builds return the PNG directly.
            if "image/" in content_type:
                png_bytes = qr_response.content
            else:
                payload = qr_response.json()
                qr_link = (payload.get("results") or {}).get("qr_link")
                if not qr_link:
                    logger.error(
                        f"❌ Bridge returned no qr_link for {device_id}: {str(payload)[:200]}"
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="WhatsApp session is still starting. Please wait a moment.",
                    )
                # Force HTTPS so an http->https redirect can't drop the auth header.
                img_response = await client.get(
                    qr_link.replace("http://", "https://"), headers=bridge_headers
                )
                img_response.raise_for_status()
                png_bytes = img_response.content

            return Response(
                content=png_bytes,
                media_type="image/png",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ QR fetch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete/{token}")
async def complete_onboarding(token: str):
    """
    Step 4: Mark onboarding as complete

    Called when WhatsApp connection is confirmed
    """
    try:
        supabase = get_supabase()

        # Find tenant by token
        result = (
            supabase.table("tenants")
            .select("id, whatsapp_connected_at")
            .eq("signup_token", token)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Invalid token")

        tenant_id = result.data[0]["id"]
        whatsapp_connected_at = result.data[0].get("whatsapp_connected_at")

        if not whatsapp_connected_at:
            raise HTTPException(
                status_code=400,
                detail="WhatsApp not connected yet. Please scan QR code first.",
            )

        # Mark onboarding complete
        supabase.table("tenants").update(
            {
                "onboarding_completed": True,
                "status": "active",
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", tenant_id).execute()

        logger.info(f"✅ Onboarding completed for tenant {tenant_id}")

        return {
            "success": True,
            "message": "Onboarding completed successfully!",
            "tenant_id": tenant_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Complete onboarding failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════════════


@router.get("/health")
async def onboarding_health():
    """Check if onboarding API and dependencies are working"""
    health_status = {
        "onboarding_api": "ok",
        "supabase": "unknown",
        "whatsapp_bridge": "unknown",
    }

    try:
        supabase = get_supabase()
        supabase.table("tenants").select("id").limit(1).execute()
        health_status["supabase"] = "ok"
    except Exception as e:
        health_status["supabase"] = f"error: {str(e)}"

    try:
        bridge_url = get_whatsapp_bridge_url()
        bridge_user = os.getenv("BRIDGE_USER", "bijou")
        bridge_pass = os.getenv("BRIDGE_PASSWORD", "")

        # Use Basic Auth for bridge health check
        import base64
        auth_header = f"Basic {base64.b64encode(f'{bridge_user}:{bridge_pass}'.encode()).decode()}"

        # Use /devices endpoint which doesn't require device_id (GOWA v8+ compatible)
        async with httpx.AsyncClient(timeout=5.0) as client:
            bridge_health = await client.get(
                f"{bridge_url}/devices",
                headers={"Authorization": auth_header}
            )
            if bridge_health.status_code == 200:
                health_status["whatsapp_bridge"] = "ok"
            else:
                health_status["whatsapp_bridge"] = (
                    f"status: {bridge_health.status_code}"
                )
    except Exception as e:
        health_status["whatsapp_bridge"] = f"error: {str(e)}"

    overall_healthy = all(v == "ok" for v in health_status.values())

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "checks": health_status,
    }
