import logging
import os
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from pydantic import BaseModel, EmailStr
from src.core.dashboard_api_simple import get_supabase
from src.saas.email_service import get_email_service
from src.saas.tenant_manager import TenantManager
from uuid import uuid4

# Specific exception types from the auth/Supabase stack. Catching the broad
# `Exception` below was masking the real error from `db.auth.sign_up` and
# turning every Supabase auth failure (signups disabled, network blip, weak
# password, etc.) into a generic 500 with no actionable detail. 2026-08-09.
try:
    from supabase_auth.errors import AuthApiError  # type: ignore
except ImportError:  # pragma: no cover — older supabase-py
    AuthApiError = Exception  # type: ignore
try:
    import httpx  # used for the welcome-WhatsApp block AND surfaced here
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter()

# Canonical public origin. Everything user-facing (emails, WhatsApp links,
# magic links, password resets) must be built on this — NEVER on
# request.base_url.
#
# 2026-08-17 BUG: the welcome WhatsApp message and the password-reset email
# both used `os.getenv("APP_URL", "https://bijou-production.fly.dev")` as
# their fallback. Behind Fly's proxy, `bijou-production.fly.dev` is the
# internal container host — a different browser origin from app.mybijou.xyz.
# Result: the password-reset email and the welcome-WhatsApp message linked
# to the Fly machine URL, and the user's browser either showed a
# Fly-default-cert warning or, on the bare Fly host, the dashboard found
# no JWT in localStorage (origin-scoped) and bounced them to /login.
# Mirrors `_public_base_url()` in google_oauth.py:54 and every other
# canonical-URL site in this monorepo (onboarding_api.py:191, etc.).
CANONICAL_PUBLIC_URL = "https://app.mybijou.xyz"


def _public_base_url() -> str:
    """Public origin for user-facing redirects + email links. Never derived
    from the request. Caller should rstrip('/') if appending a path."""
    return (os.getenv("PUBLIC_URL") or os.getenv("APP_URL") or CANONICAL_PUBLIC_URL).rstrip("/")

# Request/Response Models
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str
    phone: str
    plan: str = "free"
    vertical: Optional[str] = None  # 'property' | 'dental' | 'fnb' | 'w3j'

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    # This project has email confirmation ON (GoTrue mailer_autoconfirm=false),
    # so a *successful* signup legitimately has no session yet — the tokens
    # only exist after the user clicks the verification link. Tokens must
    # therefore be optional, otherwise "created, awaiting verification" is not
    # representable and the endpoint is forced to report success as an error.
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user: dict
    tenant_id: str
    email_confirmation_required: bool = False
    # 2026-08-17 FIX: also expose `email` and `business_name` at the top
    # level so the static login.html (and any other consumer) can do
    # `data.email` / `data.business_name` without reaching into
    # `data.user.email` (which doesn't exist in the same shape for
    # `business_name` at all). Previously, `localStorage.setItem("email",
    # data.email)` stored the literal string "undefined" and the dashboard's
    # identity fell back to JWT-only or "—", which is what the user
    # experienced as "login is not working". Mirrors what `oauth_session()`
    # already returns for the Google sign-in path.
    email: Optional[str] = None
    business_name: Optional[str] = None

class RefreshRequest(BaseModel):
    refresh_token: str

class MagicLinkRequest(BaseModel):
    email: str


@router.post("/api/auth/refresh")
async def refresh_access_token(request: RefreshRequest):
    """
    Exchange a valid refresh_token for a new access_token.
    Called automatically by the dashboard when the access_token expires (401).
    Keeps users logged in without forcing a manual re-login.
    """
    db = get_supabase()
    try:
        result = db.auth.refresh_session(request.refresh_token)
        if not result or not result.session:
            raise HTTPException(status_code=401, detail="Refresh token invalid or expired. Please log in again.")

        # Resolve tenant_id for the refreshed user
        tenant_id = None
        try:
            link = db.table("tenant_users") \
                .select("tenant_id") \
                .eq("user_id", str(result.user.id)) \
                .maybe_single() \
                .execute()
            ld = getattr(link, "data", None) if link else None
            tenant_id = ld.get("tenant_id") if isinstance(ld, dict) else None
        except Exception:
            pass

        logging.info(f"✅ Token refreshed for user {result.user.email}")
        return {
            "access_token": result.session.access_token,
            "refresh_token": result.session.refresh_token,
            "tenant_id": tenant_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Token refresh error: {e}")
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")


@router.post("/api/auth/signup", response_model=AuthResponse)
async def signup(request: SignupRequest):
    """
    Professional signup with email/password authentication.
    Creates Supabase auth user + tenant + tenant_user link.

    The supabase-py client is sync, so a hung Supabase request will block
    the event loop. We compensate with comprehensive exception mapping in
    the outer `except` below (AuthApiError.status, httpx errors, etc.)
    so a failure surfaces as a real 4xx/5xx with a JSON body instead of
    a silent Fly-edge 500 with no body.  2026-08-09.
    """
    db = get_supabase()

    user_id = None
    try:
        # 1. Create Supabase Auth user
        # 2026-08-09: AuthApiError is raised for "email already registered",
        # "signups not allowed", "rate limit exceeded", "weak password", and
        # most other Supabase auth failures. Letting it bubble to the broad
        # `except Exception` below (instead of the cascade at step 2+) means
        # we don't create an orphan tenant for a user that was never
        # actually provisioned, and the dashboard sees the real 4xx/5xx
        # instead of a misleading 500.
        try:
            auth_response = db.auth.sign_up({
                "email": request.email,
                "password": request.password,
            })
        except AuthApiError as auth_err:
            # Let the outer `except` mapper translate it to a 4xx/5xx with
            # a useful message. We don't re-raise as HTTPException here
            # because the outer handler has richer context (it knows the
            # email, request shape, and full Supabase error payload).
            logger.warning(
                "Supabase auth.sign_up rejected signup for %s (status=%s, code=%s): %s",
                request.email,
                getattr(auth_err, "status", None),
                getattr(auth_err, "code", None),
                auth_err,
            )
            raise

        if not auth_response.user:
            raise HTTPException(status_code=400, detail="Failed to create user account")

        user_id = auth_response.user.id

        # 1a. Detect the "email already exists" case EARLY.
        # The supabase-py library (v2.x) has a known bug: when sign_up is
        # called with an email that already exists in auth.users, it
        # returns a User object with a *phantom* UUID (a freshly-generated
        # uuid4 that is NOT in auth.users) and session=None — instead of
        # either returning the existing user or raising AuthApiError.
        # We catch this here so the dashboard gets a clean 409 instead
        # of cascading into a 23503 FK violation on tenant_users.
        # 2026-08-10 FIX: `session is None` is NOT a valid signal for this.
        # With email confirmation enabled (this project: GoTrue
        # mailer_autoconfirm=false), a brand-new, perfectly successful signup
        # ALSO returns session=None — the session only appears after the user
        # clicks the verification link. The old check therefore rejected 100%
        # of new registrations with "account already exists", and left an
        # orphaned auth.users row with no tenant, so the user could neither
        # register nor log in. Both directions dead-ended.
        #
        # The correct discriminator is GoTrue's obfuscated-response contract:
        # for an email that already exists it returns identities == [], while
        # a genuinely new user gets exactly one identity. Only treat an
        # explicitly EMPTY list as "already exists" — if the attribute is
        # missing on some client version, fall through and let the signup
        # proceed rather than re-introducing a block-everyone failure.
        identities = getattr(auth_response.user, "identities", None)
        if isinstance(identities, list) and len(identities) == 0:
            logger.info(
                "Signup for %s returned a user with no identities — email "
                "already exists in auth.users; returning 409.",
                request.email,
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    "An account with this email already exists. "
                    "Please sign in instead, or use the password-reset link "
                    "if you don't remember your password."
                ),
            )

        # 2. Create tenant record
        tenant_manager = TenantManager(db)
        try:
            tenant_id = tenant_manager.create_tenant(
                business_name=request.business_name,
                whatsapp_number=request.phone,
                owner_email=request.email,
                subscription_tier=request.plan,
            )
        except Exception as tenant_err:
            # The Supabase auth user was created above. If the tenant
            # insert fails, leave them dangling and the user can never
            # sign in. Best-effort cleanup so they can retry with the
            # same email. service-role client needed to admin-delete.
            logger.exception(
                "Tenant creation failed for %s; rolling back auth user %s: %s",
                request.email, user_id, tenant_err,
            )
            try:
                db.auth.admin.delete_user(user_id)
            except Exception as cleanup_err:
                logger.warning(
                    "Could not roll back auth user %s after tenant failure: %s",
                    user_id, cleanup_err,
                )
            raise HTTPException(
                status_code=500,
                detail="Failed to create workspace. Please try again or contact support.",
            )

        if not tenant_id:
            try:
                db.auth.admin.delete_user(user_id)
            except Exception as cleanup_err:
                logger.warning(
                    "Could not roll back auth user %s: %s", user_id, cleanup_err,
                )
            raise HTTPException(
                status_code=500,
                detail="Failed to create workspace. Please try again or contact support.",
            )

        # 3. Link user to tenant in tenant_users table.
        # NOTE (2026-08-06): wrap in try/except — the `tenant_users` table
        # has a foreign key to `public.users(id)`, and if the auth.users
        # row we just created isn't mirrored in public.users (no sync
        # trigger, race condition, or migration drift), the insert raises
        # APIError 23503. Without this try/except the entire signup 500s
        # AND leaves an orphaned tenant + auth user. We now roll back
        # both so the user can retry with the same email cleanly.
        try:
            db.table("tenant_users").insert({
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": "owner",
            }).execute()
        except Exception as link_err:
            logger.exception(
                "tenant_users insert failed for user %s tenant %s; rolling back: %s",
                user_id, tenant_id, link_err,
            )
            # Roll back the tenant we just created
            try:
                db.table("tenants").delete().eq("id", tenant_id).execute()
            except Exception as tenant_rollback_err:
                logger.warning(
                    "Could not roll back tenant %s after tenant_users failure: %s",
                    tenant_id, tenant_rollback_err,
                )
            # Roll back the auth user
            try:
                db.auth.admin.delete_user(user_id)
            except Exception as auth_rollback_err:
                logger.warning(
                    "Could not roll back auth user %s after tenant_users failure: %s",
                    user_id, auth_rollback_err,
                )
            # Map FK violation to a clearer message than a generic 500
            err_str = str(link_err).lower()
            if "foreign key" in err_str or "violates" in err_str:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Account provisioning failed: the auth user was created "
                        "but the tenant linkage row could not be written. "
                        "Please try again — if it keeps happening, contact support."
                    ),
                )
            raise HTTPException(
                status_code=500,
                detail="Failed to link account to workspace. Please try again.",
            )

        # 4a. Assign vertical template if selected at signup
        if request.vertical:
            try:
                db.table("tenant_verticals").insert({
                    "tenant_id": tenant_id,
                    "vertical_id": request.vertical,
                    "enabled": True,
                }).execute()
                logging.info(f"✅ Assigned vertical '{request.vertical}' to tenant {tenant_id}")
            except Exception as vert_err:
                # Non-fatal: vertical can be assigned later from dashboard
                logging.warning(f"⚠️ Could not assign vertical: {vert_err}")

        # 4b. Auto-create client_config so AI persona works from day 1
        try:
            from datetime import datetime
            db.table("client_configs").insert({
                "tenant_id": tenant_id,
                "client_type": "general",
                "manglish_level": "medium",
                "tone": "professional",
                "enabled_tools": [],
                "system_prompt_vars": {
                    "business_name": request.business_name,
                    "business_type": "Business Services",
                    "owner_phone": request.phone,
                },
                "is_active": True,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
            logging.info(f"✅ Auto-created client_config for new tenant {tenant_id}")
        except Exception as cfg_err:
            # Non-fatal: will be auto-created on WhatsApp connection
            logging.warning(f"⚠️ Could not pre-create client_config: {cfg_err}")

        # 5. Send WhatsApp welcome message via support device (non-fatal)
        try:
            import httpx
            import re as _re
            import base64 as _b64
            bridge_url = os.getenv("BRIDGE_URL", "").rstrip("/")
            bridge_user = os.getenv("BRIDGE_USER", "")
            bridge_pass = os.getenv("BRIDGE_PASSWORD", "")
            support_device = os.getenv("SUPPORT_WA_DEVICE_ID", "")
            if bridge_url and bridge_user and support_device and request.phone:
                clean_phone = _re.sub(r"\D", "", request.phone)
                if clean_phone:
                    jid = f"{clean_phone}@s.whatsapp.net"
                    app_url = _public_base_url()
                    welcome_msg = (
                        f"\U0001f44b Hi {request.business_name}!\n\n"
                        f"Welcome to *Bijou AI* \U0001f389\n\n"
                        f"I'm your Bijou Support bot. Here's how to get started:\n\n"
                        f"1\ufe0f\u20e3 *Connect WhatsApp* \u2014 Dashboard \u2192 Settings \u2192 WhatsApp \u2192 Scan QR\n"
                        f"2\ufe0f\u20e3 *Watch your AI work* \u2014 Dashboard \u2192 Inbox\n"
                        f"3\ufe0f\u20e3 *Help & guides* \u2014 {app_url}/static/help.html\n\n"
                        f"Reply here anytime you need support \U0001f64c\n\n"
                        f"_Bijou Support Team_"
                    )
                    auth_header = _b64.b64encode(
                        f"{bridge_user}:{bridge_pass}".encode()
                    ).decode()
                    async with httpx.AsyncClient(timeout=10.0) as _client:
                        await _client.post(
                            f"{bridge_url}/send/message",
                            json={"device_id": support_device, "jid": jid, "text": welcome_msg},
                            headers={"Authorization": f"Basic {auth_header}"},
                        )
                    logging.info(f"✅ Welcome WhatsApp sent to {clean_phone}")
        except Exception as wa_err:
            logging.warning(f"⚠️ Could not send welcome WhatsApp (non-fatal): {wa_err}")

        # 6. Return JWT tokens
        # NOTE (2026-08-06): handle the case where Supabase returns a
        # user but no session. This happens when (a) the email already
        # exists in auth.users (Supabase returns the existing user
        # without a session), or (b) email confirmation is required and
        # the user hasn't confirmed yet. In both cases we previously
        # crashed with `'NoneType' object has no attribute
        # 'access_token'` and turned a real UX signal into a 500. We
        # now roll back the dangling tenant we just created and surface
        # an honest 409/403.
        # 2026-08-10 FIX: a missing session here means "email confirmation
        # pending", NOT "email already exists" — the already-exists case was
        # ruled out at step 1a via the identities check. The old code deleted
        # the auth user AND the tenant we just created and returned 409, which
        # destroyed every legitimate signup.
        #
        # Keep both rows. The user verifies by email, then logs in normally
        # and _resolve_or_link_tenant finds the tenant we persisted here.
        session = getattr(auth_response, "session", None)
        if not session or not getattr(session, "access_token", None):
            logger.info(
                "Signup for %s created tenant %s; awaiting email confirmation "
                "(no session issued yet).",
                request.email, tenant_id,
            )
            return AuthResponse(
                access_token=None,
                refresh_token=None,
                user={"id": user_id, "email": request.email},
                tenant_id=tenant_id,
                email_confirmation_required=True,
                # 2026-08-17: include the same top-level identity fields
                # login() returns. The static signup.html doesn't read them
                # today, but the dashboard does, and a missing `business_name`
                # would surface as "undefined" / "Bijou" the first time a
                # freshly-signed-up user lands anywhere that shows it.
                email=request.email,
                business_name=request.business_name,
            )

        return AuthResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            user={"id": user_id, "email": request.email},
            tenant_id=tenant_id,
            email_confirmation_required=False,
            # 2026-08-17: same top-level identity fields as login(). Keeps
            # the contract identical across both endpoints so consumers
            # (static HTML + the dashboard) can rely on a single shape.
            email=request.email,
            business_name=request.business_name,
        )

    except HTTPException:
        raise
    except Exception as e:
        # Map common Supabase Auth errors to honest HTTP status codes
        # so the dashboard can show the right message and we stop
        # returning 500 for "user already registered" / "rate limit" /
        # "signups not allowed" / network blips.  2026-08-09: expanded
        # coverage after the dashboard signup was returning 500 (no body)
        # on every retry — Fly edge timeout on a hung supabase-py call.
        msg = str(e).lower()
        # Prefer AuthApiError.status when the supabase lib gives us one
        # — it's the most reliable signal of what really went wrong.
        auth_status = getattr(e, "status", None) if isinstance(e, AuthApiError) else None
        auth_code = getattr(e, "code", None) if isinstance(e, AuthApiError) else None

        if auth_status == 422 or "already registered" in msg or "already been registered" in msg:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Try signing in instead.",
            )
        if auth_status == 429 or "rate limit" in msg or "too many requests" in msg:
            raise HTTPException(
                status_code=429,
                detail="Too many sign-up attempts. Please wait a minute and try again.",
            )
        if auth_status == 403 or "signups not allowed" in msg or "signups disabled" in msg:
            raise HTTPException(
                status_code=403,
                detail="New signups are temporarily disabled. Please try again later or contact support.",
            )
        if auth_status == 400 or "weak password" in msg or ("invalid" in msg and "password" in msg):
            raise HTTPException(
                status_code=400,
                detail="That password is too weak. Please use at least 8 characters with a mix of letters and numbers.",
            )
        if "invalid" in msg and "email" in msg:
            raise HTTPException(
                status_code=400,
                detail="That email address was rejected by the auth provider. Please use a different one.",
            )
        if auth_status == 401 and ("email" in msg and "confirm" in msg or "verified" in msg):
            raise HTTPException(
                status_code=403,
                detail="Please confirm your email address before signing in. Check your inbox for the verification link.",
            )
        # Network / transport failures — Supabase or Fly edge unreachable.
        # NOTE: the welcome-WhatsApp block below does a local `import httpx`
        # in a try, which makes `httpx` a local variable in this function and
        # shadows the module-level one. Look the class up via the real
        # module (sys.modules) instead so the `isinstance` check works
        # regardless of which path raised.
        try:
            import sys as _sys
            _httpx_mod = _sys.modules.get("httpx")
        except Exception:
            _httpx_mod = None
        if _httpx_mod is not None and isinstance(e, _httpx_mod.HTTPError):
            logging.error("Signup network error: %s", e, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="The auth service is temporarily unreachable. Please try again in a moment.",
            )
        logging.error("Signup error (status=%s, code=%s): %s",
                      auth_status, auth_code, e, exc_info=True)
        # Surface a useful hint in the detail (sanitized — no raw stack) so
        # the dashboard can show a non-vague message AND we have something
        # to grep for in Fly logs.
        safe_hint = (msg[:200] if msg else type(e).__name__).strip() or type(e).__name__
        raise HTTPException(
            status_code=500,
            detail=(
                "Signup failed. Please try again or contact support if it keeps happening. "
                f"(ref: {type(e).__name__})"
            ),
        )

def _resolve_or_link_tenant(db, user_id: str, email: Optional[str]) -> Optional[str]:
    """Return the user's tenant_id from tenant_users; if there is no link yet,
    auto-link by matching a tenant this email owns. Self-heals existing owners for
    BOTH password and Google login. Uses the service-role client, so the insert
    bypasses RLS. Returns None only if the email owns no tenant."""
    link = db.table("tenant_users").select("tenant_id").eq("user_id", user_id).execute()
    if link.data:
        return link.data[0]["tenant_id"]
    if not email:
        return None
    owned = (
        db.table("tenants")
        .select("id")
        .or_(f"owner_email.eq.{email},email.eq.{email}")
        .limit(1)
        .execute()
    )
    if not owned.data:
        return None
    tenant_id = owned.data[0]["id"]
    try:
        db.table("tenant_users").insert(
            {"tenant_id": tenant_id, "user_id": user_id, "role": "owner"}
        ).execute()
        logging.info(f"Auto-linked user {user_id} -> tenant {tenant_id} by email {email}")
    except Exception as e:
        logging.warning(f"Auto-link insert skipped ({e})")
    return tenant_id


@router.post("/api/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """
    Professional login with email/password.
    Returns JWT tokens for authenticated access.
    """
    db = get_supabase()

    try:
        # 1. Authenticate with Supabase Auth
        auth_response = db.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password,
        })

        if not auth_response.user or not auth_response.session:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_id = auth_response.user.id

        # 2. Resolve tenant (auto-links existing owners by email on first login)
        tenant_id = _resolve_or_link_tenant(db, user_id, request.email)
        if not tenant_id:
            raise HTTPException(status_code=404, detail="No tenant found for this user")

        # 3. Look up business_name for the resolved tenant.
        # 2026-08-17: the static login.html reads `data.business_name` from
        # the top level of this response and stores it in localStorage. If
        # we don't populate it here, the dashboard falls back to "Bijou" for
        # the shell and shows "undefined" anywhere else. We use maybe_single()
        # so a missing tenant row returns None instead of a 500.
        business_name: Optional[str] = None
        try:
            t_row = (
                db.table("tenants")
                .select("business_name")
                .eq("id", tenant_id)
                .maybe_single()
                .execute()
            )
            t_data = getattr(t_row, "data", None) if t_row else None
            if isinstance(t_data, dict):
                business_name = t_data.get("business_name")
        except Exception as biz_err:
            # Non-fatal: login itself succeeded, just no business_name
            # available. The dashboard has fallbacks (BUSINESS_NAME || "Bijou")
            # so the user still gets a usable shell.
            logger.warning("Could not load business_name for tenant %s: %s", tenant_id, biz_err)

        # 4. Return JWT tokens + identity fields the dashboard expects
        return AuthResponse(
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token,
            user={"id": user_id, "email": request.email},
            tenant_id=tenant_id,
            email=request.email,
            business_name=business_name,
        )

    except HTTPException:
        raise
    except Exception as e:
        # Supabase raises AuthApiError for bad creds, email-not-confirmed,
        # rate-limit, etc. — surface those as honest 4xx codes instead of
        # a generic 500. The raw message goes to logs for diagnosis.
        msg = str(e).lower()
        if "invalid login credentials" in msg or "invalid email or password" in msg:
            logger.info("Login rejected for %s: bad credentials", request.email)
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if "email not confirmed" in msg:
            raise HTTPException(
                status_code=403,
                detail="Please confirm your email before signing in. Check your inbox for the verification link.",
            )
        if "rate limit" in msg:
            raise HTTPException(
                status_code=429,
                detail="Too many sign-in attempts. Please wait a minute and try again.",
            )
        logger.error("Login error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Login failed. Please try again or contact support if it keeps happening.",
        )

@router.post("/api/auth/oauth-session")
async def oauth_session(authorization: Optional[str] = Header(None)):
    """Complete a Supabase OAuth (e.g. Google) sign-in. The client obtains a
    Supabase session via signInWithOAuth, then POSTs the access_token here; we
    resolve/auto-link the tenant and return the same shape the dashboard expects."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    db = get_supabase()
    try:
        user_resp = db.auth.get_user(token)
        user = getattr(user_resp, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid session")
        tenant_id = _resolve_or_link_tenant(db, user.id, user.email)
        if not tenant_id:
            raise HTTPException(
                status_code=404,
                detail="No tenant is registered to this Google account's email. Please sign up first.",
            )
        biz = (
            db.table("tenants").select("business_name").eq("id", tenant_id).limit(1).execute()
        )
        # 2026-08-17 FIX: also surface the refresh_token so the static
        # auth-callback.html can store it in localStorage the same way the
        # email/password login path does. Without this, the dashboard's
        # session-refresh-on-401 has no refresh token to fall back on and
        # the user gets signed out 60 min later instead of being silently
        # refreshed. Falls back to the access token if the Supabase client
        # can't surface one (older supabase-py).
        refresh_token = getattr(getattr(user_resp, "session", None), "refresh_token", None) or ""
        return {
            "access_token": token,
            "refresh_token": refresh_token,
            "tenant_id": tenant_id,
            "email": user.email,
            "business_name": (biz.data[0]["business_name"] if biz.data else None),
        }
    except HTTPException:
        raise
    except Exception as e:
        # Map common Supabase Auth errors to honest codes instead of 500.
        msg = str(e).lower()
        if "session" in msg or "token" in msg:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        logging.error(f"OAuth session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="OAuth session failed")


@router.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """
    Logout user by signing out from Supabase Auth.
    """
    db = get_supabase()

    try:
        # Extract token from Authorization header
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            db.auth.sign_out()
            return {"message": "Logged out successfully"}

        raise HTTPException(status_code=401, detail="Not authenticated")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Logout error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Logout failed")

@router.post("/api/auth/reset-password")
async def reset_password(request: MagicLinkRequest):
    """
    Send password reset email to user.
    Uses Supabase Auth's built-in password recovery.
    """
    db = get_supabase()

    if not request.email or not request.email.strip():
        raise HTTPException(status_code=400, detail="Email address is required")

    try:
        # Get the app URL for the password-reset link. 2026-08-17 FIX:
        # use the canonical public URL (not request.base_url, not the Fly
        # internal host) so the email links to the user-facing domain and
        # the user lands back on the dashboard, not on a raw Fly machine
        # URL with a cert warning. Matches the helper in google_oauth.py.
        redirect_url = f"{_public_base_url()}/reset-password"

        # Send password recovery email via Supabase Auth
        db.auth.reset_password_email(
            email=request.email,
            options={"redirect_to": redirect_url}
        )

        # Always return success (don't reveal if email exists - security best practice)
        return {
            "message": "If an account exists with this email, you will receive a password reset link shortly."
        }

    except Exception as e:
        logging.error(f"Password reset error: {e}", exc_info=True)
        # Still return success message (security best practice)
        return {
            "message": "If an account exists with this email, you will receive a password reset link shortly."
        }


class ChangePasswordRequest(BaseModel):
    new_password: str


@router.post("/api/auth/change-password")
async def change_password(
    request: ChangePasswordRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Change the authenticated user's password using their JWT.
    Requires Authorization: Bearer <access_token> header.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    token = authorization.split(" ", 1)[1]
    db = get_supabase()
    try:
        # Set the user's session so auth.update_user acts on the correct account
        db.auth.set_session(token, "")
        result = db.auth.update_user({"password": request.new_password})
        if not result.user:
            raise HTTPException(status_code=400, detail="Failed to update password")
        return {"success": True, "message": "Password updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        # Map Supabase AuthApiError to honest status codes instead of 500.
        msg = str(e).lower()
        if "different from the old" in msg or "same as" in msg:
            raise HTTPException(
                status_code=400,
                detail="New password must be different from the current password.",
            )
        if "rate limit" in msg:
            raise HTTPException(
                status_code=429,
                detail="Too many password change attempts. Please wait a minute and try again.",
            )
        if "weak" in msg or "short" in msg or "characters" in msg:
            raise HTTPException(
                status_code=400,
                detail=str(e)[:200],
            )
        if "session" in msg or "token" in msg or "unauthorized" in msg:
            raise HTTPException(
                status_code=401,
                detail="Your session expired. Please sign in again and retry.",
            )
        logging.error(f"Change password error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update password")


@router.get("/api/auth/me")
async def get_current_user(authorization: Optional[str] = Header(None)):
    """
    Return the authenticated user's email and id from their JWT.
    Used by the dashboard to display the account email.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.split(" ", 1)[1]
    db = get_supabase()
    try:
        result = db.auth.get_user(token)
        if not result or not result.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"email": result.user.email, "id": str(result.user.id)}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Get current user error: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.post("/api/auth/magic-link")
async def send_magic_link(request: MagicLinkRequest):
    """
    Endpoint to send magic link to user's email for login.
    """
    db = get_supabase()

    # Validate email is not empty
    if not request.email or not request.email.strip():
        raise HTTPException(status_code=400, detail="Email address is required.")

    # Query the tenant database to find the tenant by email
    try:
        tenant = db.table("tenants").select("id, signup_token, name") \
            .eq("email", request.email).maybe_single().execute()
    except Exception as e:
        # If tenant not found, Supabase throws an exception
        logging.warning(f"No tenant found for email: {request.email}")
        raise HTTPException(status_code=404, detail="No account found with that email.")

    # Double-check if tenant data exists
    tdata = getattr(tenant, "data", None) if tenant else None
    if not tdata:
        raise HTTPException(status_code=404, detail="No account found with that email.")

    # Construct Magic Link URL. 2026-08-17 FIX: prefer the canonical public
    # base via `_public_base_url()` so the link lands on app.mybijou.xyz
    # (or whatever PUBLIC_URL is set to), not on the Fly internal host.
    # LOGIN_URL is honored first so tests/overrides can point at a
    # different path without touching env defaults.
    login_url = os.getenv("LOGIN_URL")
    if not login_url:
        login_url = f"{_public_base_url()}/static/login.html"

    # NOTE (2026-08-06): use the validated `tdata` guard variable rather
    # than raw `tenant.data[...]` — if the tenant is missing or the column
    # is null, the line 582 check already returned 404, but a future
    # refactor could remove that check and the unguarded `tenant.data[]`
    # access would 500.
    token = tdata.get("signup_token")
    tenant_id = tdata.get("id")
    business_name = tdata.get("name", "") or ""
    if not token or not tenant_id:
        logging.warning(f"Magic link requested for {request.email} but tenant row is missing signup_token or id")
        raise HTTPException(status_code=404, detail="No account found with that email.")
    magic_link_url = f"{login_url}?token={token}&tenant_id={tenant_id}"

    # Send branded magic link email via EmailService template
    email_service = get_email_service()
    try:
        email_sent = email_service.send_login_magic_link(
            to=request.email,
            business_name=business_name,
            magic_link_url=magic_link_url,
        )

        if not email_sent:
            logging.error(f"Failed to send magic link email to {request.email}")
            raise HTTPException(status_code=500, detail="Failed to send magic link email. Please try again later.")

        return {"message": "Magic link sent successfully! Please check your email."}

    except Exception as e:
        logging.error(f"Unexpected error sending magic link: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
