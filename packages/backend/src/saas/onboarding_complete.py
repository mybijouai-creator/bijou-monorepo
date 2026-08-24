"""
Complete Automated Onboarding API
Handles: Payment → Details → QR → Knowledge → Agents
Date: February 17, 2026
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks, Depends
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import os
import uuid
from datetime import datetime, timedelta
import logging
import httpx
import base64

from supabase import create_client, Client
from src.core.whatsapp_bridge_client import WhatsAppBridgeClient

router = APIRouter(prefix="/api/onboarding/v2", tags=["onboarding-v2"])
logger = logging.getLogger(__name__)

# Supabase client
def get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY")
    )

# ============================================================================
# MODELS
# ============================================================================

class SignupRequest(BaseModel):
    business_name: str
    email: EmailStr
    phone: str
    plan: str = "free"  # 'free', 'pro', 'enterprise' (changed from 'free_trial')

class SignupResponse(BaseModel):
    tenant_id: str
    signup_token: str
    onboarding_url: str
    message: str

class DetailsRequest(BaseModel):
    business_type: Optional[str] = None
    business_address: Optional[str] = None
    business_hours: Optional[dict] = None
    owner_name: Optional[str] = None

class AgentRequest(BaseModel):
    agent_name: str
    agent_email: Optional[str] = None
    agent_phone: Optional[str] = None
    agent_whatsapp_jid: Optional[str] = None
    role: str = "agent"

# ============================================================================
# STEP 1: SIGNUP (Creates tenant + initiates payment/trial)
# ============================================================================

@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, background_tasks: BackgroundTasks):
    """
    Step 1: Tenant Signup
    - Creates tenant record
    - Generates signup_token
    - Starts free trial OR redirects to Stripe payment
    - Provisions WhatsApp device on bridge
    """
    try:
        supabase = get_supabase()

        # Check if email already exists (use owner_email from base schema)
        existing = supabase.table("tenants").select("id").eq("owner_email", request.email).execute()
        if existing.data:
            raise HTTPException(status_code=409, detail="Email already registered")

        # Create tenant with ONLY base schema columns + migration 012 columns
        slug = request.business_name.lower().replace(" ", "-")[:50]
        signup_token = str(uuid.uuid4())

        # Base schema columns that DEFINITELY exist
        tenant_data = {
            "name": request.business_name,
            "slug": slug,
            "business_name": request.business_name,  # ✅ BUG 3 FIX: Save to business_name column
            "email": request.email,                   # ✅ BUG 3 FIX: Save to email column
            "owner_email": request.email,
            "owner_phone": request.phone,
            "plan_tier": request.plan,  # 'free', 'pro', or 'enterprise'
            "is_active": True,
            "signup_token": signup_token,  # ✅ PHASE 4.2 FIX: Save signup_token to DB for magic link emails
        }

        # Add migration 012 columns (onboarding_step, payment_method, trial_ends_at)
        tenant_data["onboarding_step"] = "payment"

        # Set trial period for free plan (14 days)
        if request.plan == "free":
            tenant_data["trial_ends_at"] = (datetime.now() + timedelta(days=14)).isoformat()
            tenant_data["payment_method"] = "trial"

        result = supabase.table("tenants").insert(tenant_data).execute()
        tenant_id = result.data[0]["id"]

        # signup_token already saved to DB above; keep it for onboarding URL

        # Create onboarding progress tracker
        supabase.table("onboarding_progress").insert({
            "tenant_id": tenant_id,
            "step_payment_completed": request.plan == "free",  # Free plan skips payment
            "step_payment_at": datetime.now().isoformat() if request.plan == "free" else None,
            "current_step": "details" if request.plan == "free" else "payment"
        }).execute()

        # Provision WhatsApp device on bridge (background task)
        background_tasks.add_task(provision_whatsapp_device, tenant_id, request.business_name)

        # Return signup response — use PUBLIC_URL (canonical production URL)
        # so the QR page is served from our own backend, not the dead Vercel v0-cliste app
        frontend_url = os.getenv('PUBLIC_URL', 'https://app.mybijou.xyz').rstrip("/")
        onboarding_url = f"{frontend_url}/onboard/{signup_token}"

        logger.info(f"✅ Tenant signup successful: {tenant_id} ({request.email})")

        return SignupResponse(
            tenant_id=tenant_id,
            signup_token=signup_token,
            onboarding_url=onboarding_url,
            message=f"Signup successful! {'14-day free trial started.' if request.plan == 'free' else 'Please complete payment.'}"
        )

    except Exception as e:
        logger.error(f"❌ Signup failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")

# ============================================================================
# STEP 2: BUSINESS DETAILS
# ============================================================================

@router.post("/details/{tenant_id}")
async def submit_details(tenant_id: str, details: DetailsRequest):
    """
    Step 2: Business Details
    - Updates tenant with business info
    - Marks details step complete
    """
    try:
        supabase = get_supabase()

        # Verify tenant exists
        tenant_result = supabase.table("tenants").select("id").eq("id", tenant_id).execute()
        if not tenant_result.data:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Update tenant details.
        # NOTE (2026-08-06): the tenants table has `business_hours` (jsonb) but
        # NOT `business_type`, `business_address`, or `owner_name`. Sending
        # unknown columns to PostgREST returns PGRST204 and the whole update
        # 500s. Only write columns that exist on the table; the dropped
        # fields are kept on the request model for forward-compat and will be
        # persisted when/if the schema is migrated to add them.
        update_data = {
            "business_hours": details.business_hours,
            "onboarding_step": "whatsapp",
        }
        supabase.table("tenants").update(update_data).eq("id", tenant_id).execute()

        # Update onboarding progress
        supabase.table("onboarding_progress").update({
            "step_details_completed": True,
            "step_details_at": datetime.now().isoformat(),
            "current_step": "whatsapp"
        }).eq("tenant_id", tenant_id).execute()

        logger.info(f"✅ Details submitted for tenant {tenant_id}")

        return {
            "status": "success",
            "next_step": "whatsapp",
            "message": "Details saved! Please scan QR code to connect WhatsApp."
        }

    except Exception as e:
        logger.error(f"❌ Details submission failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STEP 3: WHATSAPP QR CODE
# ============================================================================

@router.get("/whatsapp/qr/{tenant_id}")
async def get_whatsapp_qr(tenant_id: str):
    """
    Step 3: WhatsApp QR Code
    - Creates device in bridge if it doesn't exist
    - Returns QR code from bridge for scanning
    - Fetches and caches QR image immediately (bridge deletes after 30s)
    """
    try:
        supabase = get_supabase()

        # Get tenant info for business name
        tenant_result = supabase.table("tenants").select("business_name").eq("id", tenant_id).execute()
        if not tenant_result.data:
            raise HTTPException(status_code=404, detail="Tenant not found")

        business_name = tenant_result.data[0].get("business_name", f"Bijou-{tenant_id[:8]}")

        # Check if device exists in database
        device_result = supabase.table("whatsapp_devices").select("device_id").eq("tenant_id", tenant_id).execute()

        # Setup bridge client
        bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-production.fly.dev")
        # No fallback defaults. The previous hardcoded pair shipped in a public
        # repo, so an unset env var used to mean "authenticate with a leaked
        # credential". Missing config must fail loudly instead.
        bridge_user = os.environ["BRIDGE_USER"]
        bridge_pass = os.environ["BRIDGE_PASSWORD"]

        # Generate or retrieve device_id
        if device_result.data:
            device_id = device_result.data[0]["device_id"]
            logger.info(f"Using existing device {device_id} for tenant {tenant_id}")
        else:
            # Create new device in bridge
            device_id = f"bijou-{tenant_id}"
            logger.info(f"Creating new device {device_id} for tenant {tenant_id}")

            bridge_client = WhatsAppBridgeClient(
                base_url=bridge_url,
                api_key=f"{bridge_user}:{bridge_pass}"
            )

            # Create device in bridge
            create_response = bridge_client.create_device(device_name=business_name)

            if create_response.get("code") != "SUCCESS":
                # Check if error is "already exists" which is OK
                error_msg = create_response.get("message", "")
                error_lower = error_msg.lower()
                if "already exists" not in error_lower and "duplicate" not in error_lower:
                    # Bridge is unreachable (refused, timeout, etc). The
                    # bridge_client swallows the connection error and returns
                    # it as a dict — so we map it to 503 here, not 500.
                    if any(s in error_lower for s in [
                        "no connection", "actively refused", "connection refused",
                        "timed out", "timeout", "unreachable",
                        "winerror 10061", "name or service not known",
                        "all connection attempts failed",
                    ]):
                        logger.warning(f"⚠️ Bridge unreachable while creating device for {tenant_id}: {error_msg}")
                        raise HTTPException(
                            status_code=503,
                            detail="WhatsApp bridge is unreachable right now. Please try again in a moment.",
                        )
                    raise HTTPException(status_code=500, detail=f"Failed to create device: {error_msg}")

            # Extract actual device_id from bridge response
            bridge_device_id = create_response.get("results", {}).get("id")
            if bridge_device_id:
                device_id = bridge_device_id  # Use bridge-assigned UUID
                logger.info(f"Bridge assigned device_id: {device_id}")

            # Store mapping in database
            supabase.table("whatsapp_devices").insert({
                "tenant_id": tenant_id,
                "device_id": device_id,
                "device_name": business_name
            }).execute()

            logger.info(f"✅ Device {device_id} created and stored for tenant {tenant_id}")

        # Get QR code from bridge
        bridge_client = WhatsAppBridgeClient(
            base_url=bridge_url,
            api_key=f"{bridge_user}:{bridge_pass}",
            device_id=device_id
        )

        qr_response = bridge_client.get_qr_code(device_id=device_id)

        if qr_response.get("code") != "SUCCESS":
            error_msg = qr_response.get("message", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to get QR code: {error_msg}")

        # CRITICAL: Fetch QR image immediately and convert to base64
        # GOWA bridge auto-deletes QR files after 30 seconds
        if qr_response.get("results", {}).get("qr_link"):
            original_qr_url = qr_response["results"]["qr_link"]
            # Force HTTPS to avoid redirect
            original_qr_url = original_qr_url.replace("http://", "https://")
            auth_header = f"Basic {base64.b64encode(f'{bridge_user}:{bridge_pass}'.encode()).decode()}"

            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    img_response = await client.get(
                        original_qr_url,
                        headers={"Authorization": auth_header},
                        timeout=10.0
                    )
                    img_response.raise_for_status()

                    # Convert to base64 data URI
                    qr_base64 = base64.b64encode(img_response.content).decode()
                    qr_data_uri = f"data:image/png;base64,{qr_base64}"

                    # Return base64 data URI instead of ephemeral URL
                    qr_response["results"]["qr_link"] = qr_data_uri
                    logger.info(f"✅ QR code fetched and converted to base64 for tenant {tenant_id}")
            except Exception as img_error:
                logger.warning(f"⚠️ Failed to fetch QR image, returning bridge URL: {img_error}")
                # Fallback to bridge URL if fetch fails

        logger.info(f"✅ QR code generated for tenant {tenant_id}")

        return qr_response

    except HTTPException:
        raise
    except Exception as e:
        # Bridge connection failures (refused/unreachable) should be 503
        # not 500 — the user's tenant is fine, the bridge just isn't reachable.
        msg = str(e).lower()
        if any(s in msg for s in [
            "no connection", "actively refused", "connection refused",
            "timed out", "timeout", "unreachable", "name or service not known",
            "temporary failure in name resolution",
        ]):
            logger.warning(f"⚠️ Bridge unreachable while generating QR for {tenant_id}: {e}")
            raise HTTPException(
                status_code=503,
                detail="WhatsApp bridge is unreachable right now. Please try again in a moment.",
            )
        logger.error(f"❌ QR generation failed for {tenant_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate QR: {str(e)}")

@router.get("/whatsapp/qr-image/{tenant_id}/{qr_filename}")
async def get_qr_image_proxy(tenant_id: str, qr_filename: str):
    """
    Proxy QR image from bridge to avoid Basic Auth issues.
    Fetches image from bridge with authentication, serves it publicly.
    """
    try:
        bridge_url = os.getenv("BRIDGE_URL", "https://bijou-bridge-production.fly.dev")
        # No fallback defaults. The previous hardcoded pair shipped in a public
        # repo, so an unset env var used to mean "authenticate with a leaked
        # credential". Missing config must fail loudly instead.
        bridge_user = os.environ["BRIDGE_USER"]
        bridge_pass = os.environ["BRIDGE_PASSWORD"]

        # Fetch QR image from bridge with auth
        image_url = f"{bridge_url}/statics/qrcode/{qr_filename}"
        auth_header = f"Basic {base64.b64encode(f'{bridge_user}:{bridge_pass}'.encode()).decode()}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                image_url,
                headers={"Authorization": auth_header},
                timeout=10.0
            )
            response.raise_for_status()

        # Return image without auth requirement
        return Response(
            content=response.content,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=300",  # Cache for 5 minutes
                "Content-Disposition": f"inline; filename={qr_filename}"
            }
        )
    except Exception as e:
        msg = str(e).lower()
        if any(s in msg for s in [
            "no connection", "actively refused", "connection refused",
            "timed out", "timeout", "unreachable",
            "all connection attempts failed", "winerror 10061",
            "name or service not known",
        ]):
            raise HTTPException(
                status_code=503,
                detail="WhatsApp bridge is unreachable. Please try again in a moment.",
            )
        logger.error(f"❌ QR image proxy failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch QR image: {str(e)}")

@router.post("/whatsapp/connected/{tenant_id}")
async def mark_whatsapp_connected(tenant_id: str):
    """
    Step 3 (Completion): Mark WhatsApp as connected
    - Called after successful QR scan
    - Moves to knowledge upload step
    """
    try:
        supabase = get_supabase()

        # Update progress
        supabase.table("onboarding_progress").update({
            "step_whatsapp_completed": True,
            "step_whatsapp_at": datetime.now().isoformat(),
            "current_step": "knowledge"
        }).eq("tenant_id", tenant_id).execute()

        supabase.table("tenants").update({
            "onboarding_step": "knowledge",
            "whatsapp_connected_at": datetime.now().isoformat()
        }).eq("id", tenant_id).execute()

        logger.info(f"✅ WhatsApp connected for tenant {tenant_id}")

        return {
            "status": "success",
            "next_step": "knowledge",
            "message": "WhatsApp connected! Please upload your knowledge base."
        }

    except Exception as e:
        logger.error(f"❌ WhatsApp connection update failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STEP 4: KNOWLEDGE BASE UPLOAD
# ============================================================================

@router.post("/knowledge/upload/{tenant_id}")
async def upload_knowledge(
    tenant_id: str,
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None
):
    """
    Step 4: Knowledge Base Upload
    - Accepts PDF, DOCX, TXT files
    - Stores metadata in database
    - Processes text extraction in background
    """
    try:
        supabase = get_supabase()

        uploaded_files = []
        allowed_types = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']

        for file in files:
            # Validate file type
            if file.content_type not in allowed_types:
                continue

            file_content = await file.read()

            # Record in database
            doc_result = supabase.table("knowledge_documents").insert({
                "tenant_id": tenant_id,
                "filename": file.filename,
                "file_size_bytes": len(file_content),
                "file_type": file.content_type,
                "upload_url": f"temp/{tenant_id}/{file.filename}",  # Placeholder
                "status": "uploaded"
            }).execute()

            uploaded_files.append(doc_result.data[0])

            # Queue background processing (implement later)
            # if background_tasks:
            #     background_tasks.add_task(process_knowledge_document, doc_result.data[0]["id"])

        # Update progress
        supabase.table("onboarding_progress").update({
            "step_knowledge_completed": True,
            "step_knowledge_at": datetime.now().isoformat(),
            "current_step": "agents"
        }).eq("tenant_id", tenant_id).execute()

        supabase.table("tenants").update({
            "onboarding_step": "agents"
        }).eq("id", tenant_id).execute()

        logger.info(f"✅ {len(uploaded_files)} files uploaded for tenant {tenant_id}")

        return {
            "status": "success",
            "uploaded_count": len(uploaded_files),
            "files": uploaded_files,
            "next_step": "agents",
            "message": f"{len(uploaded_files)} files uploaded successfully!"
        }

    except Exception as e:
        logger.error(f"❌ Knowledge upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STEP 5: HANDOVER AGENTS
# ============================================================================

@router.post("/agents/add/{tenant_id}")
async def add_handover_agent(tenant_id: str, agent: AgentRequest):
    """
    Step 5: Add Handover Agents
    - Configure human agents for escalations
    """
    try:
        supabase = get_supabase()

        # Insert agent
        agent_result = supabase.table("handover_agents").insert({
            "tenant_id": tenant_id,
            "agent_name": agent.agent_name,
            "agent_email": agent.agent_email,
            "agent_phone": agent.agent_phone,
            "agent_whatsapp_jid": agent.agent_whatsapp_jid,
            "role": agent.role,
            "is_active": True
        }).execute()

        logger.info(f"✅ Agent {agent.agent_name} added for tenant {tenant_id}")

        return {
            "status": "success",
            "agent": agent_result.data[0],
            "message": f"Agent {agent.agent_name} added successfully!"
        }

    except Exception as e:
        logger.error(f"❌ Agent addition failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/complete/{tenant_id}")
async def complete_onboarding(tenant_id: str):
    """
    Final Step: Complete Onboarding
    - Marks onboarding as complete
    - Grants dashboard access
    """
    try:
        supabase = get_supabase()

        # Mark complete
        supabase.table("onboarding_progress").update({
            "step_agents_completed": True,
            "step_agents_at": datetime.now().isoformat(),
            "current_step": "completed"
        }).eq("tenant_id", tenant_id).execute()

        supabase.table("tenants").update({
            "onboarding_step": "completed",
            "onboarding_completed_at": datetime.now().isoformat(),
            "is_active": True
        }).eq("id", tenant_id).execute()

        # Generate dashboard access URL — use PUBLIC_URL for canonical host
        dashboard_url = f"{os.getenv('PUBLIC_URL', 'https://app.mybijou.xyz').rstrip('/')}/dashboard?tenant={tenant_id}"

        logger.info(f"🎉 Onboarding complete for tenant {tenant_id}")

        return {
            "status": "success",
            "message": "Onboarding complete! Welcome to Bijou AI!",
            "dashboard_url": dashboard_url,
            "tenant_id": tenant_id
        }

    except Exception as e:
        logger.error(f"❌ Onboarding completion failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# STATUS ENDPOINT
# ============================================================================

@router.get("/status/{tenant_id}")
async def get_onboarding_status(tenant_id: str):
    """Get current onboarding status - with live bridge connection check"""
    try:
        supabase = get_supabase()

        tenant_result = supabase.table("tenants").select("id, onboarding_step").eq("id", tenant_id).execute()
        if not tenant_result.data:
            raise HTTPException(status_code=404, detail="Tenant not found")
        current_step = tenant_result.data[0]["onboarding_step"]

        progress_result = supabase.table("onboarding_progress").select("*").eq("tenant_id", tenant_id).execute()
        progress_data = progress_result.data[0] if progress_result.data else {}

        # ✅ BUG 1 FIX: Check bridge connection status if WhatsApp step not completed yet
        if not progress_data.get("step_whatsapp_completed", False):
            try:
                # Get bridge credentials from environment (no hardcoded fallbacks)
                bridge_url = os.getenv("BRIDGE_URL")
                bridge_user = os.getenv("BRIDGE_USER")
                bridge_pass = os.getenv("BRIDGE_PASSWORD")

                if not all([bridge_url, bridge_user, bridge_pass]):
                    logger.warning(f"⚠️ Bridge credentials not configured, skipping connection check")
                else:
                    device_id = f"bijou-{tenant_id}"

                    bridge_client = WhatsAppBridgeClient(
                        base_url=bridge_url,
                        api_key=f"{bridge_user}:{bridge_pass}",
                        device_id=device_id
                    )

                    # Check if device is logged in on bridge
                    device_info = bridge_client.get_device_info(device_id)

                    if device_info.get("code") == "SUCCESS":
                        results = device_info.get("results", {})
                        # GOWA v8 uses "state": "logged_in" (string), not "is_logged_in" (boolean)
                        device_state = results.get("state", "")
                        is_logged_in = device_state == "logged_in"

                        if is_logged_in:
                            # Update database to mark WhatsApp step complete
                            supabase.table("onboarding_progress").update({
                                "step_whatsapp_completed": True,
                                "step_whatsapp_at": datetime.now().isoformat(),
                                "current_step": "knowledge"
                            }).eq("tenant_id", tenant_id).execute()

                            supabase.table("tenants").update({
                                "whatsapp_connected": True,
                                "whatsapp_connected_at": datetime.now().isoformat(),
                                "onboarding_step": "knowledge",
                                "session_active": True
                            }).eq("id", tenant_id).execute()

                            # Update whatsapp_devices with actual JID (GOWA v8 uses "jid", not "device")
                            whatsapp_jid = results.get("jid", "")
                            if whatsapp_jid:
                                supabase.table("whatsapp_devices").update({
                                    "whatsapp_jid": whatsapp_jid,
                                    "updated_at": datetime.now().isoformat()
                                }).eq("tenant_id", tenant_id).execute()

                            logger.info(f"✅ [STATUS CHECK] WhatsApp connected for tenant {tenant_id} (JID: {whatsapp_jid})")

                            # Re-fetch updated progress
                            progress_result = supabase.table("onboarding_progress").select("*").eq("tenant_id", tenant_id).execute()
                            progress_data = progress_result.data[0] if progress_result.data else {}
                            current_step = "knowledge"
            except Exception as bridge_error:
                # Don't fail the status check if bridge is unreachable
                logger.warning(f"⚠️ Bridge check failed for {tenant_id}: {bridge_error}")

        return {
            "status": "success",
            "current_step": current_step,
            "progress": progress_data
        }

    except Exception as e:
        logger.error(f"❌ Status check failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# BACKGROUND TASKS
# ============================================================================

async def provision_whatsapp_device(tenant_id: str, business_name: str):
    """Background task: Create WhatsApp device on bridge"""
    try:
        bridge_url = os.getenv("BRIDGE_URL")
        bridge_user = os.getenv("BRIDGE_USER")
        bridge_pass = os.getenv("BRIDGE_PASSWORD")

        if not bridge_url or not bridge_user or not bridge_pass:
            logger.error(
                f"❌ [PROVISION] Missing bridge config — BRIDGE_URL/BRIDGE_USER/BRIDGE_PASSWORD must be set in env. "
                f"Skipping device provision for tenant {tenant_id}."
            )
            return

        # CRITICAL: Use predictable device_id for GOWA v8+ multi-device support
        device_id = f"bijou-{tenant_id}"

        bridge_client = WhatsAppBridgeClient(
            base_url=bridge_url,
            api_key=f"{bridge_user}:{bridge_pass}",
            device_id=device_id  # ← GOWA v8+ requires device_id for all API calls
        )

        device_response = bridge_client.create_device(device_name=business_name)

        if device_response.get("code") == "SUCCESS":
            supabase = get_supabase()
            # Store mapping (device_id already known from tenant_id)
            supabase.table("whatsapp_devices").insert({
                "tenant_id": tenant_id,
                "device_id": device_id,
                "device_name": business_name
            }).execute()

            logger.info(f"✅ WhatsApp device provisioned for tenant {tenant_id}: {device_id}")

    except Exception as e:
        logger.error(f"❌ Failed to provision device for {tenant_id}: {e}")
