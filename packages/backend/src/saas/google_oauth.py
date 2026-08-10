"""
Google OAuth 2.0 Authentication for Bijou AI
============================================

Handles user sign-in with Google OAuth for onboarding flow.

Flow:
1. GET /api/auth/google/login → Redirect to Google OAuth consent
2. GET /api/auth/google/callback → Exchange code for tokens, create tenant, redirect to onboarding QR
3. POST /api/auth/google/token → Frontend can exchange Google token for Bijou session

Author: W3J Bijou AI
"""

import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from supabase import create_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/google", tags=["google-oauth"])

# ════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════

# Canonical public origin. Everything user-facing must be built on this and
# NEVER on request.base_url.
#
# 2026-08-10 BUG: the OAuth callback used `PUBLIC_URL or str(request.base_url)`.
# Behind Fly's proxy the request host resolves to bijou-production.fly.dev, so
# users finishing Google sign-up were redirected to
# https://bijou-production.fly.dev/onboard/... — a DIFFERENT browser origin from
# app.mybijou.xyz. The dashboard keeps its JWT in localStorage, which is
# origin-scoped, so on that host it found no session and bounced to /login.
# Symptom: "redirects to the fly machine url, no QR page, no vertical".
#
# Defaulting to the canonical host matches every other module here
# (dashboard_api_simple.py:86, onboarding_api.py:191, onboarding_complete.py:124)
# and removes the request-host dependency entirely.
CANONICAL_PUBLIC_URL = "https://app.mybijou.xyz"


def _public_base_url() -> str:
    """Public origin for user-facing redirects. Never derived from the request."""
    return (os.getenv("PUBLIC_URL") or CANONICAL_PUBLIC_URL).rstrip("/")


def get_google_config():
    """Get Google OAuth configuration from environment"""
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv(
            "GOOGLE_REDIRECT_URI",
            f"{CANONICAL_PUBLIC_URL}/api/auth/google/callback",
        ),
        "scopes": [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            # Commented out advanced scopes until consent screen is verified
            # "https://www.googleapis.com/auth/gmail.send",  # For email notifications
            # "https://www.googleapis.com/auth/calendar",    # For booking appointments
            # "https://www.googleapis.com/auth/drive.file",  # For knowledge base uploads
        ]
    }

def get_supabase():
    """Get Supabase client"""
    supabase_url = os.getenv("SUPABASE_URL", "").strip('"')
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip('"')
    
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
    
    return create_client(supabase_url, supabase_key)


# ════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ════════════════════════════════════════════════════════════════

class GoogleUserInfo(BaseModel):
    """Google user profile information"""
    email: EmailStr
    name: str
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    picture: Optional[str] = None
    email_verified: bool = False


# ════════════════════════════════════════════════════════════════
# OAUTH ENDPOINTS
# ════════════════════════════════════════════════════════════════

@router.get("/login")
async def google_login():
    """
    Step 1: Redirect user to Google OAuth consent screen
    
    Usage: User clicks "Sign in with Google" → hits this endpoint → redirected to Google
    """
    config = get_google_config()
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Build Google OAuth URL
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(config["scopes"]),
        "state": state,
        "access_type": "offline",  # Get refresh token
        "prompt": "consent",  # Force consent to get refresh token
    }
    
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    logger.info(f"🔐 Redirecting user to Google OAuth: {google_auth_url[:100]}...")
    
    return RedirectResponse(url=google_auth_url)


@router.get("/callback")
async def google_callback(code: str, state: str, request: Request):
    """
    Step 2: Google redirects here with authorization code
    Exchange code for tokens → fetch user info → create tenant → redirect to QR onboarding
    """
    logger.info(f"📨 Received OAuth callback with code: {code[:20]}... state: {state[:20]}...")

    config = get_google_config()
    
    try:
        # Exchange authorization code for tokens
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "redirect_uri": config["redirect_uri"],
                    "grant_type": "authorization_code",
                },
            )
            
            if token_response.status_code != 200:
                error_detail = token_response.text
                logger.error(f"❌ Token exchange failed ({token_response.status_code}): {error_detail}")
                raise HTTPException(
                    status_code=token_response.status_code, 
                    detail=f"Failed to exchange authorization code: {error_detail}"
                )
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            
            logger.info(f"✅ Got access token: {access_token[:20]}...")
            
            # Fetch user profile from Google
            user_response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            
            if user_response.status_code != 200:
                logger.error(f"❌ Failed to fetch user info: {user_response.text}")
                raise HTTPException(status_code=400, detail="Failed to fetch user profile")
            
            user_data = user_response.json()
            user_info = GoogleUserInfo(**user_data)
            
            logger.info(f"👤 User authenticated: {user_info.email} ({user_info.name})")
            
            # Create or get tenant
            tenant_id = await create_tenant_from_google(user_info, access_token, refresh_token)
            
            # Generate onboarding token
            onboarding_token = secrets.token_urlsafe(32)
            
            # Store onboarding session in Supabase
            supabase = get_supabase()
            supabase.table("onboarding_sessions").insert({
                "token": onboarding_token,
                "tenant_id": tenant_id,
                "email": user_info.email,
                "status": "pending_whatsapp",
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
            }).execute()
            
            # Check if WhatsApp is already connected
            # Use maybe_single() to avoid 500 on missing tenant row
            tenant_info = supabase.table("tenants").select("whatsapp_connected_at, onboarding_completed").eq("id", tenant_id).maybe_single().execute()
            ti_data = getattr(tenant_info, "data", None) if tenant_info else None

            if ti_data and ti_data.get("whatsapp_connected_at"):
                # User already completed onboarding - go straight to dashboard
                logger.info(f"✅ WhatsApp already connected for {tenant_id}, skipping onboarding")
                dashboard_url = f"{_public_base_url()}/dashboard"
                return RedirectResponse(url=dashboard_url)
            
            # CRITICAL: Also update tenants.signup_token for onboarding API compatibility
            # The /api/onboarding/status/{token} endpoint looks in tenants table
            supabase.table("tenants").update({
                "signup_token": onboarding_token,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", tenant_id).execute()
            
            logger.info(f"🎫 Created onboarding session: {onboarding_token[:20]}... for tenant {tenant_id}")

            # Redirect to onboarding QR page (served from our own backend, not Vercel)
            onboarding_url = f"{_public_base_url()}/onboard/{onboarding_token}"

            return RedirectResponse(url=onboarding_url)
            
    except Exception as e:
        logger.exception(f"❌ OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


# ════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════

async def create_tenant_from_google(
    user_info: GoogleUserInfo,
    access_token: str,
    refresh_token: Optional[str]
) -> str:
    """
    Create or get existing tenant from Google user info
    
    Returns: tenant_id (UUID string)
    """
    supabase = get_supabase()
    
    try:
        # Check if tenant already exists by email
        existing = supabase.table("tenants").select("*").eq("email", user_info.email).execute()
        
        if existing.data and len(existing.data) > 0:
            tenant_id = existing.data[0]["id"]  # FIX: Use "id" not "tenant_id"
            logger.info(f"♻️  Tenant already exists: {tenant_id}")
            
            # Update last login timestamp
            supabase.table("tenants").update({
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", tenant_id).execute()  # FIX: Use "id" not "tenant_id"
            
            # IMPORTANT: Still return tenant_id so callback creates fresh onboarding_session
            return tenant_id
        
        # Create new tenant - match onboarding_api.py schema
        import re
        import secrets
        
        # Generate slug from name
        slug = user_info.name.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        slug = f"{slug}-{secrets.token_hex(4)}"
        
        # FIX: Match the exact schema from onboarding_api.py
        tenant_data = {
            "name": user_info.name,  # Required: Business/person name
            "slug": slug,  # Required: URL-friendly identifier
            "business_name": user_info.name,  # Will be updated in profile
            "email": user_info.email,
            "phone": "",  # Will be collected during profile completion
            "status": "active",  # Must be 'active', 'suspended', or 'cancelled'
            "plan": "basic",  # Start with basic plan
            "signup_token": secrets.token_urlsafe(32),  # For onboarding flow
            "onboarding_completed": False,
            "created_by": "google-oauth",
            "created_at": datetime.utcnow().isoformat(),
        }
        
        result = supabase.table("tenants").insert(tenant_data).execute()
        
        if not result.data:
            logger.error("❌ Failed to insert tenant into database")
            raise Exception("Failed to create account")
        
        tenant_id = result.data[0]["id"]  # FIX: Use "id" not "tenant_id"
        logger.info(f"✅ Created new tenant: {tenant_id} ({user_info.email})")
        
        # Create tenant_users entry (owner)
        user_data = {
            "tenant_id": tenant_id,
            "email": user_info.email,
            "role": "owner",
            "is_main_contact": True,
            "created_at": datetime.utcnow().isoformat(),
        }
        
        supabase.table("tenant_users").insert(user_data).execute()
        logger.info(f"✅ Owner user entry created for tenant {tenant_id}")
        
        return tenant_id
        
    except Exception as e:
        logger.exception(f"❌ Failed to create/get tenant: {e}")
        raise HTTPException(status_code=500, detail="Failed to create account")
