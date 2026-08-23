"""FastAPI router for self-serve billing in Settings (issue #15).

Wraps the existing src/saas/stripe_service.py with a small,
tenant-scoped API:

- GET  /api/billing/portal     → returns a Stripe Customer Portal URL
  (one-time, ~30 min TTL) that the user opens in a new tab to manage
  their subscription, payment method, and invoices.

- GET  /api/billing/summary    → returns the tenant's current plan,
  next invoice date, and subscription status from the local
  `tenants` row (mirrored from Stripe via webhooks).

Both routes are behind verify_session so tenant_id is always taken
from the authenticated session, never client input. The portal URL
is generated server-side via the Stripe SDK using the service-role
key; the customer never sees a Stripe key in the browser.

Mount in src/core/bijou.py _include_routers():

    from src.core.billing_api import router as billing_router
    app.include_router(billing_router)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.core.dashboard_api_simple import verify_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


# ── Pydantic models ──────────────────────────────────────────────────────


class PortalResponse(BaseModel):
    url: str
    session_id: str


class SubscriptionSummary(BaseModel):
    """A read-only view of the tenant's current subscription state.

    Sourced from the local `tenants` row which is kept in sync by
    stripe_service.py's webhook handlers. Stripe is the source of
    truth, but we cache the essentials here for fast dashboard renders
    without an extra Stripe round-trip.
    """
    plan: Optional[str] = None
    subscription_status: Optional[str] = None
    current_period_end: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    is_trial: Optional[bool] = None
    trial_ends_at: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/portal", response_model=PortalResponse)
async def create_portal_session(
    return_url: Optional[str] = None,
    tenant_id: str = Depends(verify_session),
):
    """Create a one-time Stripe Customer Portal session URL.

    The customer opens the URL in a new tab; Stripe hosts the page
    where they can change plan, update payment method, see invoices,
    or cancel. The session TTL is ~30 minutes; the URL is single-use.
    """
    from src.saas.stripe_service import get_stripe_service
    svc = get_stripe_service()
    if not os.getenv("STRIPE_SECRET_KEY"):
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured on this instance.",
        )
    result = svc.create_portal_session(tenant_id, return_url=return_url)
    if not result:
        raise HTTPException(
            status_code=502,
            detail="Could not create Customer Portal session. The Stripe API may be down or the tenant may not have a Stripe customer yet.",
        )
    return PortalResponse(url=result["url"], session_id=result["session_id"])


@router.get("/summary", response_model=SubscriptionSummary)
async def get_subscription_summary(
    tenant_id: str = Depends(verify_session),
):
    """Read the tenant's current plan + subscription state from Supabase.

    Mirrors the data the dashboard already shows in the Settings tab.
    Kept here so the new Billing tab in Settings can render without
    a separate Stripe round-trip.
    """
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        raise HTTPException(status_code=503, detail="Supabase not configured.")
    sb = create_client(url, key)
    try:
        result = (
            sb.table("tenants")
            .select("plan, subscription_status, current_period_end, "
                    "stripe_customer_id, is_trial, trial_ends_at")
            .eq("id", tenant_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.error(f"billing.summary query failed: {e}")
        raise HTTPException(status_code=500, detail="Could not load subscription.")

    row = getattr(result, "data", None) or {}
    return SubscriptionSummary(
        plan=row.get("plan"),
        subscription_status=row.get("subscription_status"),
        current_period_end=row.get("current_period_end"),
        stripe_customer_id=row.get("stripe_customer_id"),
        is_trial=row.get("is_trial"),
        trial_ends_at=row.get("trial_ends_at"),
    )
