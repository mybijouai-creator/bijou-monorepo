"""Thin wrapper around the Nango (nango.dev) API — replaces the dead Composio
scaffold (src/connectors/oauth_api.py, src/connectors/auth_configs.py).

Nango handles OAuth + token refresh for each tenant's connected third-party
account ("end user" in Nango's model); we only persist which integration a
tenant has connected and under which Nango connection_id (see
migrations-py/add_tenant_integrations.sql), so we can later ask Nango's proxy
to call that provider on the tenant's behalf without ever touching a token.

Env vars (support both spellings — Nango's own docs are inconsistent):
    NANGO_SECRET_KEY | NANGO_API_KEY   - required, Bearer auth
    NANGO_HOST                          - default https://api.nango.dev
                                           (self-hosted default is
                                           http://localhost:3003)
"""
from __future__ import annotations
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

TABLE = "tenant_integrations"


def _host() -> str:
    return os.getenv("NANGO_HOST", "https://api.nango.dev").rstrip("/")


def _secret_key() -> str:
    key = os.getenv("NANGO_SECRET_KEY") or os.getenv("NANGO_API_KEY")
    if not key:
        raise RuntimeError("NANGO_SECRET_KEY (or NANGO_API_KEY) must be set")
    return key


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_secret_key()}"}


async def create_connect_session(
    tenant_id: str,
    tenant_email: Optional[str],
    allowed_integrations: Optional[list[str]] = None,
) -> dict:
    """Create a short-lived (30 min) Connect session token for a tenant.

    Returns the `data` object from Nango: {"token", "connect_link", "expires_at"}.
    """
    body: dict[str, Any] = {
        "tags": {"end_user_id": tenant_id, "end_user_email": tenant_email},
    }
    if allowed_integrations:
        body["allowed_integrations"] = allowed_integrations

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_host()}/connect/sessions",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=body,
        )
    resp.raise_for_status()
    return resp.json()["data"]


def record_connection(tenant_id: str, integration_id: str, connection_id: str, supabase) -> None:
    """Upsert the tenant's connection into tenant_integrations."""
    supabase.table(TABLE).upsert(
        {
            "tenant_id": tenant_id,
            "integration_id": integration_id,
            "connection_id": connection_id,
            "status": "connected",
        },
        on_conflict="tenant_id,integration_id",
    ).execute()


def list_tenant_connections(tenant_id: str, supabase) -> list:
    result = supabase.table(TABLE).select("*").eq("tenant_id", tenant_id).execute()
    return result.data or []


def _lookup_connection_id(tenant_id: str, integration_id: str, supabase) -> Optional[str]:
    result = (
        supabase.table(TABLE)
        .select("connection_id")
        .eq("tenant_id", tenant_id)
        .eq("integration_id", integration_id)
        .maybe_single()
        .execute()
    )
    data = getattr(result, "data", None) if result else None
    return data.get("connection_id") if isinstance(data, dict) else None


async def delete_connection(tenant_id: str, integration_id: str, supabase) -> None:
    """Disconnect a tenant's integration.

    ponytail: we always remove the local row, even if the remote Nango
    delete call fails or the tenant had no recorded connection. The local
    row is what the dashboard reads to decide "connected or not" — leaving
    it behind after the user clicked "disconnect" is a worse, more visible
    failure mode than a stale connection lingering on Nango's side (which
    the tenant can also remove from the Nango dashboard, and which grants no
    access to Bijou itself). So: best-effort remote delete, unconditional
    local delete, log and continue on remote error.
    """
    connection_id = _lookup_connection_id(tenant_id, integration_id, supabase)
    if connection_id:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.delete(
                    f"{_host()}/connections/{connection_id}",
                    headers=_auth_headers(),
                    params={"provider_config_key": integration_id},
                )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(
                "Nango delete_connection failed for tenant=%s integration=%s (removing local row anyway): %s",
                tenant_id, integration_id, e,
            )

    supabase.table(TABLE).delete().eq("tenant_id", tenant_id).eq("integration_id", integration_id).execute()


async def proxy_request(
    tenant_id: str,
    integration_id: str,
    method: str,
    endpoint: str,
    supabase,
    **kwargs,
) -> httpx.Response:
    """Call a connected third-party API on the tenant's behalf via Nango's proxy.

    `endpoint` is the path on the provider's API, e.g. "/calendar/v3/users/me".
    Raises ValueError (not a crash) if the tenant has no connection for
    `integration_id` yet — callers should turn that into a 404.
    """
    connection_id = _lookup_connection_id(tenant_id, integration_id, supabase)
    if not connection_id:
        raise ValueError(f"No connection for tenant={tenant_id} integration={integration_id}")

    headers = {
        **_auth_headers(),
        "Connection-Id": connection_id,
        "Provider-Config-Key": integration_id,
        **kwargs.pop("headers", {}),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(
            method,
            f"{_host()}/proxy{endpoint}",
            headers=headers,
            **kwargs,
        )
