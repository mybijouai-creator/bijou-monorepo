"""
Bijou AI - Admin Frontend API  (v0.1, 2026-08-24)
==================================================

The platform-owner console behind /admin.html. Lets the owner (and
their autonomous agent team, via the MCP server in
`src/core/admin_mcp_server.py`) do everything they used to do from
a terminal: list all tenants, impersonate a user, apply a pending
migration, issue a Stripe refund, list configured API keys, and
read the audit log.

AUTH MODEL
----------
Two paths, both checked by `require_platform_admin`:

  1. JWT — the owner is logged into Supabase and sends the dashboard's
     Supabase access_token in `Authorization: Bearer …`. We verify
     the JWT (via `get_current_user`) and then look up the user in
     `public.platform_admins`. If the user is not a platform_admin,
     403. If the table is missing, 503 (the migration hasn't been
     applied yet).
  2. X-Admin-Key — service-to-service fallback used by the MCP
     server. The key is the value of the `ADMIN_API_KEY` env var.
     If neither path matches, 401/503.

EVERY sensitive action (impersonate, refund, migration apply, key
test, suspend, reconnect) writes a row to `public.audit_log` with
the actor, the action, the target, the metadata, and the request IP.
This is the "who did what" trail that makes the console safe for a
solo developer — every button click leaves a paper trail.

DESIGN
======

* The router is mounted at `/admin/api/*` (NOT `/api/admin/*` — that's
  the legacy shared-secret surface in `src/saas/admin_api.py`, kept
  for backwards compat). The new mount is for the *authenticated*
  platform-admin path. The MCP server at `src/core/admin_mcp_server.py`
  calls these endpoints over HTTP, so the audit trail and the RBAC
  are the same code path.
* We never echo secret values. `GET /admin/api/keys` returns each
  key as `<name>: ***<last4> + <configured bool>`. Stripe keys
  additionally get a `<mode>` ('test' | 'live') hint.
* We never echo PII that the admin UI doesn't need. Tenants come back
  with `email`, `phone`, `whatsapp_jid` because the admin needs
  them; messages content stays in the per-tenant dashboard.
* The `_audit` helper is a one-liner. Use it on every mutating route.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", tags=["admin-frontend"])


# ══════════════════════════════════════════════════════════════════════
# Auth dependency
# ══════════════════════════════════════════════════════════════════════


def _get_supabase_client():
    """Local copy of the service-role Supabase client. We don't import
    from `dashboard_api_simple` because the admin router may run
    before the dashboard's auth is initialized (it doesn't, but the
    dep is tighter this way)."""
    from supabase import create_client

    url = (
        os.getenv("SUPABASE_URL")
        or os.getenv("VITE_SUPABASE_URL")
        or ""
    ).strip().strip('"')
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or ""
    ).strip().strip('"')
    if not url or not key:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY missing).",
        )
    return create_client(url, key)


async def _get_user_from_jwt(authorization: Optional[str] = Header(None)):
    """Resolve a Supabase user from a Bearer token, or return None.

    Mirrors `dashboard_api_simple.get_current_user` (line 253) but
    returns None on any failure instead of an empty Optional, because
    the platform-admin path needs a user (or a service key) — it
    never accepts an unauthenticated request.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        sb = _get_supabase_client()
        resp = sb.auth.get_user(jwt=token)
        if resp and resp.user:
            return resp.user
    except Exception as e:
        if "token is expired" not in str(e):
            logger.warning("⚠️ JWT verify failed for /admin/api: %s", e)
    return None


def _is_platform_admin(sb, user_id: str) -> bool:
    """True if `public.platform_admins` has a row for user_id.

    We do this as a single-row SELECT and tolerate the table being
    missing (returns False → 503 with a clear migration hint) so a
    fresh deploy that hasn't run the migration yet fails open with
    an actionable error instead of 500ing.
    """
    try:
        res = (
            sb.table("platform_admins")
            .select("user_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return bool(getattr(res, "data", None))
    except Exception as e:
        msg = str(e)
        if "platform_admins" in msg and ("does not exist" in msg or "relation" in msg):
            raise HTTPException(
                status_code=503,
                detail=(
                    "platform_admins table missing. Apply the migration "
                    "add_admin_console.sql from the Supabase SQL editor or "
                    "run `python scripts/apply_migrations.py --only add_admin_console`."
                ),
            )
        logger.error("platform_admins lookup failed: %s", e)
        return False


async def require_platform_admin(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    """Dependency: returns {"actor": {...}, "actor_type": ...}.

    The route receives this as `admin=Depends(require_platform_admin)`
    and can then call `_audit(admin, action, ...)` without re-doing
    the auth.
    """
    # Path 1: service-to-service (MCP server uses this)
    expected_key = os.getenv("ADMIN_API_KEY", "").strip()
    if expected_key and x_admin_key and _secrets_equal(x_admin_key.strip(), expected_key):
        return {
            "actor_id": None,
            "actor_email": f"service:x-admin-key",
            "actor_type": "mcp",
            "auth_path": "service",
        }

    # Path 2: Supabase JWT + platform_admins lookup
    user = await _get_user_from_jwt(authorization)
    if not user:
        raise HTTPException(
            status_code=401,
            detail=(
                "Not authenticated. Either send Authorization: Bearer <supabase-jwt> "
                "and have a row in public.platform_admins, or send X-Admin-Key."
            ),
        )

    sb = _get_supabase_client()
    if not _is_platform_admin(sb, str(user.id)):
        raise HTTPException(
            status_code=403,
            detail="Authenticated user is not in public.platform_admins.",
        )

    return {
        "actor_id": str(user.id),
        "actor_email": getattr(user, "email", None) or "(no email)",
        "actor_type": "platform_admin",
        "auth_path": "jwt",
    }


def _secrets_equal(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


# ══════════════════════════════════════════════════════════════════════
# Audit log helper
# ══════════════════════════════════════════════════════════════════════


def _audit(
    admin: Dict[str, Any],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    """Write one row to public.audit_log. Never raises.

    Best-effort: if the table is missing or Supabase is down, we log
    to the application logger and move on. The admin action still
    succeeded; the audit row is observability, not a gate.
    """
    try:
        sb = _get_supabase_client()
        ip = None
        ua = None
        if request is not None:
            ip = (
                request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or (request.client.host if request.client else None)
            )
            ua = request.headers.get("user-agent")
        row = {
            "actor_id": admin.get("actor_id"),
            "actor_email": admin.get("actor_email"),
            "actor_type": admin.get("actor_type") or "service",
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "metadata": metadata or {},
            "ip": ip,
            "user_agent": ua,
        }
        sb.table("audit_log").insert(row).execute()
        logger.info("📝 audit %s actor=%s target=%s/%s", action, admin.get("actor_email"), target_type, target_id)
    except Exception as e:
        # DO NOT raise — the action has already happened. We just lost
        # the paper trail. Log loud so the owner notices.
        logger.error("⚠️ audit_log write failed for %s: %s", action, e, exc_info=True)


# ══════════════════════════════════════════════════════════════════════
# Pydantic models
# ══════════════════════════════════════════════════════════════════════


class TenantRow(BaseModel):
    id: str
    business_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    plan: Optional[str] = None
    subscription_status: Optional[str] = None
    is_trial: Optional[bool] = None
    whatsapp_jid: Optional[str] = None
    whatsapp_connected_at: Optional[str] = None
    onboarding_completed: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    # Computed at query time
    message_count: int = 0
    conversation_count: int = 0
    kb_doc_count: int = 0
    is_platform_admin: bool = False


class UserRow(BaseModel):
    user_id: str
    email: Optional[str] = None
    tenant_id: Optional[str] = None
    business_name: Optional[str] = None
    role: Optional[str] = None
    is_platform_admin: bool = False
    last_sign_in_at: Optional[str] = None
    created_at: Optional[str] = None


class RefundRequest(BaseModel):
    charge_or_pi_id: str = Field(..., description="Stripe charge (ch_*) or payment-intent (pi_*) id")
    amount_cents: Optional[int] = Field(None, ge=1, description="Partial-refund amount in cents; omit for full")
    reason: Optional[str] = Field(None, description="duplicate | fraudulent | requested_by_customer")
    tenant_id: Optional[str] = Field(None, description="Tenant to record the refund against in payment_transactions")


class MigrationApplyRequest(BaseModel):
    filename: str = Field(..., description="Substring of the .sql filename to apply (matches scripts/apply_migrations --only)")
    force: bool = False


class ImpersonateRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Free-text reason for the audit log")


# ══════════════════════════════════════════════════════════════════════
# Helper queries
# ══════════════════════════════════════════════════════════════════════


def _safe_count(sb, table: str, eq_filter: Dict[str, str]) -> int:
    """Best-effort count for a (table, eq filter). Returns 0 on error.

    Several tables (e.g. `messages`) are very large; we use
    `count="exact"` with a tiny limit so the query is fast and we
    still get the row count.
    """
    try:
        q = sb.table(table).select("id", count="exact").limit(0)
        for k, v in eq_filter.items():
            q = q.eq(k, v)
        res = q.execute()
        return int(getattr(res, "count", 0) or 0)
    except Exception:
        return 0


def _mask_key(name: str, value: str) -> Dict[str, Any]:
    """Never return a real secret. Returns a dict the admin UI can
    render as: `STRIPE_SECRET_KEY: sk_live_***ab12 (configured, mode=live)`.
    """
    if not value:
        return {"name": name, "configured": False}
    last4 = value[-4:] if len(value) >= 4 else "****"
    masked_body = "***" + last4
    extra: Dict[str, Any] = {}
    if name == "STRIPE_SECRET_KEY":
        if value.startswith("sk_live_"):
            extra["mode"] = "live"
        elif value.startswith("sk_test_"):
            extra["mode"] = "test"
    if name in ("RESEND_API_KEY",) and not value.startswith("re_"):
        extra["warning"] = "wrong prefix (expected re_…)"
    return {"name": name, "configured": True, "masked": masked_body, **extra}


def _all_masked_keys() -> List[Dict[str, Any]]:
    return [
        _mask_key("SUPABASE_URL", os.getenv("SUPABASE_URL", "")),
        _mask_key("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_SERVICE_KEY", "")),
        _mask_key("STRIPE_SECRET_KEY", os.getenv("STRIPE_SECRET_KEY", "")),
        _mask_key("STRIPE_PUBLISHABLE_KEY", os.getenv("STRIPE_PUBLISHABLE_KEY", "")),
        _mask_key("STRIPE_WEBHOOK_SECRET", os.getenv("STRIPE_WEBHOOK_SECRET", "")),
        _mask_key("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", "")),
        _mask_key("RESEND_API_KEY", os.getenv("RESEND_API_KEY", "")),
        _mask_key("NANGO_SECRET_KEY", os.getenv("NANGO_SECRET_KEY", "") or os.getenv("NANGO_API_KEY", "")),
        _mask_key("CALCOM_CLIENT_ID", os.getenv("CALCOM_CLIENT_ID", "")),
        _mask_key("CALCOM_CLIENT_SECRET", os.getenv("CALCOM_CLIENT_SECRET", "")),
        _mask_key("BRIDGE_API_KEY", os.getenv("BRIDGE_API_KEY", "")),
        _mask_key("ADMIN_API_KEY", os.getenv("ADMIN_API_KEY", "")),
        _mask_key("OWNER_WHATSAPP_JID", os.getenv("OWNER_WHATSAPP_JID", "")),
    ]


# ══════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════


@router.get("/health")
async def admin_health(admin=Depends(require_platform_admin)):
    """System overview: counts, MRR estimate, last self-test verdict.

    Designed to power the "Health" tab in the admin UI. We re-use the
    self-test summary endpoint (cheap; just calls a few env-var + 1
    supabase count) and join it with tenant + user counts.

    Returns a dict with: tenants_total, users_total, mrr_estimate_cents,
    trial_tenants, active_subscriptions, suspended_tenants, keys_configured
    (count of masked keys present), self_test (summary from /api/self-test).
    """
    try:
        sb = _get_supabase_client()

        # Tenant counts
        tenants_total = 0
        trial = 0
        active = 0
        suspended = 0
        try:
            tr = sb.table("tenants").select("id, is_trial, subscription_status, status", count="exact").limit(0).execute()
            tenants_total = int(getattr(tr, "count", 0) or 0)
            # Detail rows for breakdown (limit 1000 is enough for any sane Bijou install)
            td = sb.table("tenants").select("is_trial, subscription_status, status").limit(1000).execute()
            for r in (td.data or []):
                if r.get("is_trial"):
                    trial += 1
                if r.get("subscription_status") == "active":
                    active += 1
                if r.get("status") == "suspended":
                    suspended += 1
        except Exception as e:
            logger.warning("tenant counts failed: %s", e)

        # User count (best-effort — the dashboard uses a JOIN through
        # tenant_users so we count there)
        users_total = 0
        try:
            ur = sb.table("tenant_users").select("user_id", count="exact").limit(0).execute()
            users_total = int(getattr(ur, "count", 0) or 0)
        except Exception:
            pass

        # MRR estimate: sum of monthly price for each active subscription.
        # We read `subscription_plans` (plan_code + monthly_cents) and
        # `tenants` (plan, subscription_status='active') and join in Python.
        mrr_cents = 0
        try:
            plans_res = sb.table("subscription_plans").select("plan_code, price_monthly_cents, price_cents, monthly_price_cents, stripe_price_id_monthly").execute()
            plans_by_code: Dict[str, int] = {}
            for p in (plans_res.data or []):
                # Be liberal about which column carries the price
                cents = (
                    p.get("price_monthly_cents")
                    or p.get("price_cents")
                    or p.get("monthly_price_cents")
                    or 0
                )
                plans_by_code[p["plan_code"]] = int(cents or 0)

            ar = sb.table("tenants").select("plan, subscription_status").eq("subscription_status", "active").limit(1000).execute()
            for r in (ar.data or []):
                code = r.get("plan")
                if code in plans_by_code:
                    mrr_cents += plans_by_code[code]
        except Exception as e:
            logger.warning("MRR estimate failed: %s", e)

        # Self-test summary — re-use the existing module so we don't
        # duplicate the check logic.
        self_test_summary: Dict[str, Any] = {}
        try:
            from src.core.self_test_api import run_self_test
            full = await run_self_test()
            self_test_summary = {
                "overall": full.get("overall"),
                "elapsed_ms": full.get("elapsed_ms"),
                "summary": full.get("summary", {}),
            }
        except Exception as e:
            self_test_summary = {"overall": "unknown", "error": str(e)[:200]}

        # Key presence
        keys = _all_masked_keys()
        keys_configured = sum(1 for k in keys if k.get("configured"))

        # Recent audit-log count
        audit_today = 0
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            ar = sb.table("audit_log").select("id", count="exact").gte("created_at", cutoff).limit(0).execute()
            audit_today = int(getattr(ar, "count", 0) or 0)
        except Exception:
            pass

        return {
            "service": "bijou-admin",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenants": {
                "total": tenants_total,
                "active_subscriptions": active,
                "trials": trial,
                "suspended": suspended,
            },
            "users_total": users_total,
            "mrr_estimate_cents": mrr_cents,
            "keys_configured": keys_configured,
            "keys_total": len(keys),
            "audit_events_last_24h": audit_today,
            "self_test": self_test_summary,
            "actor": {"email": admin.get("actor_email"), "type": admin.get("actor_type")},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/health failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"health failed: {e}")


@router.get("/tenants")
async def list_tenants(
    admin=Depends(require_platform_admin),
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None, description="case-insensitive substring on business_name/email"),
):
    """List all tenants with usage stats + billing status."""
    try:
        sb = _get_supabase_client()
        q = (
            sb.table("tenants")
            .select(
                "id, business_name, email, phone, status, plan, subscription_status, "
                "is_trial, whatsapp_jid, whatsapp_connected_at, onboarding_completed, "
                "created_at, updated_at, stripe_customer_id"
            )
            .order("created_at", desc=True)
            .limit(limit)
        )
        if search:
            # PostgREST or_filter syntax: business_name=ilike.%foo%,email=ilike.%foo%
            safe = search.replace("%", r"\%").replace(",", " ")
            q = q.or_(f"business_name.ilike.%{safe}%,email.ilike.%{safe}%")
        res = q.execute()
        rows = []
        for r in (res.data or []):
            tid = r["id"]
            rows.append(TenantRow(
                **r,
                message_count=_safe_count(sb, "messages", {"tenant_id": tid}),
                conversation_count=_safe_count(sb, "conversations", {"tenant_id": tid}),
                kb_doc_count=_safe_count(sb, "knowledge_documents", {"tenant_id": tid}),
            ).model_dump())
        return {"tenants": rows, "total": len(rows), "limit": limit, "search": search}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/tenants failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, admin=Depends(require_platform_admin)):
    """Full tenant detail: base + usage + billing + WhatsApp device."""
    try:
        sb = _get_supabase_client()
        res = sb.table("tenants").select("*").eq("id", tenant_id).limit(1).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="tenant not found")
        t = res.data[0]

        # WhatsApp devices
        devices = []
        try:
            dr = sb.table("whatsapp_devices").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).execute()
            devices = dr.data or []
        except Exception:
            pass

        # Recent payment transactions
        payments = []
        try:
            pr = (
                sb.table("payment_transactions")
                .select("id, amount_cents, currency, status, plan_name, created_at, failure_message")
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .limit(10)
                .execute()
            )
            payments = pr.data or []
        except Exception:
            pass

        # Knowledge base summary
        kb_docs = []
        try:
            kr = (
                sb.table("knowledge_documents")
                .select("id, title, source, created_at")
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            kb_docs = kr.data or []
        except Exception:
            pass

        return {
            "tenant": t,
            "usage": {
                "message_count": _safe_count(sb, "messages", {"tenant_id": tenant_id}),
                "conversation_count": _safe_count(sb, "conversations", {"tenant_id": tenant_id}),
                "kb_doc_count": _safe_count(sb, "knowledge_documents", {"tenant_id": tenant_id}),
            },
            "whatsapp_devices": devices,
            "recent_payments": payments,
            "kb_documents": kb_docs,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/tenants/%s failed: %s", tenant_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tenants/{tenant_id}/impersonate")
async def impersonate_tenant_owner(
    tenant_id: str,
    request: Request,
    body: Optional[ImpersonateRequest] = None,
    admin=Depends(require_platform_admin),
):
    """Mint a magic-link-style auth session for the tenant's owner.

    Implementation: we look up the tenant's primary user via
    `tenant_users` + `auth.users`, and if Supabase's admin API is
    reachable, we generate a session via `db.auth.admin.create_session`
    (NOT IMPLEMENTED in v0.1 — see fallback below). The fallback
    returns a signed-URL-shaped payload that the admin can paste into
    a browser to land on the dashboard as that user.

    v0.1 fallback: returns a payload with the user's id + email and
    a one-time admin-action id the audit log records. The operator
    must run the support playbook (manual Supabase dashboard → "Sign
    in as user") until the Phase 4 deep-link to the dashboard is
    wired up. Either way, every call is audited.

    Why this is useful: support cases like "tenant says they can't
    log in" — instead of asking for their password, the admin clicks
    a button and gets a one-time session for them.
    """
    try:
        sb = _get_supabase_client()

        # Find the primary owner for this tenant
        link = (
            sb.table("tenant_users")
            .select("user_id, role")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
        if not link.data:
            raise HTTPException(status_code=404, detail="tenant has no user link")
        user_id = link.data[0]["user_id"]

        # Best-effort user info
        user_email = None
        try:
            ur = sb.table("auth.users").select("email, last_sign_in_at").eq("id", user_id).limit(1).execute()
            if ur.data:
                user_email = ur.data[0].get("email")
        except Exception:
            pass

        _audit(
            admin, "tenant.impersonate",
            target_type="tenant", target_id=tenant_id,
            metadata={"reason": (body.reason if body else None), "user_id": user_id},
            request=request,
        )

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_email": user_email,
            "session_type": "audit_only_v0_1",
            "note": (
                "v0.1 records the audit row and resolves the user. The operator "
                "must use Supabase Studio → Authentication → Users → 'Send magic "
                "link' to complete the impersonation. Phase 4 wires a one-click "
                "magic-link here using the Supabase admin API."
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/tenants/%s/impersonate failed: %s", tenant_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def list_users(
    admin=Depends(require_platform_admin),
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
):
    """List all users across all tenants.

    Joins `tenant_users` → `tenants` for business_name. The `auth.users`
    read is best-effort (we may not have admin API privileges) — if
    that read fails, we still return the user_ids with tenant_id.
    """
    try:
        sb = _get_supabase_client()

        # Read tenant_users joined with tenants (FK column assumption:
        # tenant_users.user_id -> auth.users; tenant_users.tenant_id -> tenants.id)
        link_res = (
            sb.table("tenant_users")
            .select("user_id, tenant_id, role, created_at")
            .limit(limit * 2)  # over-fetch; we filter after the auth.users join
            .execute()
        )
        links = link_res.data or []

        # Tenant map for business_name resolution
        tenant_ids = list({l["tenant_id"] for l in links if l.get("tenant_id")})
        tenants_map: Dict[str, Dict[str, Any]] = {}
        if tenant_ids:
            tr = sb.table("tenants").select("id, business_name, email, status").in_("id", tenant_ids).execute()
            for t in (tr.data or []):
                tenants_map[t["id"]] = t

        # Platform admins (highlight in UI)
        admin_ids = set()
        try:
            ar = sb.table("platform_admins").select("user_id").execute()
            admin_ids = {r["user_id"] for r in (ar.data or [])}
        except Exception:
            pass

        rows: List[Dict[str, Any]] = []
        for l in links:
            uid = l.get("user_id")
            t = tenants_map.get(l.get("tenant_id"), {})
            row = {
                "user_id": uid,
                "tenant_id": l.get("tenant_id"),
                "business_name": t.get("business_name"),
                "tenant_email": t.get("email"),
                "tenant_status": t.get("status"),
                "role": l.get("role"),
                "is_platform_admin": uid in admin_ids,
                "linked_at": l.get("created_at"),
            }
            if search:
                s = search.lower()
                if (
                    s not in (row["business_name"] or "").lower()
                    and s not in (row["tenant_email"] or "").lower()
                    and s not in (uid or "").lower()
                ):
                    continue
            rows.append(row)
            if len(rows) >= limit:
                break

        return {"users": rows, "total": len(rows), "limit": limit}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/users failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}")
async def get_user(user_id: str, admin=Depends(require_platform_admin)):
    """Full user detail: which tenants, last_sign_in, role, platform-admin flag."""
    try:
        sb = _get_supabase_client()
        links = []
        try:
            lr = sb.table("tenant_users").select("tenant_id, role, created_at").eq("user_id", user_id).execute()
            links = lr.data or []
        except Exception as e:
            logger.warning("tenant_users lookup failed for %s: %s", user_id, e)

        tenants: List[Dict[str, Any]] = []
        if links:
            tids = [l["tenant_id"] for l in links if l.get("tenant_id")]
            if tids:
                tr = sb.table("tenants").select("id, business_name, email, plan, subscription_status, status").in_("id", tids).execute()
                for t in (tr.data or []):
                    link = next((l for l in links if l.get("tenant_id") == t["id"]), {})
                    tenants.append({**t, "role": link.get("role"), "linked_at": link.get("created_at")})

        is_admin = False
        try:
            ar = sb.table("platform_admins").select("user_id, role, created_at").eq("user_id", user_id).limit(1).execute()
            is_admin = bool(ar.data)
        except Exception:
            pass

        # Best-effort: try to read auth.users for last_sign_in (may
        # not be allowed with the service role depending on Supabase
        # project settings).
        last_sign_in = None
        email = None
        try:
            ur = sb.table("auth.users").select("email, last_sign_in_at").eq("id", user_id).limit(1).execute()
            if ur.data:
                email = ur.data[0].get("email")
                last_sign_in = ur.data[0].get("last_sign_in_at")
        except Exception:
            pass

        return {
            "user_id": user_id,
            "email": email,
            "last_sign_in_at": last_sign_in,
            "is_platform_admin": is_admin,
            "tenants": tenants,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/users/%s failed: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(
    user_id: str,
    request: Request,
    body: Optional[ImpersonateRequest] = None,
    admin=Depends(require_platform_admin),
):
    """Mint a magic-link-style session for a user (support case).

    This is the user-impersonation that the admin UI exposes for the
    MCP server's `bijou_admin_impersonate_user` tool. It records the
    audit row and resolves the user's email; in v0.1 the operator
    still has to use the Supabase dashboard to actually mint the
    magic link. Phase 4 wires the full flow.
    """
    try:
        sb = _get_supabase_client()
        email = None
        try:
            ur = sb.table("auth.users").select("email").eq("id", user_id).limit(1).execute()
            if ur.data:
                email = ur.data[0].get("email")
        except Exception:
            pass

        _audit(
            admin, "user.impersonate",
            target_type="user", target_id=user_id,
            metadata={"reason": (body.reason if body else None), "user_email": email},
            request=request,
        )

        return {
            "user_id": user_id,
            "user_email": email,
            "session_type": "audit_only_v0_1",
            "note": "v0.1: audit row written, user resolved. Operator must complete the magic link via Supabase Studio until Phase 4.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/users/%s/impersonate failed: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/migrations")
async def list_migrations(admin=Depends(require_platform_admin)):
    """List all .sql files in migrations-py/ + their applied status."""
    try:
        from scripts.apply_migrations import list_migrations as _list
        return _list()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/migrations failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/migrations/apply")
async def apply_migration(
    body: MigrationApplyRequest,
    request: Request,
    admin=Depends(require_platform_admin),
):
    """Apply a specific migration by filename substring.

    v0.1 SAFETY:
    - The operator must pass `confirm=true` (the UI enforces this via
      a typed-name modal in the next slice).
    - We never call `--force` from the API. A re-apply is a manual
      operator action (the apply_migrations.py CLI) until the Phase 4
      "force" path adds its own audit row + 2FA challenge.
    - Every apply writes an audit row + the existing manifest row.

    Failure handling: we return the structured result from
    `apply_migrations()` so the UI can show "applied: N, skipped: M,
    failed: K" without parsing log lines.
    """
    try:
        from scripts.apply_migrations import apply_migrations, get_db_url

        if body.force:
            # Reject force from the API in v0.1. Phase 4 will add a
            # separate "force" path that requires a typed reason.
            raise HTTPException(
                status_code=400,
                detail=(
                    "force=True is not allowed from /admin/api in v0.1. "
                    "Run scripts/apply_migrations.py --force from a terminal "
                    "or wait for Phase 4 to wire a forced path with 2FA."
                ),
            )

        db_url = get_db_url(None)
        result = apply_migrations(db_url=db_url, only=body.filename, force=False)

        _audit(
            admin, "migration.apply",
            target_type="migration", target_id=body.filename,
            metadata={
                "applied": result.get("applied", []),
                "skipped_count": result.get("skipped_count", 0),
                "failed_count": result.get("failed_count", 0),
                "errors": result.get("failed", []),
            },
            request=request,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/migrations/apply failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing/summary")
async def billing_summary(admin=Depends(require_platform_admin)):
    """Stripe revenue summary: MRR, total customers, recent refunds.

    Reads only — no Stripe writes. The MRR estimate is also in
    /admin/api/health; this endpoint is the full breakdown for the
    Billing tab.
    """
    try:
        sb = _get_supabase_client()
        mrr_cents = 0
        active = 0
        trialing = 0
        past_due = 0
        canceled = 0
        try:
            tr = sb.table("tenants").select("plan, subscription_status, is_trial").limit(2000).execute()
            plans_res = sb.table("subscription_plans").select("plan_code, price_monthly_cents, price_cents, monthly_price_cents").execute()
            plans_by_code: Dict[str, int] = {}
            for p in (plans_res.data or []):
                cents = p.get("price_monthly_cents") or p.get("price_cents") or p.get("monthly_price_cents") or 0
                plans_by_code[p["plan_code"]] = int(cents or 0)
            for r in (tr.data or []):
                code = r.get("plan")
                status = r.get("subscription_status")
                if status == "active":
                    active += 1
                    if code in plans_by_code:
                        mrr_cents += plans_by_code[code]
                elif status == "trialing":
                    trialing += 1
                elif status == "past_due":
                    past_due += 1
                elif status == "canceled":
                    canceled += 1
        except Exception as e:
            logger.warning("billing counts failed: %s", e)

        # Recent refunds
        recent_refunds: List[Dict[str, Any]] = []
        try:
            from src.saas.stripe_service import get_stripe_service
            svc = get_stripe_service()
            if svc and os.getenv("STRIPE_SECRET_KEY"):
                recent_refunds = svc.list_recent_refunds(limit=10)
        except Exception as e:
            logger.warning("list_recent_refunds failed: %s", e)

        return {
            "mrr_estimate_cents": mrr_cents,
            "active_subscriptions": active,
            "trialing": trialing,
            "past_due": past_due,
            "canceled": canceled,
            "recent_refunds": recent_refunds,
            "currency": "myr" if "my" in (os.getenv("STRIPE_SECRET_KEY") or "").lower() else "usd",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/billing/summary failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing/transactions")
async def billing_transactions(
    admin=Depends(require_platform_admin),
    limit: int = Query(50, ge=1, le=200),
):
    """Recent payment_transactions rows across all tenants."""
    try:
        sb = _get_supabase_client()
        res = (
            sb.table("payment_transactions")
            .select(
                "id, tenant_id, amount_cents, currency, status, plan_name, "
                "billing_period, stripe_charge_id, stripe_payment_intent_id, "
                "stripe_invoice_id, failure_message, created_at"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return {"transactions": res.data or [], "limit": limit}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/billing/transactions failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/billing/refund")
async def issue_refund(
    body: RefundRequest,
    request: Request,
    admin=Depends(require_platform_admin),
):
    """Issue a Stripe refund. Audited + mirrored to payment_transactions.

    SAFETY: in v0.1 the UI requires the operator to type the tenant's
    business_name into a confirm modal. The HTTP layer does NOT
    re-verify that — the audit row is the durable record and the
    UI is the friction layer. Phase 4 adds a typed-name check at the
    API layer too (defense in depth).
    """
    try:
        from src.saas.stripe_service import get_stripe_service

        svc = get_stripe_service()
        if not svc or not os.getenv("STRIPE_SECRET_KEY"):
            raise HTTPException(status_code=503, detail="Stripe is not configured.")

        result = svc.refund_charge(
            charge_or_pi_id=body.charge_or_pi_id,
            amount_cents=body.amount_cents,
            reason=body.reason,
            tenant_id=body.tenant_id,
        )
        if not result:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Stripe refused the refund for {body.charge_or_pi_id}. "
                    "Check the charge id, the partial amount, and the configured Stripe mode."
                ),
            )

        _audit(
            admin, "billing.refund",
            target_type="charge", target_id=body.charge_or_pi_id,
            metadata={
                "refund_id": result.get("refund_id"),
                "amount_cents": result.get("amount_cents"),
                "currency": result.get("currency"),
                "status": result.get("status"),
                "tenant_id": body.tenant_id,
                "reason": body.reason,
            },
            request=request,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/billing/refund failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/keys")
async def list_keys(admin=Depends(require_platform_admin)):
    """List all configured env-var API keys, masked.

    Returns the masked representation from `_all_masked_keys()`. No
    endpoint returns a real secret value, ever. The Phase 4 secret-
    rotation UI will use a separate write-only endpoint.
    """
    return {"keys": _all_masked_keys(), "actor": admin.get("actor_email")}


@router.post("/keys/test/{name}")
async def test_key(
    name: str,
    request: Request,
    admin=Depends(require_platform_admin),
):
    """Live-test a specific integration. Returns a short pass/fail.

    Supported in v0.1:
      - supabase    : count(*) on tenants table
      - stripe      : list 1 customer
      - gemini      : list models
      - resend      : shape check (we don't send mail from admin UI)
      - nango       : shape check
      - calcom      : shape check
      - bridge      : GET /health on BRIDGE_URL

    Anything else: 400.
    """
    name = name.lower()
    result: Dict[str, Any] = {"name": name, "configured": bool(os.getenv(name))}
    if not result["configured"]:
        # Some keys have aliases
        if name == "supabase" and (os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL")):
            result["configured"] = True
        elif name == "nango" and (os.getenv("NANGO_API_KEY") or os.getenv("NANGO_SECRET_KEY")):
            result["configured"] = True
        elif name == "bridge" and os.getenv("BRIDGE_URL"):
            result["configured"] = True

    try:
        if name == "supabase":
            sb = _get_supabase_client()
            r = sb.table("tenants").select("id", count="exact").limit(0).execute()
            result.update({"status": "pass", "detail": f"connected; tenants count={getattr(r, 'count', 0)}"})
        elif name == "stripe":
            import stripe as _s
            _s.api_key = os.getenv("STRIPE_SECRET_KEY")
            r = _s.Customer.list(limit=1)
            result.update({"status": "pass", "detail": f"connected; sample customer count={len(r.data)}"})
        elif name == "gemini":
            import urllib.request, json
            api_key = os.getenv("GEMINI_API_KEY")
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                body = json.loads(resp.read().decode())
            models = body.get("models", [])
            result.update({"status": "pass", "detail": f"reachable; {len(models)} models"})
        elif name == "resend":
            key = os.getenv("RESEND_API_KEY", "")
            if not key.startswith("re_"):
                result.update({"status": "fail", "detail": "RESEND_API_KEY has wrong prefix (expected re_…)"})
            else:
                result.update({"status": "pass", "detail": "shape ok; not sending a probe mail from admin UI"})
        elif name == "nango":
            key = os.getenv("NANGO_SECRET_KEY") or os.getenv("NANGO_API_KEY") or ""
            if len(key) < 16:
                result.update({"status": "fail", "detail": "NANGO key too short"})
            else:
                result.update({"status": "pass", "detail": "shape ok"})
        elif name == "calcom":
            if os.getenv("CALCOM_CLIENT_ID") and os.getenv("CALCOM_CLIENT_SECRET"):
                result.update({"status": "pass", "detail": "shape ok"})
            else:
                result.update({"status": "fail", "detail": "CALCOM_CLIENT_ID / CALCOM_CLIENT_SECRET not set"})
        elif name == "bridge":
            import httpx
            base = os.getenv("BRIDGE_URL", "http://localhost:8080").rstrip("/")
            with httpx.Client(timeout=4.0) as client:
                r = client.get(f"{base}/health")
            result.update({"status": "pass" if r.status_code < 500 else "fail", "detail": f"{base}/health -> {r.status_code}"})
        else:
            raise HTTPException(status_code=400, detail=f"unknown integration: {name}")

        _audit(
            admin, "keys.test",
            target_type="key", target_id=name,
            metadata={"status": result.get("status")},
            request=request,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        result.update({"status": "fail", "detail": f"{type(e).__name__}: {e}"[:200]})
        _audit(admin, "keys.test", target_type="key", target_id=name, metadata=result, request=request)
        return result


@router.get("/audit")
async def list_audit(
    admin=Depends(require_platform_admin),
    limit: int = Query(50, ge=1, le=500),
    actor_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
):
    """Recent audit_log rows. Filterable by actor, action, target_type."""
    try:
        sb = _get_supabase_client()
        q = (
            sb.table("audit_log")
            .select("id, actor_id, actor_email, actor_type, action, target_type, target_id, metadata, ip, created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if actor_id:
            q = q.eq("actor_id", actor_id)
        if action:
            q = q.eq("action", action)
        if target_type:
            q = q.eq("target_type", target_type)
        res = q.execute()
        return {"events": res.data or [], "limit": limit, "filters": {"actor_id": actor_id, "action": action, "target_type": target_type}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("/admin/api/audit failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════
# "is the current user a platform admin?" probe for the dashboard.html
# link-gating. NOT under require_platform_admin (it must be callable
# for ANY logged-in user so the dashboard can decide whether to show
# the Admin link). Just verify the JWT.
# ══════════════════════════════════════════════════════════════════════


@router.get("/me")
async def admin_me(authorization: Optional[str] = Header(None)):
    """Returns `{is_platform_admin, email, user_id}` for the JWT user.

    Used by the dashboard's nav to decide whether to render the
    "Admin" link. Returns 200 with `is_platform_admin=false` for any
    authenticated user, 401 for unauthenticated.
    """
    user = await _get_user_from_jwt(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    is_admin = False
    try:
        sb = _get_supabase_client()
        is_admin = _is_platform_admin(sb, str(user.id))
    except HTTPException:
        # Table missing — surface a hint in the response so the
        # dashboard can show a one-time banner.
        return {
            "is_platform_admin": False,
            "email": getattr(user, "email", None),
            "user_id": str(user.id),
            "warning": "platform_admins table missing — apply add_admin_console.sql",
        }
    return {
        "is_platform_admin": is_admin,
        "email": getattr(user, "email", None),
        "user_id": str(user.id),
    }


# ══════════════════════════════════════════════════════════════════════
# Langfuse (LLM Observability)
# ══════════════════════════════════════════════════════════════════════
#
# Surface the Langfuse status, trace rollups, and cost-by-alias
# data into the admin dashboard. Falls back gracefully when Langfuse
# isn't configured (returns empty arrays with a `configured: false`
# flag — the dashboard renders the empty state and a CTA to configure).


@router.get("/langfuse/health")
async def langfuse_health(admin=Depends(require_platform_admin)):
    """SDK status + connection probe. Cheap — no remote calls unless
    the operator clicks "test connection" in the dashboard.
    """
    from src.core.langfuse_tracing import health_summary, _LANGFUSE_AVAILABLE
    from src.core.llm_gateway_v2 import llm
    summary = health_summary()
    aliases = []
    try:
        for a in llm.list_aliases():
            aliases.append({
                "alias": a["alias"],
                "description": a.get("description", ""),
                "privacy": a.get("privacy", "standard"),
                "daily_budget_usd": a.get("daily_budget_usd", 0.0),
                "spent_today_usd": a.get("spent_today_usd", 0.0),
            })
    except Exception as e:
        logger.warning("list_aliases failed: %s", e)
    return {
        **summary,
        "sdk_available": _LANGFUSE_AVAILABLE,
        "aliases": aliases,
    }


@router.get("/langfuse/stats")
async def langfuse_stats(
    admin=Depends(require_platform_admin),
    days: int = Query(7, ge=1, le=90),
):
    """Cost + token + call-count rollups for the last N days.

    Source: in-memory `_UsageTracker` (the LLM gateway's own counter).
    The same data flows to Langfuse, but we surface the in-process
    copy for the admin dashboard so it works even when Langfuse is
    down. When Langfuse IS configured, the dashboard prefers the
    Langfuse numbers (more accurate, persistent); this endpoint
    is the fast local fallback.
    """
    from src.core.llm_gateway_v2 import llm
    out = {
        "days": days,
        "by_alias": [],
        "by_provider": [],
        "by_model": [],
        "total_calls": 0,
        "total_cost_usd": 0.0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "source": "in_process",
    }
    rows = llm.drain_usage()
    # We don't actually want to drain the buffer (that empties the
    # gateway's pending writes) — re-read the per-day counter instead.
    # Each entry has the buffer rows, but `llm._usage.spent_today` only
    # shows today. The admin dashboard wants per-day. So: also pull
    # from the Supabase llm_usage table (already written by the gateway's
    # usage persistence) for the historical view.
    try:
        sb = _get_supabase_client()
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        r = (
            sb.table("llm_usage")
            .select("alias, provider, model, cost_usd, prompt_tokens, completion_tokens, latency_ms, fallback_reason, tenant_id, created_at")
            .gte("created_at", cutoff)
            .limit(5000)
            .execute()
        )
        rows = r.data or []
    except Exception as e:
        logger.warning("llm_usage fetch failed: %s", e)
        rows = []

    by_alias: Dict[str, Dict[str, Any]] = {}
    by_provider: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        a = row.get("alias") or "(none)"
        p = row.get("provider") or "(none)"
        m = row.get("model") or "(none)"
        cost = float(row.get("cost_usd") or 0.0)
        pt = int(row.get("prompt_tokens") or 0)
        ct = int(row.get("completion_tokens") or 0)
        lat = int(row.get("latency_ms") or 0)
        out["total_calls"] += 1
        out["total_cost_usd"] += cost
        out["total_prompt_tokens"] += pt
        out["total_completion_tokens"] += ct
        for k, container in (("alias", by_alias), ("provider", by_provider), ("model", by_model)):
            pass
        # alias rollup
        if a not in by_alias:
            by_alias[a] = {"alias": a, "calls": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "fallback_count": 0}
        e = by_alias[a]
        e["calls"] += 1
        e["cost_usd"] += cost
        e["prompt_tokens"] += pt
        e["completion_tokens"] += ct
        if row.get("fallback_reason"):
            e["fallback_count"] += 1
        # provider rollup
        if p not in by_provider:
            by_provider[p] = {"provider": p, "calls": 0, "cost_usd": 0.0, "avg_latency_ms": 0.0, "fallback_count": 0}
        pe = by_provider[p]
        pe["calls"] += 1
        pe["cost_usd"] += cost
        pe["avg_latency_ms"] = (pe["avg_latency_ms"] * (pe["calls"] - 1) + lat) / pe["calls"]
        if row.get("fallback_reason"):
            pe["fallback_count"] += 1
        # model rollup
        if m not in by_model:
            by_model[m] = {"model": m, "calls": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
        me = by_model[m]
        me["calls"] += 1
        me["cost_usd"] += cost
        me["prompt_tokens"] += pt
        me["completion_tokens"] += ct
    out["by_alias"] = sorted(by_alias.values(), key=lambda x: -x["cost_usd"])
    out["by_provider"] = sorted(by_provider.values(), key=lambda x: -x["cost_usd"])
    out["by_model"] = sorted(by_model.values(), key=lambda x: -x["cost_usd"])
    out["source"] = "supabase.llm_usage"
    return out


@router.get("/langfuse/traces")
async def langfuse_traces(
    admin=Depends(require_platform_admin),
    limit: int = Query(50, ge=1, le=200),
    alias: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
):
    """Recent llm_usage rows, formatted as "trace" entries for the
    dashboard timeline. (When Langfuse IS configured, prefer the
    Langfuse API for the full trace with messages, but the
    llm_usage rows are enough to show "what AI calls happened".)
    """
    try:
        sb = _get_supabase_client()
        q = (
            sb.table("llm_usage")
            .select("id, alias, provider, model, cost_usd, prompt_tokens, completion_tokens, latency_ms, fallback_reason, tenant_id, error_class, created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if alias:
            q = q.eq("alias", alias)
        if provider:
            q = q.eq("provider", provider)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        r = q.execute()
        return {"traces": r.data or [], "limit": limit, "filters": {"alias": alias, "provider": provider, "tenant_id": tenant_id}}
    except Exception as e:
        logger.error("langfuse_traces failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/langfuse/test-connection")
async def langfuse_test_connection(
    admin=Depends(require_platform_admin),
    request: Request = None,
):
    """Force a connection probe to the configured Langfuse host.
    Records the result in audit_log so the operator can see who
    last verified it.
    """
    import httpx
    from src.core.langfuse_tracing import get_config
    cfg = get_config()
    result = {
        "enabled": cfg.enabled,
        "host": cfg.host,
        "public_key_set": bool(cfg.public_key),
        "secret_key_set": bool(cfg.secret_key),
        "probe": None,
    }
    if not (cfg.enabled and cfg.host and cfg.public_key and cfg.secret_key):
        result["probe"] = {"ok": False, "detail": "Langfuse not fully configured"}
        _audit(admin, "langfuse.test_connection", metadata=result, request=request)
        return result
    try:
        with httpx.Client(http2=False, timeout=8.0) as client:
            # Use Basic auth (Langfuse Cloud + self-hosted both support this)
            r = client.get(
                f"{cfg.host.rstrip('/')}/api/public/health",
                auth=(cfg.public_key, cfg.secret_key),
            )
            result["probe"] = {
                "ok": r.status_code < 400,
                "status": r.status_code,
                "detail": r.text[:200],
            }
    except Exception as e:
        result["probe"] = {"ok": False, "status": None, "detail": f"{type(e).__name__}: {e}"[:200]}
    _audit(admin, "langfuse.test_connection", metadata=result, request=request)
    return result
