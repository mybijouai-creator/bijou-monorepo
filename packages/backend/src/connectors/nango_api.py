"""FastAPI router for Nango (nango.dev) integration connections.

Replaces the dead Composio scaffold (src/connectors/oauth_api.py). All
routes are behind verify_session so tenant_id always comes from the
authenticated session, never client input.

Mount in the main app (see src/core/bijou.py _include_routers()):

    from src.connectors.nango_api import router as nango_router
    app.include_router(nango_router)
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.core.dashboard_api_simple import verify_session
from src.connectors.nango_client import (
    create_connect_session,
    record_connection,
    list_tenant_connections,
    delete_connection,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nango", tags=["nango"])


def _supabase():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


def _tenant_email(tenant_id: str) -> Optional[str]:
    """Best-effort tenant email lookup for Nango's end_user_email tag."""
    try:
        row = _supabase().table("tenants").select("email").eq("id", tenant_id).maybe_single().execute()
        data = getattr(row, "data", None) if row else None
        return data.get("email") if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("Could not resolve tenant email for %s: %s", tenant_id, e)
        return None


class SessionRequest(BaseModel):
    integration_id: Optional[str] = None  # omit to allow connecting any integration


class ConfirmRequest(BaseModel):
    integration_id: str
    connection_id: str


@router.post("/session")
async def create_session(req: SessionRequest, tenant_id: str = Depends(verify_session)):
    """Create a Nango Connect session token for the authenticated tenant."""
    allowed = [req.integration_id] if req.integration_id else None
    try:
        data = await create_connect_session(tenant_id, _tenant_email(tenant_id), allowed_integrations=allowed)
    except Exception as e:
        logger.error("Nango create_connect_session failed for tenant=%s: %s", tenant_id, e)
        raise HTTPException(status_code=502, detail="Could not start connection with Nango")
    # 2026-08-23: surface connect_link too — a plain redirect to Nango's
    # own hosted Connect UI is simpler and more robust for the dashboard
    # than embedding Nango's frontend JS widget (which needs a CDN script
    # tag whose exact URL wasn't worth guessing at without live-testing it).
    return {"session_token": data.get("token"), "connect_link": data.get("connect_link")}


@router.post("/connections/confirm")
async def confirm_connection(req: ConfirmRequest, tenant_id: str = Depends(verify_session)):
    """Record a connection the frontend Connect UI just completed."""
    try:
        record_connection(tenant_id, req.integration_id, req.connection_id, _supabase())
    except Exception as e:
        logger.error("Failed to record Nango connection for tenant=%s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not save the connection")
    return {"success": True}


@router.get("/connections")
async def get_connections(tenant_id: str = Depends(verify_session)):
    try:
        connections = list_tenant_connections(tenant_id, _supabase())
    except Exception as e:
        logger.error("Failed to list Nango connections for tenant=%s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not load connections")
    return {"connections": connections}


@router.delete("/connections/{integration_id}")
async def remove_connection(integration_id: str, tenant_id: str = Depends(verify_session)):
    try:
        await delete_connection(tenant_id, integration_id, _supabase())
    except Exception as e:
        logger.error("Failed to delete Nango connection for tenant=%s integration=%s: %s", tenant_id, integration_id, e)
        raise HTTPException(status_code=500, detail="Could not remove the connection")
    return {"success": True}
